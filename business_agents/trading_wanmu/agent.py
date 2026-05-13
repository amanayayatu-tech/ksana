"""Wanmu trading agent."""

from __future__ import annotations

from typing import Any

from chairman.models import ResearchSignal
from business_agents._common.perplexity_results import PerplexityContext
from business_agents._common.trading_agent import TradingAgent, extract_signal_features


class WanmuTradingAgent(TradingAgent):
    agent_name = "trading_wanmu"
    methodology_id = "wanmu_single_sided"
    agent_id = "wanmu_single_sided"
    output_dir_name = "wanmu"
    recommendation_prefix = "R-WM"

    def add_method_specific_fields(
        self,
        base: dict[str, Any],
        signal: ResearchSignal,
        context: PerplexityContext,
    ) -> dict[str, Any]:
        features = extract_signal_features(signal)
        trigger_count = features["trigger_count"]
        has_causal_fill = context.has_filled_results
        three_models = {
            "long_term_value": False,
            "objective_change": trigger_count > 0,
            "subjective_cognition_gap": has_causal_fill,
        }
        missing_items = []
        if not has_causal_fill:
            missing_items.append("缺主观认知差因果回填")
        if not signal.data_points:
            missing_items.append("缺价量 data_points")
        if not has_causal_fill:
            missing_items.extend(["缺 TAM 刀", "缺竞争刀", "缺概率/赔率/斜率三率"])
        base["upstream_research_signals"][0]["mapped_to_three_models"] = {
            **three_models,
            "missing_items": missing_items,
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
                "wanmu_rating": {
                    "star": 3 if has_causal_fill else 2,
                    "grade": "C" if has_causal_fill else "D",
                    "risk_color": "yellow" if has_causal_fill else "red",
                    "why": "仍缺完整三刀三率，试运行期不升级。",
                },
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
                "three_models": three_models,
                "three_cuts": {
                    "tam": None,
                    "penetration": "price_volume_trigger_only" if trigger_count else None,
                    "competition": None,
                    "missing": [item for item in missing_items if "刀" in item],
                },
                "three_rates": {
                    "probability": min(60, 35 + trigger_count * 5 + (8 if has_causal_fill else 0)),
                    "odds": min(65, 35 + trigger_count * 6),
                    "slope": None if not has_causal_fill else "needs_manual_quantification",
                    "missing": [item for item in missing_items if "率" in item],
                },
                "safety_margin": {
                    "fcf_ev": None,
                    "valuation_percentile_5y": None,
                    "implied_irr_2y": None,
                    "bayesian_confidence": 45 + trigger_count * 4 if has_causal_fill else None,
                    "alternative_path": "none",
                    "passed": False,
                    "not_passed_reason": "三刀三率数据不足，且试运行期禁用 long。",
                },
                "methodology_gaps": missing_items,
                "perplexity_deep_research_requests": [],
            }
        )
        return base
