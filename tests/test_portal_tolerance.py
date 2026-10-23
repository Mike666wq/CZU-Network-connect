"""Tolerance for Dr.COM portal configuration drift and AUTH_BLOCKED cooldown.

Covers the v0.4.2 long-running fix: a backend tweak to a non-critical portal
field must no longer brick the guard, and an AUTH_BLOCKED state must
eventually retry on its own instead of waiting for a manual click.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_protocol_regression import (  # noqa: E402
    CONFIG_PATH, base_config, portal_page, service_for,
)

from campus_assistant.engine import Supervisor, State  # noqa: E402
from campus_assistant.protocol import PortalResult  # noqa: E402
from campus_assistant.service import CampusService  # noqa: E402


def _known_good_settings(**overrides) -> dict:
    settings = {
        "login_method": "1", "enable_r3": "0", "en_md5": "0", "password_cut": "0",
        "account_suffix": "", "account_prefix": "1", "io_mode": "0",
        "program_index": "1",
    }
    settings.update(overrides)
    return settings


class PortalToleranceTests(unittest.TestCase):
    def test_critical_key_mismatch_still_blocks(self):
        service, _ = service_for(
            portal_page(globals_="v4ip='10.20.30.40';"),
            settings=_known_good_settings(login_method="2"),
        )
        self.assertTrue(service.identify_portal())
        result = service.load_portal_config()
        self.assertFalse(result.success)
        self.assertEqual(result.detail, "portal_protocol_mismatch")
        self.assertIn("login_method", result.message)

    def test_en_md5_mismatch_still_blocks(self):
        service, _ = service_for(
            portal_page(globals_="v4ip='10.20.30.40';"),
            settings=_known_good_settings(en_md5="1"),
        )
        self.assertTrue(service.identify_portal())
        result = service.load_portal_config()
        self.assertFalse(result.success)
        self.assertEqual(result.detail, "portal_protocol_mismatch")

    def test_advisory_key_mismatch_warns_but_continues(self):
        service, _ = service_for(
            portal_page(globals_="v4ip='10.20.30.40';"),
            settings=_known_good_settings(account_prefix="0"),
        )
        self.assertTrue(service.identify_portal())
        result = service.load_portal_config()
        self.assertTrue(result.success, msg=f"expected success, got {result}")
        self.assertTrue(any("account_prefix" in w for w in service.protocol_warnings))

    def test_multiple_advisory_mismatches_are_collected(self):
        service, _ = service_for(
            portal_page(globals_="v4ip='10.20.30.40';"),
            settings=_known_good_settings(account_prefix="0", enable_r3="1"),
        )
        self.assertTrue(service.identify_portal())
        result = service.load_portal_config()
        self.assertTrue(result.success)
        self.assertEqual(len(service.protocol_warnings), 2)


class AuthBlockedCooldownTests(unittest.TestCase):
    def test_blocked_retries_after_cooldown(self):
        attempts: list[str] = []

        def always_offline():
            return False, "offline"

        def portal_ok():
            return True

        def auth_blocking():
            attempts.append("auth")
            return PortalResult(False, "account", "账号已被禁用")

        class FixedClock:
            def __init__(self):
                from datetime import datetime
                from zoneinfo import ZoneInfo
                self._t = datetime(2026, 10, 23, 12, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

            def __call__(self):
                return self._t

            def advance(self, seconds: float):
                from datetime import timedelta
                self._t = self._t + timedelta(seconds=seconds)

        clock = FixedClock()
        supervisor = Supervisor(always_offline, portal_ok, auth_blocking, now=clock)
        outcome = supervisor.check(force=True)
        self.assertEqual(outcome.state, State.AUTH_BLOCKED)
        self.assertEqual(len(attempts), 1)
        clock.advance(60)
        supervisor.check()
        self.assertEqual(len(attempts), 1)
        clock.advance(Supervisor.AUTH_BLOCK_COOLDOWN_SECONDS)
        supervisor.check()
        self.assertEqual(len(attempts), 2)


if __name__ == "__main__":
    unittest.main()
