from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from copy import deepcopy
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

import campus_assistant.gui as main
from campus_assistant.engine import Outcome, State
from campus_assistant.config import ConfigError
from campus_assistant.protocol import PortalResult

_REAL_START_CHECK = main.Window.start_check


def fixture_config() -> dict:
    return {
        "enabled": True,
        "autostart": False,
        "active_profile": "public",
        "edit_profile": "public",
        "credential_mode": "shared",
        "portal_url": "http://legacy.test/",
        "username": "shared-user",
        "password": "shared-secret",
        "provider_suffix": "",
        "internet_probe_urls": ["https://probe1.test/", "https://probe2.test/"],
        "profiles": {
            "public": {"portal_url": "http://public.test/", "username": "p-user", "password": "p-pass", "provider_suffix": "@p"},
            "dorm": {"portal_url": "http://dorm.test/", "username": "d-user", "password": "d-pass", "provider_suffix": "@d"},
        },
    }


class FakeTray:
    class ActivationReason:
        Trigger = 1

    def __init__(self, *args, **kwargs):
        self.activated = SimpleNamespace(connect=lambda callback: None)
        self.messages = []

    def setIcon(self, *_): pass
    def setToolTip(self, *_): pass
    def setContextMenu(self, *_): pass
    def show(self): pass
    def hide(self): pass
    def showMessage(self, *args): self.messages.append(args)
    @staticmethod
    def isSystemTrayAvailable(): return False


class FakeService:
    def __init__(self, config):
        self.config = config
        self.profile_name = config.get("active_profile", "public")

    def probe_internet(self): return False, "offline"
    def identify_portal(self): return False
    def authenticate(self): return PortalResult(False, "unknown", "not called")


class FakeSignal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def emit(self):
        for callback in list(self.callbacks):
            callback()


