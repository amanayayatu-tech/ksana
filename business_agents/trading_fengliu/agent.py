"""Fengliu trading agent."""

from __future__ import annotations

from typing import Any

from business_agents._common.trading_agent import TradingAgent


class FengliuTradingAgent(TradingAgent):
    agent_name = "trading_fengliu"
    methodology_id = "fengliu_reverse_odds"
    agent_id = "fengliu_reverse_odds"
    output_dir_name = "fengliu"
    recommendation_prefix = "R-FL"

    def add_method_specific_fields(self, base: dict[str, Any]) -> dict[str, Any]:
        base.update(
            {
                "strategy_layer": "tracking",
                "circle_status": "semi_insider",
                "current_market_logic": {
                    "bullish_logic": [],
                    "bearish_logic": [],
                    "dominant_side": "unknown",
                    "reflected_in_price": "unknown",
                },
                "odds_probability": {
                    "odds_score_0_100": 50,
                    "probability_score_0_100": 50,
                    "why_odds_first": "证据未回填，暂不升级。",
                },
                "kill_type": "unknown",
                "attention_purchase_mispricing": {
                    "attention_percentile": None,
                    "purchase_percentile": None,
                    "dislocation_score": 50,
                    "deep_research_eligible": True,
                },
                "perplexity_deep_research_requests": [],
                "fengliu_specific_framework": {
                    "note": "冯柳 Agent 不使用通用四重安全边际框架。",
                    "odds_score": 50,
                    "probability_score": 50,
                    "dislocation_score": 50,
                    "odds_first_rule_passed": False,
                    "kill_type_heuristic_verdict": "mixed_or_uncertain",
                    "kill_type_confidence": 50,
                },
            }
        )
        return base
