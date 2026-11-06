"""void: start an agent harness with everything recorded into runs/<date>/<run>/.

  ./void pi                                new session in a new sandbox (interactive)
  ./void pi --continue [RUN]               continue a session (default: latest run of this harness)
  ./void pi --sandbox NAME                 new session in a named sandbox (created if missing)
  ./void pi --task hello-edit [--reps 3]   headless runs, each checked by the task
  ./void pi --prompt "TEXT" [--continue]   one headless message, no check
  ./void --from runs/<date>/<run>          repeat a recorded task run with the same inputs
"""
import argparse
import json
import os
import platform
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import tomllib
import urllib.request
from datetime import datetime
from pathlib import Path

from harnesses import HARNESSES, Setup

REPO = Path(__file__).resolve().parent
RUNS = REPO / "runs"
WORK = Path.home() / ".void" / "work"  # harness working folders, one per sandbox
SSH = ["ssh", "-T", "-o", "BatchMode=yes", "-o", "LogLevel=ERROR"]
SAFE_NAME = re.compile(r"[A-Za-z0-9._-]+")  # names end up in remote shell commands


# ---------- profiles and tasks ----------

def load_profile(kind: str, name: str) -> dict:
    for candidate in (f"{name}.local.toml", f"{name}.toml"):
        path = REPO / "config" / kind / candidate
        if path.exists():
            return {"name": name} | tomllib.loads(path.read_text())
    raise SystemExit(f"no {kind} profile '{name}' in config/{kind}/")


def load_task(name: str) -> dict:
    path = REPO / "tasks" / name
    if not path.is_dir():
        raise SystemExit(f"no task '{name}' in tasks/")
    return {"name": name, "prompt": (path / "prompt.md").read_text().strip()}


def instructions_text() -> str:
    """AGENTS.md plus the cluster skill body, appended to every harness's system prompt."""
    # shortcut: the skill is always inlined because harness skill loading needs file tools we turn
    # off; upgrade to serving it through the MCP server if prompt size starts to matter
    skill = (REPO / "skills" / "hpc-cluster" / "SKILL.md").read_text().split("---", 2)[2]
    return (REPO / "AGENTS.md").read_text() + "\n" + skill.strip() + "\n"


# ---------- cluster side ----------

def check_name(name: str) -> str:
    if not SAFE_NAME.fullmatch(name):
        raise SystemExit(f"invalid sandbox name '{name}': use letters, digits, '.', '_' and '-'")
    return name


def cluster_cmd(cluster: dict, script: str) -> list[str]:
    """A shell command run on the cluster over SSH, or here for a cluster profile without ssh."""
    return [*SSH, cluster["ssh"], script] if cluster.get("ssh") else ["sh", "-c", script]


def sandbox_path(cluster: dict, name: str) -> str:
    return f"{cluster['sandbox_root']}/{name}"  # unquoted on purpose: the shell expands ~ and $WORK


def server_command(cluster: dict, sandbox: str) -> list[str]:
    path = sandbox_path(cluster, sandbox)
    if cluster.get("ssh"):
        return [*SSH, cluster["ssh"], cluster["python"], cluster["server"], "--sandbox", path]
    return [sys.executable, str(REPO / cluster["server"]), "--sandbox", str(Path(path).expanduser())]


def prepare_sandbox(cluster: dict, name: str, task: str | None) -> bool:
    """Create the sandbox unless it exists; a new one gets the task's start files. Returns True if new."""
    path = sandbox_path(cluster, name)
    if subprocess.run(cluster_cmd(cluster, f"test -d {path}")).returncode == 0:
        return False
    files = REPO / "tasks" / task / "files" if task else None
    if files and files.is_dir():
        pack = subprocess.Popen(["tar", "-C", str(files), "-cf", "-", "."], stdout=subprocess.PIPE)
        subprocess.run(cluster_cmd(cluster, f"mkdir -p {path} && tar -C {path} -xf -"),
                       stdin=pack.stdout, check=True)
        pack.wait()
    else:
        subprocess.run(cluster_cmd(cluster, f"mkdir -p {path}"), check=True)
    return True


