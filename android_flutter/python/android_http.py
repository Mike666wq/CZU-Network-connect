"""Ticket-based Android transport; importing this module does not load Java."""
from __future__ import annotations

import base64
import json
import math
import time
from urllib.parse import urljoin, urlsplit

from campus_assistant.protocol import PortalError


class AndroidHttp:
    MAX_BODY = 1_000_000
    MAX_REPLY = 2_000_000
    MAX_REDIRECTS = 4
    NATIVE_CLASS = "io.github.Mike666wq.czuconnect.AndroidHttp"
    SAFE_ERRORS = {"检查已取消", "请求总超时", "门户响应过大", "网络请求失败",
                   "网络请求参数过大", "门户跳转到其他主机，已停止", "门户跳转次数过多"}

    def __init__(self, timeout: float = 4.0, *, ticket_factory=None):
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be positive and finite")
        self.timeout = timeout
        self.last_headers = {}
        self.cancel_check = lambda: False
        self._ticket_factory = ticket_factory

    @staticmethod
    def _url(url):
        parts = urlsplit(url)
        if (parts.scheme not in {"http", "https"} or not parts.hostname
                or parts.username or parts.password or parts.fragment):
            raise ValueError
        if parts.port is not None and not 1 <= parts.port <= 65535:
            raise ValueError
        return parts

    def _check(self, deadline):
        if self.cancel_check():
            raise PortalError("检查已取消")
        if time.monotonic() >= deadline:
            raise PortalError("请求总超时")

    def _request(self, url, headers_json, deadline):
        ticket = None
        try:
            self._check(deadline)
            if self._ticket_factory is None:
                from java import jclass
                self._ticket_factory = jclass(self.NATIVE_CLASS).start
            self._check(deadline)
            remaining_ms = max(1, math.ceil((deadline - time.monotonic()) * 1000))
            ticket = self._ticket_factory(url, headers_json, remaining_ms)
            while True:
                self._check(deadline)
                wait_ms = min(50, max(1, math.ceil((deadline - time.monotonic()) * 1000)))
                done = ticket.awaitDone(wait_ms)
                self._check(deadline)
                if done:
                    break
            raw = str(ticket.result())
            self._check(deadline)
            if len(raw) > self.MAX_REPLY:
                raise PortalError("门户响应过大")
            reply = json.loads(raw)
            encoded = reply["body"]
            if not isinstance(encoded, str):
                raise ValueError
            if len(encoded) > 4 * ((self.MAX_BODY + 2) // 3):
                raise PortalError("门户响应过大")
            body = base64.b64decode(encoded, validate=True)
            # Native has already inflated gzip; do not call DirectHttp._read_body.
            if len(body) > self.MAX_BODY:
                raise PortalError("门户响应过大")
            status, encoding, final, headers = (reply[k] for k in ("status", "encoding", "final", "headers"))
            if (type(status) is not int or not 100 <= status <= 599
                    or not isinstance(encoding, str) or not encoding or len(encoding) > 80
                    or not isinstance(final, str) or final != url
                    or not isinstance(headers, dict)
                    or any(not isinstance(k, str) or not isinstance(v, str) for k, v in headers.items())):
                raise ValueError
            self._url(final)
            self._check(deadline)
            return status, body, encoding, final, headers
        except PortalError:
            raise
        except Exception:
            # Java failures may include a credential-bearing URL, even when sanitized upstream.
            self._check(deadline)
            raise PortalError("网络请求失败") from None
        finally:
            if ticket is not None:
                try:
                    ticket.cancel()
                except Exception:
                    pass

    def get(self, url: str, *, headers=None, same_host_redirects=False):
        self.last_headers = {}
        deadline = time.monotonic() + self.timeout
        try:
            original_host = self._url(url).hostname
            request_headers = headers if headers is not None else {"User-Agent": "CampusNetworkAssistant/0.1"}
            if not isinstance(request_headers, dict) or any(
                    not isinstance(k, str) or not isinstance(v, str) for k, v in request_headers.items()):
                raise ValueError
            headers_json = json.dumps(request_headers, ensure_ascii=True)
            if len(url) + len(headers_json) > 131_072:
                raise PortalError("网络请求参数过大")
            current = url
            for redirects in range(self.MAX_REDIRECTS + 1):
                status, body, encoding, final, response_headers = self._request(current, headers_json, deadline)
                location = next((v for k, v in response_headers.items() if k.lower() == "location"), "")
                if same_host_redirects and status in {301, 302, 303, 307, 308} and location:
                    target = urljoin(current, location)
                    if self._url(target).hostname != original_host:
                        raise PortalError("门户跳转到其他主机，已停止")
                    if redirects == self.MAX_REDIRECTS:
                        raise PortalError("门户跳转次数过多")
                    current = target
                    continue
                self._check(deadline)
                self.last_headers = response_headers
                return status, body, encoding, final
        except PortalError as exc:
            if str(exc) in self.SAFE_ERRORS:
                raise
            raise PortalError("网络请求失败") from None
        except Exception:
            raise PortalError("网络请求失败") from None
