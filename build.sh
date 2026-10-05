#!/bin/sh
set -eu
cd "$(dirname "$0")"
PYTHON=${PYTHON:-.venv/bin/python}
PYINSTALLER_CONFIG_DIR="$PWD/.cache/pyinstaller"
export PYINSTALLER_CONFIG_DIR
if [ ! -x "$PYTHON" ]; then
  echo "Create .venv and install requirements-dev.txt first" >&2
  exit 1
fi
"$PYTHON" -m PyInstaller --noconfirm --windowed --name "校园网助手" \
  --osx-bundle-identifier com.codex.campus-network-assistant main.py
echo "Built dist/校园网助手.app"
