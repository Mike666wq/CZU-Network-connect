"""Real transient process tests; no external network or campus authentication."""
import base64
import json
import sys
import time
from threading import Event, Timer

import pytest
from campus_assistant.protocol import BoundedHttp, PortalError


def worker(monkeypatch, script):
    monkeypatch.setattr(BoundedHttp, '_worker_command', staticmethod(lambda: [sys.executable,'-c',script]))


def test_total_deadline_terminates_even_a_completely_blocked_request(monkeypatch):
    worker(monkeypatch,'import time;time.sleep(30)')
    import campus_assistant.protocol as protocol
    created=[]
    original=protocol.subprocess.Popen
    def capture(*args,**kwargs):
        child=original(*args,**kwargs);created.append(child);return child
    monkeypatch.setattr(protocol.subprocess,'Popen',capture)
    started=time.monotonic()
    with pytest.raises(PortalError,match='请求总超时'):
        BoundedHttp(timeout=0.5).get('https://blocked.test/')
    assert time.monotonic()-started<2
    assert len(created)==1 and created[0].poll() is not None
    assert created[0].stdin.closed and created[0].stdout.closed


def test_cancel_terminates_running_child_without_waiting_for_deadline(monkeypatch):
    worker(monkeypatch,'import time;time.sleep(30)')
    cancelled=Event();http=BoundedHttp(timeout=10);http.cancel_check=cancelled.is_set
    timer=Timer(0.3,cancelled.set);started=time.monotonic();timer.start()
    try:
        with pytest.raises(PortalError,match='检查已取消'):
            http.get('https://blocked.test/')
    finally:timer.join()
    assert time.monotonic()-started<2


def test_response_and_headers_cross_process_boundary(monkeypatch):
    response={'ok':True,'status':204,'body':'','encoding':'utf-8','final':'https://ok.test/',
              'headers':{'Content-Type':'text/plain'}}
    worker(monkeypatch,'import sys;sys.stdin.buffer.read();print('+repr(json.dumps(response))+')')
    http=BoundedHttp(timeout=3)
    assert http.get('https://ok.test/')[0:2]==(204,b'')
    assert http.last_headers=={'Content-Type':'text/plain'}


def test_safe_failure_is_returned_without_original_url(monkeypatch):
    worker(monkeypatch,'import sys;sys.stdin.buffer.read();print(\'{"ok":false,"error":"URLError"}\')')
    with pytest.raises(PortalError,match='^URLError$'):
        BoundedHttp(timeout=3).get('https://bad.test/?password=secret')


def test_large_response_does_not_deadlock_at_os_pipe_capacity(monkeypatch):
    data=b'large body ' * 50_000
    reply={'ok':True,'status':200,'body':base64.b64encode(data).decode(),'encoding':'utf-8',
           'final':'https://ok.test/','headers':{}}
    script="import sys,json,base64;sys.stdin.buffer.read();print(json.dumps({'ok':True,'status':200,'body':base64.b64encode(b'large body '*50000).decode(),'encoding':'utf-8','final':'https://ok.test/','headers':{}}))"
    worker(monkeypatch,script)
    assert BoundedHttp(timeout=3).get('https://ok.test/')[1]==data


def test_credentials_are_sent_on_stdin_not_command_line(monkeypatch):
    worker(monkeypatch,"import sys,json;request=json.load(sys.stdin);assert 'private-secret' not in str(sys.argv);assert 'private-secret' in request['url'];print(json.dumps({'ok':False,'error':'URLError'}))")
    with pytest.raises(PortalError,match='^URLError$'):
        BoundedHttp(timeout=3).get('http://portal.test/login?user_password=private-secret')


def test_lean_entry_import_does_not_load_qt_or_multiprocessing():
    import subprocess
    script="import sys;import main;assert not any(k.startswith('PySide6') for k in sys.modules);assert 'multiprocessing' not in sys.modules"
    subprocess.run([sys.executable,'-c',script],check=True)
