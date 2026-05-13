"""Markdown renderer for Red Team audits."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape

from red_team.models import RedTeamAudit

TEMPLATE_DIR = Path(__file__).with_name("templates")


def render_markdown(audit: RedTeamAudit, template_name: str | None = None) -> str:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(enabled_extensions=()),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["trans"] = trans
    env.filters["to_yaml"] = to_yaml
    template = env.get_template(template_name or "audit_morning.md.j2")
    payload = audit.model_dump(mode="json")
    payload.update(payload["executive_summary"])
    return template.render(**payload)


def trans(value: Any) -> str:
    mapping = {
        "morning": "早盘",
        "evening": "晚盘",
        "ad_hoc": "临时",
        "escalation_response": "升级响应",
        "industry_concentration": "行业集中度隐性超限",
        "shared_upstream_signal": "上游信号集中依赖",
        "liquidity_drift": "流动性恶化漂移",
        "near_event_missing_catalyst": "近期公司事件未纳入 catalyst",
        "hk_us_session_mismatch": "港美股交易时段错配",
    }
    return mapping.get(str(value), str(value))


def to_yaml(value: Any) -> str:
    return yaml.safe_dump(value, allow_unicode=True, sort_keys=False).strip()
