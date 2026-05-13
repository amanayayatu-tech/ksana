"""APScheduler integration and schedule config."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger


DEFAULT_SCHEDULER_CONFIG = {
    "schedules": {
        "morning_brief": {
            "cron": "30 8 * * 1-5",
            "timezone": "Asia/Hong_Kong",
            "pipeline": "full_pipeline",
            "brief_type": "morning",
        },
        "evening_brief": {
            "cron": "30 17 * * 1-5",
            "timezone": "Asia/Hong_Kong",
            "pipeline": "full_pipeline",
            "brief_type": "evening",
        },
    },
    "ad_hoc_throttle": {"max_per_day": 3, "min_interval_minutes": 60},
    "perplexity_wait": {"enabled": True, "timeout_seconds": 1800, "poll_interval_seconds": 30},
    "notifications": {"channels": ["local"]},
}


def load_scheduler_config(path: str | Path | None = None) -> dict[str, Any]:
    if path and Path(path).exists():
        loaded = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        merged = DEFAULT_SCHEDULER_CONFIG.copy()
        merged.update(loaded)
        return merged
    return DEFAULT_SCHEDULER_CONFIG


def cron_trigger_from_expr(expr: str, timezone: str) -> CronTrigger:
    minute, hour, day, month, day_of_week = expr.split()
    return CronTrigger(
        minute=minute,
        hour=hour,
        day=day,
        month=month,
        day_of_week=day_of_week,
        timezone=timezone,
    )


def build_scheduler(run_full_pipeline_func, config: dict[str, Any] | None = None) -> BackgroundScheduler:
    config = config or DEFAULT_SCHEDULER_CONFIG
    timezone = config["schedules"]["morning_brief"]["timezone"]
    scheduler = BackgroundScheduler(timezone=timezone)
    for job_id, schedule in config["schedules"].items():
        scheduler.add_job(
            func=run_full_pipeline_func,
            trigger=cron_trigger_from_expr(schedule["cron"], schedule["timezone"]),
            args=[schedule["brief_type"]],
            id=job_id,
            max_instances=1,
            misfire_grace_time=600,
        )
    return scheduler
