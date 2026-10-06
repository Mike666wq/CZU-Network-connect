"""Opt-in safe packaged smoke test, no user configuration or campus auth requests."""
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import threading


def run_smoke(output: Path):
    # Set BEFORE creating QApplication. Safe unattended runner test; not a native memory benchmark.
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from . import __version__, gui
    from .config import DEFAULT_CONFIG
    from .engine import State
    from .service import CampusService
    from .platform_ui import platform_name
    from .protocol import BoundedHttp

    output = output.resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    calls = []
    probe_errors = []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != '/probe':
                self.send_error(404); return
            calls.append('loopback')
            self.send_response(204); self.end_headers()
        def log_message(self, *_): pass
    server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
    server.daemon_threads=True
    threading.Thread(target=server.serve_forever,daemon=True).start()
    url = f'http://127.0.0.1:{server.server_port}/probe'
    class SafeService(CampusService):
        def probe_internet(self):
            try:
                status,body,_,_=self.probe_http.get(url)
            except Exception as exc:
                probe_errors.append(type(exc).__name__ + ': ' + str(exc))
                raise
            return status == 204 and not body, 'safe-loopback'
        def identify_portal(self):
            self.portal_known=False
            self.portal_error='冒烟测试：不访问校园门户'
            return False
        def authenticate(self):
            raise AssertionError('Authentication forbidden in smoke test')
    cfg=deepcopy(DEFAULT_CONFIG)
    cfg['autostart']=False
    gui.load_config=lambda:deepcopy(cfg)
    gui.APP_DIR=output.parent/'isolated-smoke-data'
    gui.CONFIG_PATH=gui.APP_DIR/'config.json'
    gui.CampusService=SafeService
    app=QApplication.instance() or QApplication(['safe-packaged-smoke'])
    app.setQuitOnLastWindowClosed(False)
    # CI runners may emit a reachabilityChanged event immediately after Qt starts,
    # which is correct for production but can cancel this deterministic loopback-only
    # probe before it sends its first request. Native network events are therefore
    # disabled only for this isolated smoke test.
    window=gui.Window(native_network_events=False);window.show()
    result={'ok':False,'version':__version__,'platform':platform_name(),
            'frozen':bool(getattr(sys,'frozen',False)),'scope':'offscreen UI and loopback-only HTTP, no personal config',
            'auth_requests':0}
    timer=QTimer(window);timer.setInterval(50)
    completed=[False]
    def finish(ok,error=''):
        if completed[0]:return
        completed[0]=True;timer.stop()
        result.update(ok=ok,error=error,loopback_requests=len(calls),probe_errors=probe_errors)
        output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        window.hide();window.timer.stop();window.countdown_timer.stop();app.exit(0 if ok else 1)
    def inspect():
        if window.running:return
        try:
            assert window.supervisor.outcome.state==State.ONLINE,window.supervisor.outcome.state.value
            assert calls,'Production HTTP worker did not reach loopback server'
            assert not window.service.auth_submitted
            assert window.countdown_timer.isActive()
            assert '秒' in window.countdown_value.text()
            assert platform_name() in window.windowTitle()
            # Render dorm layout with an isolated draft, without invoking an auth endpoint.
            window.ui_profiles['dorm'].update(provider_suffix='@cmcc',provider_confirmed=True)
            window.scene_identified('dorm','http://172.19.0.1/',window.supervisor)
            assert window.edit_profile.currentData()=='dorm'
            assert window.dorm_provider.currentData()=='@cmcc'
            app.processEvents()
            window.grab().save(str(output.with_suffix('.png')))
            window.hide();app.processEvents()
            assert not window.countdown_timer.isActive()
            assert window.timer.isActive()
            window.show();app.processEvents()
            assert window.countdown_timer.isActive()
            result.update(probe_verified=True,form_follow_verified=True,background_timer_verified=True,
                          worker_name=Path(BoundedHttp._worker_command()[0]).name)
            finish(True)
        except Exception as exc:
            finish(False,type(exc).__name__ + ': ' + str(exc))
    timer.timeout.connect(inspect);timer.start()
    def timeout():
        if completed[0]:return
        window.supervisor.set_paused(True)
        # Let the bounded worker return before exiting its Qt thread.
        QTimer.singleShot(500,lambda:finish(False,'Packaged smoke test timed out'))
    QTimer.singleShot(20000,timeout)
    code=app.exec()
    server.shutdown();server.server_close()
    return code
