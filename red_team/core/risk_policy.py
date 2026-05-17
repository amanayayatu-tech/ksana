"""Configurable Red Team risk-budget policy."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

DEFAULT_RISK_POLICY_PATH = (
    Path(__file__).resolve().parents[2] / "orchestrator" / "config" / "risk_budget_policy.yaml"
)

DEFAULT_RISK_POLICY: dict[str, Any] = {
    "statuses": {
        "discard": {
            "risk_budget_allowed_pct": 0.0,
            "max_initial_position_pct": 0.0,
            "budget_scope": "not_eligible_for_position",
        },
        "research_priority": {
            "risk_budget_allowed_pct": 0.0,
            "max_initial_position_pct": 0.0,
            "budget_scope": "deep_research_only",
        },
        "watch": {
            "risk_budget_allowed_pct": 0.0,
            "max_initial_position_pct": 0.0,
            "budget_scope": "watchlist_or_paper_tracking_only",
        },
        "human_override_required": {
            "risk_budget_allowed_pct": 0.5,
            "max_initial_position_pct": 0.25,
            "budget_scope": "human_override_only",
        },
    },
    "red_team_verdicts": {
        "challenge": {
            "risk_budget_allowed_pct": 0.5,
            "max_initial_position_pct": 0.25,
            "budget_scope": "paper_trade_or_human_approved_tracking_position",
        },
        "monitor": {
            "risk_budget_allowed_pct": 1.0,
            "max_initial_position_pct": 0.5,
            "budget_scope": "paper_trade_or_human_approved_tracking_position",
        },
        "no_major_objection": {
            "risk_budget_allowed_pct": 1.5,
            "max_initial_position_pct": 0.75,
            "budget_scope": "paper_trade_or_human_approved_tracking_position",
        },
    },
    "conviction_candidate_no_major_objection": {
        "risk_budget_allowed_pct": 2.0,
        "max_initial_position_pct": 1.0,
        "budget_scope": "paper_trade_or_human_approved_tracking_position",
    },
    "fatal_flaw": {
        "risk_budget_allowed_pct": 0.0,
        "max_initial_position_pct": 0.0,
        "budget_scope": "blocked_by_fatal_flaw",
    },
    "high_consensus_risk_cap": {
        "risk_budget_allowed_pct": 0.5,
        "max_initial_position_pct": 0.25,
    },
    "must_not_buy_if": [
        "核心财务数据或关键催化无法确认",
        "管理层指引、监管文件或财报电话会与 thesis 明显相反",
    ],
    "position_requires": [
        "记录人工决策理由",
        "设置复查日期",
        "跟踪至少两个 kill indicators",
    ],
}


def load_risk_budget_policy(config_path: str | Path | None = None) -> dict[str, Any]:
    """Load risk-budget policy, falling back safely on missing or invalid config."""

    path = Path(config_path) if config_path else DEFAULT_RISK_POLICY_PATH
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, yaml.YAMLError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return merge_risk_budget_policy(payload)


def merge_risk_budget_policy(payload: dict[str, Any]) -> dict[str, Any]:
    policy = deepcopy(DEFAULT_RISK_POLICY)
    for section in (
        "statuses",
        "red_team_verdicts",
        "conviction_candidate_no_major_objection",
        "fatal_flaw",
        "high_consensus_risk_cap",
    ):
        if isinstance(payload.get(section), dict):
            policy[section] = _deep_merge_budget_section(policy[section], payload[section])
    for list_key in ("must_not_buy_if", "position_requires"):
        if isinstance(payload.get(list_key), list) and payload[list_key]:
            policy[list_key] = [str(item) for item in payload[list_key] if item]
    return policy


def resolve_budget_rule(
    *,
    final_verdict: str,
    red_team_verdict: str,
    fatal_flaw: bool,
    policy: dict[str, Any],
) -> dict[str, Any]:
    if fatal_flaw:
        rule = dict((policy.get("fatal_flaw") or DEFAULT_RISK_POLICY["fatal_flaw"]))
        rule["risk_budget_allowed_pct"] = 0.0
        rule["max_initial_position_pct"] = 0.0
        return rule
    status_rule = (policy.get("statuses") or {}).get(final_verdict)
    if status_rule:
        return dict(status_rule)
    if final_verdict == "conviction_candidate" and red_team_verdict == "no_major_objection":
        return dict(policy["conviction_candidate_no_major_objection"])
    verdict_rule = (policy.get("red_team_verdicts") or {}).get(red_team_verdict)
    if verdict_rule:
        return dict(verdict_rule)
    return dict((policy.get("red_team_verdicts") or {}).get("no_major_objection") or {})


def _deep_merge_budget_section(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_budget_section(merged[key], value)
        elif key in {"risk_budget_allowed_pct", "max_initial_position_pct"}:
            merged[key] = _coerce_non_negative_number(value, merged.get(key, 0.0))
        elif key == "budget_scope" and value:
            merged[key] = str(value)
        elif key not in {"risk_budget_allowed_pct", "max_initial_position_pct", "budget_scope"}:
            merged[key] = value
    return merged


def _coerce_non_negative_number(value: Any, default: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    if number < 0:
        return float(default)
    return number
