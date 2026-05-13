"""Liguofei trading agent."""

from __future__ import annotations

from typing import Any

from chairman.models import ResearchSignal
from business_agents._common.perplexity_results import PerplexityContext
from business_agents._common.trading_agent import TradingAgent, extract_signal_features


class LiguofeiTradingAgent(TradingAgent):
    agent_name = "trading_liguofei"
    methodology_id = "liguofei_zen_value"
    agent_id = "liguofei_zen_value"
    output_dir_name = "liguofei"
    recommendation_prefix = "R-LF"

    def add_method_specific_fields(
        self,
        base: dict[str, Any],
        signal: ResearchSignal,
        context: PerplexityContext,
    ) -> dict[str, Any]:
        features = extract_signal_features(signal)
        trigger_count = features["trigger_count"]
        has_causal_fill = context.has_filled_results
        subjective_win_rate = 52 + trigger_count * 3 + (6 if has_causal_fill else 0)
        posterior_confidence = 45 + trigger_count * 4 + (8 if has_causal_fill else 0)
        not_passed = []
        if subjective_win_rate < 95:
            not_passed.append("主观胜率低于 95% 门槛")
        if posterior_confidence < 70:
            not_passed.append("贝叶斯后验低于 70% 门槛")
        if not has_causal_fill:
            not_passed.append("缺 Perplexity 因果回填")
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
            "evolution_power_change": has_causal_fill and trigger_count >= 2,
            "entropy_reduction_change": False,
            "not_passed_reasons": not_passed,
        }
        base.update(
            {
                "time_horizon": "event-driven",
                "moat_assessment": {
                    "subjective_win_rate_pct": min(subjective_win_rate, 80),
                    "moat_sources": [],
                    "pricing_power_evidence": [],
                    "moat_narrowing_risks": [],
                    "not_passed_reason": "公开价量信号不能证明护城河变化。",
                },
                "evolution_power": {
                    "connector_score": min(65, 35 + trigger_count * 8 + (8 if has_causal_fill else 0)),
                    "data_dimensions": ["public_price_volume"] + (["manual_causal_research"] if has_causal_fill else []),
                    "emergent_businesses": [],
                    "not_passed_reason": "缺业务进化证据，不能穿过 95%/70% 双门槛。",
                },
                "entropy_reduction": {
                    "leadership_will": 30 if has_causal_fill else 0,
                    "org_vitality_evidence": [],
                    "resource_concentration_evidence": [],
                    "not_passed_reason": "没有组织和资源集中证据。",
                },
                "bayesian_update": {
                    "prior_view": "unknown",
                    "new_evidence": "4.1 public price-volume signal"
                    + (" plus manual Perplexity fill" if has_causal_fill else " pending manual fill"),
                    "posterior_change": "neutral",
                    "action": "wait",
                    "posterior_confidence": min(posterior_confidence, 80),
                    "not_passed_reasons": not_passed,
                },
                "margin_of_safety": {
                    "fcf_ev_yield": None,
                    "valuation_percentile_5y": None,
                    "implied_2y_irr": None,
                    "posterior_confidence": min(posterior_confidence, 80),
                    "growth_exception": {"type": "none"},
                    "passed": False,
                    "not_passed_reason": "缺估值与现金流数据，且试运行期禁用 long。",
                },
                "time_box": {
                    "catalyst_type": "weekly",
                    "max_wait": "7d",
                    "due_action": "review",
                    "posterior_confidence_at_review": min(posterior_confidence, 80),
                    "not_passed_reasons": not_passed,
                },
                "portfolio_drawdown_guard": {
                    "current_mdd": None,
                    "trigger_level": "none",
                    "forced_action": None,
                },
                "key_point_data": [],
                "red_team": {
                    "strongest_bear_case": "价量异动可能只是公开数据噪声或指数/资金面扰动。",
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
                "not_passed_reasons": not_passed,
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
                    "win_rate_subjective": min(subjective_win_rate, 80),
                    "posterior_confidence": min(posterior_confidence, 80),
                    "win_rate_95_passed": False,
                    "bayesian_70_passed": False,
                    "both_passed": False,
                    "consistency": "both_failed",
                    "gap_explanation": "；".join(not_passed),
                },
            }
        )
        return base
