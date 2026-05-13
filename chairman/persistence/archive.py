"""Archive Chairman brief files to data/briefs/YYYYMMDD."""

from __future__ import annotations

from pathlib import Path

from chairman.models import ChairmanBrief
from chairman.output.json_metadata_renderer import render_json_metadata
from chairman.output.markdown_renderer import render_markdown


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
    return markdown_path, json_path
