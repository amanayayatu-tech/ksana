"""Daemon helpers for Orchestrator."""

from __future__ import annotations

from orchestrator.core.pipeline import run_full_pipeline
from orchestrator.core.scheduler import build_scheduler


def start_daemon() -> None:
    scheduler = build_scheduler(lambda brief_type: run_full_pipeline(brief_type=brief_type, date=""))
    scheduler.start()


def daemon_status() -> str:
    return "configured"
