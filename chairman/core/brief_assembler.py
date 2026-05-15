"""Assemble Chairman brief metadata from validated inputs."""

from __future__ import annotations

import os
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from business_agents._common.knowledge_store import get_recent_knowledge_summary
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
    FPartnerRecommendation,
    Priority,
    Recommendation,
    ResearchSignal,
    WPartnerRecommendation,
)
from orchestrator.core.partner_performance import load_partner_performance_context

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
    data_dir: str | Path | None = None,
) -> ChairmanBrief:
    """Build a ChairmanBrief from validated research signals and recommendations."""

    started_at = time.perf_counter()
    normalized_type = BriefType(brief_type)
    signal_by_id = {signal.research_signal_id: signal for signal in research_signals}
    grouped = _group_recommendations(recommendations)
    knowledge_memory = build_knowledge_memory(
        grouped,
        data_dir=data_dir,
        date=date,
    )
    partner_performance_context = load_partner_performance_context(data_dir)

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
        historical_knowledge = knowledge_memory.get(group_recs[0].ticker, {})
        verdict = build_chairman_verdict(
            group_recs,
            consensus.model_dump(mode="json"),
            disagreement.model_dump(mode="json"),
            historical_knowledge,
            [item.model_dump(mode="json") for item in escalation.escalations],
            research_signal,
            partner_performance_context,
        )

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
                "historical_knowledge": historical_knowledge,
                "chairman_verdict": verdict,
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
        knowledge_memory=knowledge_memory,
        final_verdicts=build_final_verdicts(summaries),
        partner_performance_context=partner_performance_context,
        chairman_observations=build_observations(summaries),
        chairman_version=CHAIRMAN_VERSION,
        decisions_applied=DECISIONS_APPLIED,
        llm_used=bool(use_llm and llm_client),
        llm_model=os.getenv("LLM_MODEL") if use_llm and llm_client else None,
        processing_time_seconds=round(time.perf_counter() - started_at, 4),
        input_files_consumed=input_files_consumed or [],
    )


