"""Lean request entry and safe profiling invariants; never access external networks."""
from pathlib import Path
import json
import subprocess
import sys


def test_worker_handles_bad_input_without_loading_gui_or_echoing_secrets():
    result=subprocess.run([sys.executable,'main.py','--http-worker'],input=b'{broken private-secret',capture_output=True,check=True)
    reply=json.loads(result.stdout)
    assert reply['ok'] is False
    assert reply['error'] == 'JSONDecodeError'
    assert b'private-secret' not in result.stdout
    assert result.stderr == b''


def test_worker_argument_does_not_import_gui_module():
    # Abort after checking dispatcher selection, before any actual HTTP request.
    script="import sys,main,campus_assistant.protocol as p;p.http_worker_entry=lambda:0;sys.argv=['main.py','--http-worker'];assert main.main()==0;assert not any(k.startswith('PySide6') for k in sys.modules)"
    subprocess.run([sys.executable,'-c',script],check=True)


def test_runtime_source_has_no_resource_tracker_transport():
    source=Path('campus_assistant/protocol.py').read_text()
    assert 'import multiprocessing' not in source
    assert 'subprocess.Popen' in source
    assert 'stderr=subprocess.DEVNULL' in source
