"""Archive Red Team audits."""

from __future__ import annotations

from pathlib import Path

from red_team.models import RedTeamAudit
from red_team.output.json_metadata_renderer import render_json_metadata
from red_team.output.markdown_renderer import render_markdown


def archive_audit(audit: RedTeamAudit, data_dir: str | Path) -> tuple[Path, Path]:
    compact = audit.audit_id.split("-")[1]
    output_dir = Path(data_dir) / "red_team_audits" / compact
    output_dir.mkdir(parents=True, exist_ok=True)
    md_path = output_dir / f"{audit.audit_id}.md"
    json_path = output_dir / f"{audit.audit_id}.json"
    md_path.write_text(render_markdown(audit), encoding="utf-8")
    json_path.write_text(render_json_metadata(audit), encoding="utf-8")
    return md_path, json_path