def build_chairman_verdict(
    recommendations: list[Recommendation],
    consensus: dict[str, Any],
    disagreement: dict[str, Any],
    historical_knowledge: dict[str, Any],
    escalation_items: list[dict[str, Any]],
    research_signal: ResearchSignal | None,
    partner_performance_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create deterministic CIO-style decision navigation for Nepha."""

    partner_performance_context = partner_performance_context or {}
    lead_view = select_lead_agent(recommendations, partner_performance_context)
    has_perplexity = any(
        ref.used_perplexity_results
        for rec in recommendations
        for ref in rec.upstream_research_signals
    )
    pending_prompts = []
    if research_signal:
        pending_prompts = research_signal.perplexity_research.get("prompts_pending", []) or []
    history_entries = historical_knowledge.get("entries", []) or []
    similar_cases = historical_knowledge.get("similar_cases", []) or []
    open_questions = historical_knowledge.get("open_questions", []) or []
    historical_conflicts = historical_knowledge.get("historical_conflicts", []) or []
    has_high_escalation = any(item.get("priority") in {"critical", "high"} for item in escalation_items)
    consensus_level = str(consensus.get("consensus_level") or "other")

    final_verdict = "wait"
    action_route = "watchlist_monitor"
    if consensus_level in {"full_consensus_avoid", "majority_avoid"}:
        final_verdict = "reject"
        action_route = "drop_or_require_new_signal"
    elif consensus_level == "all_abstain" or (not has_perplexity and pending_prompts):
        final_verdict = "research_more"
        action_route = "run_or_update_perplexity_research"
    elif consensus_level in {"full_consensus_long", "majority_long"} and has_perplexity and not has_high_escalation:
        final_verdict = "act" if len(open_questions) <= 2 else "wait"
        action_route = "trial_position_candidate_after_nepha_review" if final_verdict == "act" else "watchlist_monitor"
    elif consensus_level == "split_long_vs_avoid" or has_high_escalation:
        final_verdict = "wait"
        action_route = "send_to_red_team_before_action"

    confidence = estimate_chairman_confidence(
        recommendations,
        consensus_level=consensus_level,
        has_perplexity=has_perplexity,
        history_entries=len(history_entries),
        similar_cases=len(similar_cases),
        open_questions=len(open_questions),
        historical_conflicts=len(historical_conflicts),
        has_high_escalation=has_high_escalation,
        average_performance_multiplier=average_performance_multiplier(
            recommendations,
            partner_performance_context,
        ),
    )
    return {
        "final_verdict": final_verdict,
        "action_route": action_route,
        "confidence": confidence,
        "lead_agent": lead_view,
        "decision_chain": build_decision_chain(
            recommendations,
            consensus,
            disagreement,
            lead_view,
            has_perplexity=has_perplexity,
            pending_prompts=pending_prompts,
            historical_knowledge=historical_knowledge,
            escalation_items=escalation_items,
            partner_performance_context=partner_performance_context,
        ),
        "history_context": {
            "entries_count": len(history_entries),
            "similar_cases_count": len(similar_cases),
            "latest_prompt_id": history_entries[0].get("prompt_id") if history_entries else None,
            "similar_case_prompt_ids": [
                case.get("prompt_id") for case in similar_cases[:5] if case.get("prompt_id")
            ],
            "open_questions_count": len(open_questions),
            "open_questions_sample": open_questions[:3],
            "historical_conflicts": historical_conflicts[:3],
        },
        "dissent_summary": build_dissent_summary(disagreement, escalation_items, open_questions),
        "red_team_rebuttal_policy": {
            "if_red_team_verdict": {
                "block": "downgrade_to_reject_and_require_nepha_override",
                "challenge": "downgrade_to_research_more_until_objection_closed",
                "monitor": "keep_wait_or_research_more",
            },
            "second_chairman_review_required": True,
        },
    }


def select_lead_agent(
    recommendations: list[Recommendation],
    partner_performance_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    scored = sorted(
        recommendations,
        key=lambda rec: rec.confidence
        * get_chairman_weight_multiplier(rec)
        * performance_multiplier_for_agent(rec.agent_id.value, partner_performance_context or {}),
        reverse=True,
    )
    if not scored:
        return {}
    lead = scored[0]
    performance_multiplier = performance_multiplier_for_agent(
        lead.agent_id.value,
        partner_performance_context or {},
    )
    return {
        "agent_id": lead.agent_id.value,
        "recommendation_id": lead.recommendation_id,
        "direction": lead.direction.value,
        "confidence": lead.confidence,
        "chairman_weight_multiplier": get_chairman_weight_multiplier(lead),
        "performance_weight_multiplier": performance_multiplier,
        "combined_weighted_score": round(
            lead.confidence * get_chairman_weight_multiplier(lead) * performance_multiplier,
            4,
        ),
        "reason": lead.one_liner_thesis or lead.thesis,
    }


def performance_multiplier_for_agent(agent_id: str, partner_performance_context: dict[str, Any]) -> float:
    profile = (partner_performance_context.get("profiles") or {}).get(agent_id) or {}
    return float(profile.get("performance_weight_multiplier") or 1.0)


def average_performance_multiplier(
    recommendations: list[Recommendation],
    partner_performance_context: dict[str, Any],
) -> float:
    if not recommendations:
        return 1.0
    values = [
        performance_multiplier_for_agent(rec.agent_id.value, partner_performance_context)
        for rec in recommendations
    ]
    return sum(values) / len(values)


def estimate_chairman_confidence(
    recommendations: list[Recommendation],
    *,
    consensus_level: str,
    has_perplexity: bool,
    history_entries: int,
    similar_cases: int,
    open_questions: int,
    historical_conflicts: int,
    has_high_escalation: bool,
    average_performance_multiplier: float = 1.0,
) -> int:
    if not recommendations:
        return 0
    average = sum(rec.confidence for rec in recommendations) / len(recommendations)
    adjustment = 0
    if consensus_level.startswith("full_consensus"):
        adjustment += 8
    elif consensus_level.startswith("majority"):
        adjustment += 4
    elif consensus_level in {"split_long_vs_avoid", "all_abstain"}:
        adjustment -= 10
    if has_perplexity:
        adjustment += 6
    if history_entries:
        adjustment += 4
    if similar_cases:
        adjustment += 2
    adjustment -= min(12, open_questions * 2)
    adjustment -= min(10, historical_conflicts * 3)
    if has_high_escalation:
        adjustment -= 10
    adjustment += round((average_performance_multiplier - 1.0) * 12)
    return max(0, min(95, round(average + adjustment)))


def build_decision_chain(
    recommendations: list[Recommendation],
    consensus: dict[str, Any],
    disagreement: dict[str, Any],
    lead_view: dict[str, Any],
    *,
    has_perplexity: bool,
    pending_prompts: list[Any],
    historical_knowledge: dict[str, Any],
    escalation_items: list[dict[str, Any]],
    partner_performance_context: dict[str, Any],
) -> list[str]:
    entries = historical_knowledge.get("entries", []) or []
    similar_cases = historical_knowledge.get("similar_cases", []) or []
    open_questions = historical_knowledge.get("open_questions", []) or []
    historical_conflicts = historical_knowledge.get("historical_conflicts", []) or []
    directions = ", ".join(f"{rec.agent_id.value}:{rec.direction.value}/{rec.confidence}" for rec in recommendations)
    chain = [
        f"三位 Agent 当前分布为 {directions}；共识类型是 {consensus.get('consensus_level')}。",
        f"Chairman 暂时最重视 {lead_view.get('agent_id')}，因为其方向为 {lead_view.get('direction')}，置信度 {lead_view.get('confidence')}，权重 ×{lead_view.get('chairman_weight_multiplier')}。",
    ]
    if has_perplexity:
        chain.append("至少一位 Agent 已消费 Perplexity 回填，证据链不是纯价量推断。")
    elif pending_prompts:
        chain.append(f"Perplexity 仍有待研究 prompt：{', '.join(map(str, pending_prompts[:3]))}，不能升级为高置信裁决。")
    else:
        chain.append("未检测到 Perplexity 深度研究背书，裁决必须保守。")
    if entries:
        chain.append(f"知识库中存在 {len(entries)} 条历史研究，最近一条是 {entries[0].get('prompt_id')}。")
    else:
        chain.append("知识库尚无该标的历史研究，本次判断缺少纵向记忆。")
    if similar_cases:
        case_ids = ", ".join(str(case.get("prompt_id")) for case in similar_cases[:3])
        chain.append(f"找到 {len(similar_cases)} 条相似历史案例：{case_ids}；只作为类比，不直接替代本次判断。")
    if open_questions:
        chain.append(f"仍有 {len(open_questions)} 个未关闭问题，优先关注：{open_questions[0]}")
    if historical_conflicts:
        chain.append(f"知识库存在 {len(historical_conflicts)} 条历史冲突/反例，裁决必须先解释：{historical_conflicts[0]}")
    performance_notes = build_performance_chain_notes(recommendations, partner_performance_context)
    chain.extend(performance_notes)
    if disagreement.get("primary_type"):
        chain.append(f"主要分歧类型为 {disagreement.get('primary_type')}：{disagreement.get('narrative')}")
    if escalation_items:
        chain.append(f"已产生 {len(escalation_items)} 条 Red Team 待审事项，行动前需要先处理。")
    return chain


def build_performance_chain_notes(
    recommendations: list[Recommendation],
    partner_performance_context: dict[str, Any],
) -> list[str]:
    profiles = partner_performance_context.get("profiles") or {}
    notes: list[str] = []
    for rec in recommendations:
        profile = profiles.get(rec.agent_id.value)
        if not profile:
            continue
        notes.append(
            f"{rec.agent_id.value} 历史表现权重 ×{profile.get('performance_weight_multiplier', 1.0)}；"
            f"验证分布 {profile.get('verification_status_counts', {})}。"
        )
    if not notes and partner_performance_context.get("visibility") == "chairman_only":
        notes.append("Partner Performance Log 暂无已验证样本；当前只记录，不反向污染三位 Agent 方法论。")
    return notes


def build_dissent_summary(
    disagreement: dict[str, Any],
    escalation_items: list[dict[str, Any]],
    open_questions: list[str],
) -> str:
    if escalation_items:
        return str(escalation_items[0].get("reason") or "Red Team escalation required.")
    if open_questions:
        return f"历史研究仍有未关闭问题：{open_questions[0]}"
    if disagreement.get("primary_type"):
        return str(disagreement.get("narrative") or disagreement.get("primary_type"))
    return "暂无强反对，但仍需 Red Team 独立复核。"


def build_final_verdicts(summaries: list[dict[str, Any]]) -> dict[str, Any]:
    items = {
        summary["ticker"]: summary.get("chairman_verdict", {})
        for summary in summaries
        if summary.get("chairman_verdict")
    }
    counts: dict[str, int] = defaultdict(int)
    for item in items.values():
        counts[str(item.get("final_verdict") or "unknown")] += 1
    return {"by_ticker": items, "counts": dict(counts)}


def build_knowledge_memory(
    grouped: dict[tuple[str, str], list[Recommendation]],
    *,
    data_dir: str | Path | None,
    date: str,
) -> dict[str, Any]:
    """Load recent Perplexity-derived memory for each ticker in the brief."""

    if data_dir is None:
        return {}
    memory: dict[str, Any] = {}
    for ticker, _market in grouped:
        summary = get_recent_knowledge_summary(data_dir, ticker, as_of_date=date)
        if has_reusable_knowledge(summary):
            memory[ticker] = summary
    return memory


def has_reusable_knowledge(summary: dict[str, Any]) -> bool:
    return any(
        summary.get(key)
        for key in (
            "entries",
            "similar_cases",
            "open_questions",
            "historical_conflicts",
            "closed_questions",
        )
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

    if rec.agent_id == AgentId.W_PARTNER and isinstance(rec, WPartnerRecommendation):
        view["collaborative_validation_summary"] = summarize_w_partner_collaborative_validation(rec)
        view["w_partner_rating"] = rec.w_partner_rating
    if rec.agent_id == AgentId.F_PARTNER and isinstance(rec, FPartnerRecommendation):
        view["outsider_handling"] = classify_f_partner_outsider_handling(rec)
        view["logic_kill_routing"] = classify_f_partner_logic_kill_routing(rec)
        view["f_partner_specific_framework"] = rec.f_partner_specific_framework
    if rec.agent_id == AgentId.G_PARTNER:
        mapped_to_three_powers = [
            signal.mapped_to_three_powers
            for signal in rec.upstream_research_signals
            if signal.mapped_to_three_powers
        ]
        view["mapped_to_three_powers"] = mapped_to_three_powers
        view["action"] = getattr(rec, "action", None)

    return view


def summarize_w_partner_collaborative_validation(rec: WPartnerRecommendation) -> dict[str, Any]:
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
    upstream_counted = int(breakdown.get("upstream_k_deep_signals_counted") or 0)
    upstream_from_refs = sum(
        1 for signal in rec.upstream_research_signals if signal.contributes_to_collaborative_validation
    )

    return {
        "independent_validators_count": validation.get("independent_validators_count", 0),
        "upstream_k_deep_signals_counted": max(upstream_counted, upstream_from_refs),
        "four_one_counted_as_validator": max(upstream_counted, upstream_from_refs) > 0,
        "nepha_manual_validation_with_evidence_url": len(valid_manual_entries),
        "nepha_manual_validation_without_evidence_url": len(invalid_manual_entries),
        "all_counted_nepha_entries_have_evidence_url": not invalid_manual_entries,
    }


def classify_f_partner_outsider_handling(rec: FPartnerRecommendation) -> dict[str, Any]:
    """Display the three DEC-013 outsider cases for FPartner."""

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


def classify_f_partner_logic_kill_routing(rec: FPartnerRecommendation) -> dict[str, Any]:
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


def _extract_logic_kill_confidence(rec: FPartnerRecommendation) -> float | None:
    heuristic = rec.kill_type_heuristic or {}
    logic_kill = heuristic.get("logic_kill", {}) if isinstance(heuristic, dict) else {}
    if isinstance(logic_kill, dict) and logic_kill.get("confidence") is not None:
        return float(logic_kill["confidence"])
    if rec.f_partner_specific_framework.get("kill_type_heuristic_verdict") == "logic_kill":
        value = rec.f_partner_specific_framework.get("kill_type_confidence")
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
    """Build K deep research upstream coverage status."""

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
