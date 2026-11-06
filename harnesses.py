"""How to start each harness for a run. One function per harness; register new ones in HARNESSES.

Every function writes the harness's config into the run folder and returns the command to start
it. Common rules: the model is reached only through the LLM proxy, the cluster only through the
MCP tap, the harness's own file/shell tools are off, and nothing is read from the user's normal
harness settings.
"""
import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Setup:
    run: Path              # run folder
    model: dict            # model profile
    proxy_url: str         # LLM proxy, e.g. http://127.0.0.1:8400
    mcp: list[str]         # command that starts the MCP server through the tap
    instructions: Path     # AGENTS.md + cluster skill, appended to the system prompt
    prompt: str | None     # None: interactive
    resume: bool           # continue the latest session found in run/session


@dataclass
class Launch:
    cmd: list[str]
    env: dict[str, str] = field(default_factory=dict)


def _write_json(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")
    return path


def pi(s: Setup) -> Launch:
    agent_dir = s.run / "config" / "pi"
    model = s.model["model"]
    _write_json(agent_dir / "models.json", {"providers": {"void": {
        "api": "openai-completions", "baseUrl": f"{s.proxy_url}/v1", "apiKey": "void",
        "models": [{"id": model, "contextWindow": s.model["context"],
                    "reasoning": s.model.get("reasoning", False)}]}}})
    _write_json(agent_dir / "mcp.json", {"mcpServers": {"cluster": {
        "command": s.mcp[0], "args": s.mcp[1:], "exposure": "direct", "timeout": 120}}})
    cmd = ["pi", "--provider", "void", "--model", model, "--tools", "mcp__cluster__*",
           "--no-context-files", "--append-system-prompt", str(s.instructions),
           "--session-dir", str(s.run / "session")]
    if s.resume:
        cmd.append("--continue")
    if s.prompt:
        cmd += ["--mode", "json", s.prompt]
    return Launch(cmd, {"PI_CODING_AGENT_DIR": str(agent_dir)})


def claude(s: Setup) -> Launch:
    model = s.model["model"]
    mcp = _write_json(s.run / "config" / "claude-mcp.json", {"mcpServers": {"cluster": {
        "command": s.mcp[0], "args": s.mcp[1:]}}})
    # "=" form: these options take lists and would otherwise swallow the prompt
    cmd = ["claude", "--bare", "--model", model, "--tools=", "--allowedTools=mcp__cluster",
           "--strict-mcp-config", f"--mcp-config={mcp}",
           f"--append-system-prompt-file={s.instructions}"]
    if s.resume:
        cmd.append("--continue")
    if s.prompt:
        cmd += ["-p", "--output-format=stream-json", "--verbose", s.prompt]
    return Launch(cmd, {
        "CLAUDE_CONFIG_DIR": str(s.run / "session" / "claude"),  # settings + sessions, isolated
        "ANTHROPIC_BASE_URL": s.proxy_url,
        "ANTHROPIC_API_KEY": "void",  # local servers ignore it; --bare requires one
        # background calls (titles, summaries) must also go to our model
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": model,
        "ANTHROPIC_DEFAULT_SONNET_MODEL": model,
        "ANTHROPIC_DEFAULT_OPUS_MODEL": model,
        "CLAUDE_CODE_SUBAGENT_MODEL": model,
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
    })


def opencode(s: Setup) -> Launch:
    model = s.model["model"]
    config = _write_json(s.run / "config" / "opencode.json", {
        "$schema": "https://opencode.ai/config.json",
        "autoupdate": False,
        "share": "disabled",
        "provider": {"void": {"npm": "@ai-sdk/openai-compatible", "name": "void",
                              "options": {"baseURL": f"{s.proxy_url}/v1", "apiKey": "void"},
                              "models": {model: {"name": model, "limit": {
                                  "context": s.model["context"],
                                  # shortcut: fixed output cap so background calls (titles) cannot
                                  # run for 32k tokens; move to the model profile if models differ
                                  "output": 4096}}}}},
        "model": f"void/{model}",
        "instructions": [str(s.instructions)],
        "mcp": {"cluster": {"type": "local", "command": s.mcp, "enabled": True}},
        "tools": {"*": False, "cluster_*": True},
    })
    cmd = ["opencode", "run", "--format", "json"] if s.prompt else ["opencode"]
    if s.resume:
        cmd.append("--continue")
    if s.prompt:
        cmd.append(s.prompt)
    return Launch(cmd, {
        "OPENCODE_CONFIG": str(config),
        # global config folder: an empty shared one instead of yours; OpenCode installs its npm
        # packages there, so they are downloaded once instead of 60 MB per run folder
        "XDG_CONFIG_HOME": str(Path.home() / ".void" / "opencode-config"),
        "XDG_DATA_HOME": str(s.run / "session" / "data"),    # sessions database
        "XDG_STATE_HOME": str(s.run / "session" / "state"),
        "OPENCODE_DISABLE_CLAUDE_CODE": "1",  # do not read ~/.claude
        "OPENCODE_DISABLE_AUTOUPDATE": "1",
    })


HARNESSES = {"pi": pi, "claude": claude, "opencode": opencode}
