"""Configuration loading for Opportunity Screener scoring."""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any

import yaml


DEFAULT_SCORING_CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "orchestrator" / "config" / "opportunity_scoring.yaml"
)


@dataclass(frozen=True)
class OpportunityScoringConfig:
    expectation_gap: float = 0.24
    valuation: float = 0.18
    catalyst: float = 0.18
    investment_attractiveness: float = 0.22
    positioning: float = 0.10
    business_quality: float = 0.08
    risk_penalty_above: float = 55.0
    risk_penalty_weight: float = 0.18
    non_consensus_score_cap: int = 60
    min_why_market_wrong_items: int = 1
    min_why_market_wrong_text_length: int = 8


def load_opportunity_scoring_config(
    config_path: str | Path | None = None,
) -> OpportunityScoringConfig:
    """Load scoring weights, falling back field-by-field to safe defaults."""

    path = Path(config_path) if config_path else DEFAULT_SCORING_CONFIG_PATH
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, yaml.YAMLError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return opportunity_scoring_config_from_mapping(payload)


def opportunity_scoring_config_from_mapping(payload: dict[str, Any]) -> OpportunityScoringConfig:
    config = OpportunityScoringConfig()
    values: dict[str, Any] = {}
    known = {item.name for item in fields(OpportunityScoringConfig)}
    aliases = {
        "expectation_gap_weight": "expectation_gap",
        "valuation_weight": "valuation",
        "catalyst_weight": "catalyst",
        "investment_attractiveness_weight": "investment_attractiveness",
        "positioning_weight": "positioning",
        "business_quality_weight": "business_quality",
    }
    for raw_key, raw_value in payload.items():
        key = aliases.get(str(raw_key), str(raw_key))
        if key not in known:
            continue
        default = getattr(config, key)
        parsed = _coerce_number(raw_value, default)
        if key in {
            "non_consensus_score_cap",
            "min_why_market_wrong_items",
            "min_why_market_wrong_text_length",
        }:
            parsed = int(max(0, min(100, parsed)))
        values[key] = parsed
    return replace(config, **values)


def normalize_scoring_config(
    config: OpportunityScoringConfig | dict[str, Any] | None = None,
    *,
    config_path: str | Path | None = None,
) -> OpportunityScoringConfig:
    if isinstance(config, OpportunityScoringConfig):
        return config
    if isinstance(config, dict):
        return opportunity_scoring_config_from_mapping(config)
    return load_opportunity_scoring_config(config_path)


def _coerce_number(value: Any, default: float | int) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    if number < 0:
        return float(default)
    return number
