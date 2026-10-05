"""Explicit opt-in, loopback-only resource profiling. No personal config or real authentication."""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit


def run_session(window_type, namespace: dict, report_path: Path, soak_cycles: int = 0) -> int:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from .config import DEFAULT_CONFIG
    from .service import CampusService
    from .protocol import BoundedHttp

    report_path = report_path.resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    meta = {'pid': os.getpid(), 'phase': 'warmup', 'loopback_requests': 0,
            'auth_requests': 0, 'mode': 'loopback-only', 'soak_cycles': soak_cycles}

    def publish():
        temp = report_path.with_suffix('.tmp')
        temp.write_text(json.dumps(meta), encoding='utf-8')
        temp.replace(report_path)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != '/probe':
                self.send_error(404); return
            meta['loopback_requests'] += 1
            time.sleep(1.25)
            self.send_response(204); self.end_headers()
        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    probe_url = f'http://127.0.0.1:{server.server_port}/probe'

    class SafeService(CampusService):
        def probe_internet(self):
            # Use the exact production bounded transport, but target only our own local server.
            assert urlsplit(probe_url).hostname == '127.0.0.1'
            status, body, _, _ = self.probe_http.get(probe_url)
            return status == 204 and not body, 'profile-loopback'
        def identify_portal(self):
            self.portal_known = False
            self.portal_error = '性能测试：不访问校园门户'
            return False
        def authenticate(self):
            raise AssertionError('Authentication is forbidden in resource profiling')

    cfg = deepcopy(DEFAULT_CONFIG)
    cfg['autostart'] = False
    cfg['username'] = ''; cfg['password'] = ''
    namespace['load_config'] = lambda: deepcopy(cfg)
    namespace['CampusService'] = SafeService
    namespace['APP_DIR'] = report_path.parent / 'isolated-profile-data'
    namespace['CONFIG_PATH'] = namespace['APP_DIR'] / 'config.json'
    namespace['save_config'] = lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError('Save disabled during profiling'))

    app = QApplication.instance() or QApplication(['campus-resource-profile'])
    app.setQuitOnLastWindowClosed(False)
    window = window_type()
    window.show()
    publish()
    running = QTimer(window)
    running.setInterval(3500)
    running.timeout.connect(window.start_check)
    started = time.monotonic()
    soak_started = None
    soak_start_count = 0
    transitions = QTimer(window)
    transitions.setInterval(100)

    def set_phase(phase):
        if meta['phase'] != phase:
            meta['phase'] = phase
            publish()

    def finish():
        if window.running:
            return
        running.stop(); transitions.stop(); window.timer.stop()
        window.countdown_timer.stop()
        meta['phase'] = 'complete'
        meta['duration_seconds'] = round(time.monotonic() - started, 2)
        # Production request processes have completed when window.running is false.
        meta['remaining_http_children'] = []
        meta['request_running_at_finish'] = window.running
        publish()
        window.hide(); app.quit()

    def advance():
        nonlocal soak_started, soak_start_count
        elapsed = time.monotonic() - started
        if elapsed < 5:
            return
        if elapsed < 15:
            set_phase('visible_idle')
        elif elapsed < 30:
            if meta['phase'] != 'hidden_idle':
                window.hide()
                set_phase('hidden_idle')
        elif elapsed < 45:
            if meta['phase'] != 'active_checks':
                window.show()
                set_phase('active_checks')
                window.start_check(); running.start()
        elif elapsed < 60:
            if meta['phase'] != 'hidden_after_checks':
                running.stop()
                window.hide()
                set_phase('hidden_after_checks')
        elif soak_cycles:
            if soak_started is None:
                running.stop(); window.hide(); window.timer.stop()
                soak_started = time.monotonic(); soak_start_count = meta['loopback_requests']
                set_phase('repeated_checks')
            completed = meta['loopback_requests'] - soak_start_count
            if completed >= soak_cycles and not window.running:
                finish()
            elif not window.running:
                window.start_check()
        else:
            finish()
        if time.monotonic() - started > 240:
            window.supervisor.set_paused(True)
            finish()

    transitions.timeout.connect(advance)
    transitions.start()
    result = app.exec()
    server.shutdown(); server.server_close()
    return result
