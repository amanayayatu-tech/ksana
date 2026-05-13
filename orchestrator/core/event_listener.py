"""Event-driven ad hoc signal detection with throttling."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import yaml


def find_high_urgency_signals(data_dir: str | Path) -> list[Path]:
    """Return research_signal YAML files marked urgency: high."""

    root = Path(data_dir)
    matches = []
    for path in sorted((root / "research_signals").glob("*.y*ml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        payload = data.get("research_signal", data)
        if payload.get("urgency") == "high":
            matches.append(path)
    return matches


class AdHocThrottle:
    """File-backed ad hoc throttle: max 3/day and min interval."""

    def __init__(self, data_dir: str | Path, max_per_day: int = 3, min_interval_minutes: int = 60):
        self.path = Path(data_dir) / "orchestrator" / "ad_hoc_triggers.json"
        self.max_per_day = max_per_day
        self.min_interval = timedelta(minutes=min_interval_minutes)

    def allow(self, now: datetime | None = None) -> bool:
        now = now or datetime.now()
        records = self._load()
        todays = [datetime.fromisoformat(ts) for ts in records if ts[:10] == now.date().isoformat()]
        if len(todays) >= self.max_per_day:
            return False
        if todays and now - max(todays) < self.min_interval:
            return False
        return True

    def record(self, now: datetime | None = None) -> None:
        now = now or datetime.now()
        records = self._load()
        records.append(now.isoformat())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load(self) -> list[str]:
        if not self.path.exists():
            return []
        return json.loads(self.path.read_text(encoding="utf-8"))
