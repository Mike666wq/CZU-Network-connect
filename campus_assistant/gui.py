from __future__ import annotations

import os
import plistlib
import time
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

from PySide6.QtCore import QObject, QTimer, Signal, Slot
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton, QSystemTrayIcon, QVBoxLayout, QWidget, QMenu)

from campus_assistant import __version__
from campus_assistant.config import APP_DIR, CONFIG_PATH, DORM_PROVIDERS, ConfigError, load_config, save_config
from campus_assistant.engine import Outcome, State, Supervisor
from campus_assistant.service import CampusService
from campus_assistant.scheduler import PollScheduler
from campus_assistant.audit import record_event
from campus_assistant.dashboard import build_workspace, countdown_remaining
from campus_assistant.platform_ui import platform_name


class Worker(QObject):
    finished = Signal(object, object)
    progress = Signal(str, object)
    scene_identified = Signal(str, str, object)

    def __init__(self, supervisor: Supervisor, force: bool = False):
        super().__init__(); self.supervisor = supervisor; self.force = force

    @Slot()
    def run(self):
        self.supervisor.progress = lambda message: self.progress.emit(message, self.supervisor)
        self.supervisor.scene_changed = lambda name, entrance: self.scene_identified.emit(name, entrance, self.supervisor)
        try:
            outcome = self.supervisor.check(force=self.force)
        except Exception:
            # Always release the GUI's running state; never expose credentials from exceptions.
            outcome = Outcome(State.ERROR, "后台检查失败，请点击重试", 30)
        finally:
            self.supervisor.progress = lambda message: None
            self.supervisor.scene_changed = lambda name, entrance: None
        self.finished.emit(outcome, self.supervisor)


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("校园网助手 · v" + __version__ + " · " + platform_name())
        self.resize(520, 470)
        self.fields: dict[str, QLineEdit] = {}
        self.running = False
        self.next_reason = "startup"
        self.running_reason = "startup"
        self.worker_result = None
        self.check_started = 0.0
        self.check_phase = "正在检查网络"
        self.check_timer = QTimer(self)
        self.check_timer.setInterval(1000)
        self.check_timer.timeout.connect(self.update_check_progress)
        self.quit_after_check = False
        self.loading_config = False
        self.syncing_scene = False
        self.detected_scene = ""
        self.detected_entrance = ""
        self.manual_paused = False
        self.invalid_config = False
        self.config = load_config()
        self.ui_profiles = deepcopy(self.config["profiles"])
        self.service = CampusService(self.config)
        self.supervisor = Supervisor(self.service.probe_internet, self.service.identify_portal, self.service.authenticate)
        self.build_ui()
        self.apply_config_to_ui()
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.timer_tick)
        self.network_poll_timer = QTimer(self)
        self.network_poll_timer.setInterval(60_000)
        self.network_poll_timer.timeout.connect(self.poll_network_signature)
        self.network_poll_timer.start()
        self.network_signature = self.get_network_signature()
        self.scheduler = PollScheduler(time.monotonic(), self.network_signature,
                                       datetime.now(ZoneInfo("Asia/Shanghai")))
        self.countdown_timer = QTimer(self)
        self.countdown_timer.setInterval(1000)
        self.countdown_timer.timeout.connect(self.refresh_countdown)
        if self.isVisible():
            self.countdown_timer.start()
        self.refresh_countdown()
        self.tray = QSystemTrayIcon(self)
        self.tray.setIcon(self.style().standardIcon(self.style().StandardPixmap.SP_ComputerIcon))
        self.tray.setToolTip("校园网助手")
        tray_menu = QMenu(self)
        for label, slot in (("显示窗口", self.showNormal), ("立即检查", self.start_check), ("退出", self.quit_app)):
            act = tray_menu.addAction(label); act.triggered.connect(slot)
        self.tray.setContextMenu(tray_menu)
        self.tray.activated.connect(lambda reason: self.showNormal() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        self.tray.show()
        menu = self.menuBar()
        file_menu = menu.addMenu("操作")
        for label, slot in (("立即检查", self.start_check), ("重试", self.retry), ("暂停/恢复", self.toggle_pause),
                            ("打开配置文件夹", self.open_folder), ("退出", self.quit_app)):
            act = QAction(label, self); act.triggered.connect(slot); file_menu.addAction(act)
        self.hide_on_close = True
        self.pending = False; self.pending_force = False
        self.network_info = None
        try:
            from PySide6.QtNetwork import QNetworkInformation
            if QNetworkInformation.loadDefaultBackend():
                self.network_info = QNetworkInformation.instance()
                self.network_info.reachabilityChanged.connect(lambda *_: self.network_event())
        except (ImportError, AttributeError):
            self.network_info = None
        self.start_check()

    @Slot()
    def refresh_countdown(self, now_monotonic=None, now_wall=None):
        """Presentation only; uses saved settings and never dispatches network work."""
        if not hasattr(self, "scheduler"):
            return
        if self.quit_after_check:
            value, detail = "退出中", "正在停止后台任务"
        elif not self.config.get("enabled", True):
            value, detail = "已关闭", "自动检查未启用\n修改后请保存配置"
        elif self.invalid_config:
            value, detail = "待配置", "配置文件无效\n修正后重新加载"
        elif self.manual_paused or self.supervisor.paused:
            value, detail = "已暂停", "恢复后重新检查"
        elif self.running:
            value, detail = "检查中", "本轮结束后重新计时\n正在等待实际响应"
        else:
            monotonic = time.monotonic() if now_monotonic is None else now_monotonic
            wall = datetime.now(ZoneInfo("Asia/Shanghai")) if now_wall is None else now_wall
            remaining = countdown_remaining(self.scheduler, monotonic, wall)
            value = f"{remaining} 秒"
            if remaining == 0:
                detail = "已到检查时间，等待后台调度"
            elif self.supervisor.auth_blocked:
                detail = "仍会检查网络 · 认证待处理\n23:58–00:15 午夜恢复窗口"
            else:
                detail = "稳定在线约 10 分钟检查一次\n23:58–00:15 午夜恢复窗口"
        self.countdown_value.setText(value)
        self.schedule_label.setText(detail)

    def build_ui(self):
        self._ui_config_path = CONFIG_PATH
        build_workspace(self)

    def apply_config_to_ui(self):
        cfg = self.config
        self.loading_config = True
        self.ui_profiles = deepcopy(cfg["profiles"])
        self.enabled.setChecked(cfg.get("enabled", True)); self.autostart.setChecked(cfg.get("autostart", False))
        self.cred_mode.setCurrentIndex(self.cred_mode.findData(cfg.get("credential_mode", "shared")))
        self.profile.setCurrentIndex(self.profile.findData(cfg.get("active_profile", "public")))
        self.edit_profile.setCurrentIndex(self.edit_profile.findData(cfg.get("edit_profile", "public")))
        for key in ("username", "password"):
            self.fields[key].setText(str(cfg.get(key, "")))
        self.refresh_profile_fields(); self.apply_mode_visibility()
        self.loading_config = False
        self.last_edit_profile = self.edit_profile.currentData() or "public"
        if self.detected_scene:
            self.sync_scene_editor(self.detected_scene)

    def refresh_profile_fields(self):
        name = self.edit_profile.currentData() or "public"
        p = self.ui_profiles[name]
        self.fields["portal_url"].setText(p.get("portal_url", ""))
        for suffix, key in (("username", "username"), ("password", "password"), ("suffix", "provider_suffix")):
            self.fields[f"{name}_{suffix}"].setText(p.get(key, ""))
        if name == "dorm":
            confirmed = p.get("provider_confirmed", bool(p.get("provider_suffix", "")))
            value = p.get("provider_suffix", "") if confirmed else "-1"
            index = self.dorm_provider.findData(value)
            was_blocked = self.dorm_provider.blockSignals(True)
            try:
                self.dorm_provider.setCurrentIndex(max(0, index))
            finally:
                self.dorm_provider.blockSignals(was_blocked)

    def dorm_provider_changed(self):
        if self.loading_config:
            return
        value = self.dorm_provider.currentData()
        self.fields["dorm_suffix"].setText(value if value != "-1" else "")
        self.ui_profiles["dorm"]["provider_suffix"] = value if value != "-1" else ""
        self.ui_profiles["dorm"]["provider_confirmed"] = value != "-1"

    def profile_changed(self):
        self.apply_mode_visibility()

    def edit_profile_changed(self):
        if self.loading_config: return
        if not self.syncing_scene:
            self.follow_scene.setChecked(False)
        self.store_editor_values(self.last_edit_profile)
        self.last_edit_profile = self.edit_profile.currentData() or "public"
        self.refresh_profile_fields(); self.apply_mode_visibility()

    def follow_scene_changed(self, enabled):
        if enabled and self.detected_scene:
            self.sync_scene_editor(self.detected_scene)

    def sync_scene_editor(self, name):
        if not self.follow_scene.isChecked() or name not in {"public", "dorm"}:
            return
        self.syncing_scene = True
        try:
            self.edit_profile.setCurrentIndex(self.edit_profile.findData(name))
        finally:
            self.syncing_scene = False

    @Slot(str, str, object)
    def scene_identified(self, name, entrance, worker_supervisor):
        # Immutable signal payloads; ignore events from a reloaded or cancelled worker.
        if worker_supervisor is not self.supervisor or self.manual_paused or self.invalid_config:
            return
        if name not in {"public", "dorm"}:
            return
        changed = (self.detected_scene, self.detected_entrance) != (name, entrance)
        self.detected_scene, self.detected_entrance = name, entrance
        self.scene_label.setText("当前识别场景：" + {"public": "公共网", "dorm": "宿舍网"}[name])
        self.active_entrance_label.setText("当前认证入口：" + entrance)
        self.sync_scene_editor(name)
        if changed and self.follow_scene.isChecked():
            QTimer.singleShot(0, lambda: self.reveal_active_form(worker_supervisor))
        if changed:
            self.dashboard.add_event("已识别" + {"public": "公共网", "dorm": "宿舍网"}[name] + "，表单已同步" if self.follow_scene.isChecked() else "已识别当前场景，保留手动编辑表单")

    def reveal_active_form(self, worker_supervisor):
        if worker_supervisor is self.supervisor and self.follow_scene.isChecked():
            target = self.dorm_provider if self.edit_profile.currentData() == "dorm" else self.fields["portal_url"]
            self.config_scroll.ensureWidgetVisible(target, 0, 12)

    def store_editor_values(self, name: str | None = None):
        if not hasattr(self, "ui_profiles"): return
        name = name or self.edit_profile.currentData() or "public"
        p = self.ui_profiles[name]
        p.update(portal_url=self.fields["portal_url"].text(),
            username=self.fields[f"{name}_username"].text(), password=self.fields[f"{name}_password"].text(),
            provider_suffix=self.fields[f"{name}_suffix"].text())
        if name == "dorm":
            value = self.dorm_provider.currentData()
            p["provider_suffix"] = value if value != "-1" else ""
            p["provider_confirmed"] = self.dorm_provider.currentData() != "-1"

    def apply_mode_visibility(self):
        shared = self.cred_mode.currentData() == "shared"
        for k in ("username", "password"): self.form.setRowVisible(self.fields[k], shared)
        active = self.edit_profile.currentData() or "public"
        for p in ("public", "dorm"):
            self.form.setRowVisible(self.fields[f"{p}_username"], not shared and p == active)
            self.form.setRowVisible(self.fields[f"{p}_password"], not shared and p == active)
            self.form.setRowVisible(self.fields[f"{p}_suffix"], p == active and p == "public")
        self.form.setRowVisible(self.dorm_provider, active == "dorm")

    def save(self):
        old_autostart = self.config.get("autostart", False)
        cfg = self.config.copy(); cfg["enabled"] = self.enabled.isChecked(); cfg["autostart"] = self.autostart.isChecked()
        cfg["credential_mode"] = self.cred_mode.currentData(); cfg["active_profile"] = self.profile.currentData()
        cfg["edit_profile"] = self.edit_profile.currentData()
        self.store_editor_values()
        for key in ("username", "password"): cfg[key] = self.fields[key].text()
        cfg["profiles"] = deepcopy(self.ui_profiles)
        try:
            save_config(cfg); self.replace_config(load_config())
            self.invalid_config = False
            if cfg["autostart"] != old_autostart: self.apply_autostart(cfg["autostart"])
            self.set_status(State.WAITING, "配置已保存并生效")
            if not self.manual_paused and not self.running: self.start_check()
        except (ConfigError, OSError) as exc:
            self.invalid_config = True
            self.supervisor.set_paused(True)
            QMessageBox.warning(self, "配置无效", str(exc))

    def load_new_config(self):
        self.replace_config(load_config())

    def replace_config(self, config):
        old = self.supervisor
        old.set_paused(True)
        if self.running: self.pending = True
        self.config = config; self.service = CampusService(self.config)
        self.supervisor = Supervisor(self.service.probe_internet, self.service.identify_portal, self.service.authenticate)
        self.invalid_config = False
        # A reload must not revert the form to a legacy public editor while at the dorm.
        if self.manual_paused: self.supervisor.set_paused(True)

    def reload_config(self):
        old_autostart = self.config.get("autostart", False)
        try:
            config = load_config()
            self.replace_config(config)
            if config.get("autostart", False) != old_autostart: self.apply_autostart(config.get("autostart", False))
            self.apply_config_to_ui(); self.set_status(State.WAITING, "已重载配置文件")
            if not self.manual_paused and not self.running: self.start_check()
        except (ConfigError, OSError) as exc:
            self.invalid_config = True
            self.supervisor.set_paused(True); self.set_status(State.NEEDS_CONFIG, str(exc))
            QMessageBox.warning(self, "配置文件无效", f"自动认证已暂停，请修正配置文件后再次重载。\n{exc}")

    def current_network_signature(self):
        signature = self.get_network_signature()
        if self.network_info is not None:
            signature += f"|reachability:{self.network_info.reachability()}"
        return signature

    def arm_scheduler_timer(self):
        """Sleep until the actual heartbeat/recovery deadline instead of polling every five seconds."""
        self.timer.stop()
        if (self.running or self.quit_after_check or self.manual_paused or self.invalid_config or
                not self.config.get("enabled", True) or self.supervisor.paused):
            return
        seconds = self.scheduler.seconds_until_due(
            time.monotonic(), datetime.now(ZoneInfo("Asia/Shanghai")))
        self.timer.start(max(1, seconds * 1000))

    def timer_tick(self):
        signature = self.current_network_signature()
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        tick = self.scheduler.tick(time.monotonic(), now, signature,
                                   max(1, self.supervisor.outcome.next_seconds))
        self.network_signature = signature
        if tick.network_changed:
            self.supervisor.network_changed(signature)
        if not tick.due:
            self.arm_scheduler_timer()
            return
        self.next_reason = ("network" if tick.network_changed else "wake" if tick.woke else
                            "midnight" if tick.special_time and now.hour == 23 else
                            "midnight_extra" if tick.special_time else "heartbeat")
        if self.running:
            if tick.network_changed or tick.special_time or tick.woke:
                self.pending = True
        else:
            self.start_check()

    def poll_network_signature(self):
        """Low-frequency fallback for platforms that miss a native network-change event."""
        signature = self.current_network_signature()
        if signature != self.network_signature:
            self.handle_network_change(signature)
            return
        if self.scheduler.seconds_until_due(
                time.monotonic(), datetime.now(ZoneInfo("Asia/Shanghai"))) == 0:
            self.timer_tick()

    def handle_network_change(self, signature):
        if signature == self.network_signature:
            return
        self.network_signature = signature
        self.supervisor.network_changed(signature)
        self.scheduler.reschedule(time.monotonic(), max(1, self.supervisor.outcome.next_seconds))
        self.pending = self.running
        self.next_reason = "network"
        if not self.running and not (self.manual_paused or self.invalid_config or self.supervisor.paused):
            self.start_check()

    def network_event(self):
        self.handle_network_change(self.current_network_signature())

    @staticmethod
    def get_network_signature():
        try:
            import psutil
            return "|".join(sorted(f"{name}:{a.address}" for name, values in psutil.net_if_addrs().items()
                for a in values if a.family.name in {"AF_INET", "AF_INET6"} and not a.address.startswith("127.")))
        except Exception:
            return "unknown"

    def start_check(self):
        if self.running:
            self.pending = True; return
        if not self.config.get("enabled", True): return
        self.timer.stop()
        from PySide6.QtCore import QThread
        force = self.pending_force; self.pending_force = False; self.pending = False
        self.running_reason = self.next_reason
        self.next_reason = "manual"
        self.running = True; self.thread = QThread(self); self.worker = Worker(self.supervisor, force); self.worker.moveToThread(self.thread)
        self.worker_result = None
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.check_progress)
        self.worker.scene_identified.connect(self.scene_identified)
        self.worker.finished.connect(self.worker_result_ready); self.worker.finished.connect(self.thread.quit)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread_finished)
        self.thread.finished.connect(self.thread.deleteLater)
        self.check_started = time.monotonic()
        self.check_phase = "正在检查网络"
        if self.isVisible():
            self.check_timer.start()
        self.update_check_progress()
        self.dashboard.begin(self.running_reason)
        self.refresh_countdown()
        self.thread.start()

    @Slot(str, object)
    def check_progress(self, message, worker_supervisor):
        if self.running and worker_supervisor is self.supervisor:
            self.check_phase = message
            self.dashboard.progress(message)
            self.update_check_progress()

    @Slot()
    def update_check_progress(self):
        if not self.running or self.manual_paused or self.invalid_config or self.quit_after_check:
            return
        elapsed = max(0, int(time.monotonic() - self.check_started))
        suffix = "；请求仍在等待，可暂停并等待当前请求结束" if elapsed >= 20 else ""
        self.status_label.setText(f"{self.check_phase}…（已等待 {elapsed} 秒{suffix}）")
        self.dashboard.elapsed.setText(f"本轮已用时 {elapsed:02d} 秒 · 正在等待实际响应")

    @Slot(object, object)
    def worker_result_ready(self, outcome, worker_supervisor):
        self.worker_result = (outcome, worker_supervisor)

    @Slot()
    def thread_finished(self):
        if self.worker_result is not None:
            self.check_done(*self.worker_result)
        if self.quit_after_check:
            QApplication.quit()

    def check_done(self, outcome, worker_supervisor):
        self.check_timer.stop()
        self.running = False
        if worker_supervisor is self.supervisor:
            if self.invalid_config:
                self.set_status(State.NEEDS_CONFIG, "配置文件无效，自动检查已暂停")
            elif self.manual_paused:
                self.set_status(State.PAUSED, "自动检查已暂停")
            else:
                self.set_status(outcome.state, outcome.message)
            detected = getattr(self.service, "profile_name", "") if getattr(self.service, "portal_known", False) else ""
            detail = getattr(self.service, "portal_error", "") if not detected else ""
            if detected:
                self.scene_identified(detected, getattr(self.service, "profile", {}).get("portal_url", ""), worker_supervisor)
            elif not self.manual_paused:
                self.detected_scene = ""
                self.detected_entrance = ""
                self.scene_label.setText("当前识别场景：未确认" + ("；" + detail if detail else ""))
                self.active_entrance_label.setText("当前认证入口：未确认（未提交凭据）")
            record_event(APP_DIR / "events.jsonl", state=outcome.state.value, scene=detected,
                         next_seconds=outcome.next_seconds,
                         auth_attempted=getattr(self.service, "auth_submitted", False), reason=self.running_reason)
            if outcome.notify: self.tray.showMessage("校园网认证", outcome.message)
            self.supervisor.outcome = outcome
            self.scheduler.reschedule(time.monotonic(), max(1, outcome.next_seconds))
            self.arm_scheduler_timer()
            self.refresh_countdown()
        else:
            self.pending = True
        if self.quit_after_check:
            self.thread.finished.connect(QApplication.quit)
            return
        if self.pending:
            QTimer.singleShot(0, self.start_check)

    def set_status(self, state, message):
        self.status_label.setText(f"{state.value}：{message}")
        self.dashboard.finish(state, message, getattr(self.service, "auth_submitted", False))
        needs_provider = state == State.NEEDS_CONFIG and "服务商" in message
        self.dorm_provider.setStyleSheet("border: 1px solid #efc27d;" if needs_provider else "")
        if needs_provider:
            QTimer.singleShot(0, lambda: self.reveal_active_form(self.supervisor))
        self.refresh_countdown()
    def retry(self):
        self.next_reason = "retry"
        if self.running: self.pending = True; self.pending_force = True; return
        self.supervisor.auth_blocked = False
        self.supervisor.unknown_count = 0
        self.supervisor.offline_count = 0
        self.start_check()
    def toggle_pause(self):
        self.manual_paused = not self.manual_paused
        self.supervisor.set_paused(self.manual_paused or self.invalid_config)
        if self.supervisor.paused:
            self.timer.stop()
        self.set_status(State.PAUSED if self.supervisor.paused else State.WAITING,
                        "已暂停" if self.supervisor.paused else "已恢复，即将重新检查")
        if not self.supervisor.paused:
            self.next_reason = "resume"
            self.start_check()
    def open_folder(self):
        APP_DIR.mkdir(parents=True, exist_ok=True)
        if sys.platform == "darwin": subprocess.Popen(["open", str(APP_DIR)])
        elif os.name == "nt": os.startfile(str(APP_DIR))
        else: subprocess.Popen(["xdg-open", str(APP_DIR)])
    def open_portal(self):
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        profile = self.service.profile_name if self.service.profile_name in {"public", "dorm"} else "public"
        QDesktopServices.openUrl(QUrl(self.config["profiles"][profile]["portal_url"]))
    def showEvent(self, event):
        super().showEvent(event)
        if hasattr(self, "countdown_timer"):
            self.countdown_timer.start()
            self.refresh_countdown()
        if self.running:
            self.check_timer.start()
            self.update_check_progress()

    def hideEvent(self, event):
        # Pause display-only timers. Do not stop the network scheduler or cancel requests.
        if hasattr(self, "countdown_timer"):
            self.countdown_timer.stop()
        self.check_timer.stop()
        super().hideEvent(event)

    def closeEvent(self, event):
        if self.hide_on_close and self.tray.isSystemTrayAvailable(): self.hide(); event.ignore()
        else:
            self.quit_app(); event.accept()
    def quit_app(self):
        self.hide_on_close = False; self.supervisor.set_paused(True)
        if self.running:
            self.quit_after_check = True
            self.refresh_countdown()
        else: QApplication.quit()

    @staticmethod
    def apply_autostart(enabled: bool):
        if sys.platform == "darwin":
            path = Path.home() / "Library/LaunchAgents/com.codex.campus-network-assistant.plist"
            if enabled:
                path.parent.mkdir(parents=True, exist_ok=True)
                executable = sys.executable
                app_path = Path(executable).resolve().parents[2] if getattr(sys, "frozen", False) else None
                args = ["open", "-a", str(app_path)] if app_path else [executable, str(Path(__file__).resolve().parents[1] / "main.py")]
                path.write_bytes(plistlib.dumps({"Label": "com.codex.campus-network-assistant", "ProgramArguments": args,
                    "RunAtLoad": True, "KeepAlive": False}))
            else:
                path.unlink(missing_ok=True)
        elif os.name == "nt":
            from campus_assistant.windows_startup import set_startup
            set_startup(enabled)


def run_gui() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    try:
        window = Window()
        window.show()
        return app.exec()
    except ConfigError as exc:
        QMessageBox.critical(None, "配置文件无效", f"自动检查已停止。打开配置文件夹并修正后重启。\n{exc}")
        return 2
