"""Load manually filled Perplexity research results from local files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from chairman.models import ResearchSignal

MAX_PERPLEXITY_ANSWER_CHARS = 2600
MAX_PERPLEXITY_PROMPT_CHARS = 900


@dataclass(frozen=True)
class PerplexityContext:
    """Per-signal Perplexity context passed into trading agents."""

    yaml_text: str
    filled_prompt_ids: list[str]
    all_prompt_ids: list[str]
    skipped_prompt_ids: list[str]
    pending_prompt_ids: list[str]

    @property
    def has_filled_results(self) -> bool:
        return bool(self.filled_prompt_ids)


def collect_perplexity_context(data_dir: str | Path, signal: ResearchSignal) -> PerplexityContext:
    """Return filled/skipped Perplexity files connected to a research signal."""

    root = Path(data_dir)
    prompt_records = load_prompt_records(root, signal)
    if not prompt_records:
        return PerplexityContext("无", [], [], [], [])

    filled_ids: list[str] = []
    skipped_ids: list[str] = []
    pending_ids: list[str] = []
    for record in prompt_records:
        if record.get("status") == "filled":
            filled_ids.append(str(record["prompt_id"]))
        elif record.get("status") in {"skipped", "skip_cold_start"}:
            skipped_ids.append(str(record["prompt_id"]))
        else:
            pending_ids.append(str(record["prompt_id"]))

    payload = {"perplexity_research": [shape_record_for_prompt(record) for record in prompt_records]}
    yaml_text = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False).strip()
    return PerplexityContext(
        yaml_text=yaml_text,
        filled_prompt_ids=filled_ids,
        all_prompt_ids=[str(record["prompt_id"]) for record in prompt_records],
        skipped_prompt_ids=skipped_ids,
        pending_prompt_ids=pending_ids,
    )


def sync_signal_perplexity_status(data_dir: str | Path, signal: ResearchSignal) -> ResearchSignal:
    """Return a signal copy with pending/filled/skipped prompt status synchronized."""

    context = collect_perplexity_context(data_dir, signal)
    if not context.all_prompt_ids:
        return signal
    current = dict(signal.perplexity_research or {})
    filled_records = [
        record
        for record in load_prompt_records(Path(data_dir), signal)
        if record.get("status") == "filled"
    ]
    summaries = [record.get("answer_text", "").strip() for record in filled_records if record.get("answer_text")]
    current.update(
        {
            "prompts_requested": context.all_prompt_ids,
            "prompts_filled_back": context.filled_prompt_ids,
            "prompts_skipped_by_nepha": context.skipped_prompt_ids,
            "prompts_pending": context.pending_prompt_ids,
            "coverage_ratio": round(
                len(context.filled_prompt_ids) / len(context.all_prompt_ids),
                4,
            )
            if context.all_prompt_ids
            else 0,
            "results_summary": "\n\n".join(summaries)[:2000] if summaries else None,
            "confidence_after_research": 60 if summaries else None,
        }
    )
    payload = signal.model_dump(mode="json")
    payload["perplexity_research"] = current
    payload["research_planning_context"] = sync_cold_start_planning_context(
        payload.get("research_planning_context"),
        closed_prompt_ids=set(context.filled_prompt_ids) | set(context.skipped_prompt_ids),
    )
    return ResearchSignal.model_validate(payload)


def sync_signal_file_perplexity_status(data_dir: str | Path, prompt_id: str) -> list[Path]:
    """Persist synchronized status for research_signal files connected to prompt_id."""

    root = Path(data_dir)
    changed: list[Path] = []
    for path in sorted((root / "research_signals").glob("*.y*ml")):
        data = read_yaml(path)
        payload = data.get("research_signal", data) if isinstance(data, dict) else {}
        if not isinstance(payload, dict):
            continue
        signal = ResearchSignal.model_validate(payload)
        if prompt_id not in prompt_ids_for_signal(signal):
            continue
        synced = sync_signal_perplexity_status(root, signal)
        path.write_text(
            yaml.safe_dump({"research_signal": synced.model_dump(mode="json")}, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        changed.append(path)
    return changed


def load_prompt_records(root: Path, signal: ResearchSignal) -> list[dict[str, Any]]:
    prompt_ids = prompt_ids_for_signal(signal)
    records: dict[str, dict[str, Any]] = {}

    for path in sorted((root / "pull_requests").glob("*.y*ml")):
        data = read_yaml(path)
        prompt = data.get("prompt", data) if isinstance(data, dict) else {}
        prompt_id = str(prompt.get("prompt_id") or path.stem)
        related_signal_id = str(prompt.get("related_signal_id") or "")
        if prompt_id in prompt_ids or (
            related_signal_id == signal.research_signal_id
            and prompt_record_matches_signal(prompt, signal)
        ):
            prompt_ids.add(prompt_id)
            records[prompt_id] = {
                "prompt_id": prompt_id,
                "related_signal_id": related_signal_id or signal.research_signal_id,
                "priority": prompt.get("priority") or "",
                **compact_prompt_text(str(prompt.get("prompt_text") or "")),
                "prompt_text_for_match": str(prompt.get("prompt_text") or ""),
                "prompt_path": str(path),
            }

    for prompt_id in sorted(prompt_ids):
        record = records.setdefault(
            prompt_id,
            {
                "prompt_id": prompt_id,
                "related_signal_id": signal.research_signal_id,
                "priority": "",
                **compact_prompt_text(""),
                "prompt_text_for_match": "",
                "prompt_path": "",
            },
        )
        record.update(load_result_status(root, record))

    return [records[prompt_id] for prompt_id in sorted(records)]


def sync_cold_start_planning_context(context: Any, *, closed_prompt_ids: set[str]) -> Any:
    if not isinstance(context, dict) or not closed_prompt_ids:
        return context
    pending = []
    for item in context.get("cold_start_pending") or []:
        if not isinstance(item, dict):
            continue
        prompt_id = str(item.get("prompt_id") or "")
        if prompt_id and prompt_id not in closed_prompt_ids:
            pending.append(item)
    if len(pending) == len(context.get("cold_start_pending") or []):
        return context

    updated = dict(context)
    updated["cold_start_pending"] = pending
    directives = [
        str(item)
        for item in updated.get("prompt_directives") or []
        if "冷启动历史研究" not in str(item) or "置信度不得超过 50%" not in str(item)
    ]
    if pending:
        directives.append(f"当前存在 {len(pending)} 条未完成的冷启动历史研究，Trading Agent 评估结论置信度不得超过 50%。")
    updated["prompt_directives"] = directives
    return updated


def prompt_ids_for_signal(signal: ResearchSignal) -> set[str]:
    values = signal.perplexity_research or {}
    ids: set[str] = set()
    for key in ("prompts_requested", "prompts_pending", "prompts_filled_back"):
        for prompt_id in values.get(key, []) or []:
            ids.add(str(prompt_id))
    return ids


def load_result_status(root: Path, record: dict[str, Any] | str) -> dict[str, Any]:
    if isinstance(record, str):
        record = {"prompt_id": record, "related_signal_id": "", "prompt_text": ""}
    prompt_id = str(record["prompt_id"])
    results_dir = root / "perplexity_results"
    filled_path = results_dir / f"{prompt_id}_filled.yaml"
    skipped_path = results_dir / f"{prompt_id}_skipped.yaml"
    if filled_path.exists():
        data = read_yaml(filled_path)
        mismatch = result_mismatch_reason(data, record)
        if mismatch:
            return {
                "status": "pending",
                "result_path": "",
                "ignored_result_path": str(filled_path),
                "ignored_result_reason": mismatch,
            }
        return {
            "status": "filled",
            "result_path": str(filled_path),
            **compact_answer_text(extract_answer_text(data)),
            "filled_at": data.get("filled_at") or data.get("created_at") or "",
            "source": data.get("source") or "perplexity",
        }
    if skipped_path.exists():
        data = read_yaml(skipped_path)
        mismatch = result_mismatch_reason(data, record)
        if mismatch:
            return {
                "status": "pending",
                "result_path": "",
                "ignored_result_path": str(skipped_path),
                "ignored_result_reason": mismatch,
            }
        return {
            "status": data.get("status") or "skipped",
            "result_path": str(skipped_path),
            "skipped_at": data.get("skipped_at") or data.get("created_at") or "",
            "skip_reason": data.get("reason") or data.get("skip_reason") or "",
        }
    return {"status": "pending", "result_path": ""}


def prompt_record_matches_signal(prompt: dict[str, Any], signal: ResearchSignal) -> bool:
    """Protect reruns from reusing same-date prompt records for a different ticker."""

    prompt_text = str(prompt.get("prompt_text") or "")
    if not prompt_text:
        return True
    haystack = prompt_text.upper()
    for target in signal.candidate_targets:
        ticker = str(target.ticker or "").upper()
        company_name = str(target.company_name or "").upper()
        if ticker and ticker in haystack:
            return True
        if company_name and company_name in haystack:
            return True
    return False


def result_mismatch_reason(data: Any, record: dict[str, Any]) -> str:
    """Return why a filled/skipped result should not be attached to this prompt."""

    if not isinstance(data, dict):
        return ""
    expected_prompt_id = str(record.get("prompt_id") or "")
    actual_prompt_id = str(data.get("prompt_id") or "")
    if actual_prompt_id and expected_prompt_id and actual_prompt_id != expected_prompt_id:
        return f"prompt_id mismatch: expected {expected_prompt_id}, got {actual_prompt_id}"

    expected_signal_id = str(record.get("related_signal_id") or "")
    actual_signal_id = str(data.get("related_signal_id") or "")
    if actual_signal_id and expected_signal_id and actual_signal_id != expected_signal_id:
        return f"related_signal_id mismatch: expected {expected_signal_id}, got {actual_signal_id}"

    expected_text = normalize_prompt_text(str(record.get("prompt_text_for_match") or record.get("prompt_text") or ""))
    actual_text = normalize_prompt_text(str(data.get("prompt_text") or ""))
    if actual_text and expected_text and actual_text != expected_text:
        return "prompt_text mismatch; ignored stale Perplexity result from an older rerun"
    return ""


def normalize_prompt_text(value: str) -> str:
    return " ".join(value.split())


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


def compact_answer_text(text: str) -> dict[str, Any]:
    """Keep LLM prompts responsive while preserving the full result on disk."""

    if len(text) <= MAX_PERPLEXITY_ANSWER_CHARS:
        return {
            "answer_text": text,
            "answer_text_truncated": False,
            "answer_text_original_chars": len(text),
        }
    return {
        "answer_text": text[:MAX_PERPLEXITY_ANSWER_CHARS].rstrip()
        + "\n\n[已截断：完整回填内容请查看 result_path 指向的本地文件]",
        "answer_text_truncated": True,
        "answer_text_original_chars": len(text),
    }


def compact_prompt_text(text: str) -> dict[str, Any]:
    """Keep generated K deep prompts from crowding out the filled research answer."""

    if len(text) <= MAX_PERPLEXITY_PROMPT_CHARS:
        return {
            "prompt_text": text,
            "prompt_text_truncated": False,
            "prompt_text_original_chars": len(text),
        }
    return {
        "prompt_text": text[:MAX_PERPLEXITY_PROMPT_CHARS].rstrip()
        + "\n\n[已截断：完整 prompt 请查看 prompt_path 指向的本地文件]",
        "prompt_text_truncated": True,
        "prompt_text_original_chars": len(text),
    }


def shape_record_for_prompt(record: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in record.items()
        if key not in {"prompt_text_for_match"}
    }


def read_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
