"""Pydantic validation plus business constraints for business-agent outputs."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from chairman.core.input_validator import validate_recommendation
from chairman.models import Recommendation, ResearchSignal
from business_agents._common.stock_pool import StockPool


class PerplexityPrompt(BaseModel):
    model_config = ConfigDict(extra="allow")

    prompt_id: str
    related_signal_id: str | list[str] | None = None
    priority: str = "P1"
    prompt_text: str = ""
    research_question_set: dict[str, Any] = Field(default_factory=dict)


class PerplexityPromptBrief(BaseModel):
    brief_id: str
    prompts: list[PerplexityPrompt] = Field(default_factory=list)


class ResearchAgentResult(BaseModel):
    research_signals: list[ResearchSignal] = Field(default_factory=list)
    perplexity_prompt_brief: PerplexityPromptBrief


class OutputValidationError(Exception):
    """Structured output validation error."""


class OutputValidator:
    """Retry wrapper around strict Pydantic/business validation."""

    def __init__(self, max_retries: int = 2) -> None:
        self.max_retries = max_retries
        self.attempts = 0
        self.errors: list[str] = []

    def validate_with_retry(self, producer, validator, fallback_factory):
        """Call producer until validator accepts output, then fallback after max retries."""

        for _ in range(self.max_retries + 1):
            self.attempts += 1
            try:
                return validator(producer())
            except Exception as exc:
                self.errors.append(str(exc))
        return validator(fallback_factory(self.errors))


def parse_json_payload(text: str) -> dict[str, Any]:
    """Parse strict JSON, including accidental fenced JSON."""

    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        stripped = stripped.removeprefix("json").strip()
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise OutputValidationError(f"invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise OutputValidationError("JSON root must be object")
    return payload


def validate_research_agent_output(payload: str | dict[str, Any], stock_pool: StockPool) -> ResearchAgentResult:
    """Validate K deep research-agent output and stock-pool constraints."""

    data = parse_json_payload(payload) if isinstance(payload, str) else payload
    try:
        result = ResearchAgentResult.model_validate(data)
    except ValidationError as exc:
        raise OutputValidationError(str(exc)) from exc
    _validate_research_constraints(result, stock_pool)
    return result


def validate_trading_recommendation_output(
    payload: str | dict[str, Any],
    *,
    agent_id: str,
    stock_pool: StockPool,
) -> Recommendation:
    """Validate trading recommendation output and hard business constraints."""

    data = parse_json_payload(payload) if isinstance(payload, str) else payload
    try:
        rec = validate_recommendation(data, agent_hint=agent_id)
    except Exception as exc:
        raise OutputValidationError(str(exc)) from exc
    _validate_recommendation_constraints(rec, stock_pool)
    return rec


def _validate_research_constraints(result: ResearchAgentResult, stock_pool: StockPool) -> None:
    allowed = stock_pool.all_allowed_research_tickers()
    a_shares = stock_pool.a_share_tickers()
    for signal in result.research_signals:
        if not signal.routing_recommendation:
            raise OutputValidationError("research_signal.routing_recommendation is required")
        for target in signal.candidate_targets:
            if target.ticker not in allowed:
                raise OutputValidationError(f"ticker outside stock_pool: {target.ticker}")
            if target.ticker in a_shares:
                raise OutputValidationError(f"A-share ticker blocked from research signal output: {target.ticker}")
        if signal.signal_type == "abstain" and not getattr(signal, "abstain_reason", None):
            raise OutputValidationError("signal_type=abstain requires abstain_reason")


def _validate_recommendation_constraints(rec: Recommendation, stock_pool: StockPool) -> None:
    if rec.ticker not in stock_pool.trading_tickers() and rec.ticker not in stock_pool.watchlist_tickers():
        raise OutputValidationError(f"trading recommendation ticker outside tradable stock_pool: {rec.ticker}")
    if rec.ticker in stock_pool.a_share_tickers():
        raise OutputValidationError(f"A-share ticker blocked from trading recommendation: {rec.ticker}")
    if rec.ticker in stock_pool.watchlist_tickers() and rec.direction.value not in {"watch", "abstain"}:
        raise OutputValidationError("watchlist ticker may only output watch or abstain")
    if rec.deployment_compliance.any_failure_must_abstain and rec.direction.value != "abstain":
        raise OutputValidationError("deployment_compliance failure must force abstain")
    if any(s.evidence_unverified_inherited for s in rec.upstream_research_signals) and rec.confidence > 70:
        raise OutputValidationError("evidence_unverified_inherited caps confidence at 70")
