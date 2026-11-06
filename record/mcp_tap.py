"""Record every MCP message between a harness and any stdio MCP server.

The harness starts this tap instead of the server; the tap starts the server and passes every
line through unchanged:
    python mcp_tap.py --log runs/<date>/<run>/mcp.jsonl -- <server command ...>

Each message becomes one line in the log: {"t": unix time, "dir": "to_server"|"to_client", "msg": ...}.
The server's stderr goes to our stderr and to <log name>.stderr.log next to the log.
"""
import argparse
import json
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path


def pump(src, dst, log, direction, lock):
    """Forward lines from src to dst and log each one. Forward first, so logging adds no delay."""
    try:
        for line in iter(src.readline, b""):
            dst.write(line)
            dst.flush()
            try:
                msg = json.loads(line)
            except ValueError:
                msg = line.decode(errors="replace")  # keep non-JSON lines too, they explain failures
            with lock:
                log.write(json.dumps({"t": time.time(), "dir": direction, "msg": msg}) + "\n")
                log.flush()
    except (BrokenPipeError, ValueError):  # the other side closed
        pass
    finally:
        if direction == "to_server":
            dst.close()  # harness closed its end: let the server see EOF and exit


def tee(src, *dsts):
    for chunk in iter(lambda: src.read1(4096), b""):
        for d in dsts:
            d.write(chunk)
            d.flush()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--log", type=Path, required=True, help="JSONL file to append messages to")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="-- <MCP server command ...>")
    args = parser.parse_args()
    cmd = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not cmd:
        parser.error("missing server command after --")

    args.log.parent.mkdir(parents=True, exist_ok=True)
    # SIGTERM from the harness should still stop the server (see finally below)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))

    with open(args.log, "a") as log, open(args.log.with_suffix(".stderr.log"), "ab") as errlog:
        server = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE)
        lock = threading.Lock()
        # to_server is a daemon: it may block on the harness's stdin after the server is gone
        threading.Thread(target=pump, daemon=True,
                         args=(sys.stdin.buffer, server.stdin, log, "to_server", lock)).start()
        to_client = threading.Thread(target=pump,
                                     args=(server.stdout, sys.stdout.buffer, log, "to_client", lock))
        stderr = threading.Thread(target=tee, args=(server.stderr, sys.stderr.buffer, errlog))
        to_client.start()
        stderr.start()
        try:
            code = server.wait()
            to_client.join()
            stderr.join()
            return code
        finally:
            if server.poll() is None:
                server.terminate()


if __name__ == "__main__":
    sys.exit(main())
