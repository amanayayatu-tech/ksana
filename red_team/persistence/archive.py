"""Archive Red Team audits."""

from __future__ import annotations

from pathlib import Path

from red_team.models import RedTeamAudit
from red_team.output.json_metadata_renderer import render_json_metadata
from red_team.output.markdown_renderer import render_markdown
from orchestrator.reporting.html_renderer import ReportPresentation, render_report_html


def archive_audit(audit: RedTeamAudit, data_dir: str | Path) -> tuple[Path, Path]:
    compact = audit.audit_id.split("-")[1]
    output_dir = Path(data_dir) / "red_team_audits" / compact
    output_dir.mkdir(parents=True, exist_ok=True)
    md_path = output_dir / f"{audit.audit_id}.md"
    html_path = output_dir / f"{audit.audit_id}.html"
    json_path = output_dir / f"{audit.audit_id}.json"
    markdown = render_markdown(audit)
    md_path.write_text(markdown, encoding="utf-8")
    html_path.write_text(
        render_report_html(
            markdown,
            ReportPresentation(
                title=f"风险审计报告 — {audit.audit_id}",
                report_label="Risk Audit",
                eyebrow="RESEARCHOS RISK AUDITOR",
                source_path=f"{audit.audit_id}.md",
            ),
        ),
        encoding="utf-8",
    )
    json_path.write_text(render_json_metadata(audit), encoding="utf-8")
    return md_path, json_path
