from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from threading import Event, Thread
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

from campus_android import Bridge, DEFAULTS
from campus_assistant import __version__
from campus_assistant.config import ConfigError, load_config
from campus_assistant.service import CampusService
from core_test_fixtures import CompletedTicket, FixtureNetwork, run


class Clock:
    def __init__(self):
        self.mono = 10.0
        self.wall = datetime(2026, 10, 23, 4, tzinfo=timezone.utc)

    def advance(self, seconds):
        self.mono += seconds
        self.wall += timedelta(seconds=seconds)


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.private = TemporaryDirectory()
        self.addCleanup(self.private.cleanup)
        self.network = FixtureNetwork()
        self.services = []
        def service_factory(config, http):
            service = CampusService(config, http=http)
            self.services.append(service)
            return service
        self.bridge = Bridge(self.private.name, transport_factory=self.network.transport_factory,
                             service_factory=service_factory)

    def configure(self, **changes):
        value = {"username": "fixture-user", "password": "fixture-password", "isp": "", "scene": "public"}
        self.bridge.save_config(json.dumps(value | changes))

    def snap(self):
        return json.loads(self.bridge.snapshot())

    def test_initialization_is_private_and_has_no_network_or_java(self):
        self.assertEqual(self.network.requests, [])
        self.assertEqual(json.loads(self.bridge.get_config()), DEFAULTS)
        self.assertEqual(self.network.timeouts, [10.0, 4.0])
        self.assertEqual(self.snap()["state"], "waiting")
        self.assertEqual(self.snap()["nextSeconds"], 0)
        self.assertEqual(self.snap()["coreVersion"], __version__)
        self.assertEqual(len(self.services), 1)
        self.assertTrue(self.bridge.config_path.is_relative_to(Path(self.private.name)))
        with patch("android_http.AndroidHttp.get", side_effect=AssertionError("No network during init")):
            with TemporaryDirectory() as private:
                Bridge(private)

    def test_real_service_public_login_and_verified_online(self):
        self.configure()
        delay = self.bridge.tick("wifi", True)
        self.assertIs(type(delay), int)
        self.assertGreater(delay, 0)
        self.assertTrue(self.snap()["online"])
        self.assertEqual(self.snap()["state"], "authenticated")
        query, = self.network.login_queries()
        self.assertEqual(query["user_account"], [",0,fixture-user"])
        self.assertEqual(query["user_password"], ["fixture-password"])
        self.assertEqual(query["wlan_user_ip"], ["10.20.30.40"])
        self.assertEqual(query["wlan_user_mac"], ["000000000000"])
        self.assertEqual(query["login_method"], ["1"])
        requests = len(self.network.requests)
        self.bridge.tick("wifi")
        self.assertEqual(len(self.network.requests), requests)
        self.assertTrue(all(isinstance(line, str) for line in self.snap()["logs"]))

    def test_dorm_provider_mapping_and_default_scene_detection(self):
        self.network.scene = "dorm"
        self.network.settings["account_prefix"] = 0
        self.configure(isp="@unicom", scene="auto")
        self.bridge.tick("wifi")
        query, = self.network.login_queries()
        self.assertEqual(query["user_account"], ["fixture-user@unicom"])
        self.assertTrue(self.snap()["online"])
        cfg = load_config(self.bridge.config_path)
        self.assertEqual(cfg["profiles"]["dorm"]["provider_suffix"], "@unicom")
        self.assertTrue(cfg["profiles"]["dorm"]["provider_confirmed"])
        roots = [urlsplit(u).hostname for u, _, _ in self.network.requests if urlsplit(u).path == "/"]
        self.assertEqual(roots[:2], ["192.168.255.4", "172.19.0.1"])

    def test_existing_session_skips_credentials_and_config(self):
        self.network.scenario = "already_online"
        self.configure(username="", password="")
        self.bridge.tick("wifi")
        self.assertTrue(self.snap()["online"])
        self.assertEqual(self.network.login_queries(), [])
        self.assertFalse(any("loadConfig" in u for u, _, _ in self.network.requests))

    def test_credentials_and_provider_errors_have_safe_specific_messages(self):
        for changes, expected in (({"username": ""}, "账号和密码"),
                                  ({"scene": "dorm", "isp": "-1"}, "选择宿舍服务商"),
                                  ({"scene": "dorm", "isp": "@cmcc", "username": "user@unicom"}, "服务商不同")):
            with self.subTest(changes=changes):
                self.network.scene = "dorm" if changes.get("scene") == "dorm" else "public"
                self.network.settings["account_prefix"] = 0 if self.network.scene == "dorm" else 1
                self.configure(**changes)
                self.bridge.tick("wifi", True)
                self.assertEqual(self.snap()["state"], "needs_config")
                self.assertIn(expected, self.snap()["message"])
                self.assertEqual(self.network.login_queries(), [])

    def test_critical_blocks_and_advisory_drift_still_authenticates(self):
        self.configure()
        self.network.settings["en_md5"] = 1
        self.bridge.tick("wifi", True)
        self.assertEqual(self.snap()["state"], "needs_config")
        self.assertIn("门户参数", self.snap()["message"])
        self.assertEqual(self.network.login_queries(), [])
        self.network.settings["en_md5"] = 0
        self.network.settings["enable_r3"] = "private-server-text"
        self.bridge.tick("wifi", True)
        self.assertTrue(self.snap()["online"])
        self.assertNotIn("private-server-text", self.bridge.snapshot())

    def test_cooldown_reuses_supervisor_and_unchanged_config(self):
        self.configure()
        self.network.login_response = {"result": 0, "msg": "invalid password private-server-text"}
        clock = Clock()
        self.bridge._supervisor.now = lambda: clock.wall
        with patch("campus_android.time.monotonic", side_effect=lambda: clock.mono), \
                patch.object(Bridge, "_now", side_effect=lambda: clock.wall):
            self.bridge.tick("wifi")
            supervisor, service = self.bridge._supervisor, self.bridge._service
            self.assertEqual(self.snap()["state"], "auth_blocked")
            self.assertEqual(len(self.network.login_queries()), 1)
            with patch("campus_android.save_config", side_effect=AssertionError("Unchanged config must not write")):
                self.bridge.save_config(self.bridge.get_config())
            self.assertIs(self.bridge._supervisor, supervisor)
            self.assertIs(self.bridge._service, service)
            clock.advance(60)
            self.bridge.network_changed("wifi-b")
            self.bridge.tick("wifi-b")
            self.assertEqual(len(self.network.login_queries()), 1)
            clock.advance(300)
            self.bridge.network_changed("wifi-c")
            self.bridge.tick("wifi-c")
            self.assertEqual(len(self.network.login_queries()), 2)
            self.assertIs(self.bridge._supervisor, supervisor)
            self.assertNotIn("private-server-text", self.bridge.snapshot())

    def test_invalid_config_never_changes_saved_data_or_service(self):
        self.configure()
        before = self.bridge.config_path.read_bytes()
        supervisor = self.bridge._supervisor
        for value in ("[]", "{", 'null', '{"isp":"cmcc"}', '{"scene":"x"}',
                      '{"password":true}', '{"username":"a\\n"}', '{"unknown":"x"}',
                      json.dumps({"password": "x" * 1025})):
            with self.subTest(value=value[:40]):
                with self.assertRaises(ConfigError):
                    self.bridge.save_config(value)
                self.assertEqual(self.bridge.config_path.read_bytes(), before)
                self.assertIs(self.bridge._supervisor, supervisor)

    def test_real_scheduled_cooldown_retries_once_at_300_seconds(self):
        self.configure()
        self.network.login_response = {"result": 0, "msg": "invalid password"}
        clock = Clock()
        self.bridge._supervisor.now = lambda: clock.wall
        supervisor, service = self.bridge._supervisor, self.bridge._service
        with patch("campus_android.time.monotonic", side_effect=lambda: clock.mono), \
                patch.object(Bridge, "_now", side_effect=lambda: clock.wall):
            self.assertEqual(self.bridge.tick("wifi", False), 300)
            self.assertEqual(self.snap()["nextSeconds"], 300)
            self.assertEqual(len(self.network.login_queries()), 1)
            clock.advance(299)
            self.bridge.tick("wifi", False)
            self.assertEqual(len(self.network.login_queries()), 1)
            self.assertEqual(self.snap()["nextSeconds"], 1)
            clock.advance(1)
            self.assertEqual(self.bridge.tick("wifi", False), 300)
            self.assertEqual(len(self.network.login_queries()), 2)
            self.bridge.tick("wifi", False)
            self.assertEqual(len(self.network.login_queries()), 2)
            self.assertIs(self.bridge._supervisor, supervisor)
            self.assertIs(self.bridge._service, service)

    def test_online_after_block_does_not_get_stuck_on_expired_cooldown(self):
        self.configure()
        self.network.login_response = {"result": 0, "msg": "invalid password"}
        clock = Clock()
        self.bridge._supervisor.now = lambda: clock.wall
        with patch("campus_android.time.monotonic", side_effect=lambda: clock.mono), \
                patch.object(Bridge, "_now", side_effect=lambda: clock.wall):
            self.bridge.tick("wifi")
            clock.advance(300)
            self.network.online = True
            self.assertEqual(self.bridge.tick("wifi"), 600)
            self.assertTrue(self.snap()["online"])
            self.assertEqual(len(self.network.login_queries()), 1)

    def test_changed_config_is_due_without_network_change(self):
        self.configure()
        self.bridge.tick("wifi")
        previous = self.bridge._service
        self.configure(username="changed-user")
        self.assertIsNot(self.bridge._service, previous)
        self.assertEqual(self.snap()["nextSeconds"], 0)
        self.assertFalse(self.snap()["online"])
        self.bridge.tick("wifi")
        self.assertTrue(self.snap()["online"])

    def test_stop_and_network_change_do_not_wait_on_worker_or_do_io(self):
        errors = []
        def controls():
            try:
                self.bridge.stop()
                self.bridge.network_changed("new-wifi")
            except BaseException as exc:
                errors.append(exc)
        with self.bridge._worker:
            with patch("pathlib.Path.open", side_effect=AssertionError("Control must not access files")), \
                    patch("campus_android.record_event", side_effect=AssertionError("No audit in control")):
                thread = Thread(target=controls, daemon=True)
                thread.start()
                thread.join(0.5)
                self.assertFalse(thread.is_alive(), "Control waited on the serial worker")
        self.assertEqual(errors, [])
        self.assertEqual(self.snap()["state"], "paused")
        self.assertEqual(self.bridge.tick("new-wifi", True), 0)
        self.assertEqual(self.network.requests, [])
        self.bridge.resume()
        self.assertEqual(self.snap()["nextSeconds"], 0)
        self.bridge.tick("new-wifi")
        self.assertGreater(len(self.network.requests), 0)

    def test_cancelled_ticket_never_publishes_or_logs_and_resumes(self):
        self.configure()
        started = Event()
        original_start = self.network.start
        waited = []
        class Pending(CompletedTicket):
            def awaitDone(self, ms):
                started.set()
                waited.append(ms)
                time.sleep(ms / 1000)
                return False
        ticket = Pending({})
        def start(url, headers, timeout):
            return ticket
        self.bridge._service.probe_http._ticket_factory = start
        result = []
        with patch.object(self.bridge, "_persist_logs") as logs, patch("campus_android.record_event") as audit:
            thread = Thread(target=lambda: result.append(self.bridge.tick("wifi")), daemon=True)
            thread.start()
            self.assertTrue(started.wait(1))
            generation = self.bridge._supervisor.generation
            self.bridge.network_changed("wifi-new")
            self.assertGreater(self.bridge._supervisor.generation, generation)
            self.bridge.stop()
            thread.join(1)
            self.assertFalse(thread.is_alive())
            self.assertEqual(result, [0])
            self.assertTrue(ticket.cancelled)
            self.assertLessEqual(max(waited), 50)
            self.assertEqual(self.snap()["state"], "paused")
            self.assertEqual(self.snap()["logs"], [])
            logs.assert_not_called()
            audit.assert_not_called()
        self.bridge._service.probe_http._ticket_factory = original_start
        self.bridge.resume()
        self.bridge.tick("wifi-new")
        self.assertTrue(self.snap()["online"])

    def test_late_uncancellable_service_result_rolls_back_cooldown(self):
        self.configure()
        started, release = Event(), Event()
        original_auth = self.bridge._supervisor.authenticate
        def late_auth():
            started.set()
            release.wait(2)
            return original_auth()
        self.bridge._supervisor.authenticate = late_auth
        thread = Thread(target=lambda: self.bridge.tick("wifi"), daemon=True)
        thread.start()
        self.assertTrue(started.wait(1))
        self.bridge.network_changed("new")
        release.set()
        thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertFalse(self.snap()["online"])
        self.assertEqual(self.snap()["logs"], [])
        self.assertFalse(self.bridge._supervisor.auth_blocked)
        self.bridge._supervisor.authenticate = original_auth
        self.bridge.tick("new")
        self.assertTrue(self.snap()["online"])

    def test_logs_are_bounded_safe_and_persist_across_instances(self):
        self.configure()
        with patch("campus_android.record_event", wraps=__import__("campus_android").record_event) as audit:
            for _ in range(105):
                self.bridge.tick("wifi", True)
            self.assertTrue(all(call.args == (self.bridge.audit_path,) for call in audit.call_args_list))
        self.assertEqual(len(self.snap()["logs"]), 100)
        self.assertLess(self.bridge.logs_path.stat().st_size, 32_768)
        for path in (self.bridge.logs_path, self.bridge.audit_path):
            text = path.read_text()
            for secret in ("fixture-user", "fixture-password", "http", "private-server-text"):
                self.assertNotIn(secret, text)
        restored = Bridge(self.private.name, transport_factory=self.network.transport_factory)
        self.assertEqual(json.loads(restored.snapshot())["logs"], self.snap()["logs"])
        self.assertEqual(json.loads(restored.get_config()), json.loads(self.bridge.get_config()))

    def test_untrusted_persisted_log_fields_are_discarded(self):
        self.bridge.logs_path.write_text(json.dumps([
            {"status": "online", "reason": "manual", "body": "private-secret"},
            {"status": "private-secret", "reason": "manual"},
            {"status": "error", "reason": "http://private-secret"},
            {"status": [], "reason": {}}, "private-secret"]))
        bridge = Bridge(self.private.name, transport_factory=self.network.transport_factory)
        snap = json.loads(bridge.snapshot())
        self.assertEqual(len(snap["logs"]), 1)
        self.assertNotIn("private-secret", bridge.snapshot())

    def test_device_check_entry_point(self):
        result = json.loads(run(self.private.name))
        self.assertEqual(result, {"ok": True, "coreVersion": __version__, "checks": ["public", "dorm"]})


if __name__ == "__main__":
    unittest.main()
