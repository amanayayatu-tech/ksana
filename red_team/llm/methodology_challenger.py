"""Generate method-specific Red Team challenge questions."""

from __future__ import annotations

import json
import logging
from typing import Any

from chairman.llm.narrative_generator import LLMClient, LLMError, LLMTimeout
from chairman.models import AgentId, Recommendation, ResearchSignal
from red_team.models import Challenge, MethodologyChallenge

logger = logging.getLogger(__name__)


def generate_challenges(
    recommendation: Recommendation,
    research_signal: ResearchSignal | None = None,
    llm_client: LLMClient | None = None,
    *,
    use_llm: bool = True,
) -> MethodologyChallenge:
    """Generate 1-3 audit questions for one recommendation."""

    if use_llm and llm_client is not None:
        try:
            text = llm_client.complete(
                system_prompt=build_system_prompt(),
                user_prompt=build_user_prompt(recommendation, research_signal),
                max_tokens=400,
                timeout_seconds=30,
                temperature=0.2,
            )
            challenges = parse_challenges(text)
            if challenges:
                return _challenge_set(recommendation, challenges, agent_response_required=True)
        except (LLMError, LLMTimeout) as exc:
            logger.warning("Red Team LLM challenge failed; using templates: %s", exc)

    return _challenge_set(
        recommendation,
        fallback_challenges(recommendation, research_signal),
        agent_response_required=_requires_response(recommendation),
    )


def build_system_prompt() -> str:
    """Strict Red Team challenge prompt."""

    return """
你是投资委员会的独立审计员（Red Team）。任务：针对一条交易建议提出 1-3 个最尖锐的质疑问题。

输出：1-3 条质疑，每条 ≤ 100 字，必须是疑问句。

严格规则：
1. 你不替 PM（Nepha）做决策
2. 你不预测未来
3. 不使用感叹号
4. 必须引用 recommendation 中的具体字段
5. 站在该方法论的对立面思考，但不否定方法论本身
"""


def build_user_prompt(
    recommendation: Recommendation,
    research_signal: ResearchSignal | None,
) -> str:
    """Build a compact structured prompt."""

    payload: dict[str, Any] = {
        "recommendation": recommendation.model_dump(mode="json"),
        "research_signal": research_signal.model_dump(mode="json") if research_signal else None,
    }
    return json.dumps(payload, ensure_ascii=False)


def parse_challenges(text: str) -> list[Challenge]:
    """Parse LLM output lines into questions."""

    challenges: list[Challenge] = []
    for raw_line in text.splitlines():
        line = raw_line.strip().lstrip("-0123456789.、) ")
        if not line:
            continue
        if not line.endswith(("?", "？")):
            line = f"{line}？"
        challenges.append(Challenge(text=line[:100], referenced_fields=[]))
        if len(challenges) == 3:
            break
    return challenges


def fallback_challenges(
    recommendation: Recommendation,
    research_signal: ResearchSignal | None = None,
) -> list[Challenge]:
    """Template challenge library for --no-llm and LLM failures."""

    agent_id = recommendation.agent_id
    if agent_id == AgentId.F_PARTNER:
        confidence = _field(recommendation, "f_partner_specific_framework", {}).get(
            "kill_type_confidence", "未填"
        )
        questions = [
            "thesis 中“负面已充分”的判断依据是哪个时点的市场情绪数据？是否可能负面仍在展开？",
            "关注度/购买度错配的购买度分位反向计算，是否考虑了资金流结构扭曲？",
            f"kill_type 判定的 confidence 是 {confidence}，距离 DEC-014 阈值 0.65 还有多远？",
        ]
    elif agent_id == AgentId.W_PARTNER:
        three_models = _field(recommendation, "three_models", {})
        hit_count = sum(1 for value in three_models.values() if value is True)
        questions = [
            f"三型命中了 {hit_count} 型，但每一型的 confidence 是否经过 ≥0.70 检验？",
            "核心问题压缩到 ≤3 个，被压缩掉的问题清单在哪？是否可审计？",
            "三率（概率/赔率/斜率）是否同时通过？任一未通过的话理由是什么？",
        ]
    elif agent_id == AgentId.G_PARTNER:
        moat = _field(recommendation, "moat_assessment", {})
        time_box = _field(recommendation, "time_box", {})
        questions = [
            f"subjective_win_rate_pct={moat.get('subjective_win_rate_pct', '未填')} 是否经过 95% 门槛的反向质疑？",
            "护城河、进化力、熵减力的判断有没有可量化支撑证据？",
            f"时间盒下一次到期是 {time_box.get('max_wait', '未填')}，到期时 posterior < 70% 是否能执行 reduce 或 exit？",
        ]
    else:
        posterior = research_signal.bayesian_update.get("posterior_minus_market_prior") if research_signal else "未填"
        questions = [
            "非连续变化的硬数据是否被独立第三方验证？",
            f"贝叶斯 posterior_minus_market_prior={posterior}%，市场先验怎么估的？",
            "证伪点在多长时间内可检测？如果无法证伪，这个信号是否应该 invalidate？",
        ]

    return [Challenge(text=q, referenced_fields=[]) for q in questions[:3]]


def _challenge_set(
    recommendation: Recommendation,
    challenges: list[Challenge],
    *,
    agent_response_required: bool,
) -> MethodologyChallenge:
    return MethodologyChallenge(
        recommendation_id=recommendation.recommendation_id,
        agent_id=recommendation.agent_id.value,
        ticker=recommendation.ticker,
        challenges=challenges[:3],
        agent_response_required=agent_response_required,
    )


def _requires_response(recommendation: Recommendation) -> bool:
    return recommendation.direction.value in {"long", "avoid"}


def _field(recommendation: Recommendation, name: str, default: Any) -> Any:
    return getattr(recommendation, name, default) or default
