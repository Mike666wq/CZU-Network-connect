from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class Tick:
    due: bool
    network_changed: bool
    special_time: bool
    woke: bool = False


class PollScheduler:
    """Deterministic polling deadline and daily extra checks."""

    def __init__(self, initial_monotonic: float, network_id: str = "", initial_wall: datetime | None = None):
        self.deadline = initial_monotonic
        self.network_id = network_id
        self.last_minute = ""
        self.last_monotonic = initial_monotonic
        self.last_wall = initial_wall or datetime.now(timezone.utc)

    def tick(self, now_monotonic: float, now: datetime, network_id: str, delay: int) -> Tick:
        changed = network_id != self.network_id
        if changed:
            self.network_id = network_id
        minute = now.strftime("%Y%m%d%H%M")
        special = ((now.hour, now.minute) in {(0, 0), (0, 12)} and minute != self.last_minute)
        if special:
            self.last_minute = minute
        wall_gap = max(0.0, (now.astimezone(timezone.utc) - self.last_wall.astimezone(timezone.utc)).total_seconds())
        mono_gap = max(0.0, now_monotonic - self.last_monotonic)
        woke = wall_gap - mono_gap > 10 or wall_gap > max(delay + 10, 40)
        self.last_wall, self.last_monotonic = now, now_monotonic
        due = changed or special or woke or now_monotonic >= self.deadline
        if due:
            self.deadline = now_monotonic + delay
        return Tick(due, changed, special, woke)

    def reschedule(self, now_monotonic: float, delay: int) -> None:
        self.deadline = now_monotonic + delay
