"""Assemble Chairman brief metadata from validated inputs."""

from __future__ import annotations

import os
import time
from collections import defaultdict
from datetime import datetime
from typing import Any

from chairman import CHAIRMAN_VERSION
from chairman.core.consensus_calculator import calculate_direction_consensus
from chairman.core.disagreement_classifier import classify_disagreement
from chairman.core.escalation_router import determine_escalation
from chairman.core.weight_applier import get_chairman_weight_multiplier
from chairman.llm.narrative_generator import LLMClient, generate_disagreement_narrative
from chairman.models import (
    AgentId,
    BriefType,
    ChairmanBrief,
    Direction,
    DisagreementAnalysis,
    Escalation,
    FengliuRecommendation,
    Priority,
    Recommendation,
    ResearchSignal,
    WanmuRecommendation,
)

DECISIONS_APPLIED = [
    "DEC-001",
    "DEC-002",
    "DEC-003",
    "DEC-004",
    "DEC-005",
    "DEC-007",
    "DEC-008",
    "DEC-011",
    "DEC-013",
    "DEC-014",
    "DEC-016",
]


def assemble_brief(
    *,
    research_signals: list[ResearchSignal],
    recommendations: list[Recommendation],
    brief_type: BriefType | str,
    date: str,
    llm_client: LLMClient | None = None,
    use_llm: bool = True,
    input_files_consumed: list[str] | None = None,
) -> ChairmanBrief:
    """Build a ChairmanBrief from validated research signals and recommendations."""

    started_at = time.perf_counter()
    normalized_type = BriefType(brief_type)
    signal_by_id = {signal.research_signal_id: signal for signal in research_signals}
    grouped = _group_recommendations(recommendations)

    summaries: list[dict[str, Any]] = []
    all_escalations: list[Escalation] = []

    for group_recs in grouped.values():
        research_signal = _find_primary_signal(group_recs, signal_by_id)
        consensus = calculate_direction_consensus(group_recs, research_signal)
        disagreement = classify_disagreement(group_recs, research_signal, consensus)
        narrative = generate_disagreement_narrative(
            group_recs,
            disagreement,
            llm_client,
            use_llm=use_llm,
        )
        disagreement_payload = disagreement.model_dump()
        disagreement_payload["narrative"] = narrative
        disagreement = DisagreementAnalysis(**disagreement_payload)
        escalation = determine_escalation(group_recs, consensus, disagreement)
        all_escalations.extend(escalation.escalations)

        summaries.append(
            {
                "ticker": group_recs[0].ticker,
                "market": group_recs[0].market,
                "research_signal_id": research_signal.research_signal_id if research_signal else None,
                "direction_consensus": consensus.model_dump(mode="json"),
                "individual_views": [build_individual_view(rec) for rec in group_recs],
                "disagreement_analysis": disagreement.model_dump(mode="json"),
                "position_aggregation": build_position_aggregation(group_recs),
                "nepha_action_hint": build_nepha_action_hint(disagreement),
            }
        )

    upstream_coverage = build_upstream_coverage(research_signals, recommendations)
    red_team_queue = build_red_team_queue(all_escalations)
    executive_summary = build_executive_summary(
        research_signals=research_signals,
        recommendations=recommendations,
        summaries=summaries,
        upstream_coverage=upstream_coverage,
        red_team_queue=red_team_queue,
    )

    return ChairmanBrief(
        brief_id=build_brief_id(date, normalized_type),
        generated_at=datetime.now().astimezone(),
        brief_type=normalized_type,
        executive_summary=executive_summary,
        per_recommendation_summary=summaries,
        upstream_coverage_status=upstream_coverage,
        red_team_queue=red_team_queue,
        chairman_observations=build_observations(summaries),
        chairman_version=CHAIRMAN_VERSION,
        decisions_applied=DECISIONS_APPLIED,
        llm_used=bool(use_llm and llm_client),
        llm_model=os.getenv("LLM_MODEL") if use_llm and llm_client else None,
        processing_time_seconds=round(time.perf_counter() - started_at, 4),
        input_files_consumed=input_files_consumed or [],
    )


def build_brief_id(date: str, brief_type: BriefType) -> str:
    """Build BRIEF-YYYYMMDD-AM/PM/ADHOC."""

    compact_date = date.replace("-", "")
    suffix = {
        BriefType.MORNING: "AM",
        BriefType.EVENING: "PM",
        BriefType.AD_HOC: "ADHOC",
    }[brief_type]
    return f"BRIEF-{compact_date}-{suffix}"


