#!/usr/bin/env python3
"""Stage the current, unmodified core whitelist for the Android Python runtime."""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parents[2]
MODULES = ("__init__", "audit", "config", "engine", "presentation", "protocol", "scheduler", "service")
DEFAULT_OUTPUT = ROOT / "android_flutter/android/app/build/generated/python"


def stage_core(output_dir: Path = DEFAULT_OUTPUT, *, source_dir: Path = ROOT / "campus_assistant") -> Path:
    sources = [source_dir / (name + ".py") for name in MODULES]
    for source in sources:
        if not source.is_file():
            raise FileNotFoundError(source)
    package = output_dir / "campus_assistant"
    if package.resolve() == source_dir.resolve():
        raise ValueError("staging destination must differ from core source")
    output_dir.mkdir(parents=True, exist_ok=True)
    if package.exists():
        shutil.rmtree(package)
    package.mkdir()
    for source in sources:
        shutil.copyfile(source, package / source.name)
    return package


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT,
                        help="Python source root; campus_assistant is recreated inside it")
    args = parser.parse_args()
    print(stage_core(args.output_dir))


if __name__ == "__main__":
    main()
