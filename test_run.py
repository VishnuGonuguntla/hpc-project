import json
import sys
from datetime import datetime

import pytest

import harnesses
import run as void

# A stand-in for a harness: an MCP client that does the hello-edit task without a model.
FAKE_AGENT = """
import json, os, sys, anyio
assert os.path.samefile(os.environ["PWD"], os.getcwd()), "harness must see its own folder as PWD"
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
cmd = json.loads(sys.argv[1])
async def main():
    params = StdioServerParameters(command=cmd[0], args=cmd[1:])
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        await s.call_tool("edit_file", {"path": "hello.txt", "old_text": "todo", "new_text": "done"})
anyio.run(main)
"""


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(void, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(void, "WORK", tmp_path / "work")
    agent = tmp_path / "fake_agent.py"
    agent.write_text(FAKE_AGENT)
    monkeypatch.setitem(harnesses.HARNESSES, "fake", lambda s: harnesses.Launch(
        [sys.executable, str(agent), json.dumps(s.mcp)]))
    cluster = {"name": "local", "server": "mcp_server/server.py", "sandbox_root": str(tmp_path / "sb")}
    model = {"name": "m", "model": "m", "upstream": "http://127.0.0.1:9", "context": 1}
    return {"harness": "fake", "model": model, "cluster": cluster, "task": void.load_task("hello-edit"),
            "prompt": None}


def manifest(run):
    return json.loads((run / "manifest.json").read_text())


def test_task_run_records_everything(env):
    run = void.one_run(env, rep=1)

    assert run.name.endswith("_fake_m_hello-edit_r1")
    m = manifest(run)
    assert m["mode"] == "new" and m["sandbox"]["created"] and m["exit_code"] == 0
    assert m["inputs"] == env and m["git"]["commit"]
    assert json.loads((run / "result.json").read_text())["passed"]
    assert (run / "sandbox" / "hello.txt").read_text().endswith("status: done\n")
    calls = [json.loads(line)["msg"] for line in (run / "mcp.jsonl").read_text().splitlines()]
    assert any(c.get("method") == "tools/call" for c in calls)
    instructions = (run / "config" / "instructions.md").read_text()
    assert instructions.startswith("# Agent instructions")
    assert "#SBATCH --export=NONE" in instructions        # skill body is inlined ...
    assert "name: hpc-cluster" not in instructions        # ... without its header


def test_continue_and_reuse_keep_the_sandbox(env):
    env = env | {"task": None}  # interactive-style run: no task files, no check
    first = void.one_run(env, sandbox="shared")
    (first / "session" / "conversation.txt").write_text("turn 1")

    cont = void.one_run(env, parent=first)
    reuse = void.one_run(env, sandbox="shared")

    assert manifest(first)["mode"] == "new"
    assert manifest(cont)["mode"] == "continue" and manifest(cont)["continues"] == str(first)
    assert (cont / "session" / "conversation.txt").read_text() == "turn 1"  # session copied
    assert manifest(reuse)["mode"] == "reuse-sandbox"
    assert not (reuse / "session" / "conversation.txt").exists()            # new session
    assert {manifest(r)["sandbox"]["name"] for r in (first, cont, reuse)} == {"shared"}
    assert void.latest_run("fake") == reuse


def test_new_run_dir_never_reuses_a_folder(env):
    now = datetime(2026, 11, 6, 16, 2, 11)
    a = void.new_run_dir(now, "pi", "m", None, None)
    b = void.new_run_dir(now, "pi", "m", None, None)
    assert a.name == "16-02-11_pi_m" and b.name == "16-02-11_pi_m-2"
    assert a.parent.name == "2026-11-06"


@pytest.mark.parametrize("name", ["../x", "a b", "x;rm -rf ~", ""])
def test_unsafe_sandbox_names_are_refused(name):
    with pytest.raises(SystemExit):
        void.check_name(name)


def test_ssh_cluster_command_runs_remotely():
    cluster = {"ssh": "host", "python": "$WORK/v/bin/python", "server": "~/s.py", "sandbox_root": "~/sb"}
    cmd = void.server_command(cluster, "~/sb/x")
    assert cmd[0] == "ssh" and cmd[cmd.index("host") + 1:] == ["$WORK/v/bin/python", "~/s.py",
                                                               "--sandbox", "~/sb/x"]
    assert void.cluster_cmd(cluster, "test -d ~/sb/x")[-2:] == ["host", "test -d ~/sb/x"]


def test_context_warning():
    model = {"model": "m", "context": 32768}
    assert "4096" in void.context_warning(model, {"context_length": 4096})
    assert void.context_warning(model, {"context_length": 32768}) is None
    assert void.context_warning(model, {}) is None  # model not loaded: unknown, no warning


# ---------- --dir ----------

def test_dir_works_in_place_and_snapshot_skips_git(env, tmp_path):
    project = tmp_path / "project"
    (project / ".git").mkdir(parents=True)
    (project / ".git" / "HEAD").write_text("ref")
    (project / "hello.txt").write_text("Hello from the sandbox.\nstatus: todo\n")
    folder = void.check_dir(env["cluster"], str(project))

    run = void.one_run(env, folder=folder, rep=1)
    cont = void.one_run(env | {"task": None}, parent=run)

    assert (project / "hello.txt").read_text().endswith("status: done\n")   # edited in place
    assert manifest(run)["sandbox"] == {"name": None, "path": str(project.resolve()), "created": False}
    assert manifest(cont)["sandbox"]["path"] == str(project.resolve())      # continue keeps it
    assert (run / "sandbox" / "hello.txt").exists() and not (run / "sandbox" / ".git").exists()


def test_snapshot_limit_skips_big_sandboxes(env, tmp_path, monkeypatch):
    monkeypatch.setattr(void, "SNAPSHOT_LIMIT", 1000)
    big = tmp_path / "big"
    big.mkdir()
    (big / "data.bin").write_bytes(b"x" * 5000)
    with pytest.raises(RuntimeError, match="snapshot skipped"):
        void.snapshot_sandbox(env["cluster"], str(big), tmp_path / "snap")
    assert not (tmp_path / "snap").exists()


@pytest.mark.parametrize("path", ["/", "~", "~/..", void.REPO.parent, void.REPO, void.REPO / "runs",
                                  "a b", "x;rm -rf ~", ""])
def test_dangerous_local_dirs_are_refused(path):
    with pytest.raises(SystemExit):
        void.check_dir({"name": "local"}, str(path))


@pytest.mark.parametrize("path,ok", [("~/proj", True), ("$WORK/stencil", True), ("/home/hpc/x/proj", True),
                                     ("~", False), ("~/", False), ("$WORK", False), ("/home", False),
                                     ("~/a/../..", False), ("$(whoami)", False)])
def test_remote_dirs_must_be_project_folders(path, ok):
    cluster = {"ssh": "host"}
    if ok:
        assert void.check_dir(cluster, path) == path
    else:
        with pytest.raises(SystemExit):
            void.check_dir(cluster, path)
