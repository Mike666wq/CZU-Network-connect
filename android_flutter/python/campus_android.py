"""Synchronous Android entry point. The native worker owns all scheduling."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
from threading import Lock
import time

from campus_assistant import __version__
from campus_assistant.audit import record_event
from campus_assistant.config import ConfigError, load_config, save_config
from campus_assistant.engine import State, Supervisor
from campus_assistant.scheduler import PollScheduler
from campus_assistant.service import CampusService

from android_http import AndroidHttp


ISPS = {"-1", "", "@cmcc", "@unicom", "@telecom"}
DEFAULTS = {"username": "", "password": "", "isp": "-1", "scene": "auto"}
STATE_LABELS = {state.name.lower(): state.value for state in State}
MESSAGES = {
    "waiting": "等待校园网络或下一次检查",
    "paused": "自动检查已暂停",
    "stopped": "自动检查已停止",
    "checking": "正在检查网络",
    "online": "互联网已连通",
    "authenticated": "校园网认证成功且互联网已连通",
    "portal": "校园门户可用，等待互联网恢复",
    "needs_config": "请检查账号和校园网配置",
    "auth_blocked": "认证被拒绝，冷却后自动重试；也可修改配置后重试",
    "error": "本轮检查暂时未完成，将稍后重试",
}
REASON_MESSAGES = {
    "credentials_missing": "请先填写账号和密码；未发送凭据",
    "provider_missing": "请先选择宿舍服务商并保存；未发送凭据",
    "provider_mismatch": "账号末尾的服务商与所选服务商不同；未发送凭据",
    "portal_protocol_mismatch": "门户参数与已验证设置不同；未发送凭据",
    "portal_ipv4_missing": "门户未提供有效 IPv4 地址；未发送凭据",
    "portal_unidentified": "未识别到受支持的校园门户；未发送凭据",
    "account": "账号或密码有误，认证已暂停；请检查后重试",
    "disabled": "账号已停用；请联系校园网服务方",
    "debt": "账号欠费或余额不足；请检查后重试",
    "authenticated_no_internet": "门户报告认证成功，互联网仍不可用",
    "already_online_no_internet": "账号此前已认证，互联网仍不可用；未重复登录",
}
REASON_LABELS = {"startup": "首次检查", "manual": "手动检查", "heartbeat": "定时检查",
                 "network": "网络变化", "wake": "唤醒检查", "midnight": "恢复时段检查",
                 "resume": "恢复检查"}
REASONS = {"startup", "manual", "heartbeat", "network", "wake", "midnight", "resume"}
# These fields are speculative until the bridge generation has been checked.
CHECK_FIELDS = ("outcome", "auth_blocked", "auth_notice_sent", "auth_blocked_at",
                "blocked_scene", "blocked_state", "blocked_reason", "blocked_message",
                "unknown_count", "offline_count", "_scene_generation")


class Bridge:
    def __init__(self, data_dir, transport_factory=None, service_factory=None):
        self.data_dir = Path(data_dir)
        if not self.data_dir.is_absolute():
            raise ValueError("data_dir must be an absolute app-private path")
        self.config_path = self.data_dir / "config.json"
        self.logs_path = self.data_dir / "android_logs.json"
        self.audit_path = self.data_dir / "events.jsonl"
        self._worker = Lock()
        # This lock protects only short memory updates, never I/O or core checks.
        self._control = Lock()
        self._generation = 0
        self._active_generation = 0
        self._published_generation = 0
        self._paused = False
        self._network_id = ""
        self._transport_factory = transport_factory or AndroidHttp
        self._service_factory = service_factory or CampusService
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            self._config = load_config(self.config_path)
        except (OSError, ValueError):
            raise ConfigError("Private configuration could not be loaded") from None
        self._scheduler = PollScheduler(time.monotonic(), initial_wall=self._now())
        self._status = "waiting"
        self._message = MESSAGES["waiting"]
        self._logs = self._load_logs()
        self._install_service(self._config)

    @staticmethod
    def _now():
        return datetime.now(timezone.utc)

    def _install_service(self, config):
        portal_http = self._transport_factory(timeout=10.0)
        probe_http = self._transport_factory(timeout=4.0)
        service = self._service_factory(deepcopy(config), http=portal_http)
        service.probe_http = probe_http
        supervisor = Supervisor(service.probe_internet, service.identify_portal,
                                service.authenticate, now=self._now)
        service.set_cancel_check(lambda: (
            self._paused or self._generation != self._active_generation
            or supervisor.paused or supervisor.generation != supervisor._active_generation))
        with self._control:
            supervisor.set_paused(self._paused)
            supervisor.network_changed(self._network_id)
            supervisor.enabled = config["enabled"]
            self._service, self._supervisor = service, supervisor

    @staticmethod
    def _public_config(config):
        dorm = config["profiles"]["dorm"]
        suffix = dorm["provider_suffix"] if dorm.get("provider_confirmed", False) else "-1"
        isp = suffix if suffix in ISPS else "-1"
        return {"username": config["username"], "password": config["password"],
                "isp": isp, "scene": config["active_profile"]}

    def get_config(self):
        with self._control:
            value = self._public_config(self._config)
        return json.dumps(value, ensure_ascii=True)

    @staticmethod
    def _payload(payload):
        try:
            if not isinstance(payload, str) or len(payload) > 16_384:
                raise ValueError
            value = json.loads(payload)
            if not isinstance(value, dict) or value.keys() - DEFAULTS.keys():
                raise ValueError
            value = DEFAULTS | value
            if any(not isinstance(v, str) for v in value.values()):
                raise ValueError
            if value["scene"] not in {"auto", "public", "dorm"} or value["isp"] not in ISPS:
                raise ValueError
            if any(len(value[k]) > 1024 or any(ord(c) < 32 for c in value[k])
                   for k in ("username", "password")):
                raise ValueError
            return value
        except (TypeError, ValueError):
            raise ConfigError("Invalid Android configuration") from None

    def save_config(self, payload):
        value = self._payload(payload)
        with self._worker:
            config = deepcopy(self._config)
            config.update(username=value["username"], password=value["password"],
                          active_profile=value["scene"], credential_mode="shared")
            config["profiles"]["public"]["provider_suffix"] = ""
            dorm = config["profiles"]["dorm"]
            dorm["provider_suffix"] = value["isp"] if value["isp"] != "-1" else ""
            dorm["provider_confirmed"] = value["isp"] != "-1"
            if config == self._config:
                return
            try:
                save_config(config, self.config_path)
            except (OSError, ValueError):
                raise ConfigError("Private configuration could not be saved") from None
            self._install_service(config)
            with self._control:
                self._config = config
                self._generation += 1
                self._scheduler.reschedule(time.monotonic(), 0)
            # No network work until the next explicit tick.

    def stop(self):
        with self._control:
            if not self._paused:
                self._paused = True
                self._generation += 1
                self._supervisor.set_paused(True)

    def resume(self):
        with self._worker:
            with self._control:
                if self._paused:
                    self._paused = False
                    self._generation += 1
                    self._supervisor.set_paused(False)
                    self._scheduler.reschedule(time.monotonic(), 0)

    def network_changed(self, network_id):
        if not isinstance(network_id, str):
            raise ValueError("network_id must be text")
        with self._control:
            if network_id != self._network_id:
                self._network_id = network_id
                self._generation += 1
                self._supervisor.network_changed(network_id)

    def _remaining(self):
        if self._paused:
            return 0
        if self._published_generation != self._generation:
            return 0
        return self._scheduler.seconds_until_due(time.monotonic(), self._now())

    def tick(self, network_id, force=False):
        if not isinstance(network_id, str) or type(force) is not bool:
            raise ValueError("tick expects a network ID and a boolean force flag")
        self.network_changed(network_id)
        with self._control:
            requested_generation = self._generation
        with self._worker:
            with self._control:
                if (self._paused or requested_generation != self._generation
                        or network_id != self._network_id):
                    return self._remaining()
                generation = self._generation
                pending = self._published_generation != generation
                now, wall = time.monotonic(), self._now()
                scheduled = self._scheduler.tick(now, wall, network_id,
                                                 self._supervisor.outcome.next_seconds)
                if not (force or pending or scheduled.due):
                    return self._remaining()
                self._active_generation = generation
                supervisor = self._supervisor
                checkpoint = {key: getattr(supervisor, key) for key in CHECK_FIELDS}
            outcome = supervisor.check(force=force)
            with self._control:
                if self._paused or generation != self._generation:
                    for key, value in checkpoint.items():
                        setattr(supervisor, key, value)
                    supervisor._scene_generation = None
                    return self._remaining()
                self._status = outcome.state.name.lower()
                self._message = REASON_MESSAGES.get(outcome.reason, MESSAGES[self._status])
                self._published_generation = generation
                next_seconds = outcome.next_seconds
                if (supervisor.auth_blocked and supervisor.auth_blocked_at > 0
                        and outcome.state in {State.AUTH_BLOCKED, State.NEEDS_CONFIG}):
                    cooldown = (supervisor.AUTH_BLOCK_COOLDOWN_SECONDS
                                - (supervisor.now().timestamp() - supervisor.auth_blocked_at))
                    next_seconds = min(next_seconds, max(0, math.ceil(cooldown)))
                self._scheduler.reschedule(time.monotonic(), next_seconds)
                delay = self._remaining()
                reason = ("manual" if force else "network" if scheduled.network_changed else
                          "midnight" if scheduled.special_time else "wake" if scheduled.woke else
                          "startup" if not self._logs else "heartbeat")
                entry = {"status": self._status, "reason": reason}
                self._logs = (self._logs + [entry])[-100:]
                scene = self._service.profile_name
                attempted = self._service.auth_submitted
            self._persist_logs()
            record_event(self.audit_path, state=entry["status"], scene=scene,
                         next_seconds=delay, auth_attempted=attempted, reason=reason)
            return delay

    def snapshot(self):
        with self._control:
            status = ("paused" if self._paused else "waiting"
                      if self._published_generation != self._generation else self._status)
            valid = not self._paused and self._published_generation == self._generation
            value = {"status": STATE_LABELS[status], "state": status,
                     "message": self._message if valid else MESSAGES[status],
                     "online": status in {"online", "authenticated"}, "coreVersion": __version__,
                     "nextSeconds": self._remaining(), "logs": [
                         REASON_LABELS[e["reason"]] + "：" + STATE_LABELS[e["status"]]
                         for e in self._logs]}
        return json.dumps(value, ensure_ascii=True)

    def _load_logs(self):
        try:
            if self.logs_path.stat().st_size > 32_768:
                return []
            entries = json.loads(self.logs_path.read_text(encoding="utf-8"))
            if not isinstance(entries, list):
                return []
            return [{"status": e["status"], "reason": e["reason"]} for e in entries[-100:]
                    if isinstance(e, dict) and isinstance(e.get("status"), str)
                    and isinstance(e.get("reason"), str)
                    and e["status"] in MESSAGES and e["reason"] in REASONS]
        except (OSError, ValueError):
            return []

    def _persist_logs(self):
        temp = self.logs_path.with_suffix(".json.tmp")
        try:
            temp.write_text(json.dumps(self._logs, ensure_ascii=True), encoding="utf-8")
            os.chmod(temp, 0o600)
            temp.replace(self.logs_path)
        except OSError:
            # Diagnostic storage failure must not break network scheduling.
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass
