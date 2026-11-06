"""Sandboxed file tools for a cluster login node, served over MCP stdio.

Start it over SSH from the agent's machine:
    ssh <host> <venv>/bin/python server.py --sandbox ~/agent-sandbox

Every path is relative to the sandbox and cannot leave it. No shell, no delete.
"""
import argparse
import functools
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

MAX_READ = 32 * 1024
MAX_WRITE = 256 * 1024
MAX_LIST = 200

SANDBOX = Path("~/agent-sandbox").expanduser().resolve()  # set from --sandbox in main()

READ_ONLY = ToolAnnotations(read_only_hint=True)
CHANGES_FILES = ToolAnnotations(read_only_hint=False, destructive_hint=True)

mcp = MCPServer(
    "cluster-sandbox",
    instructions="File tools on a cluster login node. All paths are relative to the sandbox "
    "root; nothing outside it is reachable. There is no shell and no delete.",
)


def _resolve(path: str) -> Path:
    # resolve() follows symlinks, so a link pointing out of the sandbox is caught too
    p = (SANDBOX / path).resolve()
    if not p.is_relative_to(SANDBOX):
        raise ToolError(f"path '{path}' is outside the sandbox")
    return p


def _show_errors(fn):
    """Pass the reason for a failure to the model; the SDK hides plain exception text."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (OSError, ValueError) as e:
            raise ToolError(f"{type(e).__name__}: {e}") from e

    return wrapper


@mcp.tool(annotations=READ_ONLY)
@_show_errors
def list_dir(path: str = ".") -> str:
    """List a directory in the sandbox. Directories end with '/'."""
    entries = sorted(_resolve(path).iterdir())
    lines = [f"{e.relative_to(SANDBOX)}{'/' if e.is_dir() else ''}" for e in entries[:MAX_LIST]]
    if len(entries) > MAX_LIST:
        lines.append(f"... {len(entries) - MAX_LIST} more entries not shown")
    return "\n".join(lines) or "(empty)"


@mcp.tool(annotations=READ_ONLY)
@_show_errors
def read_file(path: str) -> str:
    """Read a text file in the sandbox (at most 32 KiB)."""
    data = _resolve(path).read_bytes()
    text = data[:MAX_READ].decode(errors="replace")
    return text + (f"\n... truncated, file has {len(data)} bytes" if len(data) > MAX_READ else "")


@mcp.tool(annotations=CHANGES_FILES)
@_show_errors
def write_file(path: str, content: str, overwrite: bool = False) -> str:
    """Create a text file in the sandbox (at most 256 KiB); parent directories are created.
    An existing file is only replaced with overwrite=true."""
    if len(content.encode()) > MAX_WRITE:
        raise ToolError("content too large (max 256 KiB)")
    p = _resolve(path)
    if p.exists() and not overwrite:
        raise ToolError(f"'{path}' already exists; pass overwrite=true to replace it")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return f"wrote {len(content)} characters to {path}"


@mcp.tool(annotations=CHANGES_FILES)
@_show_errors
def edit_file(path: str, old_text: str, new_text: str) -> str:
    """Replace old_text with new_text in a sandbox file. old_text must occur exactly once."""
    p = _resolve(path)
    text = p.read_text()
    if (n := text.count(old_text)) != 1:
        raise ToolError(f"old_text occurs {n} times in '{path}'; it must occur exactly once")
    p.write_text(text.replace(old_text, new_text, 1))
    return f"edited {path}"


def main() -> None:
    global SANDBOX
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sandbox", type=Path, default=Path("~/agent-sandbox"),
                        help="the only directory the tools can reach (default: ~/agent-sandbox)")
    SANDBOX = parser.parse_args().sandbox.expanduser().resolve()
    SANDBOX.mkdir(parents=True, exist_ok=True)
    mcp.run()  # stdio


if __name__ == "__main__":
    main()
