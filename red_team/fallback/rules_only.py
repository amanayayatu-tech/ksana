"""Rules-only fallback when Red Team LLM/full flow fails."""

from __future__ import annotations

from pathlib import Path

from chairman.models import Recommendation, ResearchSignal
from red_team.core.audit_assembler import assemble_audit
from red_team.output.json_metadata_renderer import render_json_metadata
from red_team.output.markdown_renderer import render_markdown


def rules_only_fallback(
    *,
    data_dir: str | Path,
    date: str,
    audit_type: str,
    chairman_brief: dict,
    recommendations: list[Recommendation],
    research_signals: list[ResearchSignal],
    failure_reason: str,
) -> tuple[Path, Path]:
    """Generate a rules-only Red Team audit and log the failure reason."""

    root = Path(data_dir)
    compact = date.replace("-", "")
    audit = assemble_audit(
        chairman_brief=chairman_brief,
        recommendations=recommendations,
        research_signals=research_signals,
        audit_type=audit_type,
        date=date,
        use_llm=False,
        rules_only=True,
    )
    output_dir = root / "red_team_audits" / compact
    output_dir.mkdir(parents=True, exist_ok=True)
    md_path = output_dir / f"{audit.audit_id}.md"
    json_path = output_dir / f"{audit.audit_id}.json"
    md_path.write_text(
        f"# ⚠️ Red Team LLM 失败，仅规则审计部分有效\n\n失败原因：{failure_reason}\n\n"
        + render_markdown(audit),
        encoding="utf-8",
    )
    json_path.write_text(render_json_metadata(audit), encoding="utf-8")
    return md_path, json_path
