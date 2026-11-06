import sys

import anyio
import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.server.mcpserver.exceptions import ToolError

import server


@pytest.fixture
def box(tmp_path, monkeypatch):
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    (sandbox / "a.txt").write_text("one\ntwo\n")
    monkeypatch.setattr(server, "SANDBOX", sandbox.resolve())
    return sandbox


@pytest.mark.parametrize("path", ["../outside.txt", "/etc/passwd", "sub/../../x"])
def test_paths_outside_sandbox_are_refused(box, path):
    with pytest.raises(ToolError, match="outside the sandbox"):
        server.read_file(path)


def test_symlink_out_of_sandbox_is_refused(box, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("secret")
    (box / "link.txt").symlink_to(secret)
    (box / "linkdir").symlink_to(tmp_path)

    for call in (lambda: server.read_file("link.txt"),
                 lambda: server.write_file("link.txt", "x", overwrite=True),
                 lambda: server.edit_file("linkdir/secret.txt", "secret", "x"),
                 lambda: server.list_dir("linkdir")):
        with pytest.raises(ToolError, match="outside the sandbox"):
            call()
    assert secret.read_text() == "secret"


def test_edit_needs_exactly_one_match(box):
    for old in ("missing", "o"):  # 0 matches, 2 matches ("one", "two")
        with pytest.raises(ToolError, match="must occur exactly once"):
            server.edit_file("a.txt", old, "x")
    assert (box / "a.txt").read_text() == "one\ntwo\n"

    server.edit_file("a.txt", "two", "three")
    assert (box / "a.txt").read_text() == "one\nthree\n"


def test_write_limits(box):
    with pytest.raises(ToolError, match="overwrite=true"):
        server.write_file("a.txt", "x")
    with pytest.raises(ToolError, match="too large"):
        server.write_file("big.txt", "x" * (server.MAX_WRITE + 1))
    assert not (box / "big.txt").exists()

    server.write_file("a.txt", "x", overwrite=True)
    server.write_file("new/dir/b.txt", "hi")
    assert (box / "a.txt").read_text() == "x"
    assert (box / "new/dir/b.txt").read_text() == "hi"


def test_errors_tell_the_model_why(box):
    with pytest.raises(ToolError, match="FileNotFoundError"):
        server.read_file("nope.txt")


def test_list_and_truncated_read(box):
    (box / "d").mkdir()
    (box / "big.txt").write_bytes(b"x" * (server.MAX_READ + 10))
    assert server.list_dir() == "a.txt\nbig.txt\nd/"
    assert server.read_file("big.txt").endswith(f"truncated, file has {server.MAX_READ + 10} bytes")


def test_stdio_end_to_end(tmp_path):
    """Start the server as a real process, the way a harness does."""
    (tmp_path / "hello.txt").write_text("hi")
    params = StdioServerParameters(command=sys.executable,
                                   args=[server.__file__, "--sandbox", str(tmp_path)])

    async def session():
        async with stdio_client(params) as (read, write), ClientSession(read, write) as s:
            await s.initialize()
            tools = {t.name: t for t in (await s.list_tools()).tools}
            return tools, await s.call_tool("read_file", {"path": "hello.txt"})

    tools, result = anyio.run(session)
    assert set(tools) == {"list_dir", "read_file", "write_file", "edit_file"}
    assert tools["read_file"].annotations.read_only_hint is True
    assert tools["write_file"].annotations.destructive_hint is True
    assert result.content[0].text == "hi"
