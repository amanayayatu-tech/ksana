from __future__ import annotations

from orchestrator.core.models import PipelineStep
from orchestrator.core.pipeline import build_full_pipeline_steps, run_full_pipeline
from tests.orchestrator.conftest import py_step, write_pipeline_inputs


def test_full_pipeline_happy_path(tmp_path):
    data_dir = tmp_path / "data"
    write_pipeline_inputs(data_dir)

    result = run_full_pipeline(brief_type="morning", date="2026-05-13", data_dir=data_dir)

    assert result.status == "completed"
    assert (data_dir / "briefs" / "20260513" / "BRIEF-20260513-AM.json").exists()
    assert (data_dir / "red_team_audits" / "20260513" / "AUDIT-20260513-AM.json").exists()
    assert list((data_dir / "notifications").rglob("notification.log"))


def test_pipeline_with_one_agent_failure(tmp_path):
    data_dir = tmp_path / "data"
    write_pipeline_inputs(data_dir)
    steps = build_full_pipeline_steps(date="2026-05-13", brief_type="morning", data_dir=data_dir)
    for step in steps:
        if step.name == "trading_f_partner":
            step.command = py_step("raise SystemExit(2)")

    result = run_full_pipeline(
        brief_type="morning",
        date="2026-05-13",
        data_dir=data_dir,
        steps=steps,
    )

    assert result.status == "completed"
    assert result.step_results["trading_f_partner"].status == "failed"
    assert result.step_results["trading_w_partner"].status == "success"


def test_pipeline_chairman_fallback(tmp_path):
    data_dir = tmp_path / "data"
    write_pipeline_inputs(data_dir)
    steps = build_full_pipeline_steps(date="2026-05-13", brief_type="morning", data_dir=data_dir)
    for step in steps:
        if step.name == "chairman":
            step.command = py_step("raise SystemExit(2)")

    result = run_full_pipeline(
        brief_type="morning",
        date="2026-05-13",
        data_dir=data_dir,
        steps=steps,
    )

    assert result.status == "partial_success"
    assert result.fallback_path and result.fallback_path.exists()
    assert (data_dir / "briefs" / "20260513" / "BRIEF-20260513-AM-FALLBACK.md").exists()
    assert "red_team" not in result.step_results


def test_pipeline_research_scan_failure(tmp_path):
    data_dir = tmp_path / "data"
    steps = [
        PipelineStep(name="research_scan", command=py_step("raise SystemExit(2)"), max_retries=0),
        PipelineStep(name="trading_f_partner", command=py_step("print('skip')"), skip_on_failure=True),
        PipelineStep(name="trading_w_partner", command=py_step("print('skip')"), skip_on_failure=True),
        PipelineStep(name="trading_g_partner", command=py_step("print('skip')"), skip_on_failure=True),
        PipelineStep(name="perplexity_wait", command=py_step("print('skip')"), skip_on_failure=True),
        PipelineStep(name="chairman", command=py_step("print('skip')")),
        PipelineStep(name="red_team", command=py_step("print('skip')")),
        PipelineStep(name="notify", command=py_step("print('skip')"), skip_on_failure=True),
    ]

    result = run_full_pipeline(
        brief_type="morning",
        date="2026-05-13",
        data_dir=data_dir,
        steps=steps,
    )

    assert result.status == "partial_success"
    assert result.fallback_path and result.fallback_path.exists()
    assert list((data_dir / "notifications").rglob("notification.log"))
