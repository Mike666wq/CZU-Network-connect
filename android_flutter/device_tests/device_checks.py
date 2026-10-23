"""Debug-only device fixtures. All HTTP requests are rewritten to loopback."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from urllib.parse import urlsplit

from java import jclass
from android_http import AndroidHttp
from campus_android import Bridge
from campus_assistant import __version__
from campus_assistant.engine import interval_for
from campus_assistant.protocol import PortalResult
from campus_assistant.service import CampusService


def integration(data_dir, loopback):
    native = jclass("io.github.Mike666wq.czuconnect.AndroidHttp")

    class Ticket:
        def __init__(self, inner, original):
            self.inner, self.original = inner, original

        def awaitDone(self, ms):
            return self.inner.awaitDone(ms)

        def cancel(self):
            self.inner.cancel()

        def result(self):
            response = json.loads(str(self.inner.result()))
            response["final"] = self.original
            return json.dumps(response)

    class Loopback:
        @staticmethod
        def start(url, headers, timeout):
            parts = urlsplit(url)
            target = loopback.rstrip("/") + (parts.path or "/")
            if parts.query:
                target += "?" + parts.query
            return Ticket(native.start(target, headers, timeout), url)

    class TestService(CampusService):
        def probe_internet(self):
            status, body, _, _ = self.probe_http.get("https://probe.invalid/probe")
            return status == 204 and not body, "loopback"

    factory = lambda timeout: AndroidHttp(timeout, ticket_factory=Loopback.start)
    bridge = Bridge(data_dir, transport_factory=factory, service_factory=TestService)
    bridge.save_config(json.dumps({"username": "fixture-user", "password": "fixture-secret",
                                   "isp": "", "scene": "public"}))
    bridge.tick("loopback", True)
    snapshot = json.loads(bridge.snapshot())
    assert snapshot["online"], snapshot
    assert snapshot["coreVersion"] == __version__
    serialized = json.dumps(snapshot)
    assert "fixture-user" not in serialized and "fixture-secret" not in serialized
    bridge.stop()
    assert not json.loads(bridge.snapshot())["online"]
    bridge.resume()

    class BlockedService(CampusService):
        def probe_internet(self):
            return False, "fixture"

        def identify_portal(self):
            self.profile_name = "public"
            return True

        def authenticate(self):
            attempts.append(1)
            return PortalResult(False, "account", "fixture refusal")

    attempts = []
    blocked = Bridge(str(Path(data_dir) / "blocked"), transport_factory=factory, service_factory=BlockedService)
    clock = [datetime(2026, 10, 23, 12, tzinfo=timezone.utc)]
    blocked._supervisor.now = lambda: clock[0]
    blocked.tick("loopback", True)
    blocked._scheduler.reschedule(0, 0)
    blocked.tick("loopback")
    assert len(attempts) == 1
    clock[0] += timedelta(seconds=301)
    blocked._scheduler.reschedule(0, 0)
    blocked.tick("loopback")
    assert len(attempts) == 2
    assert interval_for(datetime(2026, 10, 23, 23, 58), True) == 60
    assert interval_for(datetime(2026, 10, 24, 0, 8), True) == 30
    return __version__


def safe_bridge(data_dir):
    class SafeService(CampusService):
        def probe_internet(self):
            return True, "fixture"

        def identify_portal(self):
            return False

        def authenticate(self):
            raise AssertionError("Lifecycle tests must never submit credentials")

    return Bridge(data_dir, service_factory=SafeService)
