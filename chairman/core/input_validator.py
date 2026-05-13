"""Schema loading and validation for Chairman inputs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from chairman.models import (
    AgentId,
    FengliuRecommendation,
    LiguofeiRecommendation,
    Recommendation,
    ResearchSignal,
    ValidationResult,
    WanmuRecommendation,
    format_validation_error,
)

AGENT_CLASS_BY_ID = {
    AgentId.FENGLIU.value: FengliuRecommendation,
    AgentId.WANMU.value: WanmuRecommendation,
    AgentId.LIGUOFEI.value: LiguofeiRecommendation,
}

AGENT_ID_BY_PATH_PART = {
    "fengliu": AgentId.FENGLIU.value,
    "wanmu": AgentId.WANMU.value,
    "liguofei": AgentId.LIGUOFEI.value,
}


class InputValidationError(Exception):
    """Readable validation exception used by CLI and fallback."""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def load_yaml_file(path: str | Path) -> dict[str, Any]:
    """Load a YAML file and return a mapping."""

    source = Path(path)
    with source.open("r", encoding="utf-8") as file_obj:
        data = yaml.safe_load(file_obj) or {}
    if not isinstance(data, dict):
        raise InputValidationError([f"{source}: YAML root must be a mapping"])
    return data


def unwrap_payload(data: dict[str, Any], wrapper_key: str) -> dict[str, Any]:
    """Accept either raw payloads or top-level recommendation/research_signal wrappers."""

    payload = data.get(wrapper_key, data)
    if not isinstance(payload, dict):
        raise InputValidationError([f"{wrapper_key}: payload must be a mapping"])
    return payload


def infer_agent_id(path: str | Path | None = None, data: dict[str, Any] | None = None) -> str | None:
    """Infer agent id from payload or path."""

    if data and data.get("agent_id"):
        return str(data["agent_id"])
    if not path:
        return None
    parts = {part.lower() for part in Path(path).parts}
    for path_part, agent_id in AGENT_ID_BY_PATH_PART.items():
        if path_part in parts:
            return agent_id
    return None


def validate_research_signal(data: dict[str, Any], source_path: str | Path | None = None) -> ResearchSignal:
    """Validate a 4.1 research_signal payload."""

    payload = unwrap_payload(data, "research_signal")
    if "research_signal_id" not in payload and source_path:
        payload = {**payload, "research_signal_id": Path(source_path).stem}
    try:
        return ResearchSignal.model_validate(payload)
    except ValidationError as error:
        raise InputValidationError(format_validation_error(error)) from error


def validate_recommendation(
    data: dict[str, Any],
    agent_hint: str | None = None,
    source_path: str | Path | None = None,
) -> Recommendation:
    """Validate a trading-agent recommendation payload."""

    payload = unwrap_payload(data, "recommendation")
    agent_id = agent_hint or infer_agent_id(source_path, payload)
    if not agent_id:
        raise InputValidationError(["agent_id: required or inferable from path"])
    if agent_id not in AGENT_CLASS_BY_ID:
        raise InputValidationError([f"agent_id: unsupported value {agent_id!r}"])

    payload = {**payload, "agent_id": agent_id}
    if "recommendation_id" not in payload and source_path:
        payload["recommendation_id"] = Path(source_path).stem

    try:
        return AGENT_CLASS_BY_ID[agent_id].model_validate(payload)
    except ValidationError as error:
        raise InputValidationError(format_validation_error(error)) from error


def validate_file(path: str | Path, kind: str, agent_hint: str | None = None) -> ValidationResult:
    """Validate a single YAML file without throwing Pydantic stack traces."""

    try:
        data = load_yaml_file(path)
        if kind == "research_signal":
            item = validate_research_signal(data, path)
        elif kind == "recommendation":
            item = validate_recommendation(data, agent_hint, path)
        else:
            raise InputValidationError([f"kind: unsupported value {kind!r}"])
        return ValidationResult(valid=True, item=item)
    except InputValidationError as error:
        return ValidationResult(valid=False, errors=error.errors)


def collect_input_files(data_dir: str | Path, date: str) -> tuple[list[Path], list[Path]]:
    """Return research_signal and recommendation YAML files for a date."""

    root = Path(data_dir)
    compact_date = date.replace("-", "")
    signal_files = sorted((root / "research_signals").glob(f"*{compact_date}*.y*ml"))
    recommendation_root = root / "recommendations" / compact_date
    recommendation_files = (
        sorted(recommendation_root.rglob("*.yaml")) + sorted(recommendation_root.rglob("*.yml"))
    )
    return signal_files, recommendation_files


def load_inputs(data_dir: str | Path, date: str) -> tuple[list[ResearchSignal], list[Recommendation], list[str]]:
    """Load and validate all inputs for a Chairman run."""

    signal_files, recommendation_files = collect_input_files(data_dir, date)
    consumed_files: list[str] = []
    signals: list[ResearchSignal] = []
    recommendations: list[Recommendation] = []
    errors: list[str] = []

    for path in signal_files:
        result = validate_file(path, "research_signal")
        if result.valid:
            signals.append(result.item)
            consumed_files.append(str(path))
        else:
            errors.extend([f"{path}: {message}" for message in result.errors])

    for path in recommendation_files:
        result = validate_file(path, "recommendation")
        if result.valid:
            recommendations.append(result.item)
            consumed_files.append(str(path))
        else:
            errors.extend([f"{path}: {message}" for message in result.errors])

    if errors:
        raise InputValidationError(errors)
    if not signals and not recommendations:
        raise InputValidationError([f"no input YAML files found for date {date} under {data_dir}"])
    return signals, recommendations, consumed_files
