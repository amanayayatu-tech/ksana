"""Markdown rendering for Chairman briefs."""

from __future__ import annotations

from pathlib import Path
import re
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
    env.filters["advice_label"] = advice_label
    env.filters["advice_text"] = advice_text
    env.filters["table_cell"] = table_cell
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
        "full_consensus_long": "三方一致买入候选",
        "full_consensus_avoid": "三方一致回避",
        "majority_long": "多数买入候选",
        "majority_avoid": "多数回避",
        "split_long_vs_avoid": "买入候选 / 回避分歧",
        "mixed_long_watch": "买入候选 / 观察混合",
        "mostly_abstain": "多数暂不判断",
        "all_abstain": "全员暂不判断",
        "act": "行动候选",
        "wait": "等待观察",
        "reject": "否决",
        "research_more": "补充研究",
        "watchlist_monitor": "观察名单跟踪",
        "drop_or_require_new_signal": "移出或等待新信号",
        "run_or_update_perplexity_research": "补充/更新 Perplexity 研究",
        "trial_position_candidate_after_nepha_review": "Nepha 复核后的行动候选",
        "send_to_red_team_before_action": "行动前先交 Red Team",
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


def advice_label(value: Any) -> str:
    """Human-facing investment recommendation label for internal direction enums."""

    mapping = {
        "long": "买入候选",
        "short": "反向风险",
        "watch": "观察",
        "avoid": "回避",
        "abstain": "暂不判断",
    }
    return mapping.get(str(value), str(value))


def advice_text(value: Any) -> str:
    """Translate internal direction terms inside free-form report text."""

    text = str(value or "")
    replacements = [
        ("第一阶段禁止输出 long/short/leverage/put/hedge", "当前不展示杠杆、衍生品或内部方向标签"),
        ("第一阶段禁止 long/short/leverage/put/hedge", "当前不展示杠杆、衍生品或内部方向标签"),
        ("long/short/leverage/put/hedge", "买入候选/反向风险/杠杆/期权/对冲"),
        ("第一阶段 long 禁用", "证据闭环不足，暂不升级为买入候选"),
        ("第一阶段禁止 long", "证据闭环不足，暂不升级为买入候选"),
        ("禁止 long", "禁止直接给出买入候选"),
        ("不能升级为 long", "不能升级为买入候选"),
        ("输出 long", "输出买入候选"),
        ("只能保守 watch", "只能保守观察"),
        ("只能输出 watch", "只能输出观察"),
        ("只能 watch", "只能观察"),
        ("更保守的 abstain", "更保守的暂不判断"),
        ("维持 watch 或 abstain", "维持观察或暂不判断"),
        ("watch 或 abstain", "观察或暂不判断"),
    ]
    for old, new in replacements:
        text = text.replace(old, new)
    direction_labels = {"long": "买入候选", "short": "反向风险", "watch": "观察", "avoid": "回避", "abstain": "暂不判断"}
    text = re.sub(
        r"\b(direction|selected_direction|final_direction|action)=("
        r"long|short|watch|avoid|abstain)\b",
        lambda match: f"{match.group(1)}={direction_labels[match.group(2)]}",
        text,
    )
    return text


def table_cell(value: Any) -> str:
    """Escape Markdown table separators inside generated cell text."""

    text = str(value or "")
    text = " ".join(text.split())
    return text.replace("|", r"\|")


def to_yaml(value: Any) -> str:
    """YAML dump filter for fallback-style appendices."""

    return yaml.safe_dump(value, allow_unicode=True, sort_keys=False).strip()
