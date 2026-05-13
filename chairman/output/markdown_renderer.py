"""Markdown rendering for Chairman briefs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape

from chairman.models import ChairmanBrief

TEMPLATE_DIR = Path(__file__).with_name("templates")


def render_markdown(brief: ChairmanBrief, template_name: str | None = None) -> str:
    """Render a Chairman brief to Markdown."""

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(enabled_extensions=()),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["trans"] = trans
    env.filters["to_yaml"] = to_yaml
    selected = template_name or (
        "evening_brief.md.j2" if brief.brief_type.value == "evening" else "morning_brief.md.j2"
    )
    template = env.get_template(selected)
    payload = brief.model_dump(mode="json")
    payload["time_zone_local"] = "Asia/Shanghai"
    payload["total_signals_today"] = payload["executive_summary"]["total_signals_today"]
    payload["total_recommendations"] = payload["executive_summary"]["total_recommendations"]
    payload["full_consensus_long"] = payload["executive_summary"]["full_consensus_long"]
    payload["full_consensus_avoid"] = payload["executive_summary"]["full_consensus_avoid"]
    payload["split_decisions"] = payload["executive_summary"]["split_decisions"]
    payload["red_team_high_priority"] = payload["executive_summary"]["red_team_high_priority"]
    payload["abstain_with_high_signals"] = payload["executive_summary"]["abstain_with_high_signals"]
    payload["perplexity_prompts_pending"] = payload["executive_summary"][
        "perplexity_prompts_pending"
    ]
    payload["pending_prompts"] = []
    return template.render(**payload)


def trans(value: Any) -> str:
    """Small translation filter for enums and status strings."""

    mapping = {
        "morning": "早盘",
        "evening": "晚盘",
        "ad_hoc": "临时",
        "full_consensus_long": "三方一致 long",
        "full_consensus_avoid": "三方一致 avoid",
        "majority_long": "多数 long",
        "majority_avoid": "多数 avoid",
        "split_long_vs_avoid": "long / avoid 分歧",
        "mixed_long_watch": "long / watch 混合",
        "mostly_abstain": "多数 abstain",
        "all_abstain": "全员 abstain",
        "methodology_dna": "方法论 DNA 差异",
        "data_input_difference": "数据输入差异",
        "upstream_signal_consumption": "上游信号采纳差异",
        "evidence_unverified_propagation": "未验证证据传播",
        "potential_agent_error": "潜在 Agent 错误",
        "passed": "通过",
        "has_failure": "存在硬规则失败",
        "not_applicable": "不适用",
    }
    return mapping.get(str(value), str(value))


def to_yaml(value: Any) -> str:
    """YAML dump filter for fallback-style appendices."""

    return yaml.safe_dump(value, allow_unicode=True, sort_keys=False).strip()
