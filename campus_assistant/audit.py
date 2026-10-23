"""Small local diagnostic journal. Never accepts URLs, accounts, passwords or server bodies."""
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import json
import os
from . import __version__


def record_event(path: Path, *, state: str, scene: str, next_seconds: int,
                 auth_attempted: bool, reason: str) -> bool:
    reasons = {'startup', 'manual', 'retry', 'heartbeat', 'network', 'wake', 'midnight', 'midnight_extra', 'resume'}
    event = {
        'version': __version__,
        'time': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
        'reason': reason if reason in reasons else 'manual',
        'state': state,
        'scene': scene if scene in {'public', 'dorm'} else 'unknown',
        'auth_attempted': bool(auth_attempted),
        'next_seconds': int(next_seconds),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > 1_000_000:
            previous = path.with_name('events.previous.jsonl')
            # Windows os.replace refuses an existing destination unless it is
            # removed first; drop the stale archive so rotation never fails.
            previous.unlink(missing_ok=True)
            path.replace(previous)
        with path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + '\n')
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return True
    except OSError:
        return False


def record_block(path: Path, *, reason: str, category: str, detail: str,
                 portal_keys: dict | None = None) -> bool:
    """Persist an AUTH_BLOCKED event so the next 'program is stuck' report can be
    diagnosed from the log alone. Never stores credentials or response bodies."""
    event = {
        'version': __version__,
        'time': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
        'event': 'auth_blocked',
        'reason': str(reason)[:200],
        'category': str(category)[:64],
        'detail': str(detail)[:200],
        'portal_keys': sorted(str(k) for k in (portal_keys or {}).keys()),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + '\n')
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return True
    except OSError:
        return False
