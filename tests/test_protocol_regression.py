from __future__ import annotations

import base64
import io
import json
import unittest
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

from campus_assistant.engine import State, Supervisor
from campus_assistant.protocol import DirectHttp, PortalError, parse_jsonp
from campus_assistant.service import CampusService


PORTAL_URL = "http://portal.test/"
PORTAL_HOST = "portal.test"
CONFIG_PATH = "/eportal/portal/page/loadConfig"
LOGIN_PATH = "/eportal/portal/login"


class FakeHttp:
    """In-memory HTTP fixture. It never opens a socket."""

    def __init__(self, page: str, settings: dict | None = None, login_response: dict | None = None,
                 online_result: int = 0):
        self.page = page.encode("gbk")
        self.settings = settings or {
            "program_index": "public-campus",
            "login_method": 1,
            "enable_r3": 0,
            "en_md5": 0,
            "password_cut": 0,
            "account_suffix": "",
            "account_prefix": 1,
            "io_mode": 0,
        }
        self.login_response = login_response or {"result": 1}
        self.online_result = online_result
        self.last_headers: dict[str, str] = {}
        self.calls: list[tuple[str, bool]] = []
        self.root_final_url = ""

    def get(self, url: str, *, headers=None, same_host_redirects: bool = False):
        self.calls.append((url, same_host_redirects))
        parts = urlsplit(url)
        final = url
        if parts.path == "/":
            self.last_headers = {"Server": "DrcomServer1.0"}
            return 200, self.page, "gb2312", self.root_final_url or final
        if parts.path == CONFIG_PATH:
            self.last_headers = {"Content-Type": "application/javascript; charset=utf-8"}
            payload = "drfixture(" + json.dumps({"data": self.settings}) + ");"
            return 200, payload.encode(), "utf-8", final
        if parts.path == "/drcom/chkstatus":
            self.last_headers = {"Content-Type": "application/javascript; charset=utf-8"}
            payload = "drfixture(" + json.dumps({"result": self.online_result}) + ");"
            return 200, payload.encode(), "utf-8", final
        if parts.path == LOGIN_PATH:
            self.last_headers = {"Content-Type": "application/javascript; charset=utf-8"}
            payload = "drfixture(" + json.dumps(self.login_response) + ");"
            return 200, payload.encode(), "utf-8", final
        raise AssertionError(f"Unexpected fake request: {parts.path}")


def base_config(**overrides) -> dict:
    config = {
        "active_profile": "public",
        "credential_mode": "shared",
        "username": "shared-user",
        "password": "shared-secret",
        "provider_suffix": "",
        "profiles": {
            "public": {"portal_url": PORTAL_URL, "username": "pub-user", "password": "pub-secret", "provider_suffix": ""},
            "dorm": {"portal_url": "http://dorm.test/", "username": "dorm-user", "password": "dorm-secret", "provider_suffix": ""},
        },
        "internet_probe_urls": [],
    }
    config.update(overrides)
    return config


def portal_page(query: str = "", globals_: str = "") -> str:
    return (
        "<html><body>/drcom/ <script src='a41.js?version=1748398885004'></script>"
        + globals_
        + "</body></html>"
    )


def service_for(page: str, *, config: dict | None = None, settings: dict | None = None,
                online_result: int = 0, final_url: str = "") -> tuple[CampusService, FakeHttp]:
    fake = FakeHttp(page, settings=settings, online_result=online_result)
    fake.root_final_url = final_url
    service = CampusService(config or base_config(), http=fake)
    return service, fake


