#!/bin/sh
set -eu
cd "$(dirname "$0")"
PYTHON=${PYTHON:-.venv/bin/python}
export PYINSTALLER_CONFIG_DIR="$PWD/.cache/pyinstaller"
if [ ! -x "$PYTHON" ]; then
  echo "Create .venv and install requirements-release.txt first" >&2
  exit 1
fi
VERSION=$("$PYTHON" -c 'from campus_assistant import __version__; print(__version__)')
"$PYTHON" -c 'import platform,sys; assert sys.platform == "darwin" and platform.machine() == "arm64", "Build the Mac M-series app on an arm64 macOS host"'
"$PYTHON" -m PyInstaller --noconfirm --clean --windowed --noupx --name "校园网助手" \
  --target-architecture arm64 --osx-bundle-identifier io.github.Mike666wq.czu-network-connect main.py
# Changing the generated plist requires re-signing the bundle; this is not Apple notarization.
"$PYTHON" - "$VERSION" <<'PY'
from pathlib import Path
import plistlib
import sys
path = Path('dist/校园网助手.app/Contents/Info.plist')
with path.open('rb') as handle:
    data = plistlib.load(handle)
data['CFBundleShortVersionString'] = sys.argv[1]
data['CFBundleVersion'] = sys.argv[1]
with path.open('wb') as handle:
    plistlib.dump(data, handle)
PY
codesign --force --deep --sign - 'dist/校园网助手.app'
codesign --verify --deep --strict 'dist/校园网助手.app'
echo "Built Mac M-series app v$VERSION: dist/校园网助手.app"
