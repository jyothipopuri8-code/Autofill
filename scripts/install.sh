#!/usr/bin/env bash
# Linux/macOS setup: creates .venv, installs the agent, builds the extension if Node is present.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"

"$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
  || { echo "Python 3.11+ is required (set PYTHON=/path/to/python3.11)." >&2; exit 1; }

echo "==> Creating .venv and installing the agent"
[ -x "$ROOT/.venv/bin/python" ] || "$PYTHON" -m venv "$ROOT/.venv"
"$ROOT/.venv/bin/python" -m pip install --quiet --upgrade pip
"$ROOT/.venv/bin/python" -m pip install --quiet -e "$ROOT/backend"

if [ "${SKIP_EXTENSION:-0}" != "1" ]; then
  if command -v npm >/dev/null 2>&1; then
    echo "==> Building the extension"
    (cd "$ROOT/extension" && npm ci --silent && npm run --silent build)
  else
    echo "WARNING: Node.js not found; the extension was not built (install Node 20+ and re-run)." >&2
  fi
fi

cat <<MSG

Done.
  Start the agent:    scripts/start-agent.sh
  Load the extension: chrome://extensions -> Developer mode -> Load unpacked -> $ROOT/extension/dist
  Pair it:            $ROOT/.venv/bin/python -m autofill_agent token   (paste into the extension popup)
  Review page:        http://127.0.0.1:${AUTOFILL_PORT:-8765}/ui/
MSG
