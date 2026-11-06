import json
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import anyio
import httpx2
import pytest
import uvicorn
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from starlette.applications import Starlette
from starlette.responses import StreamingResponse
from starlette.routing import Route

HERE = Path(__file__).parent
TAP = HERE / "mcp_tap.py"
PROXY = HERE / "llm_proxy.py"
SERVER = HERE.parent / "mcp_server" / "server.py"


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


# ---------- MCP tap ----------

def test_tap_passes_through_and_records(tmp_path):
    (tmp_path / "hello.txt").write_text("hi")
    log = tmp_path / "run" / "mcp.jsonl"
    params = StdioServerParameters(command=sys.executable, args=[
        str(TAP), "--log", str(log), "--",
        sys.executable, str(SERVER), "--sandbox", str(tmp_path)])

    async def session():
        async with stdio_client(params) as (read, write), ClientSession(read, write) as s:
            await s.initialize()
            return await s.call_tool("read_file", {"path": "hello.txt"})

    assert anyio.run(session).content[0].text == "hi"

    records = read_jsonl(log)
    assert records[0]["dir"] == "to_server" and records[0]["msg"]["method"] == "initialize"
    call = next(r for r in records if r["msg"].get("method") == "tools/call")
    reply = next(r for r in records if r["dir"] == "to_client" and r["msg"].get("id") == call["msg"]["id"])
    assert call["msg"]["params"]["name"] == "read_file"
    assert reply["msg"]["result"]["content"][0]["text"] == "hi"
    assert [r["t"] for r in records] == sorted(r["t"] for r in records)


def test_tap_keeps_exit_code_and_stderr(tmp_path):
    log = tmp_path / "mcp.jsonl"
    fake_server = "import sys; sys.stderr.write('boom'); sys.exit(3)"
    done = subprocess.run([sys.executable, str(TAP), "--log", str(log), "--",
                           sys.executable, "-c", fake_server], input=b"", capture_output=True)
    assert done.returncode == 3
    assert b"boom" in done.stderr
    assert (tmp_path / "mcp.stderr.log").read_text() == "boom"


# ---------- LLM proxy ----------

def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for_port(port, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            return
        except OSError:
            time.sleep(0.05)
    raise TimeoutError(f"nothing listening on {port}")


CHUNK_PAUSE = 0.3


async def fake_model(request):
    auth_ok = request.headers.get("authorization") == "Bearer secret-123"

    async def chunks():
        for i in range(3):
            yield f"data: chunk{i} auth_ok={auth_ok}\n\n".encode()
            await anyio.sleep(CHUNK_PAUSE)

    return StreamingResponse(chunks(), media_type="text/event-stream")


@pytest.fixture
def proxy(tmp_path):
    up_port, proxy_port = free_port(), free_port()
    upstream = uvicorn.Server(uvicorn.Config(
        Starlette(routes=[Route("/v1/chat/completions", fake_model, methods=["POST"])]),
        port=up_port, log_level="warning"))
    threading.Thread(target=upstream.run, daemon=True).start()
    log = tmp_path / "llm.jsonl"
    proc = subprocess.Popen([sys.executable, str(PROXY), "--upstream", f"http://127.0.0.1:{up_port}",
                             "--port", str(proxy_port), "--log", str(log)])
    try:
        wait_for_port(up_port)
        wait_for_port(proxy_port)
        yield f"http://127.0.0.1:{proxy_port}", log
    finally:
        proc.terminate()
        proc.wait()
        upstream.should_exit = True


def test_proxy_streams_unbuffered_and_records(proxy):
    url, log = proxy
    body = {"model": "m", "messages": [{"role": "user", "content": "hi"}], "stream": True}
    received, arrivals = b"", []
    t0 = time.time()
    with httpx2.stream("POST", f"{url}/v1/chat/completions", json=body,
                       headers={"Authorization": "Bearer secret-123"}) as resp:
        for chunk in resp.iter_raw():
            arrivals.append(time.time() - t0)
            received += chunk
    total = time.time() - t0

    expected = b"".join(f"data: chunk{i} auth_ok=True\n\n".encode() for i in range(3))
    assert received == expected  # byte-identical, and the key reached the model server
    assert arrivals[0] < total - 2 * CHUNK_PAUSE + 0.15  # first chunk did not wait for the rest

    (record,) = read_jsonl(log)
    assert record["request"] == body and record["status"] == 200
    assert record["response"] == expected.decode()
    assert record["t_start"] <= record["t_first_byte"] < record["t_end"]
    assert record["t_end"] - record["t_first_byte"] >= 2 * CHUNK_PAUSE - 0.05
    assert "secret-123" not in log.read_text()


def test_proxy_reports_unreachable_upstream(tmp_path):
    port = free_port()
    log = tmp_path / "llm.jsonl"
    proc = subprocess.Popen([sys.executable, str(PROXY), "--upstream", f"http://127.0.0.1:{free_port()}",
                             "--port", str(port), "--log", str(log)])
    try:
        wait_for_port(port)
        resp = httpx2.post(f"http://127.0.0.1:{port}/v1/models", json={})
        assert resp.status_code == 502 and "unreachable" in resp.text
        assert read_jsonl(log)[0]["status"] == 502
    finally:
        proc.terminate()
        proc.wait()