class ProtocolRegressionTests(unittest.TestCase):
    def test_jsonp_is_parsed_as_data_and_never_executed(self):
        marker: list[str] = []
        with self.assertRaises(PortalError):
            parse_jsonp('dr1({"result":1});marker.append("executed")')
        self.assertEqual(marker, [])
        self.assertEqual(parse_jsonp('dr1({"result":1});'), {"result": 1})

    def test_cross_host_redirect_is_stopped_without_following_credentials(self):
        requested: list[str] = []

        class RedirectOpener:
            def open(self, request, timeout):
                requested.append(request.full_url)
                raise HTTPError(
                    request.full_url,
                    302,
                    "redirect",
                    {"Location": "http://attacker.test/collect"},
                    io.BytesIO(b""),
                )

        http = DirectHttp()
        http.opener = RedirectOpener()
        with self.assertRaises(PortalError):
            http.get("http://portal.test:801/eportal/portal/login?user_password=secret", same_host_redirects=True)
        self.assertEqual(len(requested), 1)
        self.assertEqual(urlsplit(requested[0]).hostname, "portal.test")
        self.assertNotIn("attacker.test", "\n".join(requested))

    def test_drcom_identity_is_accepted_and_sets_known_portal(self):
        service, fake = service_for(portal_page())
        self.assertTrue(service.identify_portal())
        self.assertTrue(service.portal_known)
        self.assertEqual(service.profile_name, "public")
        self.assertEqual(service.portal_host, PORTAL_HOST)
        self.assertEqual(len(fake.calls), 1)

    def test_loadconfig_uses_portal_endpoint_and_nested_data_fields(self):
        service, fake = service_for(portal_page(globals_="v4ip='10.20.30.40';"), final_url=PORTAL_URL + "?ip=10.20.30.40")
        self.assertTrue(service.identify_portal())
        result = service.authenticate()
        self.assertTrue(result.success, result.message)

        load_calls = [url for url, _ in fake.calls if urlsplit(url).path.endswith("loadConfig")]
        self.assertEqual(len(load_calls), 1)
        parts = urlsplit(load_calls[0])
        self.assertEqual(parts.path, CONFIG_PATH)
        query = parse_qs(parts.query, keep_blank_values=True)
        self.assertEqual(query.get("program_index"), [""])
        self.assertEqual(query.get("wlan_vlan_id"), ["1"])
        self.assertEqual(query.get("wlan_user_ip"), [base64.b64encode(b"10.20.30.40").decode()])
        self.assertEqual(query.get("wlan_user_ipv6"), [base64.b64encode(b"").decode()])
        self.assertEqual(query.get("wlan_ac_ip"), [base64.b64encode(b"").decode()])
        self.assertEqual(query.get("wlan_user_ssid"), [""])
        self.assertEqual(query.get("wlan_user_areaid"), [""])
        self.assertIn("callback", query)
        self.assertIn("jsVersion", query)

    def test_portal_online_check_skips_login_submission(self):
        service, fake = service_for(portal_page(globals_="v4ip='10.20.30.40';"), online_result=1,
                                    final_url=PORTAL_URL + "?ip=10.20.30.40")
        self.assertTrue(service.identify_portal())
        result = service.authenticate()
        self.assertEqual(result.category, "already_online")
        self.assertFalse(any(urlsplit(url).path == LOGIN_PATH for url, _ in fake.calls))

    def test_method1_login_accepts_minimal_runtime_and_uses_raw_values(self):
        service, fake = service_for(portal_page(globals_="v4ip='10.20.30.40';"), final_url=PORTAL_URL + "?ip=10.20.30.40")
        self.assertTrue(service.identify_portal())
        result = service.authenticate()
        self.assertTrue(result.success, result.message)

        calls = [url for url, _ in fake.calls if urlsplit(url).path == LOGIN_PATH]
        self.assertEqual(len(calls), 1)
        query = parse_qs(urlsplit(calls[0]).query, keep_blank_values=True)
        self.assertEqual(query["login_method"], ["1"])
        self.assertEqual(query["program_index"], ["public-campus"])
        self.assertEqual(query["user_account"], [",0,shared-user"])
        self.assertEqual(query["user_password"], ["shared-secret"])
        self.assertEqual(query["wlan_user_ip"], ["10.20.30.40"])
        self.assertEqual(query["wlan_user_ipv6"], [""])
        self.assertEqual(query["wlan_ac_ip"], [""])
        self.assertEqual(query["wlan_ac_name"], [""])
        self.assertEqual(query["wlan_ap_mac"], ["000000000000"])
        self.assertEqual(query["gw_id"], ["000000000000"])
        self.assertEqual(query["wlan_user_ssid"], [""])
        self.assertEqual(query["wlan_user_areaid"], [""])
        self.assertEqual(query["terminal_type"], ["1"])
        self.assertEqual(query["jsVersion"], ["4.2.1"])
        self.assertEqual(query["lang"], ["zh"])

    def test_unknown_mac_defaults_to_zero_and_is_not_a_blocker(self):
        service, fake = service_for(portal_page(globals_="v4ip='10.20.30.40';"), final_url=PORTAL_URL + "?ip=10.20.30.40")
        self.assertTrue(service.identify_portal())
        result = service.authenticate()
        self.assertTrue(result.success, result.message)
        call = next(url for url, _ in fake.calls if urlsplit(url).path == LOGIN_PATH)
        self.assertEqual(parse_qs(urlsplit(call).query, keep_blank_values=True)["wlan_user_mac"], ["000000000000"])

    def test_ipv4_query_alias_and_inline_v4ip_fallback_are_resolved(self):
        cases = (
            (portal_page(), "http://portal.test/?UserIP=10.1.2.3", "10.1.2.3"),
            (portal_page(globals_="v4ip='10.9.8.7';"), "", "10.9.8.7"),
        )
        for page, root_final, expected in cases:
            with self.subTest(expected=expected):
                service, _ = service_for(page)
                # Simulate the captive redirect URL as the portal document URL.
                service.http.root_final_url = root_final
                self.assertTrue(service.identify_portal())
                self.assertEqual(service.runtime["ip"], expected)

    def test_online_state_does_not_reauthenticate(self):
        calls = {"probe": 0, "identify": 0, "auth": 0}

        def probe():
            calls["probe"] += 1
            return True, "public"

        def identify():
            calls["identify"] += 1
            return True

        def authenticate():
            calls["auth"] += 1
            return type("Result", (), {"success": True, "category": "success", "message": "ok"})()

        outcome = Supervisor(probe, identify, authenticate).check()
        self.assertEqual(outcome.state, State.ONLINE)
        self.assertEqual(calls, {"probe": 1, "identify": 0, "auth": 0})

    def test_shared_credentials_use_the_active_profile_provider_suffix(self):
        config = base_config(provider_suffix="wrong-global-suffix")
        config["profiles"]["public"]["provider_suffix"] = "@public-isp"
        service, fake = service_for(portal_page(globals_="v4ip='10.20.30.40';"), config=config,
                                    final_url=PORTAL_URL + "?ip=10.20.30.40")
        self.assertTrue(service.identify_portal())
        result = service.authenticate()
        self.assertTrue(result.success, result.message)
        call = next(url for url, _ in fake.calls if urlsplit(url).path == LOGIN_PATH)
        query = parse_qs(urlsplit(call).query, keep_blank_values=True)
        self.assertEqual(query["user_account"], [",0,shared-user@public-isp"])
        self.assertEqual(query["user_password"], ["shared-secret"])

    def test_login_method1_ip_mac_and_ac_addresses_are_not_base64(self):
        page = portal_page(globals_="v4ip='10.20.30.40'; ss4='aa-bb:cc-dd';")
        service, fake = service_for(page, final_url=PORTAL_URL + "?ip=10.20.30.40")
        self.assertTrue(service.identify_portal())
        service.runtime.update({"ipv6": "2001:db8::1", "ac_ip": "10.0.0.8", "ac_name": "access-controller"})
        result = service.authenticate()
        self.assertTrue(result.success, result.message)
        call = next(url for url, _ in fake.calls if urlsplit(url).path == LOGIN_PATH)
        query = parse_qs(urlsplit(call).query, keep_blank_values=True)
        self.assertEqual(query["wlan_user_ip"], ["10.20.30.40"])
        self.assertEqual(query["wlan_user_ipv6"], ["2001:db8::1"])
        self.assertEqual(query["wlan_ac_ip"], ["10.0.0.8"])
        self.assertEqual(query["wlan_user_mac"], ["aabbccdd"])
        self.assertEqual(query["wlan_ac_name"], ["access-controller"])


if __name__ == "__main__":
    unittest.main()