@pytest.fixture
def gui(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    config = fixture_config()
    saved: list[dict] = []
    start_calls: list[main.Window] = []

    monkeypatch.setattr(main, "APP_DIR", tmp_path / "app-data")
    monkeypatch.setattr(main, "load_config", lambda: deepcopy(config))
    monkeypatch.setattr(main, "save_config", lambda cfg: saved.append(deepcopy(cfg)) or tmp_path / "config.json")
    monkeypatch.setattr(main, "CampusService", FakeService)
    monkeypatch.setattr(main, "QSystemTrayIcon", FakeTray)
    monkeypatch.setattr(main.Window, "apply_autostart", staticmethod(lambda enabled: None))
    monkeypatch.setattr(main.Window, "get_network_signature", staticmethod(lambda: "test-network"))

    class FakeNetworkInformation:
        @staticmethod
        def loadDefaultBackend(): return False

    monkeypatch.setitem(__import__("sys").modules, "PySide6.QtNetwork",
                        SimpleNamespace(QNetworkInformation=FakeNetworkInformation))
    monkeypatch.setattr(main.Window, "start_check", lambda self: start_calls.append(self))

    window = main.Window()
    window.timer.stop()
    if not hasattr(window, "network_info"):
        window.network_info = None
    start_calls.clear()
    try:
        yield SimpleNamespace(app=app, window=window, saved=saved, starts=start_calls, config=config)
    finally:
        window.timer.stop()
        window.hide()
        window.deleteLater()
        app.processEvents()


def test_timer_tick_starts_check_when_deadline_expires(gui):
    window = gui.window
    window.scheduler.deadline = 0.0
    window.network_signature = "test-network"

    window.timer_tick()

    assert gui.starts == [window]


def test_network_event_checks_deadline_without_undefined_clock(gui):
    window = gui.window
    window.network_info = SimpleNamespace(reachability=lambda: "reachable")
    window.network_signature = "test-network|reachability:unknown"

    window.network_event()

    assert gui.starts == [window]


def test_switching_editor_profile_keeps_each_portal_url_and_values(gui):
    window = gui.window
    window.fields["portal_url"].setText("http://changed-public.test/")
    window.fields["public_username"].setText("changed-public-user")

    window.edit_profile.setCurrentIndex(window.edit_profile.findData("dorm"))
    assert window.fields["portal_url"].text() == "http://dorm.test/"
    assert window.ui_profiles["public"]["portal_url"] == "http://changed-public.test/"
    assert window.ui_profiles["public"]["username"] == "changed-public-user"

    window.fields["portal_url"].setText("http://changed-dorm.test/")
    window.edit_profile.setCurrentIndex(window.edit_profile.findData("public"))
    assert window.fields["portal_url"].text() == "http://changed-public.test/"
    assert window.ui_profiles["dorm"]["portal_url"] == "http://changed-dorm.test/"

    window.save()
    assert gui.saved[-1]["profiles"]["public"]["portal_url"] == "http://changed-public.test/"
    assert gui.saved[-1]["profiles"]["dorm"]["portal_url"] == "http://changed-dorm.test/"


def test_old_worker_result_does_not_overwrite_reloaded_supervisor(gui):
    window = gui.window
    window.running = True
    old_supervisor = window.supervisor

    window.load_new_config()
    new_supervisor = window.supervisor
    assert new_supervisor is not old_supervisor
    before = new_supervisor.outcome

    window.check_done(Outcome(State.ERROR, "stale worker result", 60), old_supervisor)

    assert new_supervisor.outcome is before


def test_manual_pause_survives_loading_new_config(gui):
    window = gui.window
    window.toggle_pause()
    assert window.supervisor.paused
    window.load_new_config()
    assert window.supervisor.paused


def test_invalid_reload_pauses_then_valid_reload_restores_automatic_checks(gui, monkeypatch):
    window = gui.window
    state = {"invalid": True}
    def load():
        if state["invalid"]: raise ConfigError("invalid test config")
        return deepcopy(gui.config)
    monkeypatch.setattr(main, "load_config", load)
    monkeypatch.setattr(main.QMessageBox, "warning", lambda *args: None)

    window.reload_config()
    assert window.invalid_config and window.supervisor.paused
    state["invalid"] = False
    window.reload_config()
    assert not window.invalid_config
    assert not window.supervisor.paused
    assert gui.starts == [window]

def test_quit_waits_until_running_worker_returns(gui, monkeypatch):
    window = gui.window
    window.running = True
    class FakeThread:
        def __init__(self): self.finished = FakeSignal()

    window.thread = FakeThread()
    app_control = SimpleNamespace(quit=lambda: quit_calls.append("quit"))
    quit_calls: list[str] = []
    monkeypatch.setattr(main, "QApplication", app_control)

    window.quit_app()

    assert window.quit_after_check
    assert window.supervisor.paused
    assert quit_calls == []

    window.check_done(Outcome(State.PAUSED, "done", 60), window.supervisor)

    assert quit_calls == []

    window.thread.finished.emit()

    assert quit_calls == ["quit"]


def test_real_worker_delivers_online_result_to_window(gui):
    import time
    from campus_assistant.engine import Supervisor
    window = gui.window
    window.supervisor = Supervisor(lambda: (True, "fake"), lambda: False, lambda: None)
    _REAL_START_CHECK(window)
    deadline = time.monotonic() + 3
    while window.running and time.monotonic() < deadline:
        gui.app.processEvents()
        time.sleep(0.005)
    assert not window.running
    assert window.supervisor.outcome.state == State.ONLINE
    assert "互联网已连通" in window.status_label.text()
    assert not window.check_timer.isActive()


def test_progress_shows_elapsed_time_and_ignores_old_supervisor(gui):
    import time
    window = gui.window
    window.running = True
    window.check_started = time.monotonic() - 21
    window.check_progress("正在识别校园门户", window.supervisor)
    assert "正在识别校园门户" in window.status_label.text()
    assert "21 秒" in window.status_label.text()
    before = window.status_label.text()
    window.check_progress("stale", object())
    assert window.status_label.text() == before
    window.manual_paused = True
    window.update_check_progress()
    assert window.status_label.text() == before
    window.running = False


def test_worker_unexpected_exception_still_returns_safe_result():
    worker = main.Worker(SimpleNamespace(check=lambda **kwargs: (_ for _ in ()).throw(RuntimeError("secret"))))
    results = []
    worker.finished.connect(lambda outcome, supervisor: results.append(outcome))
    worker.run()
    assert len(results) == 1
    assert results[0].state == State.ERROR
    assert "secret" not in results[0].message


def test_dorm_provider_dropdown_saves_explicit_choice(gui):
    window = gui.window
    window.edit_profile.setCurrentIndex(window.edit_profile.findData('dorm'))
    assert window.dorm_provider.currentData() == '-1'
    window.dorm_provider.setCurrentIndex(window.dorm_provider.findData('@telecom'))
    window.store_editor_values('dorm')
    assert window.ui_profiles['dorm']['provider_suffix'] == '@telecom'
    assert window.ui_profiles['dorm']['provider_confirmed'] is True
    window.dorm_provider.setCurrentIndex(window.dorm_provider.findData(''))
    window.store_editor_values('dorm')
    assert window.ui_profiles['dorm']['provider_suffix'] == ''
    assert window.ui_profiles['dorm']['provider_confirmed'] is True


def test_scene_signal_switches_form_and_provider_without_changing_shared_credentials(gui):
    window = gui.window
    window.profile.setCurrentIndex(window.profile.findData('auto'))
    window.fields['username'].setText('shared-student')
    window.fields['password'].setText('shared-password')
    window.fields['portal_url'].setText('http://custom-public.test/')
    window.ui_profiles['dorm'].update(provider_suffix='@telecom', provider_confirmed=True)
    window.scene_identified('dorm', 'http://dorm.test/', window.supervisor)
    assert window.edit_profile.currentData() == 'dorm'
    assert window.fields['portal_url'].text() == 'http://dorm.test/'
    assert window.active_entrance_label.text() == '当前认证入口：http://dorm.test/'
    assert window.dorm_provider.currentData() == '@telecom'
    assert window.form.isRowVisible(window.dorm_provider)
    assert not window.form.isRowVisible(window.fields['public_suffix'])
    assert window.fields['username'].text() == 'shared-student'
    assert window.fields['password'].text() == 'shared-password'
    assert window.ui_profiles['public']['portal_url'] == 'http://custom-public.test/'
    assert window.profile.currentData() == 'auto'
    assert window.follow_scene.isChecked()
    window.scene_identified('public', 'http://portal.test/', window.supervisor)
    assert window.edit_profile.currentData() == 'public'
    assert window.fields['portal_url'].text() == 'http://custom-public.test/'
    assert not window.form.isRowVisible(window.dorm_provider)
    assert window.ui_profiles['dorm']['provider_suffix'] == '@telecom'
    assert window.fields['password'].text() == 'shared-password'


def test_stale_scene_signal_cannot_switch_current_form(gui):
    window = gui.window
    window.scene_identified('dorm', 'http://old.test/', object())
    assert window.edit_profile.currentData() == 'public'
    assert window.active_entrance_label.text() == '当前认证入口：等待识别'


def test_unsaved_provider_survives_scene_switch_round_trip(gui):
    window = gui.window
    window.scene_identified('dorm', 'http://dorm.test/', window.supervisor)
    window.dorm_provider.setCurrentIndex(window.dorm_provider.findData('@cmcc'))
    window.scene_identified('public', 'http://portal.test/', window.supervisor)
    window.scene_identified('dorm', 'http://dorm.test/', window.supervisor)
    assert window.dorm_provider.currentData() == '@cmcc'
    assert window.ui_profiles['dorm']['provider_confirmed'] is True
    assert window.ui_profiles['dorm']['provider_suffix'] == '@cmcc'


def test_explicit_noncurrent_edit_temporarily_disables_form_following(gui):
    window = gui.window
    window.scene_identified('dorm', 'http://dorm.test/', window.supervisor)
    window.edit_profile.setCurrentIndex(window.edit_profile.findData('public'))
    assert not window.follow_scene.isChecked()
    window.scene_identified('dorm', 'http://dorm.test/', window.supervisor)
    assert window.edit_profile.currentData() == 'public'
    assert 'dorm.test' in window.active_entrance_label.text()
    window.follow_scene.setChecked(True)
    assert window.edit_profile.currentData() == 'dorm'


def test_saved_provider_config_restarts_check_with_correct_scene_profile(gui, monkeypatch):
    window = gui.window
    window.profile.setCurrentIndex(window.profile.findData('auto'))
    window.scene_identified('dorm', 'http://dorm.test/', window.supervisor)
    window.dorm_provider.setCurrentIndex(window.dorm_provider.findData('@unicom'))
    monkeypatch.setattr(main, 'load_config', lambda: deepcopy(gui.saved[-1]))
    window.save()
    saved = gui.saved[-1]
    assert saved['active_profile'] == 'auto'
    assert saved['profiles']['dorm']['provider_suffix'] == '@unicom'
    assert saved['profiles']['dorm']['provider_confirmed'] is True
    assert saved['profiles']['dorm']['portal_url'] == 'http://dorm.test/'
    assert saved['profiles']['public']['portal_url'] == gui.config['profiles']['public']['portal_url']
    assert window.supervisor.auth_blocked is False
    assert gui.starts == [window]


def test_real_worker_scene_signal_switches_ui_before_missing_provider_result(gui, monkeypatch):
    import time
    from campus_assistant.service import CampusService
    from campus_assistant.engine import Supervisor
    from test_dorm_and_midnight import TwoScenes, dorm_config

    window = gui.window
    cfg = dorm_config(confirmed=False, active='auto')
    http = TwoScenes()
    window.config = cfg
    window.apply_config_to_ui()
    window.service = CampusService(cfg, http=http)
    window.supervisor = Supervisor(lambda: (False, 'offline'), window.service.identify_portal, window.service.authenticate)
    _REAL_START_CHECK(window)
    deadline = time.monotonic() + 3
    while window.running and time.monotonic() < deadline:
        gui.app.processEvents()
        time.sleep(0.005)
    assert not window.running
    assert window.supervisor.outcome.state == State.NEEDS_CONFIG
    assert '认证被拒绝' not in window.status_label.text()
    assert window.edit_profile.currentData() == 'dorm'
    assert window.fields['portal_url'].text() == 'http://dorm.test/'
    assert window.dorm_provider.currentData() == '-1'
    assert window.form.isRowVisible(window.dorm_provider)
    assert window.fields['username'].text() == 'shared-user'
    assert window.fields['password'].text() == 'shared-secret'
    assert window.active_entrance_label.text() == '当前认证入口：http://dorm.test/'
    assert not window.service.auth_submitted

    # Save selected provider and repeat through the real worker and fresh service.
    window.dorm_provider.setCurrentIndex(window.dorm_provider.findData('@cmcc'))
    monkeypatch.setattr(main, 'load_config', lambda: deepcopy(gui.saved[-1]))
    monkeypatch.setattr(main, 'CampusService', lambda config: CampusService(config, http=http))
    window.save()
    probes = iter([(False, 'offline'), (True, 'online')])
    window.supervisor.probe = lambda: next(probes)
    _REAL_START_CHECK(window)
    deadline = time.monotonic() + 3
    while window.running and time.monotonic() < deadline:
        gui.app.processEvents()
        time.sleep(0.005)
    assert not window.running
    assert window.supervisor.outcome.state == State.AUTHENTICATED
    assert window.service.profile_name == 'dorm'
    assert window.dorm_provider.currentData() == '@cmcc'
    assert window.service.auth_submitted
