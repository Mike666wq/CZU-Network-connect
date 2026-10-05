from __future__ import annotations

import json
import gzip
import io
import re
import base64
import subprocess
import sys
import os
from pathlib import Path
import time
from urllib.parse import urlsplit, urljoin
from dataclasses import dataclass
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class PortalError(Exception):
    pass


@dataclass(frozen=True)
class PortalResult:
    success: bool
    category: str
    message: str


ERRORS = {
    "2": ("already_online", "该账号当前已在线"),
    "3": ("temporary", "认证服务繁忙"),
    "5": ("temporary", "认证 challenge 失败"),
    "6": ("temporary", "认证 challenge 超时"),
    "7": ("temporary", "Radius 认证失败"),
    "8": ("temporary", "Radius 认证超时"),
    "11": ("temporary", "认证服务暂时错误"),
    "998": ("configuration", "门户参数不完整"),
}


class DirectHttp:
    """HTTP access that bypasses system HTTP proxy settings without changing VPN."""

    def __init__(self, timeout: float = 3.0):
        self.timeout = timeout
        self.last_headers = {}
        class NoRedirect(HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    @staticmethod
    def _read_body(response):
        body = response.read(1_000_001)
        if len(body) > 1_000_000:
            raise PortalError("门户响应过大")
        encoding = response.headers.get("Content-Encoding", "").lower()
        if encoding == "gzip" or body.startswith(b"\x1f\x8b"):
            try:
                with gzip.GzipFile(fileobj=io.BytesIO(body)) as compressed:
                    body = compressed.read(1_000_001)
                if len(body) > 1_000_000:
                    raise PortalError("门户响应过大")
            except (OSError, EOFError):
                raise PortalError("门户压缩响应无法解析") from None
        return body

    def get(self, url: str, *, headers: dict[str, str] | None = None, same_host_redirects: bool = False) -> tuple[int, bytes, str, str]:
        current = url
        original_host = urlsplit(url).hostname
        for _ in range(4):
            req = Request(current, headers=headers or {"User-Agent": "CampusNetworkAssistant/0.1"})
            try:
                with self.opener.open(req, timeout=self.timeout) as response:
                    self.last_headers = dict(response.headers.items())
                    return response.status, self._read_body(response), response.headers.get_content_charset() or "utf-8", response.geturl()
            except PortalError:
                raise
            except Exception as exc:
                response = getattr(exc, "fp", None)
                headers_obj = getattr(exc, "headers", None)
                code = getattr(exc, "code", None)
                location = headers_obj.get("Location") if headers_obj else None
                if code in {301, 302, 303, 307, 308} and location and same_host_redirects:
                    target = urljoin(current, location)
                    if urlsplit(target).hostname != original_host:
                        raise PortalError("门户跳转到其他主机，已停止") from None
                    current = target
                    continue
                if isinstance(code, int) and response is not None:
                    # Do not follow redirects. Preserve status/Location as scene evidence.
                    with exc as error_response:
                        self.last_headers = dict(error_response.headers.items())
                        return code, self._read_body(error_response), error_response.headers.get_content_charset() or "utf-8", current
                if isinstance(code, int):
                    raise PortalError(f"HTTP {code}") from None
                raise PortalError(type(exc).__name__) from None
        raise PortalError("门户跳转次数过多")


def http_worker_entry() -> int:
    """One bounded HTTP request over private stdin/stdout, without Qt or a resource tracker."""
    try:
        raw = sys.stdin.buffer.read(131_073)
        if len(raw) > 131_072:
            raise PortalError("网络请求参数过大")
        request = json.loads(raw)
        http = DirectHttp(float(request["timeout"]))
        result = http.get(request["url"], headers=request.get("headers"),
                          same_host_redirects=bool(request.get("same_host_redirects")))
        status, body, encoding, final = result
        reply = {"ok": True, "status": status, "body": base64.b64encode(body).decode("ascii"),
                 "encoding": encoding, "final": final, "headers": http.last_headers}
    except PortalError as exc:
        reply = {"ok": False, "error": str(exc)}
    except Exception as exc:
        reply = {"ok": False, "error": type(exc).__name__}
    # This channel is not a log: credentials never enter argv or console diagnostics.
    sys.stdout.buffer.write(json.dumps(reply, ensure_ascii=True).encode("ascii"))
    sys.stdout.buffer.flush()
    return 0


class BoundedHttp:
    """Total deadline and cancellation, with a transient stdlib-only child process.

    Separate from the GUI entry path; no multiprocessing/resource_tracker daemon.
    The exact proxy bypass, TLS checks, body bounds and redirect rules are unchanged.
    Credentials travel over private stdin, not command-line arguments or log files.
    """

    def __init__(self, timeout: float = 4.0):
        self.timeout = timeout
        self.last_headers = {}
        self.cancel_check = lambda: False

    @staticmethod
    def _worker_command():
        if getattr(sys, "frozen", False):
            if sys.platform == "win32":
                worker = Path(sys.executable).resolve().parent / "http-worker" / "campus-http-worker.exe"
                if not worker.is_file():
                    raise PortalError("网络请求工作程序缺失，请完整解压应用包")
                return [str(worker)]
            return [sys.executable, "--http-worker"]
        return [sys.executable, str(Path(__file__).resolve().parents[1] / "main.py"), "--http-worker"]

    def get(self, url, *, headers=None, same_host_redirects=False):
        if self.cancel_check():
            raise PortalError("检查已取消")
        self.last_headers = {}
        payload = json.dumps({"url": url, "headers": headers, "same_host_redirects": same_host_redirects,
                              "timeout": self.timeout}, ensure_ascii=True).encode("ascii")
        if len(payload) > 131_072:
            raise PortalError("网络请求参数过大")
        deadline = time.monotonic() + self.timeout
        process = None
        try:
            options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
            process = subprocess.Popen(self._worker_command(), stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, **options)
            first = True
            while True:
                if self.cancel_check():
                    raise PortalError("检查已取消")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise PortalError("请求总超时")
                try:
                    output, _ = process.communicate(input=payload if first else None, timeout=min(0.05, remaining))
                    break
                except subprocess.TimeoutExpired:
                    first = False
            if process.returncode != 0 or len(output) > 2_000_000:
                raise PortalError("网络请求进程异常")
            response = json.loads(output)
            if not response.get("ok"):
                raise PortalError(response.get("error", "网络请求进程异常"))
            body = base64.b64decode(response["body"], validate=True)
            if len(body) > 1_000_000:
                raise PortalError("门户响应过大")
            self.last_headers = response["headers"]
            return response["status"], body, response["encoding"], response["final"]
        except (OSError, EOFError, KeyError, TypeError, ValueError):
            raise PortalError("网络请求进程异常") from None
        finally:
            if process is not None:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(0.2)
                    except subprocess.TimeoutExpired:
                        process.kill(); process.wait()
                for pipe in (process.stdin, process.stdout):
                    if pipe is not None:
                        pipe.close()


def parse_jsonp(payload: bytes | str, encoding: str = "utf-8") -> dict:
    if isinstance(payload, bytes):
        try:
            text = payload.decode(encoding, "strict")
        except (LookupError, UnicodeDecodeError) as exc:
            raise PortalError("门户返回编码无法解析") from exc
    else:
        text = payload
    match = re.fullmatch(r"\s*[\w$.]+\s*\((.*)\)\s*;?\s*", text, flags=re.S)
    if not match:
        raise PortalError("门户返回格式无法识别")
    try:
        obj = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise PortalError("门户返回内容无法解析") from exc
    if not isinstance(obj, dict):
        raise PortalError("门户返回结构异常")
    return obj


def classify_result(obj: dict) -> PortalResult:
    result = str(obj.get("result", "")).lower()
    if result in {"1", "ok", "success"}:
        return PortalResult(True, "success", "门户报告认证成功")
    code = str(obj.get("ret_code", obj.get("retCode", "")))
    if code == "2":
        return PortalResult(False, "already_online", "账号已在线")
    if code in ERRORS:
        category, message = ERRORS[code]
        return PortalResult(False, category, message)
    # Server-provided text is never logged; classify conservatively.
    return PortalResult(False, "unknown", "门户返回未识别结果")
