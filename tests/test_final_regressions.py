from __future__ import annotations

import json
from urllib.parse import urlsplit

from campus_assistant.engine import State, Supervisor
from campus_assistant.service import CampusService


class PortalFixture:
    def __init__(self, message: str = "", ret_code: int = 7, on_load=None):
        self.message, self.ret_code, self.on_load = message, ret_code, on_load
        self.calls = []
        self.last_headers = {}
        self.root_final_url = "http://portal.test/?ip=10.20.30.40"

    def get(self, url, *, headers=None, same_host_redirects=False):
        self.calls.append(url)
        path = urlsplit(url).path
        if path == "/":
            return 200, b"<html>/drcom/ <script src='a41.js'></script> Dr.COMWebLoginID_pc</html>", "gbk", self.root_final_url
        if path.endswith("/page/loadConfig"):
            if self.on_load: self.on_load()
            payload = {"code": 1, "data": {"program_index": "public-campus", "login_method": 1,
                "enable_r3": 0, "en_md5": 0, "password_cut": 0, "account_suffix": "",
                "account_prefix": 1, "io_mode": 0}}
            return 200, ("dr0(" + json.dumps(payload) + ");").encode(), "utf-8", url
        if path == "/drcom/chkstatus":
            return 200, b'dr0({"result":0});', "utf-8", url
        if path.endswith("/portal/login"):
            body = json.dumps({"result": 0, "ret_code": self.ret_code, "msg": self.message}, ensure_ascii=False)
            return 200, ("dr0(" + body + ");").encode("gbk"), "gbk", url
        raise AssertionError(path)


def config():
    return {"active_profile": "public", "credential_mode": "shared", "username": "user", "password": "secret",
        "profiles": {"public": {"portal_url": "http://portal.test/", "username": "", "password": "", "provider_suffix": ""},
                     "dorm": {"portal_url": "http://dorm.test/", "username": "", "password": "", "provider_suffix": ""}},
        "internet_probe_urls": []}


def service_and_http(http):
    service = CampusService(config(), http=http)
    service.profile = config()["profiles"]["public"]
    return service


def test_gbk_password_message_overrides_radius_temporary_code_without_leaking_text():
    http = PortalFixture("密码错误", ret_code=7)
    service = service_and_http(http)
    assert service.identify_portal()
    result = service.authenticate()
    assert result.category == "account"
    assert result.message == "账号或密码错误"
    assert "secret" not in result.message


def test_radius_timeout_remains_temporary():
    http = PortalFixture("Radius timeout", ret_code=7)
    service = service_and_http(http)
    assert service.identify_portal()
    assert service.authenticate().category == "temporary"


def test_network_change_during_loadconfig_prevents_login_submission():
    holder = {}
    http = PortalFixture(on_load=lambda: holder["supervisor"].network_changed("new-wifi"))
    service = service_and_http(http)
    sup = Supervisor(lambda: (False, "offline"), service.identify_portal, service.authenticate)
    holder["supervisor"] = sup
    outcome = sup.check()
    assert outcome.state == State.CHECKING
    assert not any(urlsplit(url).path.endswith("/portal/login") for url in http.calls)
