"""Cold-start historical research planning for new tickers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader

from business_agents._common.llm_client import LLMClient
from business_agents.research_agent.methodology_profile import build_gate_question_groups

VALID_DIMENSIONS = (
    "business_model",
    "industry_structure",
    "competitive_position",
    "capital_market_expectation",
    "regulatory_environment",
)
DIMENSION_LABELS = {
    "business_model": "商业模式",
    "industry_structure": "行业结构",
    "competitive_position": "竞争格局",
    "capital_market_expectation": "资本市场预期差",
    "regulatory_environment": "监管环境",
}
VALID_HORIZONS = {"6m", "9m", "12m"}
MIN_COLD_START_PROMPTS = 3
MAX_COLD_START_PROMPTS = 5


def build_cold_start_prompts(
    ticker: str,
    name: str,
    market: str,
    triggers: list[dict[str, Any]],
    features: dict[str, Any],
    llm_client: LLMClient | None,
    *,
    trace_messages: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Ask an LLM to create 6-12 month historical research prompts for a new ticker."""

    if llm_client is None:
        return []

    env = Environment(
        loader=FileSystemLoader(str(Path(__file__).with_name("prompts"))),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    gate_constraints = build_gate_question_groups(
        {
            "ticker": ticker,
            "name": name,
            "display_name": f"{ticker} {name}".strip(),
            "trigger_rule_text": "、".join(trigger.get("rule", "") for trigger in triggers),
            "event_date": features.get("latest_date"),
            "latest_close": features.get("latest_close"),
            "five_day_change_pct": features.get("five_day_change_pct"),
            "ten_day_change_pct": features.get("ten_day_change_pct"),
            "max_volume_ratio": features.get("max_volume_ratio"),
        }
    )
    system_prompt = env.get_template("cold_start_system_prompt.j2").render()
    user_prompt = env.get_template("cold_start_user_prompt.j2").render(
        ticker=ticker,
        company_name=name,
        market=market,
        trigger_rules_yaml=yaml.safe_dump(triggers, allow_unicode=True, sort_keys=False).strip(),
        price_features_yaml=yaml.safe_dump(features, allow_unicode=True, sort_keys=False).strip(),
        gate_constraints_yaml=yaml.safe_dump(gate_constraints, allow_unicode=True, sort_keys=False).strip(),
        dimensions_yaml=yaml.safe_dump(DIMENSION_LABELS, allow_unicode=True, sort_keys=False).strip(),
    )
    if trace_messages is not None:
        trace_messages.extend(
            [
                {"role": "system", "content": system_prompt, "purpose": "cold_start_research_planning"},
                {"role": "user", "content": user_prompt, "purpose": "cold_start_research_planning"},
            ]
        )
    try:
        text = llm_client.complete(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=3200,
            timeout_seconds=180,
            temperature=0.2,
        )
    except Exception:
        return build_fallback_cold_start_prompts(
            ticker,
            name,
            generation_source="fallback_template_after_llm_error",
        )
    try:
        payload = parse_json_object(text)
        prompts = normalize_cold_start_prompts(
            payload.get("cold_start_prompts"),
            ticker=ticker,
            name=name,
        )
    except (json.JSONDecodeError, ValueError):
        prompts = build_fallback_cold_start_prompts(
            ticker,
            name,
            generation_source="fallback_template_after_llm_parse_error",
        )
    return prompts[:MAX_COLD_START_PROMPTS]


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse strict JSON while tolerating accidental fenced JSON."""

    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        stripped = stripped.removeprefix("json").strip()
    data = json.loads(stripped)
    if not isinstance(data, dict):
        raise ValueError("cold-start LLM output must be a JSON object")
    return data


def normalize_cold_start_prompts(
    raw_items: Any,
    *,
    ticker: str,
    name: str,
) -> list[dict[str, Any]]:
    """Normalize LLM output to a stable PR-compatible schema."""

    if not isinstance(raw_items, list):
        raise ValueError("cold_start_prompts must be a list")

    normalized: list[dict[str, Any]] = []
    used_dimensions: set[str] = set()
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        dimension = normalize_dimension(item.get("research_dimension"))
        if not dimension or dimension in used_dimensions:
            continue
        prompt_text = str(item.get("prompt_text") or "").strip()
        if not prompt_text:
            prompt_text = template_prompt(ticker, name, dimension, str(item.get("research_horizon") or "12m"))
        priority_order = normalize_priority_order(item.get("priority_order"), len(normalized) + 1)
        horizon = normalize_horizon(item.get("research_horizon"), dimension)
        normalized.append(
            {
                "cold_start": True,
                "research_horizon": horizon,
                "research_dimension": dimension,
                "research_dimension_label": DIMENSION_LABELS[dimension],
                "priority_order": priority_order,
                "title": str(item.get("title") or DIMENSION_LABELS[dimension]).strip()[:120],
                "cold_start_rationale": str(item.get("cold_start_rationale") or item.get("rationale") or "").strip(),
                "prompt_text": prompt_text,
                "generation_source": "llm_cold_start_planner",
            }
        )
        used_dimensions.add(dimension)
        if len(normalized) >= MAX_COLD_START_PROMPTS:
            break

    if len(normalized) < MIN_COLD_START_PROMPTS:
        normalized.extend(
            fallback_prompts(
                ticker=ticker,
                name=name,
                start_priority=len(normalized) + 1,
                used_dimensions=used_dimensions,
            )
        )
    return resequence(normalized[:MAX_COLD_START_PROMPTS])


def normalize_dimension(value: Any) -> str:
    text = str(value or "").strip()
    return text if text in VALID_DIMENSIONS else ""


def normalize_horizon(value: Any, dimension: str) -> str:
    text = str(value or "").strip().lower()
    if text in VALID_HORIZONS:
        return text
    return "12m" if dimension in {"business_model", "capital_market_expectation"} else "6m"


def normalize_priority_order(value: Any, fallback: int) -> int:
    try:
        order = int(value)
    except (TypeError, ValueError):
        order = fallback
    return max(1, min(MAX_COLD_START_PROMPTS, order))


def resequence(prompts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    prompts = sorted(prompts, key=lambda item: int(item.get("priority_order") or 99))
    for index, prompt in enumerate(prompts, start=1):
        prompt["priority_order"] = index
    return prompts


def fallback_prompts(
    *,
    ticker: str,
    name: str,
    start_priority: int,
    used_dimensions: set[str],
) -> list[dict[str, Any]]:
    prompts: list[dict[str, Any]] = []
    for dimension in ("business_model", "competitive_position", "capital_market_expectation"):
        if dimension in used_dimensions:
            continue
        horizon = "12m" if dimension in {"business_model", "capital_market_expectation"} else "6m"
        prompts.append(
            {
                "cold_start": True,
                "research_horizon": horizon,
                "research_dimension": dimension,
                "research_dimension_label": DIMENSION_LABELS[dimension],
                "priority_order": start_priority + len(prompts),
                "title": DIMENSION_LABELS[dimension],
                "cold_start_rationale": "LLM 输出少于 3 条时的兜底补足，确保新股票至少完成基本面、竞争和预期差三类历史补课。",
                "prompt_text": template_prompt(ticker, name, dimension, horizon),
                "generation_source": "fallback_template_after_llm",
            }
        )
        if start_priority + len(prompts) > MIN_COLD_START_PROMPTS:
            break
    return prompts


def build_fallback_cold_start_prompts(
    ticker: str,
    name: str,
    *,
    generation_source: str,
) -> list[dict[str, Any]]:
    prompts = fallback_prompts(
        ticker=ticker,
        name=name,
        start_priority=1,
        used_dimensions=set(),
    )
    for prompt in prompts:
        prompt["generation_source"] = generation_source
    return resequence(prompts[:MAX_COLD_START_PROMPTS])


def template_prompt(ticker: str, name: str, dimension: str, horizon: str) -> str:
    display_name = f"{ticker} {name}".strip()
    if dimension == "business_model":
        return (
            f"请研究 {display_name} 过去 {horizon} 的核心收入结构、主要业务线增长、毛利率和经营杠杆变化。"
            "请提供至少 3 个可验证的财报、公告或公司材料来源，判断这些结构性变化是否已经被市场充分定价。"
        )
    if dimension == "competitive_position":
        return (
            f"请研究 {display_name} 所在细分市场过去 {horizon} 的竞争格局变化：新进入者、核心竞品产品/定价动作、"
            "市场份额拐点、并购或融资时间线，并判断公司的护城河是在强化还是被削弱。"
        )
    if dimension == "capital_market_expectation":
        return (
            f"请研究 {display_name} 过去 {horizon} 的资本市场预期差：卖方 EPS/评级/目标价修正、机构持仓变化、"
            "主流叙事是否过于一致，以及哪些公开反证可能颠覆共识。"
        )
    if dimension == "industry_structure":
        return (
            f"请研究 {display_name} 所在行业过去 {horizon} 的需求、供给、成本曲线、渗透率和定价权变化，"
            "并判断行业结构是否正在改变公司的中长期胜率。"
        )
    return (
        f"请研究 {display_name} 过去 {horizon} 的监管、政策、诉讼或合规环境变化，"
        "列出关键事件时间线、官方来源和对收入/利润/估值叙事的影响。"
    )
