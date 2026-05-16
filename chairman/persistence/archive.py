"""Archive Chairman brief files to data/briefs/YYYYMMDD."""

from __future__ import annotations

from pathlib import Path

from chairman.models import ChairmanBrief
from chairman.output.json_metadata_renderer import render_json_metadata
from chairman.output.markdown_renderer import render_markdown
from orchestrator.core.decision_verification import append_verification_cases_from_brief
from orchestrator.core.learning import append_learning_from_brief
from orchestrator.core.partner_performance import append_partner_snapshots_from_brief, write_partner_review_report


def archive_brief(brief: ChairmanBrief, data_dir: str | Path) -> tuple[Path, Path]:
    """Write Markdown and JSON outputs for a brief."""

    root = Path(data_dir)
    compact_date = brief.brief_id.split("-")[1]
    output_dir = root / "briefs" / compact_date
    output_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = output_dir / f"{brief.brief_id}.md"
    json_path = output_dir / f"{brief.brief_id}.json"
    markdown_path.write_text(render_markdown(brief), encoding="utf-8")
    json_path.write_text(render_json_metadata(brief), encoding="utf-8")
    append_verification_cases_from_brief(brief, data_dir)
    append_partner_snapshots_from_brief(brief, data_dir)
    append_learning_from_brief(brief, data_dir)
    write_partner_review_report(data_dir, as_of_date=compact_date)
    return markdown_path, json_path
