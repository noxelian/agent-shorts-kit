#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PYTHON_BIN="${PYTHON_BIN:-python3}"
"$PYTHON_BIN" -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ is required"'

if [[ ! -x .venv/bin/python ]]; then
  "$PYTHON_BIN" -m venv .venv
fi

./.venv/bin/pip install -r pipeline/requirements.txt
npm --prefix pipeline/remotion ci

if [[ ! -f pipeline/.env ]]; then
  cp .env.example pipeline/.env
  echo "Created pipeline/.env — add your provider key before generation."
fi

./.venv/bin/python -c 'from PIL import Image; import platform; print("Python/Pillow OK:", platform.machine())'
echo "Setup complete. Add references, configure pipeline/.env, then run:"
echo "  ./.venv/bin/python shorts.py doctor"