def build_individual_view(rec: Recommendation) -> dict[str, Any]:
    """Build per-agent display payload, preserving method-specific fields."""

    view = {
        "agent_id": rec.agent_id.value,
        "recommendation_id": rec.recommendation_id,
        "direction": rec.direction.value,
        "confidence": rec.confidence,
        "chairman_weight_multiplier": get_chairman_weight_multiplier(rec),
        "one_liner_thesis": rec.one_liner_thesis or rec.thesis,
        "abstain_reason": rec.abstain_reason or rec.deployment_compliance.abstain_reason,
        "position_size_pct": rec.position_size_pct,
        "entry_zone": rec.entry_zone,
        "target_price": rec.target_price,
        "stop_loss": rec.stop_loss,
        "deployment_compliance": rec.deployment_compliance.model_dump(mode="json"),
        "authority_resolution": rec.authority_resolution.model_dump(mode="json"),
    }

    if rec.agent_id == AgentId.WANMU and isinstance(rec, WanmuRecommendation):
        view["collaborative_validation_summary"] = summarize_wanmu_collaborative_validation(rec)
        view["wanmu_rating"] = rec.wanmu_rating
    if rec.agent_id == AgentId.FENGLIU and isinstance(rec, FengliuRecommendation):
        view["outsider_handling"] = classify_fengliu_outsider_handling(rec)
        view["logic_kill_routing"] = classify_fengliu_logic_kill_routing(rec)
        view["fengliu_specific_framework"] = rec.fengliu_specific_framework
    if rec.agent_id == AgentId.LIGUOFEI:
        mapped_to_three_powers = [
            signal.mapped_to_three_powers
            for signal in rec.upstream_research_signals
            if signal.mapped_to_three_powers
        ]
        view["mapped_to_three_powers"] = mapped_to_three_powers
        view["action"] = getattr(rec, "action", None)

    return view


def summarize_wanmu_collaborative_validation(rec: WanmuRecommendation) -> dict[str, Any]:
    """Summarize DEC-007 and DEC-016 collaborative-validation details."""

    validation = rec.collaborative_validation or {}
    breakdown = validation.get("validators_breakdown", {}) or {}
    entries = breakdown.get("nepha_manual_validation_entries", []) or []
    valid_manual_entries = [entry for entry in entries if entry.get("evidence_url")]
    invalid_manual_entries = [
        entry
        for entry in entries
        if entry.get("counts_as_validator") and not entry.get("evidence_url")
    ]
    upstream_counted = int(breakdown.get("upstream_4_1_signals_counted") or 0)
    upstream_from_refs = sum(
        1 for signal in rec.upstream_research_signals if signal.contributes_to_collaborative_validation
    )

    return {
        "independent_validators_count": validation.get("independent_validators_count", 0),
        "upstream_4_1_signals_counted": max(upstream_counted, upstream_from_refs),
        "four_one_counted_as_validator": max(upstream_counted, upstream_from_refs) > 0,
        "nepha_manual_validation_with_evidence_url": len(valid_manual_entries),
        "nepha_manual_validation_without_evidence_url": len(invalid_manual_entries),
        "all_counted_nepha_entries_have_evidence_url": not invalid_manual_entries,
    }


def classify_fengliu_outsider_handling(rec: FengliuRecommendation) -> dict[str, Any]:
    """Display the three DEC-013 outsider cases for Fengliu."""

    if rec.circle_status != "outsider":
        return {"case": "not_outsider", "display": "非 outsider，不适用 DEC-013 三档。"}
    abstain_reason = rec.abstain_reason or rec.deployment_compliance.abstain_reason
    if rec.direction == Direction.LONG:
        return {"case": "case_1_outsider_with_clear_trend_signal", "expected_action": "long"}
    if rec.direction == Direction.ABSTAIN or abstain_reason == "circle_status_outsider":
        return {"case": "case_2_outsider_no_trend_signal", "expected_action": "abstain"}
    if rec.direction == Direction.AVOID:
        return {"case": "case_3_outsider_with_logic_break", "expected_action": "avoid"}
    return {"case": "outsider_unclassified", "expected_action": "review"}


def classify_fengliu_logic_kill_routing(rec: FengliuRecommendation) -> dict[str, Any]:
    """Display DEC-014 logic-kill confidence routing."""

    confidence = _extract_logic_kill_confidence(rec)
    if confidence is None:
        return {"route": "not_logic_kill", "confidence": None}
    normalized = confidence / 100 if confidence > 1 else confidence
    if normalized >= 0.65:
        return {"route": "avoid_expected", "confidence": normalized}
    if normalized >= 0.50:
        return {"route": "abstain_expected", "confidence": normalized}
    return {"route": "not_logic_kill", "confidence": normalized}


def _extract_logic_kill_confidence(rec: FengliuRecommendation) -> float | None:
    heuristic = rec.kill_type_heuristic or {}
    logic_kill = heuristic.get("logic_kill", {}) if isinstance(heuristic, dict) else {}
    if isinstance(logic_kill, dict) and logic_kill.get("confidence") is not None:
        return float(logic_kill["confidence"])
    if rec.fengliu_specific_framework.get("kill_type_heuristic_verdict") == "logic_kill":
        value = rec.fengliu_specific_framework.get("kill_type_confidence")
        return float(value) if value is not None else None
    return None


