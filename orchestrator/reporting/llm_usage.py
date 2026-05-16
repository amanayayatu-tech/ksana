"""Estimate per-run LLM token usage and GPT-5.5 cost from local artifacts."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

GPT55_INPUT_USD_PER_1M = 5.0
GPT55_OUTPUT_USD_PER_1M = 30.0
GPT55_PRICING_SOURCE = "https://openai.com/api/pricing/"

STEP_LABELS = {
    "research_scan": "异常扫描 Research Agent",
    "trading_f_partner": "Value Partner",
    "trading_w_partner": "Momentum Partner",
    "trading_g_partner": "Quality Partner",
    "chairman": "CIO Agent",
    "red_team": "Risk Auditor",
    "perplexity_wait": "Deep Research 等待",
    "notify": "通知",
}

AGENT_LOG_DIRS = {
    "research_scan": "research_agent",
    "trading_f_partner": "trading_f_partner",
    "trading_w_partner": "trading_w_partner",
    "trading_g_partner": "trading_g_partner",
}


def build_run_llm_usage(data_dir: str | Path, run_id: str) -> dict[str, Any]:
    """Build a per-run token/cost summary from local logs and generated files."""

    root = Path(data_dir)
    db_path = root / "orchestrator" / "runs.db"
    if not db_path.exists():
        return {}
    run_row = load_run_row(db_path, run_id)
    if not run_row:
        return {}
    metadata = parse_json(run_row.get("metadata_json")) or {}
    compact = compact_date(metadata.get("date") or str(run_row.get("started_at") or "")[:10])
    step_rows = load_step_rows(db_path, run_id)
    steps = [build_step_usage(root, compact, step) for step in step_rows]
    totals = sum_usage(steps)
    return {
        "run_id": run_id,
        "date": metadata.get("date") or str(run_row.get("started_at") or "")[:10],
        "pipeline_type": run_row.get("pipeline_type") or "",
        "status": run_row.get("status") or "",
        "model": "gpt-5.5",
        "pricing": {
            "input_usd_per_1m": GPT55_INPUT_USD_PER_1M,
            "output_usd_per_1m": GPT55_OUTPUT_USD_PER_1M,
            "source": GPT55_PRICING_SOURCE,
            "basis": "standard_api_non_cached",
        },
        "estimation_method": "local_prompt_and_artifact_estimate",
        "accuracy_note": (
            "当前本地运行历史没有保存 OpenAI/Codex 官方 usage 字段；"
            "这里按本地 .llm.log prompt 与生成产物文本估算 token，用于预算口径。"
        ),
        "totals": totals,
        "steps": steps,
    }


def load_run_row(db_path: Path, run_id: str) -> dict[str, Any] | None:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM pipeline_runs WHERE run_id = ?", (run_id,)).fetchone()
    return dict(row) if row else None


def load_step_rows(db_path: Path, run_id: str) -> list[dict[str, Any]]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT *
            FROM step_executions
            WHERE run_id = ?
            ORDER BY started_at ASC, ended_at ASC
            """,
            (run_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def build_step_usage(data_dir: Path, compact: str, step: dict[str, Any]) -> dict[str, Any]:
    step_name = str(step.get("step_name") or "")
    output_paths = collect_step_output_paths(data_dir, step)
    input_text = ""
    output_text = read_output_text(output_paths)
    llm_used = False
    evidence_paths: list[str] = []
    method = "no_llm_or_not_recorded"

    agent_dir = AGENT_LOG_DIRS.get(step_name)
    if compact and agent_dir:
        agent_log = find_matching_agent_log(data_dir, compact, agent_dir, output_paths, step)
        if agent_log:
            agent_payload = parse_json(read_text(agent_log)) or {}
            llm_used = bool(agent_payload.get("llm_used"))
            llm_log = agent_log.with_suffix(".llm.log")
            input_text = read_text(llm_log)
            if not output_text:
                output_text = read_output_text([Path(path) for path in agent_payload.get("output_files", [])])
            evidence_paths.extend([relative_to_data(data_dir, agent_log), relative_to_data(data_dir, llm_log)])
            method = "agent_llm_log_and_outputs" if llm_used else "agent_no_llm"
    elif step_name in {"chairman", "red_team"}:
        metadata_payload = load_first_json_output(output_paths)
        llm_used = bool(metadata_payload.get("llm_used"))
        input_text = read_step_input_text(data_dir, compact, step_name, metadata_payload)
        method = "report_artifact_estimate" if llm_used else "report_no_llm"
        evidence_paths.extend(relative_to_data(data_dir, path) for path in output_paths if path.exists())

    input_tokens = estimate_tokens(input_text) if llm_used else 0
    output_tokens = estimate_tokens(output_text) if llm_used else 0
    cost = calculate_gpt55_cost(input_tokens, output_tokens)
    return {
        "step_name": step_name,
        "label": STEP_LABELS.get(step_name, step_name),
        "status": step.get("status") or "",
        "llm_used": llm_used,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "estimated_cost_usd": cost,
        "method": method,
        "evidence_paths": [path for path in evidence_paths if path],
    }


def collect_step_output_paths(data_dir: Path, step: dict[str, Any]) -> list[Path]:
    paths: list[Path] = []
    for value in parse_json(step.get("output_files_json")) or []:
        if isinstance(value, str):
            paths.append(resolve_data_path(data_dir, value))
    for stream_key in ("stdout_path", "stderr_path"):
        stream_path = resolve_data_path(data_dir, str(step.get(stream_key) or ""))
        if stream_path.exists():
            paths.extend(parse_generated_paths(data_dir, read_text(stream_path)))
    return dedupe_paths(paths)


def parse_generated_paths(data_dir: Path, text: str) -> list[Path]:
    paths: list[Path] = []
    for line in text.splitlines():
        match = re.match(r"^(?:generated|metadata):\s+(.+)$", line.strip())
        if match:
            paths.append(resolve_data_path(data_dir, match.group(1).strip()))
    return paths


def find_matching_agent_log(
    data_dir: Path,
    compact: str,
    agent_dir: str,
    output_paths: list[Path],
    step: dict[str, Any],
) -> Path | None:
    output_set = {normalize_path(path) for path in output_paths}
    candidates: list[tuple[int, float, Path]] = []
    step_time = parse_datetime(str(step.get("ended_at") or step.get("started_at") or ""))
    for path in agent_log_candidates(data_dir, compact, agent_dir):
        payload = parse_json(read_text(path)) or {}
        logged_outputs = {normalize_path(resolve_data_path(data_dir, str(item))) for item in payload.get("output_files", [])}
        overlap = len(output_set & logged_outputs) if output_set else 0
        if output_set and overlap == 0:
            continue
        distance = abs(path.stat().st_mtime - step_time.timestamp()) if step_time else path.stat().st_mtime
        candidates.append((-overlap, distance, path))
    if not candidates:
        return None
    return sorted(candidates)[0][2]


def agent_log_candidates(data_dir: Path, compact: str, agent_dir: str) -> list[Path]:
    roots: list[Path] = []
    if compact:
        roots.append(data_dir / "agent_logs" / compact / agent_dir)
    roots.extend(sorted((data_dir / "agent_logs").glob(f"*/{agent_dir}")))

    seen: set[str] = set()
    paths: list[Path] = []
    for root in roots:
        key = normalize_path(root)
        if key in seen or not root.exists():
            continue
        seen.add(key)
        paths.extend(sorted(root.glob("*.json")))
    return paths


def read_step_input_text(data_dir: Path, compact: str, step_name: str, metadata_payload: dict[str, Any]) -> str:
    input_paths: list[Path] = []
    if step_name == "chairman":
        for item in metadata_payload.get("input_files_consumed", []) or []:
            input_paths.append(resolve_data_path(data_dir, str(item)))
    elif step_name == "red_team":
        brief_id = str(metadata_payload.get("chairman_brief_consumed") or "")
        if brief_id:
            input_paths.extend((data_dir / "briefs" / compact).glob(f"{brief_id}.*"))
        input_paths.extend((data_dir / "recommendations" / compact).rglob("*.yaml"))
    return "\n\n".join(read_text(path) for path in dedupe_paths(input_paths) if path.exists())


def load_first_json_output(paths: list[Path]) -> dict[str, Any]:
    for path in paths:
        if path.suffix.lower() == ".json":
            payload = parse_json(read_text(path))
            if isinstance(payload, dict):
                return payload
    return {}


def read_output_text(paths: list[Path]) -> str:
    selected: list[Path] = []
    for path in dedupe_paths(paths):
        if not path.exists():
            continue
        suffix = path.suffix.lower()
        if suffix in {".yaml", ".yml", ".md", ".txt"}:
            selected.append(path)
    if not selected:
        selected = [path for path in dedupe_paths(paths) if path.exists() and path.suffix.lower() == ".json"]
    return "\n\n".join(read_text(path) for path in selected)


def estimate_tokens(text: str) -> int:
    text = text or ""
    if not text.strip():
        return 0
    cjk_chars = len(re.findall(r"[\u3400-\u9fff]", text))
    non_cjk_chars = max(0, len(text) - cjk_chars)
    return max(1, round(cjk_chars + non_cjk_chars / 4))


def calculate_gpt55_cost(input_tokens: int, output_tokens: int) -> float:
    return round(
        input_tokens / 1_000_000 * GPT55_INPUT_USD_PER_1M
        + output_tokens / 1_000_000 * GPT55_OUTPUT_USD_PER_1M,
        6,
    )


def sum_usage(steps: list[dict[str, Any]]) -> dict[str, Any]:
    input_tokens = sum(int(step.get("input_tokens") or 0) for step in steps)
    output_tokens = sum(int(step.get("output_tokens") or 0) for step in steps)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "estimated_cost_usd": calculate_gpt55_cost(input_tokens, output_tokens),
        "llm_step_count": sum(1 for step in steps if step.get("llm_used")),
    }


def parse_json(value: Any) -> Any:
    if not value:
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except json.JSONDecodeError:
        return None


def compact_date(date: str) -> str:
    compact = re.sub(r"\D", "", date or "")
    return compact[:8] if len(compact) >= 8 else ""


def resolve_data_path(data_dir: Path, value: str) -> Path:
    if not value:
        return Path("")
    path = Path(value)
    if path.is_absolute():
        return path
    if path.parts and path.parts[0] == data_dir.name:
        return data_dir.parent / path
    return data_dir / path


def normalize_path(path: Path) -> str:
    try:
        return str(path.expanduser().resolve())
    except OSError:
        return str(path)


def dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    unique: list[Path] = []
    for path in paths:
        key = normalize_path(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def relative_to_data(data_dir: Path, path: Path) -> str:
    if not path:
        return ""
    try:
        return str(path.relative_to(data_dir.parent))
    except ValueError:
        return str(path)


def parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
