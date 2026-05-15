"""Decision verification queue and objective definitions."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from chairman.models import ChairmanBrief

DEFAULT_WINDOWS = [1, 7, 30, 90]

OBJECTIVES: dict[str, dict[str, Any]] = {
    "long": {
        "primary_goal": "thesis_and_price_validation",
        "validated_if": [
            "core_thesis_confirmed_by_public_evidence",
            "price_or_fundamental_response_supports_expected_direction_within_window",
        ],
        "partially_validated_if": [
            "core_thesis_confirmed_but_price_timing_wrong",
            "price_moves_correctly_but_thesis_evidence_remains_incomplete",
        ],
        "invalidated_if": [
            "core_thesis_refuted_by_public_evidence",
            "price_moves_against_decision_and_no_thesis_support_emerges",
        ],
    },
    "watch": {
        "primary_goal": "optionality_and_information_gate_validation",
        "validated_if": [
            "open_questions_remain_material",
            "waiting_avoids_action_before_key_evidence_arrives",
        ],
        "partially_validated_if": [
            "price_moves_but_original_open_questions_were_real",
            "some_required_evidence_arrives_after_the_decision_window",
        ],
        "invalidated_if": [
            "high_quality_evidence_was_already_available_and_ignored",
            "watch_was_used_to_avoid_a_clear_decision_without_reason",
        ],
    },
    "avoid": {
        "primary_goal": "risk_avoidance_or_thesis_break_validation",
        "validated_if": [
            "stated_risk_materializes",
            "core_thesis_break_is_confirmed_by_public_evidence",
        ],
        "partially_validated_if": [
            "risk_materializes_late_after_a_temporary_rally",
            "risk_evidence_strengthens_but_price_has_not_yet_reflected_it",
        ],
        "invalidated_if": [
            "stated_risk_is_refuted",
            "company_thesis_strengthens_and_price_reacts_without_new_negative_evidence",
        ],
    },
    "abstain": {
        "primary_goal": "insufficient_evidence_validation",
        "validated_if": [
            "evidence_remains_insufficient_or_conflicting",
            "new_information_is_required_before_any_directional_decision",
        ],
        "partially_validated_if": [
            "some_evidence_arrives_but_not_enough_for_a_high_quality_decision",
        ],
        "invalidated_if": [
            "high_quality_public_evidence_was_already_available_and_material",
            "abstain_ignored_a_clear_methodology_pass_or_fail",
        ],
    },
}


def append_verification_cases_from_brief(brief: ChairmanBrief, data_dir: str | Path) -> Path:
    """Upsert pending verification cases generated from a Chairman brief."""

    root = Path(data_dir)
    output_dir = root / "decision_verification"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "pending_cases.json"
    existing = load_cases(output_path)
    by_id = {case["case_id"]: case for case in existing}
    for summary in brief.per_recommendation_summary:
        case = build_case_from_summary(brief, summary)
        by_id[case["case_id"]] = merge_verification_case(by_id.get(case["case_id"]), case)
    output_path.write_text(
        json.dumps(list(by_id.values()), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output_path


def load_cases(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8") or "[]")
    return data if isinstance(data, list) else []


def build_case_from_summary(brief: ChairmanBrief, summary: dict[str, Any]) -> dict[str, Any]:
    verdict = summary.get("chairman_verdict", {}) or {}
    direction = map_chairman_verdict_to_direction(verdict)
    ticker = str(summary.get("ticker") or "UNKNOWN")
    brief_id = brief.brief_id
    return {
        "case_id": f"DV-{brief_id}-{ticker}",
        "source_brief_id": brief_id,
        "source_signal_id": summary.get("research_signal_id"),
        "ticker": ticker,
        "decision_direction": direction,
        "chairman_final_verdict": verdict.get("final_verdict") or "wait",
        "verification_windows_days": DEFAULT_WINDOWS,
        "objective": OBJECTIVES[direction],
        "status": "pending",
        "evidence_url": "",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def merge_verification_case(existing: dict[str, Any] | None, generated: dict[str, Any]) -> dict[str, Any]:
    """Preserve manual verification annotations when regenerating a brief."""

    if not existing:
        return generated
    merged = {**existing, **generated}
    if existing.get("status") and existing.get("status") != "pending":
        for key in (
            "status",
            "evidence_url",
            "verification_notes",
            "verified_at",
            "verified_by",
            "verification_results",
        ):
            if key in existing:
                merged[key] = existing[key]
    elif existing.get("evidence_url"):
        merged["evidence_url"] = existing["evidence_url"]
    merged["created_at"] = existing.get("created_at") or generated.get("created_at")
    return merged


def map_chairman_verdict_to_direction(verdict: dict[str, Any]) -> str:
    final_verdict = str(verdict.get("final_verdict") or "wait")
    if final_verdict == "act":
        return normalize_decision_direction((verdict.get("lead_agent") or {}).get("direction"))
    if final_verdict == "reject":
        return "avoid"
    if final_verdict in {"wait", "research_more"}:
        return "watch"
    return "watch"


def normalize_decision_direction(value: Any) -> str:
    direction = str(value or "watch")
    if direction in {"long", "watch", "avoid", "abstain"}:
        return direction
    return "watch"
