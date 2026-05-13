"""Whole-pipeline fallback."""

from __future__ import annotations

from pathlib import Path


def pipeline_fallback(
    *,
    data_dir: str | Path,
    date: str,
    run_id: str,
    failed_step: str,
    reason: str,
) -> Path:
    """Write a degraded fallback artifact for Nepha."""

    compact = date.replace("-", "")
    output_dir = Path(data_dir) / "briefs" / compact
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"FALLBACK-{run_id}.md"
    output_path.write_text(
        f"# ⚠️ Pipeline 部分失败\n\n"
        f"- run_id: `{run_id}`\n"
        f"- failed_step: `{failed_step}`\n"
        f"- reason: {reason}\n\n"
        "仅有原始建议或部分中间产物可参考，请手动审查。\n",
        encoding="utf-8",
    )
    return output_path
