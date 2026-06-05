#!/bin/zsh
cd "$(dirname "$0")"
PY="/Users/og/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
exec "$PY" -m review_migrator.gui

