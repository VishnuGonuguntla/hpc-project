"""Record every request between a harness and a model server, streaming responses through unbuffered.

The harness uses http://127.0.0.1:<port> as its model URL; any path is forwarded, so OpenAI- and
Anthropic-style APIs both work:
    python llm_proxy.py --upstream http://127.0.0.1:11434 --port 8400 --log runs/<date>/<run>/llm.jsonl

One line per request in the log: timings (t_start, t_first_byte, t_end), method, path, status,
request headers (secrets removed) and body, and the raw response text. Nothing is interpreted
here; tokens and turns are extracted later from the raw data.
"""
import argparse
import json
import time
from pathlib import Path

import httpx2
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

SECRET_HEADERS = {"authorization", "proxy-authorization", "x-api-key", "cookie"}
# shortcut: accept-encoding is dropped so responses come back uncompressed and stay readable in the
# log; upgrade if an upstream ever needs compression
NOT_FORWARDED = {"host", "content-length", "transfer-encoding", "connection", "accept-encoding"}
NOT_RETURNED = {"content-length", "transfer-encoding", "connection"}
METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]


def _body(raw: bytes):
    try:
        return json.loads(raw)
    except ValueError:
        return raw.decode(errors="replace")


def make_app(upstream: str, log_path: str) -> Starlette:
    client = httpx2.AsyncClient(base_url=upstream, timeout=None)  # generations can take minutes
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    log = open(log_path, "a")

    def write(record):
        log.write(json.dumps(record) + "\n")
        log.flush()

    async def proxy(request: Request):
        record = {"t_start": time.time(), "method": request.method, "path": request.url.path,
                  "query": request.url.query}
        raw = await request.body()
        record["request_headers"] = {k: v for k, v in request.headers.items()
                                     if k not in SECRET_HEADERS | NOT_FORWARDED}
        record["request"] = _body(raw)
        upstream_req = client.build_request(
            request.method, request.url.path, params=request.query_params, content=raw,
            headers={k: v for k, v in request.headers.items() if k not in NOT_FORWARDED})
        try:
            resp = await client.send(upstream_req, stream=True)
        except httpx2.HTTPError as e:
            write(record | {"t_end": time.time(), "status": 502, "error": repr(e)})
            return JSONResponse({"error": f"llm_proxy: upstream unreachable: {e!r}"}, status_code=502)
        record["status"] = resp.status_code

        async def stream():
            chunks = []
            try:
                async for chunk in resp.aiter_raw():
                    if not chunks:
                        record["t_first_byte"] = time.time()
                    chunks.append(chunk)
                    yield chunk
            except httpx2.HTTPError as e:
                record["error"] = repr(e)
            finally:
                await resp.aclose()
                write(record | {"t_end": time.time(),
                                "response": b"".join(chunks).decode(errors="replace")})

        headers = {k: v for k, v in resp.headers.items() if k.lower() not in NOT_RETURNED}
        return StreamingResponse(stream(), status_code=resp.status_code, headers=headers)

    return Starlette(routes=[Route("/{path:path}", proxy, methods=METHODS)])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--upstream", required=True, help="model server URL, e.g. http://127.0.0.1:11434")
    parser.add_argument("--port", type=int, default=8400)
    parser.add_argument("--log", required=True, help="JSONL file to append records to")
    args = parser.parse_args()
    uvicorn.run(make_app(args.upstream, args.log), host="127.0.0.1", port=args.port,
                log_level="warning")


if __name__ == "__main__":
    main()