def snapshot_sandbox(cluster: dict, name: str, dest: Path) -> None:
    # shortcut: copies the whole sandbox every run; switch to rsync or a size limit for big sandboxes
    dest.mkdir(parents=True, exist_ok=True)
    pack = subprocess.Popen(cluster_cmd(cluster, f"tar -C {sandbox_path(cluster, name)} -cf - ."),
                            stdout=subprocess.PIPE)
    subprocess.run(["tar", "-C", str(dest), "-xf", "-"], stdin=pack.stdout, check=True)
    if pack.wait():
        raise RuntimeError("could not read the sandbox")


# ---------- recording helpers ----------

def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_proxy(model: dict, log: Path) -> tuple[subprocess.Popen, str]:
    port = free_port()
    proc = subprocess.Popen([sys.executable, str(REPO / "record" / "llm_proxy.py"),
                             "--upstream", model["upstream"], "--port", str(port), "--log", str(log)])
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.1).close()
            return proc, f"http://127.0.0.1:{port}"
        except OSError:
            if proc.poll() is not None:
                break
            time.sleep(0.1)
    proc.kill()
    raise SystemExit("LLM proxy did not start")


def model_info(model: dict) -> dict:
    """What the model server reports right now. Only Ollama is queried so far."""
    if model.get("server") != "ollama":
        return {}

    def get(path):
        with urllib.request.urlopen(model["upstream"] + path, timeout=5) as r:
            return json.load(r)

    try:
        tags = {m["name"]: m for m in get("/api/tags")["models"]}
        loaded = {m["name"]: m for m in get("/api/ps")["models"]}
        return {"server_version": get("/api/version")["version"],
                "digest": tags.get(model["model"], {}).get("digest"),
                "context_length": loaded.get(model["model"], {}).get("context_length")}
    except OSError as e:
        return {"error": repr(e)}


def context_warning(model: dict, info: dict) -> str | None:
    ctx = info.get("context_length")
    if ctx and ctx < model["context"]:
        return (f"model server runs {model['model']} with context {ctx}, profile expects "
                f"{model['context']}: long prompts are silently cut (Ollama: OLLAMA_CONTEXT_LENGTH)")
    return None


