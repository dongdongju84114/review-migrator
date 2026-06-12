#!/bin/zsh
set -e
cd "$(dirname "$0")"
PY="/Users/og/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
if ! "$PY" -c "import review_migrator.gui" >/dev/null 2>&1; then
  "$PY" -m pip install -e .
fi
exec "$PY" -m review_migrator.gui
