from __future__ import annotations

import base64
import re
import uuid
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlencode, urlsplit, urljoin

from .config import DORM_PROVIDERS
from .protocol import BoundedHttp, DirectHttp, PortalError, PortalResult, classify_result, parse_jsonp


def _query_value(query: dict[str, list[str]], aliases: tuple[str, ...]) -> str:
    for key in aliases:
        if query.get(key) and query[key][0]:
            return query[key][0]
    return ""


class _ScriptSources(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sources: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "script":
            self.sources.extend(value for key, value in attrs if key.lower() == "src" and value)


def _is_public_drcom_page(text: str, document_url: str) -> bool:
    """Recognize verified login/online pages without trusting substring-only script URLs."""
    scripts = _ScriptSources()
    scripts.feed(text)
    host = urlsplit(document_url).hostname
    trusted_script = any(
        target.scheme in {"http", "https"}
        and target.hostname == host
        and not target.username and not target.password
        and target.path.rsplit("/", 1)[-1] == "a41.js"
        for target in (urlsplit(urljoin(document_url, source)) for source in scripts.sources)
    )
    # The inspected online page has a Dr.COMWebLoginID marker but no /drcom/ route.
    page_marker = bool(re.search(r"Dr\.COM(?:1\.0)?WebLoginID_[\w.-]+", text)) or "/drcom/" in text
    return trusted_script and page_marker


class CampusService:
    """Adapters for the independently inspected public and dorm Dr.COM configurations."""

    def __init__(self, config: dict, http: DirectHttp | None = None):
        self.config = config
        # Local portal requests may be slower than the small public connectivity probes.
        self.http = http if http is not None else BoundedHttp(timeout=10)
        self.probe_http = http if http is not None else BoundedHttp(timeout=4)
        self.selection_mode = config.get("active_profile", "auto")
        self.auto_mode = self.selection_mode == "auto"
        self.profile_name = self.selection_mode
        self.portal_host = ""
        self.portal_api = ""
        self.portal_known = False
        self.page = ""
        self.final_url = ""
        self.runtime: dict[str, str] = {}
        self.portal_settings: dict[str, str] = {}
        self.portal_error = ""
        self.cancel_check = lambda: False
        self.progress = lambda message: None
        self.captive_host = ""
        self.auth_submitted = False

    def set_cancel_check(self, callback):
        self.cancel_check = callback
        for transport in (self.http, self.probe_http):
            if hasattr(transport, "cancel_check"):
                transport.cancel_check = callback

    def probe_internet(self) -> tuple[bool, str]:
        self.captive_host = ""
        urls = self.config["internet_probe_urls"]
        for index, url in enumerate(urls, 1):
            if self.cancel_check():
                return False, "cancelled"
            self.progress(f"正在检测互联网（探测 {index}/{len(urls)}）")
            try:
                status, body, _, final = self.probe_http.get(url)
                if status in {301, 302, 303, 307, 308}:
                    headers = {k.lower(): v for k, v in self.probe_http.last_headers.items()}
                    target = urljoin(final, headers.get("location", ""))
                    hint = urlsplit(target).hostname
                    known_hosts = {urlsplit(p["portal_url"]).hostname for p in self.config["profiles"].values()}
                    if hint in known_hosts:
                        self.captive_host = hint
                expected = ((status == 204 and not body) or
                            (status == 200 and body.strip() == b"Microsoft Connect Test"))
                if (urlsplit(final).scheme == "https" and expected
                        and urlsplit(final).hostname == urlsplit(url).hostname):
                    return True, "public"
            except PortalError:
                pass
        return False, "offline"

    def _identify_one(self, profile_name: str) -> bool:
        profile = self.config["profiles"][profile_name]
        portal_url = profile["portal_url"].rstrip("/") + "/"
        host = urlsplit(portal_url).hostname
        try:
            status, body, charset, final = self.http.get(portal_url, same_host_redirects=True)
            if self.cancel_check(): return False
            if status != 200:
                self.portal_error = f"校园门户响应异常（HTTP {status}），未发送凭据"
                return False
            if urlsplit(final).hostname != host:
                self.portal_error = "校园门户跳转到其他主机，未发送凭据"
                return False
            text = body.decode("gbk" if "gb" in charset.lower() else charset, "replace")
            if not _is_public_drcom_page(text, final):
                self.portal_error = "入口可访问，但页面不是已支持的 Dr.COM 门户，未发送凭据"
                return False
            self.profile_name, self.profile = profile_name, profile
            self.portal_host, self.page, self.final_url = host, text, final
            protocol = urlsplit(final).scheme
            ep_port = 802 if protocol == "https" else 801
            self.portal_api = f"{protocol}://{host}:{ep_port}/eportal/portal/"
            self.portal_known = True
            query = parse_qs(urlsplit(final).query)
            aliases = {
                "ip": ("ip", "wlanuserip", "userip", "user-ip", "client_ip", "UserIP", "uip", "station_ip"),
                "ipv6": ("UserV6IP",),
                "mac": ("mac", "usermac", "user-mac", "wlanusermac", "umac", "client_mac", "station_mac"),
                "ac_ip": ("wlanacip", "acip", "switchip", "nasip", "nas-ip"),
                "ac_name": ("wlanacname", "sysname", "nasname", "nas-name"),
                "ssid": ("ssid", "wlanuserssid"), "areaid": ("areaid", "wlanuserareaid"),
                "vlan": ("vlan", "vlanid", "wlanvlanid"), "ap_mac": ("apmac", "wlanapmac"),
                "gw_id": ("gw_id", "gwid", "gw_mac"),
            }
            self.runtime = {key: _query_value(query, values) for key, values in aliases.items()}
            self.runtime.update({"ip": self.runtime.get("ip") or "0.0.0.0", "ipv6": self.runtime.get("ipv6", ""),
                "mac": self.runtime.get("mac") or "000000000000", "vlan": self.runtime.get("vlan") or "1",
                "ac_ip": self.runtime.get("ac_ip", ""), "ac_name": self.runtime.get("ac_name", ""),
                "ap_mac": self.runtime.get("ap_mac") or "000000000000", "ssid": self.runtime.get("ssid", ""),
                "areaid": self.runtime.get("areaid", ""), "gw_id": self.runtime.get("gw_id") or "000000000000"})
            # Inline public globals are a fallback when the captive redirect omits fields.
            for key, var in (("ip", "v46ip"), ("mac", "ss4"), ("ac_ip", "wlanacip"), ("ac_name", "wlanacname"),
                             ("ssid", "ssid"), ("areaid", "areaID"), ("vlan", "vlan"), ("ap_mac", "wlanapmac"), ("gw_id", "gw_id")):
                if not self.runtime.get(key) or self.runtime[key] in {"0.0.0.0", "000000000000"}:
                    m = re.search(r"\b" + re.escape(var) + r"\s*=\s*['\"]([^'\"]*)['\"]", text)
                    if m: self.runtime[key] = m.group(1)
            if self.runtime["ip"] in {"", "0.0.0.0"}:
                self.runtime["ip"] = self._first_js_string(text, ("ss5", "v4ip")) or self._hex16(self._first_js_string(text, ("ss3",))) or "0.0.0.0"
            if self.runtime["mac"] in {"", "000000000000"}:
                self.runtime["mac"] = self._first_js_string(text, ("olmac",)) or "000000000000"
            return True
        except PortalError as exc:
            self.portal_error = f"无法访问校园门户（{exc}），请检查校园网连接和认证入口；未发送凭据"
            return False
        except (UnicodeError, LookupError, ValueError):
            self.portal_error = "校园门户页面无法解析，未发送凭据"
            return False

    def identify_portal(self) -> bool:
        """Identify one configured scene in a deterministic order.

        Auto mode deliberately tries the public portal first and the dorm portal
        only if the public portal is not recognized. It never submits credentials
        during identification and never treats a generic reachable IP as a scene.
        """
        self.portal_known = False
        self.runtime = {}
        self.portal_error = ""
        self.scene_attempts: list[dict[str, str]] = []
        names = ("public", "dorm") if self.auto_mode else (self.profile_name,)
        for name in names:
            self.progress("正在识别" + ("公共网门户" if name == "public" else "宿舍网门户"))
            if self._identify_one(name):
                self.portal_error = ""
                return True
            self.scene_attempts.append({"scene": name, "error": self.portal_error or "入口未识别"})
        if self.auto_mode:
            self.portal_error = "当前不在可识别的校园网环境（公共网和宿舍网均未识别）"
        elif not self.portal_error:
            self.portal_error = "未识别到所选校园门户"
        return False

    def inspect_connected_scene(self) -> bool:
        """Identify only; never load credentials or submit a login while checking an online scene."""
        return self.identify_portal()

    @staticmethod
    def _safe_error(exc: PortalError) -> str:
        # Do not display arbitrary server content, request URLs or credential-bearing exceptions.
        reason = str(exc)
        safe = {"请求总超时", "检查已取消", "网络请求进程异常", "门户返回编码无法解析",
                "门户返回格式无法识别", "门户返回内容无法解析", "门户返回结构异常",
                "门户跳转到其他主机，已停止", "门户跳转次数过多", "URLError", "TimeoutError",
                "SSLError", "ConnectionRefusedError", "ConnectionResetError"}
        return reason if reason in safe or re.fullmatch(r"HTTP [1-5]\d{2}", reason) else "网络请求失败"

    def check_portal_status(self) -> PortalResult:
        """Read-only: never loads credentials or invokes an authentication endpoint."""
        if not self.portal_known or self.profile_name not in {"public", "dorm"}:
            return PortalResult(False, "unsupported", "校园门户身份尚未确认，未发送凭据")
        self.progress("正在查询校园网是否已认证")
        callback = "dr" + uuid.uuid4().hex[:8]
        try:
            origin = f"{urlsplit(self.final_url).scheme}://{self.portal_host}"
            chk_status, chk_body, chk_charset, _ = self.http.get(origin + "/drcom/chkstatus?" +
                urlencode(self._common_jsonp({"callback": callback})))
            if chk_status != 200:
                return PortalResult(False, "temporary", f"校园在线状态响应异常（HTTP {chk_status}），未发送凭据")
            chk = parse_jsonp(chk_body, chk_charset)
            if self.cancel_check(): return PortalResult(False, "cancelled", "网络已切换")
            if str(chk.get("result", "")) == "1":
                return PortalResult(False, "already_online", "账号已在线")
            if str(chk.get("result", "")) != "0":
                return PortalResult(False, "temporary", "门户在线状态无法确认")
        except PortalError as exc:
            return PortalResult(False, "temporary", "无法查询校园认证状态：" + self._safe_error(exc) + "；未发送凭据")
        return PortalResult(False, "not_online", "门户报告当前未认证")


    def load_portal_config(self) -> PortalResult:
        """Read-only configuration loading and strict protocol validation."""
        if not self.portal_known or self.profile_name not in {"public", "dorm"}:
            return PortalResult(False, "unsupported", "校园门户身份尚未确认，未发送凭据")
        params = self._common_jsonp({"program_index": "", "wlan_vlan_id": self.runtime["vlan"],
            "wlan_user_ip": self._b64(self.runtime["ip"]), "wlan_user_ipv6": self._b64(self.runtime["ipv6"]),
            "wlan_user_ssid": self.runtime["ssid"], "wlan_user_areaid": self.runtime["areaid"],
            "wlan_ac_ip": self._b64(self.runtime["ac_ip"]), "wlan_ap_mac": self.runtime["ap_mac"],
            "gw_id": self.runtime["gw_id"]})
        self.portal_settings = {}
        self.progress("正在读取校园门户登录配置")
        try:
            status, data, config_charset, final = self.http.get(self.portal_api + "page/loadConfig?" + urlencode(params))
            if status != 200 or urlsplit(final).hostname != self.portal_host:
                return PortalResult(False, "temporary", "门户配置 HTTP 响应异常，未发送凭据")
            if self.cancel_check(): return PortalResult(False, "cancelled", "网络已切换")
            response = parse_jsonp(data, config_charset)
            settings = response.get("data", {}) if isinstance(response.get("data", {}), dict) else {}
            self.portal_settings = {str(k): str(v) for k, v in settings.items()}
            if str(response.get("code", "1")) != "1":
                return PortalResult(False, "temporary", "门户配置暂时不可用")
            # Never guess any password transform or an alternate login mode.
            wanted = {"login_method": "1", "enable_r3": "0", "en_md5": "0", "password_cut": "0",
                      "account_suffix": "", "account_prefix": "0" if self.profile_name == "dorm" else "1", "io_mode": "0"}
            for key, expected in wanted.items():
                if str(settings.get(key, "")) != expected:
                    return PortalResult(False, "configuration", f"门户参数 {key} 与已验证设置不同，已阻止登录")
        except PortalError as exc:
            return PortalResult(False, "temporary", "读取门户配置失败：" + self._safe_error(exc) + "；未发送凭据")
        if status != 200 or self.http.last_headers.get("Location"):
            return PortalResult(False, "unknown", "门户配置响应异常")
        if "program_index" not in self.portal_settings:
            return PortalResult(False, "configuration", "门户未提供 program_index，已阻止登录")
        return PortalResult(True, "config_loaded", "门户配置已读取并验证")

    def authenticate(self) -> PortalResult:
        if self.cancel_check(): return PortalResult(False, "cancelled", "网络已切换")
        if not self.portal_known:
            return PortalResult(False, "unknown", "门户身份未确认")
        online_result = self.check_portal_status()
        if online_result.category != "not_online":
            return online_result
        profile = self.profile
        mode = self.config.get("credential_mode", "shared")
        username = profile.get("username", "") if mode == "separate" else self.config.get("username", "")
        password = profile.get("password", "") if mode == "separate" else self.config.get("password", "")
        suffix = profile.get("provider_suffix", "")
        if self.profile_name == "dorm":
            allowed = {value for _, value in DORM_PROVIDERS if value != "-1"}
            confirmed = profile.get("provider_confirmed", bool(suffix))
            if not confirmed or suffix not in allowed:
                return PortalResult(False, "configuration", "请先选择宿舍服务商并保存，未发送凭据")
            if any(username.endswith(value) and value != suffix for value in allowed if value):
                return PortalResult(False, "configuration", "账号末尾的服务商与所选服务商不同，未发送凭据")
        if not username.strip() or not password:
            return PortalResult(False, "configuration", "请先填写账号和密码；未发送凭据")
        config_result = self.load_portal_config()
        if not config_result.success:
            return config_result
        if not self.runtime.get("ip") or self.runtime["ip"] == "0.0.0.0":
            return PortalResult(False, "configuration", "门户未提供有效 IPv4 地址，已阻止登录")
        # Desktop app uses the observed PC form factor.
        term = "1"
        encode = lambda key: self._b64(self.runtime[key])
        prefix = ",0," if self.portal_settings["account_prefix"] == "1" else ""
        full_username = username if suffix and username.endswith(suffix) else username + suffix
        account = prefix + full_username
        params = {
            "program_index": self.portal_settings["program_index"], "wlan_vlan_id": self.runtime["vlan"],
            "wlan_user_ip": self.runtime["ip"], "wlan_user_ipv6": self.runtime["ipv6"],
            "wlan_user_ssid": self.runtime["ssid"], "wlan_user_areaid": self.runtime["areaid"],
            "wlan_ac_ip": self.runtime["ac_ip"], "wlan_ap_mac": self.runtime["ap_mac"], "gw_id": self.runtime["gw_id"],
            "login_method": "1", "user_account": account, "user_password": password,
            "wlan_user_mac": re.sub(r"[-:]", "", self.runtime["mac"]), "wlan_ac_name": self.runtime.get("ac_name", ""),
            "terminal_type": term,
        }
        params = self._common_jsonp(params)
        if self.cancel_check(): return PortalResult(False, "cancelled", "网络已切换")
        self.progress("正在提交校园网认证")
        self.auth_submitted = True
        # Credentials are sent once, to the exact observed portal host, with redirects disabled.
        url = self.portal_api + "login?" + urlencode(params)
        try:
            status, body, response_charset, final = self.http.get(url)
            if status != 200 or urlsplit(final).hostname != self.portal_host:
                return PortalResult(False, "unknown", "门户认证请求失败")
            obj = parse_jsonp(body, response_charset)
            result = classify_result(obj)
            if not result.success and result.category != "already_online":
                semantic = self._classify_account_message(obj)
                if semantic is not None: return semantic
            return result
        except PortalError:
            return PortalResult(False, "temporary", "门户暂时无法响应")

    @staticmethod
    def _b64(value: str) -> str:
        return base64.b64encode(value.encode()).decode()

    @staticmethod
    def _first_js_string(text: str, names: tuple[str, ...]) -> str:
        for name in names:
            match = re.search(r"\b" + re.escape(name) + r"\s*=\s*['\"]([^'\"]*)['\"]", text)
            if match and match.group(1): return match.group(1)
        return ""

    @staticmethod
    def _hex16(value: str) -> str:
        try:
            raw = bytes.fromhex(value)
            decoded = raw.decode("ascii")
            return decoded if re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", decoded) else ""
        except (ValueError, UnicodeDecodeError):
            return ""

    @staticmethod
    def _classify_account_message(obj: dict) -> PortalResult | None:
        raw = " ".join(str(obj.get(k, "")) for k in ("msg", "message", "ret_msg", "Msg", "msga")).lower()
        if any(s in raw for s in ("密码错误", "密码不正确", "口令错误", "账号或密码", "用户名或密码",
                                   "invalid password", "wrong password", "password incorrect")):
            return PortalResult(False, "account", "账号或密码错误")
        if any(s in raw for s in ("账号不存在", "账户不存在", "用户不存在", "用户名不存在", "user not found", "account not found")):
            return PortalResult(False, "account", "账号不存在")
        if any(s in raw for s in ("欠费", "费用超支", "余额不足", "arrear", "insufficient balance")):
            return PortalResult(False, "debt", "账号欠费或余额不足")
        if any(s in raw for s in ("暂停使用", "账号停用", "账户停用", "账号禁用", "账户禁用", "停机",
                                   "disabled", "account suspended")):
            return PortalResult(False, "disabled", "账号已停用")
        return None

    @staticmethod
    def _common_jsonp(params: dict) -> dict:
        return params | {"callback": "dr" + uuid.uuid4().hex[:8], "jsVersion": "4.2.1",
                         "v": str(500 + (uuid.uuid4().int % 10000)), "lang": "zh"}
