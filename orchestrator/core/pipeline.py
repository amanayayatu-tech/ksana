"""Pipeline DAG and execution."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from orchestrator.core.models import PipelineResult, PipelineStep, StepResult
from orchestrator.core.step_runner import run_step
from orchestrator.fallback.pipeline_fallback import pipeline_fallback
from orchestrator.notifications.local_notifier import LocalNotifier
from orchestrator.notifications.notifier import NotificationMessage
from orchestrator.persistence.run_log import RunLog


def build_full_pipeline_steps(
    *,
    date: str,
    brief_type: str,
    data_dir: str | Path,
    include_noop_agent_steps: bool = True,
) -> list[PipelineStep]:
    """Build the default full pipeline.

    Research and trading agent Python implementations are stage 3.7; default
    commands are no-op placeholders until their real CLIs exist.
    """

    compact = date.replace("-", "")
    python_noop = [sys.executable, "-c", "print('stage 3.7 agent step placeholder')"]
    data_dir_text = str(data_dir)
    wait_timeout = "0"
    return [
        PipelineStep(
            name="research_scan",
            command=python_noop if include_noop_agent_steps else ["research-agent", "run", "--type", "scan"],
            timeout_seconds=600,
            skip_on_failure=False,
        ),
        PipelineStep(
            name="trading_fengliu",
            command=python_noop if include_noop_agent_steps else ["trading-agent", "run", "--methodology", "fengliu"],
            timeout_seconds=900,
            depends_on=["research_scan"],
            skip_on_failure=True,
        ),
        PipelineStep(
            name="trading_wanmu",
            command=python_noop if include_noop_agent_steps else ["trading-agent", "run", "--methodology", "wanmu"],
            timeout_seconds=900,
            depends_on=["research_scan"],
            skip_on_failure=True,
        ),
        PipelineStep(
            name="trading_liguofei",
            command=python_noop if include_noop_agent_steps else ["trading-agent", "run", "--methodology", "liguofei"],
            timeout_seconds=900,
            depends_on=["research_scan"],
            skip_on_failure=True,
        ),
        PipelineStep(
            name="perplexity_wait",
            command=[
                "orchestrator",
                "wait-for-perplexity-fill",
                "--run-id",
                "{run_id}",
                "--timeout",
                wait_timeout,
                "--data-dir",
                "{data_dir}",
            ],
            timeout_seconds=1800,
            depends_on=["trading_fengliu", "trading_wanmu", "trading_liguofei"],
            skip_on_failure=True,
        ),
        PipelineStep(
            name="chairman",
            command=[
                "chairman",
                "generate-brief",
                "--type",
                "{brief_type}",
                "--date",
                "{date}",
                "--data-dir",
                "{data_dir}",
                "--no-llm",
            ],
            timeout_seconds=300,
            depends_on=["trading_fengliu", "trading_wanmu", "trading_liguofei"],
            skip_on_failure=False,
            output_files=[
                Path(data_dir_text) / "briefs" / compact / f"BRIEF-{compact}-{_brief_suffix(brief_type)}.json"
            ],
        ),
        PipelineStep(
            name="red_team",
            command=[
                "red-team",
                "audit",
                "--type",
                "{brief_type}",
                "--date",
                "{date}",
                "--data-dir",
                "{data_dir}",
                "--no-llm",
            ],
            timeout_seconds=300,
            depends_on=["chairman"],
            skip_on_failure=False,
            output_files=[
                Path(data_dir_text)
                / "red_team_audits"
                / compact
                / f"AUDIT-{compact}-{_brief_suffix(brief_type)}.json"
            ],
        ),
        PipelineStep(
            name="notify",
            command=[sys.executable, "-c", "print('notify handled by orchestrator')"],
            timeout_seconds=60,
            depends_on=["red_team"],
            skip_on_failure=True,
        ),
    ]


def run_full_pipeline(
    *,
    brief_type: str,
    date: str,
    data_dir: str | Path = "data",
    trigger_source: str = "manual",
    run_log: RunLog | None = None,
    steps: list[PipelineStep] | None = None,
) -> PipelineResult:
    """Run the standard pipeline and record state."""

    run_log = run_log or RunLog(Path(data_dir) / "orchestrator" / "runs.db")
    run_id = run_log.create_run(
        pipeline_type="full",
        trigger_source=trigger_source,
        metadata={"brief_type": brief_type, "date": date},
    )
    context = {"run_id": run_id, "date": date, "brief_type": brief_type, "data_dir": str(data_dir)}
    steps = steps or build_full_pipeline_steps(date=date, brief_type=brief_type, data_dir=data_dir)
    results: dict[str, StepResult] = {}
    fallback_path: Path | None = None

    research = _run_named("research_scan", steps, run_id, context, data_dir, run_log)
    results[research.step_name] = research
    if research.status != "success":
        fallback_path = _fallback_and_notify(data_dir, date, run_id, "research_scan", research.error or "failed", run_log)
        run_log.finish_run(run_id, "partial_success", {"failed_step": "research_scan"})
        return PipelineResult(run_id, "partial_success", results, True, fallback_path)

    trading_steps = [s for s in steps if s.name.startswith("trading_")]
    trading_results = asyncio.run(_run_parallel(trading_steps, run_id, context, data_dir, run_log))
    results.update(trading_results)
    if all(result.status != "success" for result in trading_results.values()):
        fallback_path = _fallback_and_notify(data_dir, date, run_id, "trading_agents", "all trading agents failed", run_log)
        run_log.finish_run(run_id, "partial_success", {"failed_step": "trading_agents"})
        return PipelineResult(run_id, "partial_success", results, True, fallback_path)

    for step_name in ("perplexity_wait", "chairman", "red_team", "notify"):
        step = _find_step(step_name, steps)
        result = run_step(step, run_id=run_id, context=context, data_dir=data_dir, run_log=run_log)
        results[step.name] = result
        if result.status != "success" and not step.skip_on_failure:
            if step.name == "chairman":
                _run_chairman_fallback(date, brief_type, data_dir)
            fallback_path = _fallback_and_notify(data_dir, date, run_id, step.name, result.error or "failed", run_log)
            run_log.finish_run(run_id, "partial_success", {"failed_step": step.name})
            return PipelineResult(run_id, "partial_success", results, True, fallback_path)

    _notify_completion(data_dir, run_id, results, run_log)
    run_log.finish_run(run_id, "completed", {"brief_type": brief_type, "date": date})
    return PipelineResult(run_id, "completed", results, True, fallback_path)


def run_step_by_name(
    *,
    step_name: str,
    brief_type: str,
    date: str,
    data_dir: str | Path = "data",
) -> StepResult:
    """Run one named pipeline step for debugging."""

    run_log = RunLog(Path(data_dir) / "orchestrator" / "runs.db")
    run_id = run_log.create_run(pipeline_type="partial", trigger_source="manual", metadata={"step": step_name})
    context = {"run_id": run_id, "date": date, "brief_type": brief_type, "data_dir": str(data_dir)}
    step = _find_step(step_name, build_full_pipeline_steps(date=date, brief_type=brief_type, data_dir=data_dir))
    result = run_step(step, run_id=run_id, context=context, data_dir=data_dir, run_log=run_log)
    run_log.finish_run(run_id, "completed" if result.status == "success" else "failed")
    return result


def _run_named(name: str, steps: list[PipelineStep], run_id: str, context: dict[str, str], data_dir, run_log) -> StepResult:
    return run_step(_find_step(name, steps), run_id=run_id, context=context, data_dir=data_dir, run_log=run_log)


async def _run_parallel(
    steps: list[PipelineStep],
    run_id: str,
    context: dict[str, str],
    data_dir,
    run_log,
) -> dict[str, StepResult]:
    results = await asyncio.gather(
        *[
            asyncio.to_thread(run_step, step, run_id=run_id, context=context, data_dir=data_dir, run_log=run_log)
            for step in steps
        ]
    )
    return {result.step_name: result for result in results}


def _find_step(name: str, steps: list[PipelineStep]) -> PipelineStep:
    for step in steps:
        if step.name == name:
            return step
    raise KeyError(f"unknown step {name}")


def _run_chairman_fallback(date: str, brief_type: str, data_dir: str | Path) -> None:
    step = PipelineStep(
        name="chairman_fallback",
        command=[
            "chairman",
            "fallback",
            "--type",
            brief_type,
            "--date",
            date,
            "--data-dir",
            str(data_dir),
            "--failure-reason",
            "orchestrator chairman step failed",
        ],
        max_retries=0,
    )
    run_step(step, run_id="fallback", context={}, data_dir=data_dir)


def _fallback_and_notify(data_dir, date, run_id, failed_step, reason, run_log) -> Path:
    fallback_path = pipeline_fallback(
        data_dir=data_dir,
        date=date,
        run_id=run_id,
        failed_step=failed_step,
        reason=reason,
    )
    notifier = LocalNotifier(data_dir)
    sent = notifier.send(
        NotificationMessage(
            title="Pipeline 部分失败",
            body=f"{failed_step} failed; fallback generated",
            attachments=[fallback_path],
            priority="high",
        )
    )
    run_log.record_notification(run_id, "local", "sent" if sent else "failed")
    return fallback_path


def _notify_completion(data_dir, run_id, results: dict[str, StepResult], run_log) -> bool:
    attachments = [path for result in results.values() for path in result.output_files]
    critical = any(result.step_name == "red_team" and result.status == "success" for result in results.values())
    notifier = LocalNotifier(data_dir)
    sent = notifier.send(
        NotificationMessage(
            title="Brief 与 Audit 已生成",
            body=f"run_id={run_id}",
            attachments=attachments,
            priority="normal" if critical else "low",
        )
    )
    run_log.record_notification(run_id, "local", "sent" if sent else "failed")
    return sent


def _brief_suffix(brief_type: str) -> str:
    return {"morning": "AM", "evening": "PM", "ad_hoc": "ADHOC"}.get(brief_type, "AM")
