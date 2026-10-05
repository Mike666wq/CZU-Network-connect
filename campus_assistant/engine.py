from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from zoneinfo import ZoneInfo
from enum import Enum
from threading import Event, Lock
from typing import Callable

from .protocol import PortalResult


class State(str, Enum):
    STOPPED = "已停止"
    PAUSED = "已暂停"
    CHECKING = "正在检查"
    ONLINE = "互联网已连通"
    AUTHENTICATED = "校园网已认证"
    PORTAL = "检测到校园认证门户"
    WAITING = "等待网络变化"
    NEEDS_CONFIG = "需要检查配置"
    AUTH_BLOCKED = "认证被拒绝，已暂停"
    ERROR = "暂时无法检查"


@dataclass(frozen=True)
class Outcome:
    state: State
    message: str
    next_seconds: int
    notify: bool = False


def interval_for(now: datetime, internet: bool) -> int:
    if now.tzinfo is None:
        now = now.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    now = now.astimezone(ZoneInfo("Asia/Shanghai"))
    t = now.time()
    if time(0, 0) <= t < time(0, 10):
        return 60
    if not internet:
        return 30
    return 60


class Supervisor:
    """Serialized check state machine; callbacks perform isolated probes."""

    def __init__(self, probe: Callable[[], tuple[bool, str]],
                 identify_portal: Callable[[], bool],
                 authenticate: Callable[[], PortalResult],
                 now: Callable[[], datetime] = lambda: datetime.now(ZoneInfo("Asia/Shanghai"))):
        self.probe, self.identify_portal, self.authenticate, self.now = probe, identify_portal, authenticate, now
        self.progress: Callable[[str], None] = lambda message: None
        self.scene_changed: Callable[[str, str], None] = lambda name, entrance: None
        self.blocked_scene = ""
        self.blocked_state = State.AUTH_BLOCKED
        self.blocked_message = "认证已暂停；请修正账号或配置后点重试"
        self._active_generation = 0
        self._scene_generation = None
        service = getattr(authenticate, "__self__", None)
        if service is not None and hasattr(service, "set_cancel_check"):
            service.set_cancel_check(lambda: self.paused or self.generation != self._active_generation)
        if service is not None and hasattr(service, "progress"):
            service.progress = lambda message: self.progress(message)
        self.lock = Lock()
        self.cancel = Event()
        self.paused = False
        self.enabled = True
        self.auth_blocked = False
        self.auth_notice_sent = False
        self.unknown_count = 0
        self.last_network_id: str | None = None
        self.generation = 0
        self.outcome = Outcome(State.WAITING, "等待检查", 60)

    def set_paused(self, value: bool) -> None:
        self.paused = value
        if value:
            self.generation += 1
            self.cancel.set()
        else:
            self.cancel.clear()

    def network_changed(self, network_id: str) -> None:
        if network_id != self.last_network_id:
            self.last_network_id = network_id
            self.generation += 1
            self._scene_generation = None
            self.cancel.set()

    def report_scene(self, service) -> None:
        if service is not None and getattr(service, "portal_known", False):
            name = getattr(service, "profile_name", "")
            entrance = getattr(service, "profile", {}).get("portal_url", "")
            if name in {"public", "dorm"}:
                self.scene_changed(name, entrance)

    def check(self, *, force: bool = False) -> Outcome:
        if not self.lock.acquire(blocking=False):
            return self.outcome
        try:
            if not self.enabled or self.paused:
                self.outcome = Outcome(State.PAUSED, "自动检查已暂停", 60)
                return self.outcome
            if force:
                self._scene_generation = None
                self.auth_blocked = False
                self.auth_notice_sent = False
                self.unknown_count = 0
            generation = self.generation
            self._active_generation = generation
            self.cancel.clear()
            self.outcome = Outcome(State.CHECKING, "正在检查网络", 60)
            service = getattr(self.authenticate, "__self__", None)
            if service is not None and hasattr(service, "auth_submitted"):
                service.auth_submitted = False
            try:
                self.progress("正在检测互联网")
                online, _network = self.probe()
                if generation != self.generation or self.paused:
                    return self.outcome
                if online:
                    scene_ok = False
                    inspector = getattr(service, "inspect_connected_scene", None)
                    if inspector is not None and self._scene_generation != generation:
                        self.progress("公网探测已通过，正在按顺序识别校园场景")
                        scene_ok = bool(inspector())
                        if scene_ok:
                            self._scene_generation = generation
                        if generation != self.generation or self.paused:
                            return self.outcome
                    elif service is not None:
                        scene_ok = bool(getattr(service, "portal_known", False))
                    self.report_scene(service)
                    self.unknown_count = 0
                    if scene_ok:
                        scene = {"public": "公共网", "dorm": "宿舍网"}.get(
                            getattr(service, "profile_name", ""), "校园网")
                        message = f"互联网可用；当前场景：{scene}；本轮未提交校园登录"
                    else:
                        message = "互联网可用；公共网和宿舍网入口均未识别，可能不在校园网"
                    self.outcome = Outcome(State.ONLINE, message, interval_for(self.now(), True))
                    return self.outcome
                self.progress("正在识别校园门户")
                if not self.identify_portal():
                    service = getattr(self.identify_portal, "__self__", None)
                    message = getattr(service, "portal_error", "") or "未识别到受支持的校园门户，未发送凭据"
                    self.outcome = Outcome(State.WAITING, message, interval_for(self.now(), False))
                    return self.outcome
                if generation != self.generation or self.paused:
                    return self.outcome
                self.report_scene(service)
                scene = getattr(service, "profile_name", "")
                if self.auth_blocked and scene != self.blocked_scene:
                    self.auth_blocked = False
                    self.auth_notice_sent = False
                if self.auth_blocked and not force:
                    self.outcome = Outcome(self.blocked_state, self.blocked_message, interval_for(self.now(), False))
                    return self.outcome
                self.progress("正在读取门户配置并检查认证状态")
                result = self.authenticate()
                if generation != self.generation or self.paused:
                    return self.outcome
                if result.success:
                    self.unknown_count = 0
                    # Portal success is not proof of Internet reachability.
                    self.progress("正在验证互联网是否连通")
                    online_after, _ = self.probe()
                    if generation != self.generation or self.paused:
                        return self.outcome
                    state = State.AUTHENTICATED if online_after else State.PORTAL
                    msg = "认证成功且互联网已连通" if online_after else "门户报告认证成功，互联网仍不可用"
                    self.outcome = Outcome(state, msg, interval_for(self.now(), online_after))
                elif result.category == "already_online":
                    self.progress("正在验证互联网是否连通")
                    online_after, _ = self.probe()
                    if generation != self.generation or self.paused:
                        return self.outcome
                    state = State.AUTHENTICATED if online_after else State.PORTAL
                    message = "账号此前已认证且互联网已连通" if online_after else "校园网报告已认证；公网探测未通过，未重复登录"
                    self.outcome = Outcome(State.ONLINE if online_after else State.PORTAL, message, interval_for(self.now(), online_after))
                elif result.category in {"configuration", "account", "disabled", "debt"}:
                    self.auth_blocked = True
                    self.blocked_scene = getattr(service, "profile_name", "")
                    self.blocked_state = State.NEEDS_CONFIG if result.category == "configuration" else State.AUTH_BLOCKED
                    self.blocked_message = result.message
                    notice = not self.auth_notice_sent
                    self.auth_notice_sent = True
                    self.outcome = Outcome(self.blocked_state, result.message, 60, notice)
                elif result.category == "unsupported":
                    self.outcome = Outcome(State.NEEDS_CONFIG, result.message, interval_for(self.now(), False))
                elif result.category == "unknown":
                    self.unknown_count += 1
                    delay = 300 if self.unknown_count >= 3 else interval_for(self.now(), False)
                    self.outcome = Outcome(State.ERROR, "门户返回未知结果", delay)
                else:
                    self.outcome = Outcome(State.ERROR, result.message, interval_for(self.now(), False))
            except Exception:
                self.unknown_count += 1
                delay = 300 if self.unknown_count >= 3 else interval_for(self.now(), False)
                self.outcome = Outcome(State.ERROR, "检查遇到暂时故障", delay)
            return self.outcome
        finally:
            self.lock.release()
