from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


@dataclass
class Tick:
    due: bool
    network_changed: bool
    special_time: bool
    woke: bool = False


class PollScheduler:
    """Deterministic network deadline with daily recovery-boundary checks."""

    SPECIAL_TIMES = ((23, 58), (0, 0), (0, 8))

    def __init__(self, initial_monotonic: float, network_id: str = "", initial_wall: datetime | None = None):
        self.deadline = initial_monotonic
        self.network_id = network_id
        self.last_minute = ""
        self.last_monotonic = initial_monotonic
        self.last_wall = initial_wall or datetime.now(timezone.utc)

    @staticmethod
    def _beijing(now: datetime) -> datetime:
        if now.tzinfo is None:
            now = now.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
        return now.astimezone(ZoneInfo("Asia/Shanghai"))

    def seconds_until_due(self, now_monotonic: float, now: datetime) -> int:
        """Read-only delay to the earlier of heartbeat deadline or recovery boundary."""
        remaining = max(0.0, self.deadline - now_monotonic)
        wall = self._beijing(now)
        key = wall.strftime("%Y%m%d%H%M")
        if (wall.hour, wall.minute) in self.SPECIAL_TIMES and self.last_minute != key:
            return 0
        candidates = []
        for day in (0, 1):
            base = (wall + timedelta(days=day)).date()
            for hour, minute in self.SPECIAL_TIMES:
                moment = datetime(base.year, base.month, base.day, hour, minute, tzinfo=wall.tzinfo)
                key = moment.strftime("%Y%m%d%H%M")
                if moment > wall and key != self.last_minute:
                    candidates.append((moment - wall).total_seconds())
        if candidates:
            remaining = min(remaining, min(candidates))
        return max(0, int(remaining + 0.999999))

    def tick(self, now_monotonic: float, now: datetime, network_id: str, delay: int) -> Tick:
        changed = network_id != self.network_id
        if changed:
            self.network_id = network_id
        wall = self._beijing(now)
        minute = wall.strftime("%Y%m%d%H%M")
        special = ((wall.hour, wall.minute) in self.SPECIAL_TIMES and minute != self.last_minute)
        if special:
            self.last_minute = minute
        wall_gap = max(0.0, (wall.astimezone(timezone.utc) -
                             self._beijing(self.last_wall).astimezone(timezone.utc)).total_seconds())
        mono_gap = max(0.0, now_monotonic - self.last_monotonic)
        woke = wall_gap - mono_gap > 10 or wall_gap > max(delay + 10, 40)
        self.last_wall, self.last_monotonic = now, now_monotonic
        due = changed or special or woke or now_monotonic >= self.deadline
        if due:
            self.deadline = now_monotonic + delay
        return Tick(due, changed, special, woke)

    def reschedule(self, now_monotonic: float, delay: int) -> None:
        self.deadline = now_monotonic + delay
