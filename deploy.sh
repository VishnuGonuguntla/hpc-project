#!/usr/bin/env bash
# Install or update the MCP server on a cluster login node.
#   usage: ./deploy.sh <ssh-host> [auto|uv|venv]
# Copies mcp_server/server.py to ~/agent-mcp/ and builds a venv in $WORK (or $HOME) with exactly
# the versions pinned in uv.lock. "auto" (default) uses uv if the cluster has it, else python -m venv + pip.
# Prints the command a harness uses to start the server.
set -euo pipefail

host=${1:?usage: ./deploy.sh <ssh-host> [auto|uv|venv]}
method=${2:-auto}
cd "$(dirname "$0")"

reqs=$(mktemp)
trap 'rm -f "$reqs"' EXIT
uv export --frozen --no-dev --no-emit-project --quiet -o "$reqs"  # all pins + hashes from uv.lock

ssh "$host" 'mkdir -p ~/agent-mcp'
scp -q mcp_server/server.py "$host:agent-mcp/server.py"
scp -q "$reqs" "$host:agent-mcp/requirements.txt"

ssh "$host" bash -l -s -- "$method" <<'REMOTE'
set -euo pipefail
method=$1
venv="${WORK:-$HOME}/agent-mcp-venv"
reqs="$HOME/agent-mcp/requirements.txt"

if [ "$method" = auto ]; then
    if command -v uv >/dev/null; then method=uv; else method=venv; fi
fi
case "$method" in
    uv)
        # --seed adds pip, so the venv method still works on this venv later
        uv venv --quiet --seed --allow-existing --python '>=3.12' "$venv"
        uv pip install --quiet --python "$venv/bin/python" -r "$reqs" ;;
    venv)
        module load python 2>/dev/null || true  # NHR@FAU: the system python cannot create venvs
        [ -x "$venv/bin/python" ] || python3 -m venv "$venv"
        "$venv/bin/python" -m pip install --quiet -r "$reqs" ;;
    *)
        echo "unknown method '$method' (use auto, uv or venv)" >&2; exit 1 ;;
esac

echo "installed with: $method"
echo "server command: $venv/bin/python $HOME/agent-mcp/server.py --sandbox $HOME/agent-sandbox"
REMOTE
