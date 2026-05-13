"""LLM-assisted disagreement narrative generation.

This is the only Chairman module allowed to call a language model. Core modules
stay deterministic and auditable.
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from typing import Any

from dotenv import load_dotenv

from chairman.models import DisagreementAnalysis, DisagreementType, Recommendation

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """Language-model call failed."""


class LLMTimeout(LLMError):
    """Language-model call timed out."""


class LLMClient(ABC):
    """Minimal narrative-generation client interface."""

    @abstractmethod
    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        timeout_seconds: int,
        temperature: float,
    ) -> str:
        """Return a text completion."""


class OpenAIClient(LLMClient):
    """OpenAI implementation using environment-provided credentials."""

    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        load_dotenv()
        self.model = model or os.getenv("LLM_MODEL", "gpt-5.5")
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise LLMError("OPENAI_API_KEY is not set")

    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        timeout_seconds: int,
        temperature: float,
    ) -> str:
        """Call OpenAI through the official Python client."""

        try:
            from openai import OpenAI
        except Exception as exc:  # pragma: no cover - depends on local install
            raise LLMError(f"openai package unavailable: {exc}") from exc

        try:
            client = OpenAI(api_key=self.api_key, timeout=timeout_seconds)
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return response.choices[0].message.content or ""
        except TimeoutError as exc:  # pragma: no cover - network path
            raise LLMTimeout(str(exc)) from exc
        except Exception as exc:  # pragma: no cover - network path
            raise LLMError(str(exc)) from exc


class AnthropicClient(LLMClient):
    """Anthropic placeholder behind the same interface."""

    def complete(self, **_: Any) -> str:
        raise LLMError("AnthropicClient is not configured in Chairman v0.1")


class LocalClient(LLMClient):
    """Local model placeholder behind the same interface."""

    def complete(self, **_: Any) -> str:
        raise LLMError("LocalClient is not configured in Chairman v0.1")


def build_llm_client_from_env() -> LLMClient:
    """Build an LLM client from .env settings."""

    load_dotenv()
    provider = os.getenv("LLM_PROVIDER", "openai").lower()
    model = os.getenv("LLM_MODEL", "gpt-5.5")
    if provider == "openai":
        return OpenAIClient(model=model)
    if provider == "anthropic":
        return AnthropicClient()
    if provider == "local":
        return LocalClient()
    raise LLMError(f"unsupported LLM_PROVIDER={provider!r}")


def generate_disagreement_narrative(
    recommendations: list[Recommendation],
    disagreement: DisagreementAnalysis,
    llm_client: LLMClient | None = None,
    *,
    use_llm: bool = True,
) -> str:
    """Generate a concise Chinese narrative, with template fallback on any LLM failure."""

    if not use_llm or llm_client is None:
        return template_narrative(disagreement, recommendations)

    try:
        narrative = llm_client.complete(
            system_prompt=build_system_prompt(),
            user_prompt=build_user_prompt(disagreement, recommendations),
            max_tokens=300,
            timeout_seconds=30,
            temperature=0.3,
        )
        return sanitize_narrative(narrative)
    except (LLMTimeout, LLMError) as exc:
        logger.warning("LLM narrative failed; using template narrative: %s", exc)
        return template_narrative(disagreement, recommendations)


def build_system_prompt() -> str:
    """Prompt that confines the LLM to Chief-of-Staff narrative duties."""

    return """
你是投资委员会的 Chief of Staff。任务：用 1-2 段中文（≤200字）描述
3 个分析师 Agent 在某标的上的分歧。

严格规则：
1. 只描述事实，不评价对错
2. 不替任何 Agent 表态
3. 不替 PM（Nepha）做决策
4. 不引用具体数字，除非数字出现在输入中
5. 必须区分“方法论 DNA 差异”和“可能的错误”
6. 输出语言：简体中文，专业但简洁

禁止：
- 不要说“我建议”、“应该”、“最好”
- 不要预测未来
- 不要使用感叹号
- 不要超过 200 字
"""


def build_user_prompt(disagreement: DisagreementAnalysis, recommendations: list[Recommendation]) -> str:
    """Build a compact structured prompt from already-classified data."""

    views = [
        {
            "agent_id": rec.agent_id.value,
            "direction": rec.direction.value,
            "confidence": rec.confidence,
            "thesis": rec.one_liner_thesis or rec.thesis,
        }
        for rec in recommendations
    ]
    return (
        f"disagreement_type={disagreement.primary_type}\n"
        f"red_team_escalation_required={disagreement.red_team_escalation_required}\n"
        f"views={views}"
    )


def template_narrative(
    disagreement: DisagreementAnalysis,
    recommendations: list[Recommendation],
) -> str:
    """Deterministic narrative used by --no-llm and LLM failure fallback."""

    if disagreement.primary_type is None:
        return disagreement.narrative

    agent_labels = ", ".join(f"{rec.agent_id.value}:{rec.direction.value}" for rec in recommendations)
    if disagreement.primary_type == DisagreementType.METHODOLOGY_DNA:
        return f"3 个 Agent 的分歧来源是方法论 DNA 差异：{agent_labels}。这是设计内分歧，不是错误。"
    if disagreement.primary_type == DisagreementType.EVIDENCE_UNVERIFIED_PROPAGATION:
        return "部分 Agent 继承了未验证上游证据，相关权重已按 DEC-004 自动降为 0.7。"
    if disagreement.primary_type == DisagreementType.UPSTREAM_SIGNAL_CONSUMPTION:
        return "Agent 对同一 4.1 研究信号的采纳结论不同，差异已保留给 Nepha 对照。"
    if disagreement.primary_type == DisagreementType.DATA_INPUT_DIFFERENCE:
        return "Agent 使用的数据时效存在明显差异，已标记给 Red Team 核实。"
    if disagreement.primary_type == DisagreementType.POTENTIAL_AGENT_ERROR:
        return "有 Agent 触发异常状态，已强制升级给 Red Team 复核。"
    return disagreement.narrative


def sanitize_narrative(text: str) -> str:
    """Defensively clean LLM output to keep the Chief-of-Staff tone."""

    cleaned = " ".join(text.strip().split())
    for banned in ("我建议", "应该", "最好", "！", "!"):
        cleaned = cleaned.replace(banned, "")
    return cleaned[:200]
