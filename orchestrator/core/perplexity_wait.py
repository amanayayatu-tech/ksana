"""Passive Perplexity fill waiting. This module never calls Perplexity."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass
class PerplexityWaitResult:
    all_p0_filled: bool
    filled_count: int
    skipped_count: int
    pending_count: int
    pending_prompt_ids: list[str]
    status: str


async def wait_for_perplexity_fill(
    *,
    data_dir: str | Path,
    run_id: str,
    timeout_seconds: int = 1800,
    poll_interval_seconds: int = 30,
) -> PerplexityWaitResult:
    """Wait for P0 prompt result files, then write perplexity_wait_outcome JSON."""

    root = Path(data_dir)
    p0_prompt_ids = discover_p0_prompt_ids(root)
    if not p0_prompt_ids:
        result = PerplexityWaitResult(True, 0, 0, 0, [], "skipped_no_p0")
        write_outcome(root, run_id, result)
        return result

    deadline = asyncio.get_event_loop().time() + timeout_seconds
    while True:
        result = evaluate_prompt_results(root, p0_prompt_ids)
        if result.all_p0_filled or asyncio.get_event_loop().time() >= deadline:
            write_outcome(root, run_id, result)
            return result
        await asyncio.sleep(max(0.01, poll_interval_seconds))


def discover_p0_prompt_ids(data_dir: Path) -> list[str]:
    """Read data/pull_requests/*.yaml and return P0 prompt ids."""

    prompt_ids: list[str] = []
    for path in sorted((data_dir / "pull_requests").glob("*.y*ml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        priority = data.get("priority") or data.get("prompt", {}).get("priority")
        prompt_id = data.get("prompt_id") or data.get("prompt", {}).get("prompt_id") or path.stem
        if priority == "P0":
            prompt_ids.append(str(prompt_id))
    return prompt_ids


def evaluate_prompt_results(data_dir: Path, prompt_ids: list[str]) -> PerplexityWaitResult:
    results_dir = data_dir / "perplexity_results"
    filled = []
    skipped = []
    pending = []
    for prompt_id in prompt_ids:
        if (results_dir / f"{prompt_id}_filled.yaml").exists():
            filled.append(prompt_id)
        elif (results_dir / f"{prompt_id}_skipped.yaml").exists():
            skipped.append(prompt_id)
        else:
            pending.append(prompt_id)
    return PerplexityWaitResult(
        all_p0_filled=not pending,
        filled_count=len(filled),
        skipped_count=len(skipped),
        pending_count=len(pending),
        pending_prompt_ids=pending,
        status="success" if not pending else "partial",
    )


def write_outcome(data_dir: Path, run_id: str, result: PerplexityWaitResult) -> Path:
    output_dir = data_dir / "orchestrator"
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"perplexity_wait_outcome_{run_id}.json"
    payload: dict[str, Any] = asdict(result)
    payload["evidence_unverified_prompt_ids"] = result.pending_prompt_ids
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
