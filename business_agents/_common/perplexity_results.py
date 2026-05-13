"""Load manually filled Perplexity research results from local files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from chairman.models import ResearchSignal


@dataclass(frozen=True)
class PerplexityContext:
    """Per-signal Perplexity context passed into trading agents."""

    yaml_text: str
    filled_prompt_ids: list[str]
    all_prompt_ids: list[str]

    @property
    def has_filled_results(self) -> bool:
        return bool(self.filled_prompt_ids)


def collect_perplexity_context(data_dir: str | Path, signal: ResearchSignal) -> PerplexityContext:
    """Return filled/skipped Perplexity files connected to a research signal."""

    root = Path(data_dir)
    prompt_records = load_prompt_records(root, signal)
    if not prompt_records:
        return PerplexityContext("无", [], [])

    filled_ids: list[str] = []
    for record in prompt_records:
        if record.get("status") == "filled":
            filled_ids.append(str(record["prompt_id"]))

    payload = {"perplexity_research": prompt_records}
    yaml_text = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False).strip()
    return PerplexityContext(
        yaml_text=yaml_text,
        filled_prompt_ids=filled_ids,
        all_prompt_ids=[str(record["prompt_id"]) for record in prompt_records],
    )


def load_prompt_records(root: Path, signal: ResearchSignal) -> list[dict[str, Any]]:
    prompt_ids = prompt_ids_for_signal(signal)
    records: dict[str, dict[str, Any]] = {}

    for path in sorted((root / "pull_requests").glob("*.y*ml")):
        data = read_yaml(path)
        prompt = data.get("prompt", data) if isinstance(data, dict) else {}
        prompt_id = str(prompt.get("prompt_id") or path.stem)
        related_signal_id = str(prompt.get("related_signal_id") or "")
        if related_signal_id == signal.research_signal_id or prompt_id in prompt_ids:
            prompt_ids.add(prompt_id)
            records[prompt_id] = {
                "prompt_id": prompt_id,
                "related_signal_id": related_signal_id or signal.research_signal_id,
                "priority": prompt.get("priority") or "",
                "prompt_text": prompt.get("prompt_text") or "",
                "prompt_path": str(path),
            }

    for prompt_id in sorted(prompt_ids):
        record = records.setdefault(
            prompt_id,
            {
                "prompt_id": prompt_id,
                "related_signal_id": signal.research_signal_id,
                "priority": "",
                "prompt_text": "",
                "prompt_path": "",
            },
        )
        record.update(load_result_status(root, prompt_id))

    return [records[prompt_id] for prompt_id in sorted(records)]


def prompt_ids_for_signal(signal: ResearchSignal) -> set[str]:
    values = signal.perplexity_research or {}
    ids: set[str] = set()
    for key in ("prompts_requested", "prompts_pending", "prompts_filled_back"):
        for prompt_id in values.get(key, []) or []:
            ids.add(str(prompt_id))
    return ids


def load_result_status(root: Path, prompt_id: str) -> dict[str, Any]:
    results_dir = root / "perplexity_results"
    filled_path = results_dir / f"{prompt_id}_filled.yaml"
    skipped_path = results_dir / f"{prompt_id}_skipped.yaml"
    if filled_path.exists():
        data = read_yaml(filled_path)
        return {
            "status": "filled",
            "result_path": str(filled_path),
            "answer_text": extract_answer_text(data),
            "filled_at": data.get("filled_at") or data.get("created_at") or "",
            "source": data.get("source") or "perplexity",
        }
    if skipped_path.exists():
        data = read_yaml(skipped_path)
        return {
            "status": "skipped",
            "result_path": str(skipped_path),
            "skipped_at": data.get("skipped_at") or data.get("created_at") or "",
            "skip_reason": data.get("reason") or data.get("skip_reason") or "",
        }
    return {"status": "pending", "result_path": ""}


def extract_answer_text(data: Any) -> str:
    if isinstance(data, str):
        return data
    if not isinstance(data, dict):
        return ""
    for key in ("answer_text", "answer", "content", "result", "summary"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False).strip()


def read_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
