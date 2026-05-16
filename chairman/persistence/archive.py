"""Archive Chairman brief files to data/briefs/YYYYMMDD."""

from __future__ import annotations

from pathlib import Path

from chairman.models import ChairmanBrief
from chairman.output.json_metadata_renderer import render_json_metadata
from chairman.output.markdown_renderer import render_markdown
from orchestrator.core.decision_verification import append_verification_cases_from_brief
from orchestrator.core.learning import append_learning_from_brief
from orchestrator.core.partner_performance import append_partner_snapshots_from_brief, write_partner_review_report
from orchestrator.reporting.html_renderer import ReportPresentation, render_report_html


def archive_brief(brief: ChairmanBrief, data_dir: str | Path) -> tuple[Path, Path]:
    """Write Markdown and JSON outputs for a brief."""

    root = Path(data_dir)
    compact_date = brief.brief_id.split("-")[1]
    output_dir = root / "briefs" / compact_date
    output_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = output_dir / f"{brief.brief_id}.md"
    html_path = output_dir / f"{brief.brief_id}.html"
    json_path = output_dir / f"{brief.brief_id}.json"
    markdown = render_markdown(brief)
    markdown_path.write_text(markdown, encoding="utf-8")
    html_path.write_text(
        render_report_html(
            markdown,
            ReportPresentation(
                title=f"投委会报告 — {brief.brief_id}",
                report_label="IC Brief",
                eyebrow="RESEARCHOS ALPHA COMMITTEE",
                source_path=f"{brief.brief_id}.md",
            ),
        ),
        encoding="utf-8",
    )
    json_path.write_text(render_json_metadata(brief), encoding="utf-8")
    append_verification_cases_from_brief(brief, data_dir)
    append_partner_snapshots_from_brief(brief, data_dir)
    append_learning_from_brief(brief, data_dir)
    write_partner_review_report(data_dir, as_of_date=compact_date)
    return markdown_path, json_path
