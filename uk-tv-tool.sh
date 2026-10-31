#!/bin/sh
# Starts UK TV Tool on Linux, with the Python environment setup.sh made.
cd "$(dirname "$(readlink -f "$0")")" || exit 1
if [ -x .venv/bin/python ]; then
    PY=.venv/bin/python
else
    PY=python3
fi
exec "$PY" uk_tv_tool.py "$@"
