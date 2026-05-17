"""Opportunity Memo scoring and routing helpers."""

from chairman.opportunity.config import OpportunityScoringConfig, load_opportunity_scoring_config
from chairman.opportunity.non_consensus import (
    build_non_consensus_view,
    build_why_market_might_be_wrong,
)
from chairman.opportunity.scoring import (
    classify_reason_types,
    clamp_score,
    score_business_quality,
    score_catalyst,
    score_expectation_gap,
    score_investment_attractiveness,
    score_positioning,
    score_risk_pressure,
)
from chairman.opportunity.screener import build_human_decision_checklist, build_opportunity_screener
from chairman.opportunity.status_router import (
    action_route_for_opportunity_status,
    choose_opportunity_status,
)

__all__ = [
    "OpportunityScoringConfig",
    "action_route_for_opportunity_status",
    "build_human_decision_checklist",
    "build_non_consensus_view",
    "build_opportunity_screener",
    "build_why_market_might_be_wrong",
    "choose_opportunity_status",
    "classify_reason_types",
    "clamp_score",
    "load_opportunity_scoring_config",
    "score_business_quality",
    "score_catalyst",
    "score_expectation_gap",
    "score_investment_attractiveness",
    "score_positioning",
    "score_risk_pressure",
]