def build_position_aggregation(recommendations: list[Recommendation]) -> dict[str, Any]:
    """Aggregate proposed positions without making a decision for Nepha."""

    positions = [rec.position_size_pct for rec in recommendations if rec.position_size_pct is not None]
    if not positions:
        return {
            "individual_proposals": [],
            "min_proposed": None,
            "max_proposed": None,
            "range_pct": 0,
            "deployment_layer_compliance_aggregate": "not_applicable",
        }
    return {
        "individual_proposals": [
            {"agent_id": rec.agent_id.value, "position_size_pct": rec.position_size_pct}
            for rec in recommendations
        ],
        "min_proposed": min(positions),
        "max_proposed": max(positions),
        "range_pct": round(max(positions) - min(positions), 4),
        "deployment_layer_compliance_aggregate": "passed"
        if all(not rec.deployment_compliance.any_failure_must_abstain for rec in recommendations)
        else "has_failure",
    }


def build_nepha_action_hint(disagreement: DisagreementAnalysis) -> dict[str, Any]:
    """Navigation hint, not a trading decision."""

    if not disagreement.primary_type:
        return {"primary_attention_point": None, "suggested_followup_questions": []}
    return {
        "primary_attention_point": disagreement.narrative,
        "suggested_followup_questions": [
            "这个分歧是证据差异、时效差异，还是方法论差异？",
            "是否需要 Red Team 复核关键反证？",
        ],
    }


def build_upstream_coverage(
    research_signals: list[ResearchSignal],
    recommendations: list[Recommendation],
) -> dict[str, Any]:
    """Build 4.1 research upstream coverage status."""

    signal_ids = {signal.research_signal_id for signal in research_signals}
    refs_by_signal: dict[str, list[Recommendation]] = defaultdict(list)
    for rec in recommendations:
        for signal_ref in rec.upstream_research_signals:
            refs_by_signal[signal_ref.research_signal_id].append(rec)

    signals_with_zero = sorted(signal_ids - set(refs_by_signal))
    signals_with_all_abstain = sorted(
        signal_id
        for signal_id, recs in refs_by_signal.items()
        if signal_id in signal_ids and recs and all(rec.direction == Direction.ABSTAIN for rec in recs)
    )
    pending_count = sum(
        len(signal.perplexity_research.get("prompts_pending", []) or []) for signal in research_signals
    )
    return {
        "today_signals_emitted": len(research_signals),
        "signals_with_zero_agent_response": signals_with_zero,
        "signals_with_all_abstain": signals_with_all_abstain,
        "perplexity_prompt_brief_pending": pending_count,
    }


def build_red_team_queue(escalations: list[Escalation]) -> dict[str, Any]:
    """Split Red Team escalations into template-friendly buckets."""

    return {
        "high_priority": [
            item.model_dump(mode="json")
            for item in escalations
            if item.priority in {Priority.CRITICAL, Priority.HIGH}
        ],
        "medium_priority": [
            item.model_dump(mode="json") for item in escalations if item.priority == Priority.MEDIUM
        ],
    }


def build_executive_summary(
    *,
    research_signals: list[ResearchSignal],
    recommendations: list[Recommendation],
    summaries: list[dict[str, Any]],
    upstream_coverage: dict[str, Any],
    red_team_queue: dict[str, Any],
) -> dict[str, Any]:
    """Build 30-second executive summary."""

    full_long = [
        summary["ticker"]
        for summary in summaries
        if summary["direction_consensus"]["consensus_level"] == "full_consensus_long"
    ]
    full_avoid = [
        summary["ticker"]
        for summary in summaries
        if summary["direction_consensus"]["consensus_level"] == "full_consensus_avoid"
    ]
    split = [
        summary
        for summary in summaries
        if summary["direction_consensus"]["consensus_level"] == "split_long_vs_avoid"
    ]
    return {
        "total_signals_today": len(research_signals),
        "total_recommendations": len(recommendations),
        "total_recommendations_received": len(recommendations),
        "full_consensus_long": full_long,
        "full_consensus_avoid": full_avoid,
        "split_decisions": split,
        "abstain_with_high_signals": upstream_coverage["signals_with_all_abstain"],
        "red_team_high_priority": len(red_team_queue["high_priority"]),
        "perplexity_prompts_pending": upstream_coverage["perplexity_prompt_brief_pending"],
    }


def build_observations(summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build simple Chairman observations from summaries."""

    observations: list[dict[str, Any]] = []
    for summary in summaries:
        if summary["disagreement_analysis"]["primary_type"] == "data_input_difference":
            observations.append(
                {
                    "observation_type": "data_stale",
                    "content": f"{summary['ticker']} 的 Agent 数据时效存在差异。",
                    "affected_agents": [
                        view["agent_id"] for view in summary.get("individual_views", [])
                    ],
                }
            )
    return observations


def _group_recommendations(recommendations: list[Recommendation]) -> dict[tuple[str, str], list[Recommendation]]:
    grouped: dict[tuple[str, str], list[Recommendation]] = defaultdict(list)
    for rec in recommendations:
        grouped[(rec.ticker, rec.market)].append(rec)
    return dict(grouped)


def _find_primary_signal(
    recommendations: list[Recommendation],
    signal_by_id: dict[str, ResearchSignal],
) -> ResearchSignal | None:
    for rec in recommendations:
        for signal_ref in rec.upstream_research_signals:
            if signal_ref.research_signal_id in signal_by_id:
                return signal_by_id[signal_ref.research_signal_id]
    return None
