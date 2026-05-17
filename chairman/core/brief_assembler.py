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
from orchestrator.core.learning import load_chairman_learning_context
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
    "DEC-019",
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
    learning_memory = build_learning_memory(
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
        learning_context = learning_memory.get(group_recs[0].ticker, {})
        opportunity_screener = build_opportunity_screener(
            group_recs,
            consensus.model_dump(mode="json"),
            historical_knowledge,
            research_signal,
            [item.model_dump(mode="json") for item in escalation.escalations],
            learning_context,
        )
        verdict = build_chairman_verdict(
            group_recs,
            consensus.model_dump(mode="json"),
            disagreement.model_dump(mode="json"),
            historical_knowledge,
            [item.model_dump(mode="json") for item in escalation.escalations],
            research_signal,
            partner_performance_context,
            learning_context,
            opportunity_screener,
        )

        summaries.append(
            {
                "ticker": group_recs[0].ticker,
                "market": group_recs[0].market,
                "research_signal_id": research_signal.research_signal_id if research_signal else None,
                "direction_consensus": consensus.model_dump(mode="json"),
                "individual_views": [build_individual_view(rec) for rec in group_recs],
                "disagreement_analysis": disagreement.model_dump(mode="json"),
                "operation_summary": build_operation_summary(group_recs, verdict),
                "nepha_action_hint": build_nepha_action_hint(disagreement),
                "historical_knowledge": historical_knowledge,
                "learning_context": learning_context,
                "opportunity_screener": opportunity_screener,
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
        learning_memory=learning_memory,
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
    learning_context: dict[str, Any] | None = None,
    opportunity_screener: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create deterministic CIO-style decision navigation for Nepha."""

    partner_performance_context = partner_performance_context or {}
    learning_context = learning_context or {}
    opportunity_screener = opportunity_screener or {}
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

    legacy_verdict = "wait"
    if consensus_level in {"full_consensus_avoid", "majority_avoid"}:
        legacy_verdict = "reject"
    elif consensus_level == "all_abstain" or (not has_perplexity and pending_prompts):
        legacy_verdict = "research_more"
    elif consensus_level in {"full_consensus_long", "majority_long"} and has_perplexity and not has_high_escalation:
        legacy_verdict = "act" if len(open_questions) <= 2 else "wait"
    elif consensus_level == "split_long_vs_avoid" or has_high_escalation:
        legacy_verdict = "wait"

    final_verdict = choose_opportunity_status(
        consensus_level=consensus_level,
        opportunity_score=int(opportunity_screener.get("opportunity_score") or 0),
        has_perplexity=has_perplexity,
        pending_prompts=pending_prompts,
        open_questions_count=len(open_questions),
        has_high_escalation=has_high_escalation,
    )
    action_route = action_route_for_opportunity_status(final_verdict)

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
        learning_context=learning_context,
    )
    return {
        "final_verdict": final_verdict,
        "legacy_verdict": legacy_verdict,
        "action_route": action_route,
        "confidence": confidence,
        "opportunity_screener": opportunity_screener,
        "human_decision_checklist": build_human_decision_checklist(opportunity_screener),
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
            learning_context=learning_context,
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
        "learning_context": {
            "prior_cases_count": learning_context.get("prior_cases_count", 0),
            "latest_case_id": learning_context.get("latest_case_id", ""),
            "outcome_status_counts": learning_context.get("outcome_status_counts", {}),
            "pattern_notes": (learning_context.get("pattern_notes") or [])[:5],
            "timeline_path": learning_context.get("timeline_path", ""),
        },
        "dissent_summary": build_dissent_summary(disagreement, escalation_items, open_questions),
        "red_team_rebuttal_policy": {
            "if_red_team_verdict": {
                "block": "downgrade_to_discard_or_require_nepha_override",
                "challenge": "downgrade_to_research_priority_until_objection_closed",
                "monitor": "keep_watch_or_research_priority",
            },
            "second_chairman_review_required": True,
        },
    }


def choose_opportunity_status(
    *,
    consensus_level: str,
    opportunity_score: int,
    has_perplexity: bool,
    pending_prompts: list[Any],
    open_questions_count: int,
    has_high_escalation: bool,
) -> str:
    """Map committee evidence into the new human-in-the-loop opportunity states."""

    if opportunity_score < 35:
        return "discard"
    if consensus_level in {"full_consensus_avoid", "majority_avoid"} and opportunity_score < 60:
        return "discard"
    if consensus_level == "split_long_vs_avoid" or has_high_escalation:
        return "human_override_required" if opportunity_score >= 60 else "watch"
    if consensus_level == "all_abstain" or (not has_perplexity and pending_prompts):
        return "research_priority" if opportunity_score >= 55 else "watch"
    if consensus_level in {"full_consensus_long", "majority_long"} and has_perplexity:
        if opportunity_score >= 85 and open_questions_count <= 1:
            return "conviction_candidate"
        if opportunity_score >= 65:
            return "trial_candidate"
    if opportunity_score >= 70:
        return "research_priority"
    if opportunity_score >= 50:
        return "watch"
    return "discard"


def action_route_for_opportunity_status(status: str) -> str:
    mapping = {
        "discard": "drop_or_require_new_signal",
        "watch": "watchlist_monitor",
        "research_priority": "run_or_update_perplexity_research",
        "trial_candidate": "human_review_for_trial_candidate",
        "conviction_candidate": "human_review_for_conviction_candidate",
        "human_override_required": "human_override_required",
    }
    return mapping.get(status, "watchlist_monitor")


def build_opportunity_screener(
    recommendations: list[Recommendation],
    consensus: dict[str, Any],
    historical_knowledge: dict[str, Any],
    research_signal: ResearchSignal | None,
    escalation_items: list[dict[str, Any]],
    learning_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Score whether a ticker deserves human research time before final judgment."""

    learning_context = learning_context or {}
    texts = collect_recommendation_texts(recommendations)
    signal_text = research_signal.signal_summary if research_signal else ""
    combined_text = "\n".join([*texts, signal_text]).lower()
    open_questions = historical_knowledge.get("open_questions", []) or []
    historical_conflicts = historical_knowledge.get("historical_conflicts", []) or []
    similar_cases = historical_knowledge.get("similar_cases", []) or []
    has_perplexity = any(
        ref.used_perplexity_results for rec in recommendations for ref in rec.upstream_research_signals
    )

    business_quality_score = score_business_quality(recommendations)
    expectation_gap_score = score_expectation_gap(recommendations, research_signal, combined_text)
    valuation_score = score_valuation(recommendations, combined_text)
    catalyst_score = score_catalyst(recommendations, research_signal, has_perplexity, combined_text)
    risk_score = score_risk_pressure(
        recommendations,
        open_questions=open_questions,
        historical_conflicts=historical_conflicts,
        escalation_items=escalation_items,
    )
    positioning_score = score_positioning(combined_text, consensus, similar_cases)
    investment_attractiveness_score = score_investment_attractiveness(
        recommendations,
        expectation_gap_score=expectation_gap_score,
        valuation_score=valuation_score,
        catalyst_score=catalyst_score,
        risk_score=risk_score,
    )
    opportunity_score = clamp_score(
        expectation_gap_score * 0.24
        + valuation_score * 0.18
        + catalyst_score * 0.18
        + investment_attractiveness_score * 0.22
        + positioning_score * 0.10
        + business_quality_score * 0.08
        - max(0, risk_score - 55) * 0.18
    )
    reason_type = classify_reason_types(
        expectation_gap_score=expectation_gap_score,
        valuation_score=valuation_score,
        catalyst_score=catalyst_score,
        business_quality_score=business_quality_score,
        positioning_score=positioning_score,
        combined_text=combined_text,
    )

    return {
        "ticker": recommendations[0].ticker if recommendations else "",
        "opportunity_score": opportunity_score,
        "reason_type": reason_type,
        "business_quality_score": business_quality_score,
        "investment_attractiveness_score": investment_attractiveness_score,
        "expectation_gap_score": expectation_gap_score,
        "valuation_score": valuation_score,
        "catalyst_score": catalyst_score,
        "risk_score": risk_score,
        "positioning_score": positioning_score,
        "time_horizon": infer_time_horizon(recommendations),
        "why_now": first_non_empty(
            signal_text,
            first_text_from_extras(recommendations, "catalysts"),
            first_long_thesis(recommendations),
            "当前异动需要先验证是否存在预期差或催化错配。",
        ),
        "consensus_view": consensus_view_label(consensus),
        "non_consensus_view": build_non_consensus_view(reason_type, recommendations, signal_text),
        "upside_path": first_non_empty(
            first_long_thesis(recommendations),
            "预期差被公开数据确认后，估值、盈利或叙事可能重新定价。",
        ),
        "downside_path": first_non_empty(
            first_text_from_extras(recommendations, "thesis_kill_criteria"),
            open_questions[0] if open_questions else "",
            historical_conflicts[0] if historical_conflicts else "",
            first_avoid_thesis(recommendations),
            "核心催化无法被公开证据验证，或风险比当前价格反映得更严重。",
        ),
        "kill_conditions": build_kill_conditions(recommendations, open_questions, historical_conflicts),
        "research_priority": priority_from_score(opportunity_score),
        "recommended_next_step": next_step_from_score(opportunity_score, has_perplexity, open_questions),
        "learning_feedback": {
            "prior_cases_count": learning_context.get("prior_cases_count", 0),
            "outcome_status_counts": learning_context.get("outcome_status_counts", {}),
        },
    }


def score_business_quality(recommendations: list[Recommendation]) -> int:
    values = numeric_values_from_recommendations(
        recommendations,
        ("quality", "moat", "business", "model", "selection", "rating", "evolution"),
    )
    if values:
        return clamp_score(sum(values) / len(values))
    directional = [
        rec.confidence
        for rec in recommendations
        if rec.direction in {Direction.LONG, Direction.WATCH}
    ]
    if directional:
        return clamp_score(sum(directional) / len(directional) - 5)
    return 50


def score_expectation_gap(
    recommendations: list[Recommendation],
    research_signal: ResearchSignal | None,
    combined_text: str,
) -> int:
    values = numeric_values_from_recommendations(
        recommendations,
        ("dislocation", "gap", "mispricing", "expectation", "odds", "bayesian"),
    )
    score = max(values) if values else 48
    if research_signal and research_signal.signal_type in {"mispricing", "bayesian_shift", "discontinuity"}:
        score = max(score, 72)
    marker_hits = count_markers(
        combined_text,
        ("预期差", "错定价", "mispricing", "non-consensus", "反共识", "未被定价", "边际变化"),
    )
    score += marker_hits * 6
    return clamp_score(score)


def score_valuation(recommendations: list[Recommendation], combined_text: str) -> int:
    values = numeric_values_from_recommendations(
        recommendations,
        ("valuation", "value", "odds", "margin", "safety", "估值", "安全边际"),
    )
    score = max(values) if values else 50
    score += count_markers(combined_text, ("估值", "回购", "valuation", "buyback", "reset")) * 5
    return clamp_score(score)


def score_catalyst(
    recommendations: list[Recommendation],
    research_signal: ResearchSignal | None,
    has_perplexity: bool,
    combined_text: str,
) -> int:
    catalyst_count = sum(len(as_list((rec.model_extra or {}).get("catalysts"))) for rec in recommendations)
    score = 48 + min(20, catalyst_count * 5)
    if research_signal and research_signal.research_stage in {"special_attention", "deep_research", "trade_ready"}:
        score += 8
    if has_perplexity:
        score += 8
    score += count_markers(combined_text, ("催化", "why now", "财报", "监管", "回购", "AI", "margin")) * 3
    return clamp_score(score)


def score_risk_pressure(
    recommendations: list[Recommendation],
    *,
    open_questions: list[str],
    historical_conflicts: list[str],
    escalation_items: list[dict[str, Any]],
) -> int:
    avoid_count = sum(1 for rec in recommendations if rec.direction == Direction.AVOID)
    abstain_count = sum(1 for rec in recommendations if rec.direction == Direction.ABSTAIN)
    hard_failures = sum(1 for rec in recommendations if rec.deployment_compliance.any_failure_must_abstain)
    high_escalations = sum(1 for item in escalation_items if item.get("priority") in {"critical", "high"})
    return clamp_score(
        32
        + avoid_count * 12
        + abstain_count * 6
        + hard_failures * 18
        + high_escalations * 14
        + min(18, len(open_questions) * 4)
        + min(20, len(historical_conflicts) * 7)
    )


def score_positioning(
    combined_text: str,
    consensus: dict[str, Any],
    similar_cases: list[dict[str, Any]],
) -> int:
    score = 48
    score += count_markers(
        combined_text,
        ("positioning", "crowded", "拥挤", "资金", "持仓", "无人关注", "情绪", "叙事"),
    ) * 6
    if str(consensus.get("consensus_level")) == "split_long_vs_avoid":
        score += 10
    if similar_cases:
        score += 4
    return clamp_score(score)


def score_investment_attractiveness(
    recommendations: list[Recommendation],
    *,
    expectation_gap_score: int,
    valuation_score: int,
    catalyst_score: int,
    risk_score: int,
) -> int:
    direction_scores = {
        Direction.LONG: 82,
        Direction.WATCH: 55,
        Direction.ABSTAIN: 42,
        Direction.AVOID: 20,
        Direction.SHORT: 25,
    }
    if recommendations:
        directional = sum(direction_scores[rec.direction] for rec in recommendations) / len(recommendations)
        confidence = sum(rec.confidence for rec in recommendations) / len(recommendations)
    else:
        directional = 45
        confidence = 45
    return clamp_score(
        directional * 0.35
        + confidence * 0.20
        + expectation_gap_score * 0.18
        + valuation_score * 0.14
        + catalyst_score * 0.13
        - max(0, risk_score - 55) * 0.25
    )


def classify_reason_types(
    *,
    expectation_gap_score: int,
    valuation_score: int,
    catalyst_score: int,
    business_quality_score: int,
    positioning_score: int,
    combined_text: str,
) -> list[str]:
    reasons: list[str] = []
    if expectation_gap_score >= 65:
        reasons.append("expectation_gap")
    if valuation_score >= 65:
        reasons.append("valuation_reset")
    if catalyst_score >= 65:
        reasons.append("catalyst_mispriced")
    if business_quality_score >= 68 and expectation_gap_score >= 58:
        reasons.append("quality_recovery")
    if positioning_score >= 65:
        reasons.append("positioning_extreme")
    if count_markers(combined_text, ("叙事", "narrative", "拐点", "shift")):
        reasons.append("narrative_shift")
    return reasons or ["needs_human_screening"]


def numeric_values_from_recommendations(
    recommendations: list[Recommendation],
    key_fragments: tuple[str, ...],
) -> list[float]:
    values: list[float] = []
    for rec in recommendations:
        payload = rec.model_dump(mode="json")
        values.extend(numeric_values(payload, key_fragments))
    return [value for value in values if 0 <= value <= 100]


def numeric_values(value: Any, key_fragments: tuple[str, ...], current_key: str = "") -> list[float]:
    matches: list[float] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            matches.extend(numeric_values(nested, key_fragments, str(key).lower()))
    elif isinstance(value, list):
        for item in value:
            matches.extend(numeric_values(item, key_fragments, current_key))
    elif isinstance(value, (int, float)) and any(fragment in current_key for fragment in key_fragments):
        matches.append(float(value))
    return matches


def collect_recommendation_texts(recommendations: list[Recommendation]) -> list[str]:
    texts: list[str] = []
    for rec in recommendations:
        extra = rec.model_extra or {}
        texts.append(str(rec.thesis or ""))
        texts.append(str(rec.one_liner_thesis or ""))
        for key in ("catalysts", "thesis_kill_criteria", "waiting_conditions", "analysis_gaps"):
            for item in as_list(extra.get(key)):
                texts.append(str(item))
    return [text for text in texts if text]


def as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value:
        return [value]
    return []


def count_markers(text: str, markers: tuple[str, ...]) -> int:
    lowered = text.lower()
    return sum(1 for marker in markers if marker.lower() in lowered)


def clamp_score(value: float) -> int:
    return max(0, min(100, round(value)))


def infer_time_horizon(recommendations: list[Recommendation]) -> str:
    for rec in recommendations:
        extra = rec.model_extra or {}
        for key in ("time_horizon", "holding_period", "investment_horizon"):
            if extra.get(key):
                return str(extra[key])
        if isinstance(getattr(rec, "time_box", None), dict):
            time_box = getattr(rec, "time_box")
            if time_box.get("max_wait"):
                return str(time_box["max_wait"])
    return "3-12 months"


def first_text_from_extras(recommendations: list[Recommendation], key: str) -> str:
    for rec in recommendations:
        for item in as_list((rec.model_extra or {}).get(key)):
            if isinstance(item, dict):
                text = item.get("text") or item.get("reason") or item.get("condition") or item.get("gap")
                if text:
                    return str(text)
            elif item:
                return str(item)
    return ""


def first_long_thesis(recommendations: list[Recommendation]) -> str:
    for rec in recommendations:
        if rec.direction == Direction.LONG and (rec.one_liner_thesis or rec.thesis):
            return str(rec.one_liner_thesis or rec.thesis)
    return ""


def first_avoid_thesis(recommendations: list[Recommendation]) -> str:
    for rec in recommendations:
        if rec.direction == Direction.AVOID and (rec.one_liner_thesis or rec.thesis):
            return str(rec.one_liner_thesis or rec.thesis)
    return ""


def first_non_empty(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def consensus_view_label(consensus: dict[str, Any]) -> str:
    level = str(consensus.get("consensus_level") or "other")
    mapping = {
        "full_consensus_long": "三位 Agent 已形成买入候选共识，需警惕是否只是主流共识复述。",
        "majority_long": "多数 Agent 支持机会，但仍有保留观点。",
        "split_long_vs_avoid": "Agent 明显分歧，可能是风险也可能是非共识机会来源。",
        "mixed_long_watch": "买入候选与观察混合，市场证据尚未完全闭环。",
        "full_consensus_avoid": "三位 Agent 一致回避，除非机会分异常高，否则不进入人工高优先级。",
        "majority_avoid": "多数 Agent 回避，机会假设需要更强反证。",
        "all_abstain": "全员暂不判断，当前主要任务是补证据。",
    }
    return mapping.get(level, f"共识类型为 {level}，需要人工判断其投资含义。")


def build_non_consensus_view(
    reason_type: list[str],
    recommendations: list[Recommendation],
    signal_text: str,
) -> str:
    reason_text = ", ".join(reason_type)
    thesis = first_long_thesis(recommendations) or signal_text
    if thesis:
        return f"潜在非共识点：{reason_text}；核心假设是 {thesis}"
    return f"潜在非共识点：{reason_text}；仍需补足可验证 thesis。"


def build_kill_conditions(
    recommendations: list[Recommendation],
    open_questions: list[str],
    historical_conflicts: list[str],
) -> list[str]:
    conditions: list[str] = []
    for rec in recommendations:
        for item in as_list((rec.model_extra or {}).get("thesis_kill_criteria")):
            conditions.append(str(item.get("condition") if isinstance(item, dict) else item))
    conditions.extend(str(item) for item in open_questions[:2])
    conditions.extend(str(item) for item in historical_conflicts[:2])
    if not conditions:
        conditions = [
            "核心催化剂无法被财报、监管文件、管理层电话会或主流媒体交叉验证。",
            "后续价格/基本面表现显示本次异动只是短期流动性或指数因素。",
        ]
    return dedupe_preserve_order(conditions)[:5]


def priority_from_score(score: int) -> str:
    if score >= 75:
        return "high"
    if score >= 55:
        return "medium"
    return "low"


def next_step_from_score(score: int, has_perplexity: bool, open_questions: list[str]) -> str:
    if score >= 75 and has_perplexity and not open_questions:
        return "human_ic_review"
    if score >= 55:
        return "deep_research" if not has_perplexity or open_questions else "paper_track"
    return "discard_or_wait_for_new_signal"


def build_human_decision_checklist(opportunity_screener: dict[str, Any]) -> list[str]:
    kill_conditions = opportunity_screener.get("kill_conditions") or []
    downside = opportunity_screener.get("downside_path") or "主要下行路径尚未写清。"
    return [
        f"非共识 thesis 是否真的不同于市场共识？{opportunity_screener.get('non_consensus_view', '')}",
        f"如果错了，最可能错在什么地方？{downside}",
        f"行动前必须人工确认的证伪条件：{kill_conditions[0] if kill_conditions else '暂无'}",
    ]


def dedupe_preserve_order(items: list[str]) -> list[str]:
    deduped: list[str] = []
    for item in items:
        text = " ".join(str(item or "").split())
        if text and text not in deduped:
            deduped.append(text)
    return deduped


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
    learning_context: dict[str, Any] | None = None,
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
    learning_context = learning_context or {}
    if learning_context.get("prior_cases_count"):
        adjustment += 2
    outcome_counts = learning_context.get("outcome_status_counts") or {}
    negative_outcomes = int(outcome_counts.get("price_against", 0)) + int(
        outcome_counts.get("requires_manual_review", 0)
    )
    if negative_outcomes:
        adjustment -= min(8, negative_outcomes * 2)
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
    learning_context: dict[str, Any] | None = None,
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
    chain.extend(build_learning_chain_notes(learning_context or {}))
    if disagreement.get("primary_type"):
        chain.append(f"主要分歧类型为 {disagreement.get('primary_type')}：{disagreement.get('narrative')}")
    if escalation_items:
        chain.append(f"已产生 {len(escalation_items)} 条 Red Team 待审事项，行动前需要先处理。")
    return chain


def build_learning_chain_notes(learning_context: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    prior_cases_count = int(learning_context.get("prior_cases_count") or 0)
    if prior_cases_count:
        notes.append(
            f"学习层找到 {prior_cases_count} 个该标的历史 decision case，最近一条是 "
            f"{learning_context.get('latest_case_id') or 'unknown'}。"
        )
    outcome_counts = learning_context.get("outcome_status_counts") or {}
    if outcome_counts:
        notes.append(f"历史 outcome snapshot 分布为 {outcome_counts}；价格结果只作复盘，不自动替代裁决。")
    for item in (learning_context.get("pattern_notes") or [])[:2]:
        notes.append(f"学习层提示：{item}")
    if not notes:
        notes.append("学习层暂无同标的历史 case；本次裁决会成为后续复盘样本。")
    return notes


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


def build_learning_memory(
    grouped: dict[tuple[str, str], list[Recommendation]],
    *,
    data_dir: str | Path | None,
    date: str,
) -> dict[str, Any]:
    """Load time-safe decision/outcome learning context for Chairman only."""

    if data_dir is None:
        return {}
    memory: dict[str, Any] = {}
    for ticker, _market in grouped:
        context = load_chairman_learning_context(data_dir, ticker, as_of_date=date)
        if context.get("prior_cases_count") or context.get("outcome_status_counts"):
            memory[ticker] = context
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


def build_operation_summary(
    recommendations: list[Recommendation],
    chairman_verdict: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build actionable operating guidance without proposing portfolio sizing."""

    chairman_verdict = chairman_verdict or {}
    rows = [build_operation_row(rec) for rec in recommendations]
    return {
        "rows": rows,
        "action_route": chairman_verdict.get("action_route") or "watchlist_monitor",
        "final_verdict": chairman_verdict.get("final_verdict") or "wait",
        "decision_required": any(row["nepha_decision_required"] for row in rows),
        "deployment_layer_compliance_aggregate": "passed"
        if all(not rec.deployment_compliance.any_failure_must_abstain for rec in recommendations)
        else "has_failure",
    }


def build_operation_row(rec: Recommendation) -> dict[str, Any]:
    """Translate one partner recommendation into Nepha-facing operating language."""

    return {
        "agent_id": rec.agent_id.value,
        "suggested_action": suggested_action_label(rec.direction.value),
        "reason": compact_cell(rec.one_liner_thesis or rec.thesis, fallback="未提供核心理由"),
        "waiting_condition": compact_cell(extract_waiting_condition(rec), fallback="等待下一轮公开证据或 Nepha 人工复核"),
        "risk_trigger": compact_cell(extract_risk_trigger(rec), fallback="核心 thesis 被公开数据证伪或 Red Team 升级为 block"),
        "nepha_decision_required": True,
        "nepha_decision_label": nepha_decision_label(rec.direction.value),
    }


def suggested_action_label(direction: str) -> str:
    mapping = {
        "long": "买入候选，需 Nepha 拍板",
        "watch": "继续观察，等待证据闭环",
        "avoid": "回避，降低优先级",
        "abstain": "暂不判断，补材料后再跑",
        "short": "反向风险提示，不执行交易",
    }
    return mapping.get(direction, "人工复核")


def nepha_decision_label(direction: str) -> str:
    mapping = {
        "long": "是，确认是否执行",
        "watch": "是，确认继续跟踪或补研究",
        "avoid": "是，确认是否移出观察",
        "abstain": "是，确认补资料后是否重跑",
        "short": "是，仅作风险判断",
    }
    return mapping.get(direction, "是，Nepha 最终拍板")


def extract_waiting_condition(rec: Recommendation) -> str:
    extra = rec.model_extra or {}
    candidates = first_non_empty_list_item(extra.get("analysis_gaps"))
    if candidates:
        return candidates
    if rec.direction == Direction.ABSTAIN and rec.abstain_reason:
        return f"先关闭 abstain 原因：{rec.abstain_reason}"
    if rec.direction == Direction.AVOID:
        return "除非出现新的公开证据推翻负面判断，否则不重启"
    if rec.direction == Direction.LONG:
        return "等待 Nepha 人工确认研究结论、风险触发器和执行窗口"
    return "等待未关闭问题、下一份 Perplexity 回填或新的财报/监管/资金证据"


def extract_risk_trigger(rec: Recommendation) -> str:
    extra = rec.model_extra or {}
    criteria = first_non_empty_list_item(extra.get("thesis_kill_criteria"))
    if criteria:
        return criteria
    if rec.direction == Direction.AVOID:
        return "负面 thesis 被证伪前维持回避"
    if rec.direction == Direction.ABSTAIN:
        return "关键证据继续缺失或互相矛盾"
    return "价格异动被证明只是指数/期权/短期流动性驱动，或核心催化剂无法被公开来源验证"


def first_non_empty_list_item(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    for item in value:
        if isinstance(item, dict):
            text = item.get("gap") or item.get("reason") or item.get("condition") or item.get("text")
            if text:
                return str(text)
        elif item:
            return str(item)
    return ""


def compact_cell(value: Any, *, fallback: str, limit: int = 130) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        return fallback
    return text if len(text) <= limit else f"{text[:limit - 1]}…"


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
