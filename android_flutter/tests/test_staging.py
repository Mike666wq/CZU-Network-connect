import importlib.util
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "android_flutter/tools/stage_core.py"
spec = importlib.util.spec_from_file_location("stage_core", SCRIPT)
stage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage)


class StagingTests(unittest.TestCase):
    def test_default_location_and_whitelist(self):
        self.assertEqual(stage.DEFAULT_OUTPUT, ROOT / "android_flutter/android/app/build/generated/python")
        self.assertEqual(set(stage.MODULES), {"__init__", "audit", "config", "engine", "presentation",
                                              "protocol", "scheduler", "service"})

    def test_exact_source_bytes_freshness_and_no_stale_modules(self):
        with TemporaryDirectory() as private:
            base = Path(private)
            sources = base / "source"
            sources.mkdir()
            for name in stage.MODULES:
                (sources / (name + ".py")).write_bytes((ROOT / "campus_assistant" / (name + ".py")).read_bytes())
            (sources / "gui.py").write_text("raise AssertionError('must not be staged')")
            output = base / "generated/python"
            package = stage.stage_core(output, source_dir=sources)
            (package / "stale.py").touch()
            (sources / "engine.py").write_bytes((sources / "engine.py").read_bytes() + b"\n# future edit\n")
            stage.stage_core(output, source_dir=sources)
            self.assertEqual({p.name for p in package.iterdir()}, {name + ".py" for name in stage.MODULES})
            for name in stage.MODULES:
                self.assertEqual((package / (name + ".py")).read_bytes(), (sources / (name + ".py")).read_bytes())

    def test_cli_stages_importable_headless_core_and_bridge(self):
        with TemporaryDirectory() as private:
            output = Path(private) / "generated"
            staged = subprocess.run([sys.executable, str(SCRIPT), "--output-dir", str(output)],
                                    capture_output=True, text=True, check=True)
            self.assertEqual(staged.stdout.strip(), str(output / "campus_assistant"))
            env = dict(os.environ, PYTHONPATH=os.pathsep.join([
                str(output), str(ROOT / "android_flutter/python")]), PYTHONDONTWRITEBYTECODE="1")
            code = ("import campus_assistant, campus_android; from pathlib import Path; "
                    "assert Path(campus_assistant.__file__).parent == Path(" + repr(str(output / "campus_assistant")) + "); "
                    "assert campus_android.Bridge; "
                    "assert not any(n in __import__('sys').modules for n in ('PySide6', 'psutil', 'java'))")
            subprocess.run([sys.executable, "-c", code], cwd=private, env=env, check=True,
                           capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
