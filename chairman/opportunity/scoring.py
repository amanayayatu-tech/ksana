"""Opportunity Screener sub-scores and weighted score calculation."""

from __future__ import annotations

from typing import Any

from chairman.models import Direction, Recommendation, ResearchSignal
from chairman.opportunity.config import OpportunityScoringConfig
from chairman.opportunity.utils import as_list, clamp_score, count_markers


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


def calculate_opportunity_score(
    *,
    expectation_gap_score: int,
    valuation_score: int,
    catalyst_score: int,
    investment_attractiveness_score: int,
    positioning_score: int,
    business_quality_score: int,
    risk_score: int,
    config: OpportunityScoringConfig,
) -> int:
    return clamp_score(
        expectation_gap_score * config.expectation_gap
        + valuation_score * config.valuation
        + catalyst_score * config.catalyst
        + investment_attractiveness_score * config.investment_attractiveness
        + positioning_score * config.positioning
        + business_quality_score * config.business_quality
        - max(0, risk_score - config.risk_penalty_above) * config.risk_penalty_weight
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
