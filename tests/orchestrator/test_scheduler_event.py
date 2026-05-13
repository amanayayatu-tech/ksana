from __future__ import annotations

from datetime import datetime, timedelta

import yaml

from orchestrator.core.event_listener import AdHocThrottle, find_high_urgency_signals
from orchestrator.core.scheduler import build_scheduler, load_scheduler_config


def test_cron_trigger_morning_brief():
    scheduler = build_scheduler(lambda brief_type: None)
    job_ids = {job.id for job in scheduler.get_jobs()}
    assert {"morning_brief", "evening_brief"} <= job_ids


def test_event_listener_ad_hoc_signal(tmp_path):
    signal_dir = tmp_path / "data" / "research_signals"
    signal_dir.mkdir(parents=True)
    (signal_dir / "RS-20260513-999.yaml").write_text(
        yaml.safe_dump({"research_signal": {"research_signal_id": "RS-20260513-999", "urgency": "high"}}),
        encoding="utf-8",
    )

    matches = find_high_urgency_signals(tmp_path / "data")

    assert len(matches) == 1


def test_throttle_ad_hoc(tmp_path):
    throttle = AdHocThrottle(tmp_path / "data", max_per_day=3, min_interval_minutes=0)
    now = datetime(2026, 5, 13, 9, 0, 0)
    for i in range(3):
        assert throttle.allow(now + timedelta(hours=i))
        throttle.record(now + timedelta(hours=i))

    assert not throttle.allow(now + timedelta(hours=4))


def test_config_show_defaults():
    config = load_scheduler_config()
    assert config["schedules"]["morning_brief"]["cron"] == "30 8 * * 1-5"
