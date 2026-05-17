"""Opportunity Screener payload assembly."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from chairman.models import Recommendation, ResearchSignal
from chairman.opportunity.config import OpportunityScoringConfig, normalize_scoring_config
from chairman.opportunity.non_consensus import (
    assess_non_consensus_quality,
    build_non_consensus_view,
    build_why_market_might_be_wrong,
    consensus_view_label,
)
from chairman.opportunity.scoring import (
    calculate_opportunity_score,
    classify_reason_types,
    score_business_quality,
    score_catalyst,
    score_expectation_gap,
    score_investment_attractiveness,
    score_positioning,
    score_risk_pressure,
    score_valuation,
)
from chairman.opportunity.utils import (
    as_list,
    collect_recommendation_texts,
    dedupe_preserve_order,
    first_avoid_thesis,
    first_long_thesis,
    first_non_empty,
    first_text_from_extras,
    infer_time_horizon,
)


def build_opportunity_screener(
    recommendations: list[Recommendation],
    consensus: dict[str, Any],
    historical_knowledge: dict[str, Any],
    research_signal: ResearchSignal | None,
    escalation_items: list[dict[str, Any]],
    learning_context: dict[str, Any] | None = None,
    scoring_config: OpportunityScoringConfig | dict[str, Any] | None = None,
    scoring_config_path: str | Path | None = None,
) -> dict[str, Any]:
    """Score whether a ticker deserves human research time before final judgment."""

    config = normalize_scoring_config(scoring_config, config_path=scoring_config_path)
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
    raw_opportunity_score = calculate_opportunity_score(
        expectation_gap_score=expectation_gap_score,
        valuation_score=valuation_score,
        catalyst_score=catalyst_score,
        investment_attractiveness_score=investment_attractiveness_score,
        positioning_score=positioning_score,
        business_quality_score=business_quality_score,
        risk_score=risk_score,
        config=config,
    )
    reason_type = classify_reason_types(
        expectation_gap_score=expectation_gap_score,
        valuation_score=valuation_score,
        catalyst_score=catalyst_score,
        business_quality_score=business_quality_score,
        positioning_score=positioning_score,
        combined_text=combined_text,
    )
    consensus_view = consensus_view_label(consensus)
    non_consensus_view = build_non_consensus_view(reason_type, recommendations, signal_text)
    why_market_might_be_wrong = build_why_market_might_be_wrong(
        reason_type=reason_type,
        recommendations=recommendations,
        signal_text=signal_text,
    )
    non_consensus_quality = assess_non_consensus_quality(
        why_market_might_be_wrong=why_market_might_be_wrong,
        consensus_view=consensus_view,
        non_consensus_view=non_consensus_view,
        config=config,
    )
    opportunity_score = raw_opportunity_score
    if not non_consensus_quality["is_valid"]:
        opportunity_score = min(opportunity_score, config.non_consensus_score_cap)

    return {
        "ticker": recommendations[0].ticker if recommendations else "",
        "opportunity_score": opportunity_score,
        "raw_opportunity_score": raw_opportunity_score,
        "reason_type": reason_type,
        "business_quality_score": business_quality_score,
        "investment_attractiveness_score": investment_attractiveness_score,
        "expectation_gap_score": expectation_gap_score,
        "valuation_score": valuation_score,
        "catalyst_score": catalyst_score,
        "risk_score": risk_score,
        "risk_pressure_score": risk_score,
        "positioning_score": positioning_score,
        "time_horizon": infer_time_horizon(recommendations),
        "why_now": first_non_empty(
            signal_text,
            first_text_from_extras(recommendations, "catalysts"),
            first_long_thesis(recommendations),
            "当前异动需要先验证是否存在预期差或催化错配。",
        ),
        "consensus_view": consensus_view,
        "non_consensus_view": non_consensus_view,
        "why_market_might_be_wrong": why_market_might_be_wrong,
        "non_consensus_quality": {
            **non_consensus_quality,
            "score_cap_applied": opportunity_score != raw_opportunity_score,
        },
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
        "scoring_config": {
            "expectation_gap": config.expectation_gap,
            "valuation": config.valuation,
            "catalyst": config.catalyst,
            "investment_attractiveness": config.investment_attractiveness,
            "positioning": config.positioning,
            "business_quality": config.business_quality,
            "risk_penalty_above": config.risk_penalty_above,
            "risk_penalty_weight": config.risk_penalty_weight,
            "non_consensus_score_cap": config.non_consensus_score_cap,
        },
        "learning_feedback": {
            "prior_cases_count": learning_context.get("prior_cases_count", 0),
            "outcome_status_counts": learning_context.get("outcome_status_counts", {}),
        },
    }


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
    market_wrong = opportunity_screener.get("why_market_might_be_wrong") or []
    first_market_wrong = market_wrong[0] if market_wrong else "暂无，需要先补足市场可能错在哪里。"
    return [
        f"非共识 thesis 是否真的不同于市场共识？{opportunity_screener.get('non_consensus_view', '')}",
        f"市场可能错在哪里？{first_market_wrong}",
        f"如果错了，最可能错在什么地方？{downside}",
        f"行动前必须人工确认的证伪条件：{kill_conditions[0] if kill_conditions else '暂无'}",
    ]
