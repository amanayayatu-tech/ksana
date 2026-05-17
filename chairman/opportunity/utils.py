"""Shared small helpers for Opportunity Memo assembly."""

from __future__ import annotations

from typing import Any

from chairman.models import Direction, Recommendation


def as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value:
        return [value]
    return []


def count_markers(text: str, markers: tuple[str, ...]) -> int:
    lowered = text.lower()
    return sum(1 for marker in markers if marker.lower() in lowered)


def clamp_score(value: float) -> int:
    return max(0, min(100, round(value)))


def infer_time_horizon(recommendations: list[Recommendation]) -> str:
    for rec in recommendations:
        extra = rec.model_extra or {}
        for key in ("time_horizon", "holding_period", "investment_horizon"):
            if extra.get(key):
                return str(extra[key])
        if isinstance(getattr(rec, "time_box", None), dict):
            time_box = getattr(rec, "time_box")
            if time_box.get("max_wait"):
                return str(time_box["max_wait"])
    return "3-12 months"


def first_text_from_extras(recommendations: list[Recommendation], key: str) -> str:
    for rec in recommendations:
        for item in as_list((rec.model_extra or {}).get(key)):
            if isinstance(item, dict):
                text = item.get("text") or item.get("reason") or item.get("condition") or item.get("gap")
                if text:
                    return str(text)
            elif item:
                return str(item)
    return ""


def first_long_thesis(recommendations: list[Recommendation]) -> str:
    for rec in recommendations:
        if rec.direction == Direction.LONG and (rec.one_liner_thesis or rec.thesis):
            return str(rec.one_liner_thesis or rec.thesis)
    return ""


def first_avoid_thesis(recommendations: list[Recommendation]) -> str:
    for rec in recommendations:
        if rec.direction == Direction.AVOID and (rec.one_liner_thesis or rec.thesis):
            return str(rec.one_liner_thesis or rec.thesis)
    return ""


def first_non_empty(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def dedupe_preserve_order(items: list[str]) -> list[str]:
    deduped: list[str] = []
    for item in items:
        text = " ".join(str(item or "").split())
        if text and text not in deduped:
            deduped.append(text)
    return deduped


def collect_recommendation_texts(recommendations: list[Recommendation]) -> list[str]:
    texts: list[str] = []
    for rec in recommendations:
        extra = rec.model_extra or {}
        texts.append(str(rec.thesis or ""))
        texts.append(str(rec.one_liner_thesis or ""))
        for key in ("catalysts", "thesis_kill_criteria", "waiting_conditions", "analysis_gaps"):
            for item in as_list(extra.get(key)):
                texts.append(str(item))
    return [text for text in texts if text]
