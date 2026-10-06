"""Prune Qt modules/plugins that the Widgets-only desktop UI does not use.

Run after PyInstaller embeds the HTTP helper and before the final bundle is
signed. The allow/deny lists are intentionally explicit so a future UI feature
cannot silently lose a dependency.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil


UNUSED_PLUGIN_DIRS = (
    "platforminputcontexts",
    "generic",
    "imageformats",
    "iconengines",
    "tls",
)
UNUSED_QT_FRAMEWORKS = (
    "QtPdf",
    "QtSvg",
    "QtVirtualKeyboard",
    "QtVirtualKeyboardQml",
    "QtQuick",
    "QtQml",
    "QtQmlMeta",
    "QtQmlModels",
    "QtQmlWorkerScript",
    "QtOpenGL",
)
REQUIRED_PATHS = (
    "Contents/Frameworks/PySide6/Qt/lib/QtCore.framework",
    "Contents/Frameworks/PySide6/Qt/lib/QtGui.framework",
    "Contents/Frameworks/PySide6/Qt/lib/QtWidgets.framework",
    "Contents/Frameworks/PySide6/Qt/lib/QtNetwork.framework",
    "Contents/Frameworks/PySide6/Qt/plugins/platforms/libqcocoa.dylib",
    "Contents/Frameworks/PySide6/Qt/plugins/networkinformation/libqapplenetworkinformation.dylib",
    "Contents/Helpers/campus-http-worker.app",
)


def _remove(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)


def prune(app: Path) -> dict[str, int]:
    app = app.resolve()
    if app.suffix != ".app" or not (app / "Contents").is_dir():
        raise ValueError("Expected a macOS .app bundle")
    for relative in REQUIRED_PATHS:
        if not (app / relative).exists():
            raise ValueError(f"Required bundle component missing before pruning: {relative}")

    qt = app / "Contents/Frameworks/PySide6/Qt"
    frameworks = app / "Contents/Frameworks"
    resources = app / "Contents/Resources"
    removed_plugins = 0
    removed_frameworks = 0

    for name in UNUSED_PLUGIN_DIRS:
        path = qt / "plugins" / name
        if path.exists() or path.is_symlink():
            _remove(path)
            removed_plugins += 1

    for name in UNUSED_QT_FRAMEWORKS:
        targets = (qt / "lib" / f"{name}.framework", frameworks / name, resources / name)
        found = any(path.exists() or path.is_symlink() for path in targets)
        for path in targets:
            _remove(path)
        removed_frameworks += int(found)

    for relative in REQUIRED_PATHS:
        if not (app / relative).exists():
            raise RuntimeError(f"Pruning removed required bundle component: {relative}")
    return {"plugin_dirs": removed_plugins, "qt_frameworks": removed_frameworks}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", type=Path)
    result = prune(parser.parse_args().app)
    print(f"Pruned {result['plugin_dirs']} unused Qt plugin groups and "
          f"{result['qt_frameworks']} unused Qt framework groups.")
