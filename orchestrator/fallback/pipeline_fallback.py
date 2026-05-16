"""Whole-pipeline fallback."""

from __future__ import annotations

from pathlib import Path

from orchestrator.reporting.html_renderer import ReportPresentation, render_report_html


def pipeline_fallback(
    *,
    data_dir: str | Path,
    date: str,
    run_id: str,
    failed_step: str,
    reason: str,
) -> Path:
    """Write a degraded fallback artifact for operators."""

    compact = date.replace("-", "")
    output_dir = Path(data_dir) / "briefs" / compact
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"FALLBACK-{run_id}.md"
    markdown = (
        f"# ⚠️ Pipeline 部分失败\n\n"
        f"- run_id: `{run_id}`\n"
        f"- failed_step: `{failed_step}`\n"
        f"- reason: {reason}\n\n"
        "仅有原始建议或部分中间产物可参考，请手动审查。\n"
    )
    output_path.write_text(markdown, encoding="utf-8")
    output_path.with_suffix(".html").write_text(
        render_report_html(
            markdown,
            ReportPresentation(
                title=f"Pipeline fallback — {run_id}",
                report_label="Pipeline Fallback",
                eyebrow="RESEARCHOS FALLBACK REPORT",
                source_path=output_path.name,
            ),
        ),
        encoding="utf-8",
    )
    return output_path
