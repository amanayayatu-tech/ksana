"""Liguofei trading agent."""

from __future__ import annotations

from typing import Any

from business_agents._common.trading_agent import TradingAgent


class LiguofeiTradingAgent(TradingAgent):
    agent_name = "trading_liguofei"
    methodology_id = "liguofei_zen_value"
    agent_id = "liguofei_zen_value"
    output_dir_name = "liguofei"
    recommendation_prefix = "R-LF"

    def add_method_specific_fields(self, base: dict[str, Any]) -> dict[str, Any]:
        base["action"] = "watch"
        base["one_liner_thesis"] = base["thesis"]
        base["current_price"] = None
        base["valuation_metric"] = {
            "primary": "other",
            "current_value": None,
            "historical_range": None,
            "implied_market_assumptions": None,
        }
        base["upstream_research_signals"][0]["mapped_to_three_powers"] = {
            "moat_change": False,
            "evolution_power_change": False,
            "entropy_reduction_change": False,
        }
        base.update(
            {
                "time_horizon": "event-driven",
                "moat_assessment": {
                    "subjective_win_rate_pct": 0,
                    "moat_sources": [],
                    "pricing_power_evidence": [],
                    "moat_narrowing_risks": [],
                },
                "evolution_power": {
                    "connector_score": 0,
                    "data_dimensions": [],
                    "emergent_businesses": [],
                },
                "entropy_reduction": {
                    "leadership_will": 0,
                    "org_vitality_evidence": [],
                    "resource_concentration_evidence": [],
                },
                "bayesian_update": {
                    "prior_view": "unknown",
                    "new_evidence": "4.1 signal pending validation",
                    "posterior_change": "neutral",
                    "action": "wait",
                },
                "margin_of_safety": {
                    "fcf_ev_yield": None,
                    "valuation_percentile_5y": None,
                    "implied_2y_irr": None,
                    "posterior_confidence": None,
                    "growth_exception": {"type": "none"},
                    "passed": False,
                },
                "time_box": {
                    "catalyst_type": "weekly",
                    "max_wait": "7d",
                    "due_action": "review",
                    "posterior_confidence_at_review": 0,
                },
                "portfolio_drawdown_guard": {
                    "current_mdd": None,
                    "trigger_level": "none",
                    "forced_action": None,
                },
                "key_point_data": [],
                "red_team": {
                    "strongest_bear_case": "证据未回填，不能建立高确定性判断。",
                    "what_would_change_my_mind": "Nepha 手动研究回填高质量证据。",
                },
                "perplexity_deep_research_requests": [],
                "kill_log": {"triggered": False, "reason": None},
            }
        )
        base["deployment_compliance"].update(
            {
                "negative_fcf_alternative_passed": "not_applicable",
                "negative_fcf_threshold_used": "rNPV/EV >= 1.5",
                "win_rate_95_passed": False,
                "bayesian_70_passed": False,
                "bayesian_80_passed": "not_applicable",
                "dual_gate_consistency": "both_failed",
            }
        )
        base["authority_resolution"].update(
            {
                "r5_time_box_resolution": {
                    "time_box_expired": False,
                    "decision": "re_thesis",
                    "posterior_confidence_at_review": 0,
                    "reduce_to_position_size_pct": None,
                },
                "r6_false_stop_loss_review_triggered": False,
                "r6_review_details": {},
                "r7_dual_gate_status": {
                    "win_rate_subjective": 0,
                    "posterior_confidence": 0,
                    "win_rate_95_passed": False,
                    "bayesian_70_passed": False,
                    "both_passed": False,
                    "consistency": "both_failed",
                    "gap_explanation": "debug watch output",
                },
            }
        )
        return base
