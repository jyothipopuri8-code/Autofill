#!/usr/bin/env bash
# Starts the agent on 127.0.0.1 (this computer only). Ctrl+C stops it.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ -x "$ROOT/.venv/bin/python" ] || { echo "Not installed yet: run scripts/install.sh" >&2; exit 1; }
if curl -fsS -m 2 "http://127.0.0.1:${AUTOFILL_PORT:-8765}/api/v1/health" >/dev/null 2>&1; then
  echo "The agent is already running."; exit 0
fi
cd "$ROOT/backend"
exec "$ROOT/.venv/bin/python" -m autofill_agent
