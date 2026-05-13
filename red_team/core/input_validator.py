"""Input loading for Red Team."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from chairman.core.input_validator import InputValidationError, load_inputs


def find_chairman_brief_json(
    data_dir: str | Path,
    date: str,
    audit_type: str,
    target_brief: str | None = None,
) -> Path:
    """Find the Chairman JSON metadata file consumed by Red Team."""

    root = Path(data_dir)
    compact_date = date.replace("-", "")
    brief_dir = root / "briefs" / compact_date
    if target_brief:
        path = brief_dir / f"{target_brief}.json"
        if not path.exists():
            raise InputValidationError([f"chairman brief not found: {path}"])
        return path

    suffix = {"morning": "AM", "evening": "PM", "ad_hoc": "ADHOC"}.get(audit_type, "AM")
    path = brief_dir / f"BRIEF-{compact_date}-{suffix}.json"
    if path.exists():
        return path
    candidates = sorted(brief_dir.glob("BRIEF-*.json"))
    if candidates:
        return candidates[-1]
    raise InputValidationError([f"no chairman brief JSON found under {brief_dir}"])


def load_chairman_brief(path: str | Path) -> dict[str, Any]:
    """Load Chairman brief JSON metadata."""

    with Path(path).open("r", encoding="utf-8") as file_obj:
        data = json.load(file_obj)
    if not isinstance(data, dict) or not data.get("brief_id"):
        raise InputValidationError([f"invalid chairman brief JSON: {path}"])
    return data


def load_red_team_inputs(
    data_dir: str | Path,
    date: str,
    audit_type: str,
    target_brief: str | None = None,
) -> tuple[dict[str, Any], list[Any], list[Any], list[str]]:
    """Load Chairman brief plus raw recommendation and research signal inputs."""

    brief_path = find_chairman_brief_json(data_dir, date, audit_type, target_brief)
    chairman_brief = load_chairman_brief(brief_path)
    signals, recommendations, consumed = load_inputs(data_dir, date)
    return chairman_brief, recommendations, signals, [str(brief_path), *consumed]
