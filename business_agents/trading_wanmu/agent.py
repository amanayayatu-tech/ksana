"""Wanmu trading agent."""

from __future__ import annotations

from typing import Any

from business_agents._common.trading_agent import TradingAgent


class WanmuTradingAgent(TradingAgent):
    agent_name = "trading_wanmu"
    methodology_id = "wanmu_single_sided"
    agent_id = "wanmu_single_sided"
    output_dir_name = "wanmu"
    recommendation_prefix = "R-WM"

    def add_method_specific_fields(self, base: dict[str, Any]) -> dict[str, Any]:
        base["upstream_research_signals"][0]["mapped_to_three_models"] = {
            "long_term_value": False,
            "objective_change": True,
            "subjective_cognition_gap": False,
        }
        base["upstream_research_signals"][0]["contributes_to_collaborative_validation"] = True
        base.update(
            {
                "holding_period": "monthly",
                "permissions": {
                    "margin_allowed": False,
                    "put_allowed": False,
                    "short_allowed": False,
                    "hedging_allowed": False,
                },
                "wanmu_rating": {"star": 3, "grade": "C", "risk_color": "yellow"},
                "collaborative_validation": {
                    "independent_validators_count": 1,
                    "consensus_level": "single_source",
                    "validators_breakdown": {
                        "upstream_4_1_signals_counted": 1,
                        "upstream_4_1_signals_excluded": 0,
                        "coresearcher_validators": 0,
                        "independent_sellside_reports": 0,
                        "nepha_manual_validation": 0,
                        "nepha_manual_validation_entries": [],
                    },
                    "agreement_with_other_methodologies": [],
                    "dissent_notes": [],
                    "uniqueness_flag": False,
                },
                "three_selection": {"sector": "unknown", "leader_status": "unknown", "timing": "watch"},
                "three_models": {
                    "long_term_value": False,
                    "objective_change": True,
                    "subjective_cognition_gap": False,
                },
                "three_cuts": {"tam": None, "penetration": None, "competition": None},
                "three_rates": {"probability": None, "odds": None, "slope": None},
                "safety_margin": {
                    "fcf_ev": None,
                    "valuation_percentile_5y": None,
                    "implied_irr_2y": None,
                    "bayesian_confidence": None,
                    "alternative_path": "none",
                    "passed": False,
                },
                "perplexity_deep_research_requests": [],
            }
        )
        return base
