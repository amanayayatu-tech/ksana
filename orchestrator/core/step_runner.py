"""Subprocess step execution with retries."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from orchestrator.core.models import PipelineStep, StepResult
from orchestrator.persistence.run_log import RunLog


def render_command(command: list[str], context: dict[str, str]) -> list[str]:
    """Render placeholders in a command list."""

    return [part.format(**context) for part in command]


def build_step_env() -> dict[str, str]:
    """Build a stable subprocess environment independent from Web UI injection."""

    project_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(project_root)
        if not existing_pythonpath
        else f"{project_root}{os.pathsep}{existing_pythonpath}"
    )
    return env


def run_step(
    step: PipelineStep,
    *,
    run_id: str,
    context: dict[str, str],
    data_dir: str | Path,
    run_log: RunLog | None = None,
) -> StepResult:
    """Run one pipeline step with retry handling."""

    logs_dir = Path(data_dir) / "orchestrator" / "logs" / run_id
    logs_dir.mkdir(parents=True, exist_ok=True)
    last_result: StepResult | None = None
    rendered_command = render_command(step.command, context)

    for attempt in range(1, step.max_retries + 2):
        stdout_path = logs_dir / f"{step.name}-{attempt}.out"
        stderr_path = logs_dir / f"{step.name}-{attempt}.err"
        try:
            completed = subprocess.run(
                rendered_command,
                cwd=Path(__file__).resolve().parents[2],
                env=build_step_env(),
                capture_output=True,
                text=True,
                timeout=step.timeout_seconds,
                check=False,
            )
            stdout_path.write_text(completed.stdout or "", encoding="utf-8")
            stderr_path.write_text(completed.stderr or "", encoding="utf-8")
            status = "success" if completed.returncode == 0 else "failed"
            output_files = [path for path in step.output_files if path.exists()]
            last_result = StepResult(
                step_name=step.name,
                status=status,
                exit_code=completed.returncode,
                attempts=attempt,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                output_files=output_files,
            )
            if status == "success":
                break
        except subprocess.TimeoutExpired as exc:
            stderr_path.write_text(str(exc), encoding="utf-8")
            last_result = StepResult(
                step_name=step.name,
                status="failed",
                exit_code=None,
                attempts=attempt,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                error=str(exc),
            )

    assert last_result is not None
    if run_log:
        run_log.record_step(run_id, last_result)
    return last_result
