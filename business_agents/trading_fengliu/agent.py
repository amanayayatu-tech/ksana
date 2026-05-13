"""Fengliu trading agent."""

from __future__ import annotations

from typing import Any

from chairman.models import ResearchSignal
from business_agents._common.perplexity_results import PerplexityContext
from business_agents._common.trading_agent import TradingAgent, extract_signal_features


class FengliuTradingAgent(TradingAgent):
    agent_name = "trading_fengliu"
    methodology_id = "fengliu_reverse_odds"
    agent_id = "fengliu_reverse_odds"
    output_dir_name = "fengliu"
    recommendation_prefix = "R-FL"

    def add_method_specific_fields(
        self,
        base: dict[str, Any],
        signal: ResearchSignal,
        context: PerplexityContext,
    ) -> dict[str, Any]:
        features = extract_signal_features(signal)
        trigger_count = features["trigger_count"]
        latest_change = float(features["latest_change_pct"] or 0)
        volume_ratio = float(features["volume_ratio"] or 0)
        odds_score = min(78, 38 + trigger_count * 8 + (10 if volume_ratio >= 2 else 0))
        probability_score = min(70, 35 + trigger_count * 5 + (12 if context.has_filled_results else 0))
        dislocation_score = min(75, 40 + abs(latest_change) * 2 + (8 if volume_ratio >= 2 else 0))
        kill_type = infer_kill_type(latest_change, features["trigger_rules"], context)
        base.update(
            {
                "strategy_layer": "tracking",
                "circle_status": "semi_insider" if context.has_filled_results else "outsider",
                "current_market_logic": {
                    "bullish_logic": ["price_volume_reversal_candidate"] if latest_change > 0 else [],
                    "bearish_logic": ["price_volume_pressure_candidate"] if latest_change < 0 else [],
                    "dominant_side": "bullish" if latest_change > 0 else "bearish" if latest_change < 0 else "unknown",
                    "reflected_in_price": "public_price_volume_only",
                },
                "odds_probability": {
                    "odds_score_0_100": odds_score,
                    "probability_score_0_100": probability_score,
                    "why_odds_first": "只用公开价量初筛估算赔率，缺事件因果时不能升级。",
                },
                "kill_type": kill_type,
                "attention_purchase_mispricing": {
                    "attention_percentile": min(90, 50 + trigger_count * 10),
                    "purchase_percentile": None,
                    "dislocation_score": dislocation_score,
                    "deep_research_eligible": not context.has_filled_results,
                },
                "perplexity_deep_research_requests": [],
                "fengliu_specific_framework": {
                    "note": "冯柳 Agent 不使用通用四重安全边际框架。",
                    "odds_score": odds_score,
                    "probability_score": probability_score,
                    "dislocation_score": dislocation_score,
                    "odds_first_rule_passed": False,
                    "kill_type_heuristic_verdict": kill_type,
                    "kill_type_confidence": min(70, 35 + trigger_count * 8),
                    "why_not_long": "试运行期禁用 long；且缺手工因果验证。" if not context.has_filled_results else "试运行期禁用 long。",
                },
            }
        )
        return base


def infer_kill_type(latest_change: float, rules: list[str], context: PerplexityContext) -> str:
    if latest_change <= -7:
        return "performance_kill_candidate"
    if latest_change >= 7 and context.has_filled_results:
        return "valuation_kill_reversal_candidate"
    if any("volume" in rule for rule in rules):
        return "attention_purchase_dislocation"
    return "mixed_or_uncertain"
