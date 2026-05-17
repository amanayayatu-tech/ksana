"""Opportunity status routing for human-in-the-loop review."""

from __future__ import annotations

from typing import Any


def choose_opportunity_status(
    *,
    consensus_level: str,
    opportunity_score: int,
    has_perplexity: bool,
    pending_prompts: list[Any],
    open_questions_count: int,
    has_high_escalation: bool,
) -> str:
    """Map committee evidence into human-in-the-loop opportunity states."""

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