def git_state() -> dict:
    def git(*a):
        return subprocess.run(["git", *a], cwd=REPO, capture_output=True, text=True).stdout.strip()
    return {"commit": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain"))}


def version(cmd: str) -> str:
    try:
        return subprocess.run([cmd, "--version"], capture_output=True, text=True, timeout=30).stdout.strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"unknown ({e})"


def rel(path: Path) -> str:
    return str(path.relative_to(REPO)) if path.is_relative_to(REPO) else str(path)


def write_manifest(run: Path, manifest: dict) -> None:
    (run / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def find_run(ref: str) -> Path:
    path = Path(ref)
    path = path.parent if path.name == "manifest.json" else path
    if not (path / "manifest.json").exists():
        raise SystemExit(f"'{ref}' is not a run folder")
    return path.resolve()


def latest_run(harness: str) -> Path:
    runs = sorted(p.parent for p in RUNS.glob(f"*/*_{harness}_*/manifest.json"))
    if not runs:
        raise SystemExit(f"no earlier {harness} run to continue")
    return runs[-1]


# ---------- one run ----------

def new_run_dir(now: datetime, harness: str, model: str, task: str | None, rep: int | None) -> Path:
    name = "_".join([now.strftime("%H-%M-%S"), harness, model] + ([task, f"r{rep}"] if task else []))
    base = RUNS / now.strftime("%Y-%m-%d") / name
    run, n = base, 1
    while True:
        try:
            run.mkdir(parents=True)
            return run
        except FileExistsError:  # two runs in the same second
            n += 1
            run = base.with_name(f"{base.name}-{n}")


def run_harness(cmd, env, cwd, run: Path, headless: bool, timeout: float) -> int | str:
    if not headless:
        # Ctrl-C belongs to the harness; a handler (unlike SIG_IGN) is not inherited by the child
        old = signal.signal(signal.SIGINT, lambda *_: None)
        try:
            return subprocess.run(cmd, cwd=cwd, env=env).returncode
        finally:
            signal.signal(signal.SIGINT, old)
    out = run / "harness"
    out.mkdir()
    with open(out / "events.jsonl", "wb") as stdout, open(out / "stderr.log", "wb") as stderr:
        # own process group, so a timeout also stops the tap and SSH started by the harness
        proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=stdout, stderr=stderr,
                                stdin=subprocess.DEVNULL, start_new_session=True)
        try:
            return proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait()
            return "timeout"


def one_run(inputs: dict, *, sandbox: str | None = None, parent: Path | None = None,
            rep: int | None = None, timeout: float = 1800) -> Path:
    harness, model, cluster, task = (inputs[k] for k in ("harness", "model", "cluster", "task"))
    prompt = task["prompt"] if task else inputs.get("prompt")  # None: interactive
    now = datetime.now()
    run = new_run_dir(now, harness, model["name"], task and task["name"], rep)

    if parent:
        sandbox = json.loads((parent / "manifest.json").read_text())["sandbox"]["name"]
        shutil.copytree(parent / "session", run / "session")
    else:
        (run / "session").mkdir()
    sandbox = check_name(sandbox or now.strftime(f"%Y-%m-%d_%H-%M-%S_{harness}"))
    is_new = prepare_sandbox(cluster, sandbox, task and task["name"])
    mode = "continue" if parent else ("new" if is_new else "reuse-sandbox")
    where = f"{cluster['ssh']}:" if cluster.get("ssh") else ""
    print(f"void: sandbox  {where}{sandbox_path(cluster, sandbox)}  ({mode})\nvoid: run      {rel(run)}",
          file=sys.stderr)

    info = model_info(model)
    manifest = {
        "run": rel(run), "mode": mode,
        "continues": rel(parent) if parent else None,
        "sandbox": {"name": sandbox, "path": sandbox_path(cluster, sandbox), "created": is_new},
        "inputs": inputs, "void_command": sys.argv,
        "harness": {"name": harness, "version": version(harness)},  # harness name = its command
        "model_info_start": info, "warnings": [],
        "git": git_state(),
        "host": {"hostname": platform.node(), "platform": platform.platform(),
                 "python": platform.python_version()},
        "t_start": time.time(),
    }
    if warning := context_warning(model, info):
        manifest["warnings"].append(warning)
        print(f"void: warning: {warning}", file=sys.stderr)
    write_manifest(run, manifest)

    instructions = run / "config" / "instructions.md"
    instructions.parent.mkdir(exist_ok=True)
    instructions.write_text(instructions_text())
    workdir = WORK / sandbox
    workdir.mkdir(parents=True, exist_ok=True)

    proxy, proxy_url = start_proxy(model, run / "llm.jsonl")
    tap = [sys.executable, str(REPO / "record" / "mcp_tap.py"), "--log", str(run / "mcp.jsonl"), "--",
           *server_command(cluster, sandbox)]
    launch = HARNESSES[harness](Setup(run=run, model=model, proxy_url=proxy_url, mcp=tap,
                                      instructions=instructions, prompt=prompt,
                                      resume=parent is not None))
    manifest["harness"] |= {"command": launch.cmd, "env": launch.env, "cwd": str(workdir)}
    write_manifest(run, manifest)

    try:
        # PWD too: some harnesses (OpenCode) take their project folder from it, not from the real cwd
        env = os.environ | launch.env | {"PWD": str(workdir)}
        manifest["exit_code"] = run_harness(launch.cmd, env, workdir, run,
                                            headless=prompt is not None, timeout=timeout)
    finally:
        proxy.terminate()
        proxy.wait()
        manifest["t_end"] = time.time()
        try:
            snapshot_sandbox(cluster, sandbox, run / "sandbox")
        except (RuntimeError, subprocess.CalledProcessError) as e:
            manifest["warnings"].append(f"sandbox snapshot failed: {e}")
        manifest["model_info_end"] = info = model_info(model)
        if (warning := context_warning(model, info)) and warning not in manifest["warnings"]:
            manifest["warnings"].append(warning)
            print(f"void: warning: {warning}", file=sys.stderr)
        if task:
            check = subprocess.run([sys.executable, str(REPO / "tasks" / task["name"] / "check.py"),
                                    str(run / "sandbox")], capture_output=True, text=True)
            (run / "result.json").write_text(json.dumps(
                {"passed": check.returncode == 0, "output": check.stdout + check.stderr}, indent=2) + "\n")
        write_manifest(run, manifest)

    print(f"\nvoid: run      {rel(run)}  (exit {manifest['exit_code']})"
          f"\nvoid: sandbox  {sandbox} ({mode})"
          f"\nvoid: continue ./void {harness} --continue {rel(run)}"
          f"\nvoid: reuse    ./void {harness} --sandbox {sandbox}", file=sys.stderr)
    return run


# ---------- command line ----------

def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="void", description=__doc__.splitlines()[0],
                                epilog="\n".join(__doc__.splitlines()[2:]),
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("harness", nargs="?", choices=sorted(HARNESSES))
    p.add_argument("--model", default="ollama-qwen3.5-4b", help="profile in config/models/")
    p.add_argument("--cluster", default="local", help="profile in config/clusters/")
    p.add_argument("--task", help="run headless with tasks/<TASK>/ and check the result")
    p.add_argument("--prompt", help="send one message headless instead of opening the harness")
    p.add_argument("--reps", type=int, default=1, help="repetitions of --task or --prompt")
    p.add_argument("--sandbox", help="sandbox name (reused if it exists)")
    p.add_argument("--continue", dest="cont", nargs="?", const="latest", metavar="RUN",
                   help="continue a session (default: latest run of this harness)")
    p.add_argument("--from", dest="from_run", metavar="RUN", help="repeat a recorded task run")
    p.add_argument("--timeout", type=float, default=1800, help="seconds per headless run")
    a = p.parse_args(argv)

    if a.from_run:
        inputs = json.loads((find_run(a.from_run) / "manifest.json").read_text())["inputs"]
        if not (inputs["task"] or inputs.get("prompt")):
            p.error("--from repeats headless runs; continue interactive runs with --continue")
        for rep in range(1, a.reps + 1):
            one_run(inputs, rep=rep, timeout=a.timeout)
        return

    if not a.harness:
        p.error("name a harness: " + ", ".join(sorted(HARNESSES)))
    if a.cont:
        if a.task or a.sandbox:
            p.error("--continue uses the earlier run's sandbox and inputs; drop --task/--sandbox")
        parent = latest_run(a.harness) if a.cont == "latest" else find_run(a.cont)
        inputs = json.loads((parent / "manifest.json").read_text())["inputs"]
        inputs |= {"task": None, "prompt": a.prompt}  # a continuation is interactive or one message
        if inputs["harness"] != a.harness:
            p.error(f"{parent.name} is a {inputs['harness']} run")
        one_run(inputs, parent=parent)
        return

    if a.task and a.prompt:
        p.error("use --task or --prompt, not both")
    inputs = {"harness": a.harness, "model": load_profile("models", a.model),
              "cluster": load_profile("clusters", a.cluster),
              "task": load_task(a.task) if a.task else None, "prompt": a.prompt}
    if a.task or a.prompt:
        for rep in range(1, a.reps + 1):
            one_run(inputs, sandbox=a.sandbox, rep=rep, timeout=a.timeout)
    else:
        one_run(inputs, sandbox=a.sandbox)


if __name__ == "__main__":
    main()
