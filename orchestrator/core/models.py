"""Core pipeline models."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PipelineStep:
    name: str
    command: list[str]
    timeout_seconds: int = 600
    max_retries: int = 2
    depends_on: list[str] = field(default_factory=list)
    skip_on_failure: bool = False
    output_files: list[Path] = field(default_factory=list)


@dataclass
class StepResult:
    step_name: str
    status: str
    exit_code: int | None = None
    attempts: int = 0
    stdout_path: Path | None = None
    stderr_path: Path | None = None
    output_files: list[Path] = field(default_factory=list)
    error: str | None = None


@dataclass
class PipelineResult:
    run_id: str
    status: str
    step_results: dict[str, StepResult]
    notification_sent: bool = False
    fallback_path: Path | None = None
