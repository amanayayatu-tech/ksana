"""Non-consensus thesis construction and validation."""

from __future__ import annotations

from typing import Any

from chairman.models import Recommendation
from chairman.opportunity.config import OpportunityScoringConfig
from chairman.opportunity.utils import as_list, dedupe_preserve_order, first_long_thesis

MARKET_WRONG_MARKERS = (
    "市场可能",
    "市场或许",
    "未被定价",
    "错定价",
    "忽视",
    "低估",
    "高估",
    "预期差",
    "consensus",
    "mispricing",
    "underestimate",
    "overestimate",
    "overlook",
    "wrong",
)


def consensus_view_label(consensus: dict[str, Any]) -> str:
    level = str(consensus.get("consensus_level") or "other")
    mapping = {
        "full_consensus_long": "三位 Agent 已形成买入候选共识，需警惕是否只是主流共识复述。",
        "majority_long": "多数 Agent 支持机会，但仍有保留观点。",
        "split_long_vs_avoid": "Agent 明显分歧，可能是风险也可能是非共识机会来源。",
        "mixed_long_watch": "买入候选与观察混合，市场证据尚未完全闭环。",
        "full_consensus_avoid": "三位 Agent 一致回避，除非机会分异常高，否则不进入人工高优先级。",
        "majority_avoid": "多数 Agent 回避，机会假设需要更强反证。",
        "all_abstain": "全员暂不判断，当前主要任务是补证据。",
    }
    return mapping.get(level, f"共识类型为 {level}，需要人工判断其投资含义。")


def build_non_consensus_view(
    reason_type: list[str],
    recommendations: list[Recommendation],
    signal_text: str,
) -> str:
    reason_text = ", ".join(reason_type)
    thesis = first_long_thesis(recommendations) or signal_text
    if thesis:
        return f"潜在非共识点：{reason_text}；核心假设是 {thesis}"
    return f"潜在非共识点：{reason_text}；仍需补足可验证 thesis。"


def build_why_market_might_be_wrong(
    *,
    reason_type: list[str],
    recommendations: list[Recommendation],
    signal_text: str,
) -> list[str]:
    explicit = collect_explicit_market_wrong_reasons(recommendations)
    if explicit:
        return explicit[:5]

    thesis = first_long_thesis(recommendations) or signal_text
    if not thesis:
        return []

    reasons: list[str] = []
    reason_set = set(reason_type)
    if "expectation_gap" in reason_set:
        reasons.append(f"市场可能尚未把预期差计入价格：{thesis}")
    if "valuation_reset" in reason_set:
        reasons.append("市场可能把短期估值压力外推过久，忽视估值重估或回购带来的赔率变化。")
    if "catalyst_mispriced" in reason_set:
        reasons.append("市场可能低估了催化剂兑现速度或公开证据之间的相互验证。")
    if "positioning_extreme" in reason_set:
        reasons.append("市场可能把拥挤交易或极端情绪误读为基本面结论。")
    if "quality_recovery" in reason_set:
        reasons.append("市场可能低估了商业质量修复对后续盈利和叙事的影响。")
    if not reasons and "needs_human_screening" not in reason_set:
        reasons.append(f"市场可能没有充分解释该信号背后的非共识假设：{thesis}")
    return dedupe_preserve_order(reasons)[:5]


def collect_explicit_market_wrong_reasons(recommendations: list[Recommendation]) -> list[str]:
    keys = (
        "why_market_might_be_wrong",
        "market_wrong_reasons",
        "non_consensus_evidence",
        "consensus_misread",
    )
    reasons: list[str] = []
    for rec in recommendations:
        extra = rec.model_extra or {}
        for key in keys:
            for item in as_list(extra.get(key)):
                if isinstance(item, dict):
                    text = item.get("text") or item.get("reason") or item.get("evidence")
                else:
                    text = item
                if text:
                    reasons.append(str(text))
    return dedupe_preserve_order(reasons)


def assess_non_consensus_quality(
    *,
    why_market_might_be_wrong: list[str],
    consensus_view: str,
    non_consensus_view: str,
    config: OpportunityScoringConfig,
) -> dict[str, Any]:
    valid_items = [
        item
        for item in why_market_might_be_wrong
        if is_valid_market_wrong_reason(
            item,
            consensus_view=consensus_view,
            non_consensus_view=non_consensus_view,
            min_length=config.min_why_market_wrong_text_length,
        )
    ]
    is_valid = len(valid_items) >= config.min_why_market_wrong_items
    return {
        "is_valid": is_valid,
        "valid_items_count": len(valid_items),
        "required_items_count": config.min_why_market_wrong_items,
        "score_cap": config.non_consensus_score_cap if not is_valid else None,
        "reason": "" if is_valid else "why_market_might_be_wrong 缺失、过短或只是复述共识。",
    }


def is_valid_market_wrong_reason(
    item: str,
    *,
    consensus_view: str,
    non_consensus_view: str,
    min_length: int,
) -> bool:
    text = " ".join(str(item or "").split())
    if len(text) < min_length:
        return False
    if text == " ".join(consensus_view.split()) or text == " ".join(non_consensus_view.split()):
        return False
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in MARKET_WRONG_MARKERS)
