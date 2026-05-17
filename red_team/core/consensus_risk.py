"""Detect when LLM-driven recommendations collapse into market consensus."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from chairman.models import Recommendation

STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "this",
    "that",
    "from",
    "into",
    "because",
    "company",
    "market",
    "stock",
    "price",
    "research",
    "report",
    "watch",
    "avoid",
    "long",
    "风险",
    "公司",
    "市场",
    "研究",
    "报告",
    "判断",
    "需要",
    "因为",
    "如果",
    "已经",
}

NON_CONSENSUS_MARKERS = {
    "mispricing",
    "variant",
    "non-consensus",
    "反共识",
    "预期差",
    "错定价",
    "边际变化",
    "反证",
    "无人关注",
    "未被定价",
}


def assess_consensus_risk(
    ticker: str,
    recommendations: list[Recommendation],
    verdict: dict[str, Any],
    knowledge: dict[str, Any],
) -> dict[str, Any]:
    """Score whether the committee view is too close to known/common narratives."""

    partner_texts = [recommendation_text(rec) for rec in recommendations]
    knowledge_text = knowledge_reference_text(knowledge)
    partner_tokens = [tokenize(text) for text in partner_texts]
    knowledge_tokens = tokenize(knowledge_text)
    overlap_scores = [
        overlap_ratio(tokens, knowledge_tokens) for tokens in partner_tokens if tokens and knowledge_tokens
    ]
    shared_partner_terms = shared_terms(partner_tokens)
    same_direction = len({rec.direction.value for rec in recommendations}) <= 1 and len(recommendations) >= 2
    final_verdict = str(verdict.get("final_verdict") or "unknown")
    avg_overlap = round(sum(overlap_scores) / len(overlap_scores), 4) if overlap_scores else 0.0
    marker_hits = sorted(
        marker for marker in NON_CONSENSUS_MARKERS if marker.lower() in "\n".join(partner_texts).lower()
    )

    score = 20
    if same_direction:
        score += 20
    if final_verdict in {"act", "trial_candidate", "conviction_candidate"}:
        score += 15
    if avg_overlap >= 0.35:
        score += 25
    elif avg_overlap >= 0.2:
        score += 12
    if len(shared_partner_terms) >= 5:
        score += 12
    if marker_hits:
        score -= min(18, len(marker_hits) * 6)
    if knowledge.get("historical_conflicts") or knowledge.get("open_questions"):
        score += 8
    score = max(0, min(100, score))

    if score >= 70:
        level = "high"
    elif score >= 45:
        level = "medium"
    else:
        level = "low"

    return {
        "ticker": ticker,
        "risk_level": level,
        "score": score,
        "average_overlap_with_perplexity_memory": avg_overlap,
        "same_direction_cluster": same_direction,
        "shared_partner_terms": shared_partner_terms[:12],
        "non_consensus_marker_hits": marker_hits,
        "reason": build_reason(level, avg_overlap, same_direction, marker_hits),
        "required_questions": build_required_questions(ticker, level),
    }


def recommendation_text(rec: Recommendation) -> str:
    extra = rec.model_extra or {}
    pieces = [
        rec.thesis,
        rec.one_liner_thesis,
        " ".join(str(item) for item in extra.get("catalysts", []) or []),
        " ".join(str(item) for item in extra.get("thesis_kill_criteria", []) or []),
    ]
    return "\n".join(str(piece) for piece in pieces if piece)


def knowledge_reference_text(knowledge: dict[str, Any]) -> str:
    pieces: list[str] = []
    for entry in (knowledge.get("entries") or [])[:3]:
        for key in ("event_summary", "company_conclusions", "industry_conclusions", "primary_catalysts"):
            value = entry.get(key)
            if isinstance(value, list):
                pieces.extend(str(item) for item in value)
            elif value:
                pieces.append(str(value))
    return "\n".join(pieces)


def tokenize(text: str) -> set[str]:
    tokens = {
        token.lower()
        for token in re.findall(r"[A-Za-z0-9_]{3,}|[\u4e00-\u9fff]{2,}", text or "")
        if token.lower() not in STOPWORDS
    }
    return tokens


def overlap_ratio(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return round(len(left & right) / max(1, min(len(left), len(right))), 4)


def shared_terms(token_sets: list[set[str]]) -> list[str]:
    counter: Counter[str] = Counter()
    for tokens in token_sets:
        counter.update(tokens)
    threshold = max(2, len(token_sets))
    return [token for token, count in counter.most_common() if count >= threshold]


def build_reason(level: str, avg_overlap: float, same_direction: bool, marker_hits: list[str]) -> str:
    pieces = []
    if same_direction:
        pieces.append("三位 partner 方向高度一致")
    if avg_overlap:
        pieces.append(f"与历史/Perplexity 记忆重合度 {avg_overlap}")
    if not marker_hits:
        pieces.append("缺少明确反共识或错定价表述")
    if level == "low":
        return "未发现明显共识化塌缩；仍需保留反证追问。"
    return "；".join(pieces) or "存在共识化风险。"


def build_required_questions(ticker: str, level: str) -> list[str]:
    questions = [
        f"{ticker} 的当前结论是否只是主流新闻/Perplexity 报告复述，还是存在未被价格充分反映的变量？",
        "三位 partner 是否独立提出了不同于公开叙事的可验证 edge？",
        "如果所有人都知道这个催化剂，为什么市场还会错定价？",
    ]
    if level == "high":
        questions.append("行动前必须补充至少一条反共识证据或解释为什么共识仍未被定价。")
    return questions
