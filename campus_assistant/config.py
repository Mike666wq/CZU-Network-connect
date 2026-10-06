from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


APP_DIR = Path.home() / "校园网助手"
CONFIG_PATH = APP_DIR / "config.json"
DORM_PROVIDERS = (("请选择宿舍服务商", "-1"), ("校园网", ""),
                  ("中国移动", "@cmcc"), ("中国联通", "@unicom"), ("中国电信", "@telecom"))

DEFAULT_CONFIG: dict[str, Any] = {
    "config_version": 4,
    "enabled": True,
    "autostart": False,
    "internet_probe_urls": ["https://cp.cloudflare.com/generate_204", "https://www.msftconnecttest.com/connecttest.txt"],
    "credential_mode": "shared",
    "active_profile": "auto",
    "edit_profile": "public",
    "profiles": {
        "public": {"portal_url": "http://192.168.255.4/", "username": "", "password": "", "provider_suffix": ""},
        "dorm": {"portal_url": "http://172.19.0.1/", "username": "", "password": "", "provider_suffix": "", "provider_confirmed": False},
    },
    "username": "",
    "password": "",
}


class ConfigError(ValueError):
    pass


def ensure_config(path: Path = CONFIG_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        save_config(DEFAULT_CONFIG, path)
    return path


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    ensure_config(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"配置文件无法读取：{exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError("配置文件必须是 JSON 对象")
    merged = DEFAULT_CONFIG | {k: v for k, v in data.items() if k in DEFAULT_CONFIG}
    # Versions before 0.3.0 stored the previous default scene (public) as if it
    # were an explicit choice. Migrate that legacy value to automatic detection;
    # an explicit public/dorm selection made and saved in v3+ remains unchanged.
    stored_version = data.get("config_version", 0)
    if not isinstance(stored_version, int) or stored_version < 0:
        raise ConfigError("config_version 必须是非负整数")
    if stored_version < 3 and data.get("active_profile") in {"public", "dorm"}:
        merged["active_profile"] = "auto"
    merged["config_version"] = 4
    probes = merged.get("internet_probe_urls")
    if not isinstance(probes, list) or len(probes) < 2:
        raise ConfigError("公网探测必须配置至少两个 HTTPS 地址")
    for value in probes:
        try:
            p = urlsplit(value) if isinstance(value, str) else None
            if not p or p.scheme != "https" or not p.hostname or p.username or p.password or p.fragment:
                raise ValueError
        except ValueError as exc:
            raise ConfigError("公网探测必须是有效 HTTPS 地址") from exc
    if merged.get("credential_mode") not in {"shared", "separate"}:
        raise ConfigError("credential_mode 只支持 shared 或 separate")
    for flag in ("enabled", "autostart"):
        if not isinstance(merged.get(flag), bool):
            raise ConfigError(f"{flag} 必须是布尔值")
    for key in ("username", "password"):
        if not isinstance(merged.get(key), str):
            raise ConfigError(f"{key} 必须是文本")
    profiles = merged.get("profiles")
    if not isinstance(profiles, dict) or any(not isinstance(profiles.get(p), dict) for p in ("public", "dorm")):
        raise ConfigError("profiles 必须包含 public 与 dorm 配置")
    for profile_name in ("public", "dorm"):
        profile = profiles[profile_name]
        for key in ("portal_url", "username", "password", "provider_suffix"):
            if key not in profile or not isinstance(profile[key], str):
                raise ConfigError(f"profile.{key} 必须是文本")
        if "provider_confirmed" in profile and not isinstance(profile["provider_confirmed"], bool):
            raise ConfigError("provider_confirmed 必须是布尔值")
        try:
            url = urlsplit(profile["portal_url"])
            valid_url = (url.scheme in {"http", "https"} and bool(url.hostname) and
                not url.username and not url.password and not url.query and not url.fragment and
                1 <= (url.port or (443 if url.scheme == "https" else 80)) <= 65535)
        except ValueError:
            valid_url = False
        if not valid_url:
            raise ConfigError("场景入口必须是 HTTP(S) 地址")
    if merged.get("active_profile") not in {"auto", "public", "dorm"}:
        raise ConfigError("active_profile 只支持 auto/public/dorm")
    if merged.get("edit_profile") not in {"public", "dorm"}:
        raise ConfigError("edit_profile 只支持 public/dorm")
    return merged


def save_config(config: dict[str, Any], path: Path = CONFIG_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = DEFAULT_CONFIG | {k: config[k] for k in DEFAULT_CONFIG if k in config}
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(clean, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(temp, 0o600)
    except OSError:
        pass
    try:
        load_config(temp)
    except Exception:
        temp.unlink(missing_ok=True)
        raise
    temp.replace(path)
    return path
