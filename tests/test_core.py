from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
from urllib.parse import parse_qs, urlsplit

import pytest

from campus_assistant.config import ConfigError, load_config, save_config
from campus_assistant.engine import Outcome, State, Supervisor, interval_for
from campus_assistant.protocol import PortalResult, classify_result, parse_jsonp
from campus_assistant.scheduler import PollScheduler
from datetime import timezone


def test_midnight_and_regular_cadence():
    assert interval_for(datetime(2026, 10, 5, 0, 0), False) == 60
    assert interval_for(datetime(2026, 10, 5, 0, 9, 59), False) == 60
    assert interval_for(datetime(2026, 10, 5, 0, 10), False) == 30
    assert interval_for(datetime(2026, 10, 5, 12), True) == 60


def test_jsonp_parser_never_evaluates_javascript():
    assert parse_jsonp('dr3({"result":1})')['result'] == 1
    with pytest.raises(Exception):
        parse_jsonp('dr3((function(){return {"result":1}})())')
    assert classify_result({"ret_code": "2"}).category == "already_online"
    assert classify_result({"ret_code": "5"}).category == "temporary"


def test_config_roundtrip_and_invalid_fields_are_isolated(tmp_path: Path):
    cfg_path = tmp_path / "sandbox" / "config.json"
    cfg = load_config(cfg_path)
    cfg["username"] = "test-user"
    save_config(cfg, cfg_path)
    assert load_config(cfg_path)["username"] == "test-user"
    data = cfg.copy(); data["active_profile"] = "bogus"
    with pytest.raises(ConfigError):
        save_config(data, cfg_path)
    assert load_config(cfg_path)["active_profile"] == "auto"


def test_generation_change_cancels_old_result_and_checks_do_not_overlap():
    started, release = Event(), Event()
    calls = []
    def probe():
        calls.append("probe"); started.set(); release.wait(1); return False, "wifi"
    supervisor = Supervisor(probe, lambda: calls.append("portal") or True,
                            lambda: calls.append("auth") or PortalResult(True, "success", "ok"))
    t = Thread(target=supervisor.check); t.start(); assert started.wait(1)
    before = len(calls)
    # Re-entry merges while the worker holds the lock; switching network invalidates its snapshot.
    current = supervisor.check(); assert current.state == State.CHECKING
    supervisor.network_changed("new-network"); release.set(); t.join(2)
    assert calls[:before] == ["probe"]
    assert "auth" not in calls


def test_hard_auth_error_notifies_once_and_manual_retry_resets():
    sup = Supervisor(lambda: (False, "wifi"), lambda: True,
                     lambda: PortalResult(False, "account", "账号或密码错误"))
    assert sup.check().notify is True
    assert sup.check().state == State.AUTH_BLOCKED
    assert sup.check(force=True).notify is True


def test_success_does_not_claim_authenticated_without_public_probe():
    checks = iter([(False, "wifi"), (False, "wifi")])
    sup = Supervisor(lambda: next(checks), lambda: True,
        lambda: PortalResult(True, "success", "认证成功"))
    outcome = sup.check()
    assert outcome.state == State.PORTAL
    assert "互联网仍不可用" in outcome.message


def test_hard_failure_still_checks_internet_but_never_resubmits():
    online = [False]; calls = []
    sup = Supervisor(lambda: (calls.append("probe") is None and online[0], "wifi"), lambda: True,
        lambda: calls.append("auth") or PortalResult(False, "account", "账号或密码错误"))
    # Explicit probe callback for clear result values.
    def probe(): calls.append("probe"); return (online[0], "wifi")
    sup.probe = probe
    sup.check(); assert calls.count("auth") == 1
    online[0] = True
    assert sup.check().state == State.ONLINE
    assert calls.count("auth") == 1


def test_unknown_backoff_after_three_and_success_resets_counter():
    values = iter([PortalResult(False, "unknown", "x")] * 3 + [PortalResult(True, "success", "ok")])
    probes = iter([(False, "wifi")] * 4 + [(False, "wifi")])
    sup = Supervisor(lambda: next(probes), lambda: True, lambda: next(values))
    assert sup.check().next_seconds == 30
    assert sup.check().next_seconds == 30
    assert sup.check().next_seconds == 300
    assert sup.unknown_count == 3
    assert sup.check().state == State.PORTAL
    assert sup.unknown_count == 0


def test_temporary_retry_uses_offline_and_midnight_intervals():
    for stamp, delay in ((datetime(2026, 10, 5, 12), 30), (datetime(2026, 10, 5, 0, 4), 60)):
        sup = Supervisor(lambda: (False, "wifi"), lambda: True,
            lambda: PortalResult(False, "temporary", "稍后重试"), now=lambda: stamp)
        assert sup.check().next_seconds == delay


def test_pause_during_probe_invalidates_generation_before_auth():
    calls = []; holder = {}
    def probe():
        calls.append("probe")
        holder["sup"].set_paused(True)
        return False, "wifi"
    sup = Supervisor(probe, lambda: True, lambda: calls.append("auth") or PortalResult(True, "success", "ok"))
    holder["sup"] = sup
    sup.check()
    assert calls == ["probe"]


def test_poll_scheduler_special_checks_wake_and_network_change():
    start_wall = datetime(2026, 10, 5, 23, 59, 55, tzinfo=timezone.utc)
    s = PollScheduler(10.0, "wifi-a", start_wall)
    midnight = s.tick(15, datetime(2026, 10, 6, 0, 0, tzinfo=timezone.utc), "wifi-a", 60)
    assert midnight.due and midnight.special_time
    duplicate = s.tick(20, datetime(2026, 10, 6, 0, 0, 5, tzinfo=timezone.utc), "wifi-a", 60)
    assert not duplicate.special_time
    switch = s.tick(25, datetime(2026, 10, 6, 0, 0, 10, tzinfo=timezone.utc), "wifi-b", 60)
    assert switch.due and switch.network_changed
    woke = s.tick(30, datetime(2026, 10, 6, 0, 5, tzinfo=timezone.utc), "wifi-b", 60)
    assert woke.woke and woke.due
    s.reschedule(30, 60)
    assert s.tick(90, datetime(2026, 10, 6, 0, 6, tzinfo=timezone.utc), "wifi-b", 60).due


def test_config_rejects_invalid_boolean_and_portal_authority(tmp_path):
    p = tmp_path / "config.json"
    cfg = load_config(p); cfg["enabled"] = "false"
    with pytest.raises(ConfigError): save_config(cfg, p)
    cfg = load_config(p); cfg["profiles"]["public"]["portal_url"] = "http://user:pw@/bad"
    with pytest.raises(ConfigError): save_config(cfg, p)


def test_progress_reports_read_only_online_check_without_authentication():
    phases = []
    sup = Supervisor(lambda: (True, "wifi"), lambda: pytest.fail("portal not needed"),
                     lambda: pytest.fail("authentication not needed"))
    sup.progress = phases.append
    assert sup.check().state == State.ONLINE
    assert phases == ["正在检测互联网"]


def test_legacy_public_selection_is_migrated_to_auto(tmp_path):
    p = tmp_path / "config.json"
    p.write_text('{"active_profile":"public"}', encoding="utf-8")
    cfg = load_config(p)
    assert cfg["active_profile"] == "auto"
    assert cfg["config_version"] == 3


def test_saved_v3_manual_selection_is_preserved(tmp_path):
    p = tmp_path / "config.json"
    p.write_text('{"config_version":3,"active_profile":"dorm"}', encoding="utf-8")
    cfg = load_config(p)
    assert cfg["active_profile"] == "dorm"
