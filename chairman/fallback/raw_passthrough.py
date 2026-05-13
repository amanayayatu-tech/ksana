"""Raw passthrough fallback when Chairman core flow fails."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from chairman.core.brief_assembler import build_brief_id
from chairman.core.input_validator import collect_input_files, load_yaml_file
from chairman.models import BriefType


def fallback_passthrough(
    *,
    data_dir: str | Path,
    date: str,
    brief_type: BriefType | str,
    failure_reason: str,
) -> Path:
    """Generate a raw passthrough brief and an error log."""

    root = Path(data_dir)
    compact_date = date.replace("-", "")
    normalized_type = BriefType(brief_type)
    brief_id = f"{build_brief_id(date, normalized_type)}-FALLBACK"
    errors_dir = root / "errors"
    errors_dir.mkdir(parents=True, exist_ok=True)
    error_log_id = _next_error_log_id(errors_dir, compact_date)
    error_log_path = errors_dir / f"{error_log_id}.log"
    error_log_path.write_text(
        f"generated_at={datetime.now().astimezone().isoformat()}\n"
        f"brief_type={normalized_type.value}\n"
        f"failure_reason={failure_reason}\n",
        encoding="utf-8",
    )

    signal_files, recommendation_files = collect_input_files(root, compact_date)
    research_signals = [_safe_load(path) for path in signal_files]
    recommendations = [_safe_load(path) for path in recommendation_files]

    output_dir = root / "briefs" / compact_date
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{brief_id}.md"
    output_path.write_text(
        render_fallback_markdown(
            brief_id=brief_id,
            failure_reason=failure_reason,
            error_log_id=error_log_id,
            research_signals=research_signals,
            recommendations=recommendations,
        ),
        encoding="utf-8",
    )
    return output_path


def render_fallback_markdown(
    *,
    brief_id: str,
    failure_reason: str,
    error_log_id: str,
    research_signals: list[dict[str, Any]],
    recommendations: list[dict[str, Any]],
) -> str:
    """Render raw passthrough fallback Markdown."""

    parts = [
        f"# ⚠️ Chairman 失败 — 原始建议转发 {brief_id}",
        "",
        "**注意**：Chairman 核心流程失败，以下是 3 个交易 Agent 的原始输出。",
        "未做汇总、未做权重应用、未做分歧分析。请手动审查。",
        "",
        f"**失败原因**：{failure_reason}",
        f"**错误日志**：`errors/{error_log_id}.log`",
        "",
        "---",
        "",
        "## 4.1 研究信号原文",
        "",
    ]
    for signal in research_signals:
        signal_id = _payload_id(signal, "research_signal", "research_signal_id")
        parts.extend([f"### {signal_id}", "", "```yaml", _to_yaml(signal), "```", ""])

    parts.extend(["## Agent 建议原文", ""])
    for rec in recommendations:
        payload = rec.get("recommendation", rec)
        title = f"{payload.get('agent_id', 'unknown_agent')} — {payload.get('recommendation_id', 'unknown_id')}"
        parts.extend([f"### {title}", "", "```yaml", _to_yaml(rec), "```", ""])

    parts.extend(
        [
            "---",
            "",
            "> Chairman fallback v0.1。建议在修复 Chairman 后重新生成正式 brief。",
            "",
        ]
    )
    return "\n".join(parts)


def _safe_load(path: Path) -> dict[str, Any]:
    try:
        return load_yaml_file(path)
    except Exception as exc:
        return {"_load_error": str(exc), "_source_path": str(path)}


def _payload_id(data: dict[str, Any], wrapper: str, field: str) -> str:
    payload = data.get(wrapper, data)
    if isinstance(payload, dict):
        return str(payload.get(field, "unknown_id"))
    return "unknown_id"


def _to_yaml(data: dict[str, Any]) -> str:
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False).strip()


def _next_error_log_id(errors_dir: Path, compact_date: str) -> str:
    existing = sorted(errors_dir.glob(f"CHAIRMAN-FAIL-{compact_date}-*.log"))
    return f"CHAIRMAN-FAIL-{compact_date}-{len(existing) + 1:02d}"
