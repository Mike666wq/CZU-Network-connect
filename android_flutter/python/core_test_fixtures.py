"""Socket-free core fixtures; distinct from the debug-only device_checks module."""
from __future__ import annotations

import base64
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs, urlsplit

from android_http import AndroidHttp
from campus_android import Bridge
from campus_assistant import __version__


class CompletedTicket:
    def __init__(self, reply):
        self.reply = json.dumps(reply, ensure_ascii=True)
        self.cancelled = False

    def awaitDone(self, ms):
        return True

    def cancel(self):
        self.cancelled = True

    def result(self):
        return self.reply


class FixtureNetwork:
    """Same Dr.COM shapes as the core protocol regressions, with no socket access.

    transport_factory(timeout=...) returns AndroidHttp backed by completed tickets.
    Mutable settings/login_response/online let instrumentation drive later ticks.
    Captured requests stay in memory and must never be copied to production logs.
    """

    def __init__(self, scene="public", scenario="success"):
        if scene not in {"public", "dorm"} or scenario not in {
                "success", "already_online", "account", "critical", "advisory", "unknown", "offline"}:
            raise ValueError("Unknown fixture")
        self.scene, self.scenario = scene, scenario
        self.online = False
        self.settings = {"program_index": "fixture", "login_method": 1, "enable_r3": 0,
                         "en_md5": 0, "password_cut": 0, "account_suffix": "",
                         "account_prefix": 0 if scene == "dorm" else 1, "io_mode": 0}
        if scenario == "critical":
            self.settings["en_md5"] = 1
        if scenario == "advisory":
            self.settings["enable_r3"] = "private-server-text"
        self.login_response = ({"result": 0, "msg": "invalid password private-server-text"}
                               if scenario == "account" else {"result": 1})
        if scenario == "unknown":
            self.login_response = {"msg": "private-server-text"}
        self.requests = []
        self.timeouts = []

    def transport_factory(self, timeout):
        self.timeouts.append(timeout)
        return AndroidHttp(timeout=timeout, ticket_factory=self.start)

    def start(self, url, headers_json, timeout_ms):
        self.requests.append((url, json.loads(headers_json), timeout_ms))
        parts = urlsplit(url)
        status, body, encoding, headers = 200, b"", "utf-8", {}
        if parts.scheme == "https":
            if self.online:
                status = 204
            else:
                status, headers = 302, {"Location": "http://192.168.255.4/"}
        elif parts.path == "/":
            known = parts.hostname == ("172.19.0.1" if self.scene == "dorm" else "192.168.255.4")
            if known and self.scenario != "offline":
                body = ("<!--Dr.COMWebLoginID_1.htm--><script src='a41.js'></script>"
                        "<script>v4ip='10.20.30.40';</script>").encode()
            else:
                body = b"unrelated page"
        elif parts.path == "/drcom/chkstatus":
            result = 1 if self.scenario == "already_online" else 0
            body = self._jsonp({"result": result})
            if result:
                self.online = True
        elif parts.path == "/eportal/portal/page/loadConfig":
            body = self._jsonp({"data": self.settings})
        elif parts.path == "/eportal/portal/login":
            body = self._jsonp(self.login_response)
            if self.login_response.get("result") == 1:
                self.online = True
        else:
            raise AssertionError("Unexpected fixture endpoint")
        return CompletedTicket({"status": status, "body": base64.b64encode(body).decode("ascii"),
                                "encoding": encoding, "final": url, "headers": headers})

    @staticmethod
    def _jsonp(value):
        return ("drfixture(" + json.dumps(value) + ");").encode()

    def login_queries(self):
        return [parse_qs(urlsplit(url).query, keep_blank_values=True)
                for url, _, _ in self.requests if urlsplit(url).path == "/eportal/portal/login"]


def make_bridge(data_dir, scene="public", scenario="success"):
    """Return a configured Bridge using only FixtureNetwork, never Android sockets."""
    fixture = FixtureNetwork(scene, scenario)
    bridge = Bridge(data_dir, transport_factory=fixture.transport_factory)
    bridge.save_config(json.dumps({"username": "fixture-user", "password": "fixture-password",
                                   "isp": "@cmcc" if scene == "dorm" else "-1", "scene": scene}))
    return bridge


def run(data_dir):
    """Return JSON {ok, coreVersion, checks}; isolated temporary private configs."""
    checks = []
    for scene in ("public", "dorm"):
        with TemporaryDirectory(prefix="bridge-check-", dir=Path(data_dir)) as private:
            bridge = make_bridge(private, scene)
            delay = bridge.tick("fixture-network", True)
            snapshot = json.loads(bridge.snapshot())
            assert type(delay) is int and snapshot["online"]
            assert snapshot["state"] == "authenticated"
            bridge.stop()
            assert json.loads(bridge.snapshot())["state"] == "paused"
            checks.append(scene)
    return json.dumps({"ok": True, "coreVersion": __version__, "checks": checks})
