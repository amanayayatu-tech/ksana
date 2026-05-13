"""Local FastAPI Web UI for Agent Trading System."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
import shutil
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from fastapi.templating import Jinja2Templates

PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
ENV_PATH = PROJECT_ROOT / ".env"
ENV_EXAMPLE_PATH = PROJECT_ROOT / ".env.example"
STOCK_POOL_PATH = DATA_DIR / "stock_pool" / "master_pool.yaml"

BRIEF_TYPES = {"morning": "AM", "evening": "PM"}
AGENT_COMMANDS = {
    "research": ["uv", "run", "research-agent", "run", "--type", "scan", "--data-dir", "data"],
    "fengliu": ["uv", "run", "trading-fengliu", "run", "--data-dir", "data"],
    "wanmu": ["uv", "run", "trading-wanmu", "run", "--data-dir", "data"],
    "liguofei": ["uv", "run", "trading-liguofei", "run", "--data-dir", "data"],
}
STOCK_CATEGORIES = (
    "hk_stocks",
    "us_stocks",
    "a_stocks_reference_only",
    "watchlist",
)
DEEP_RESEARCH_STATUSES = {"all", "pending", "filled", "skipped"}

app = FastAPI(title="Agent Trading System Web UI")
templates = Jinja2Templates(directory=str(PROJECT_ROOT / "templates"))
run_lock = asyncio.Lock()


@app.get("/")
def index(request: Request) -> Any:
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "active_page": "index",
            "today": datetime.now().strftime("%Y-%m-%d"),
            "env_status": get_env_status(),
        },
    )


@app.get("/history")
def history_page(request: Request) -> Any:
    return templates.TemplateResponse(
        request,
        "history.html",
        {"active_page": "history"},
    )


@app.get("/stock-pool")
def stock_pool_page(request: Request) -> Any:
    return templates.TemplateResponse(
        request,
        "stock_pool.html",
        {"active_page": "stock_pool"},
    )


@app.get("/env")
def env_page(request: Request) -> Any:
    return templates.TemplateResponse(
        request,
        "env.html",
        {
            "active_page": "env",
            "env_status": get_env_status(),
        },
    )


@app.get("/deep-research")
def deep_research_page(request: Request) -> Any:
    return templates.TemplateResponse(
        request,
        "deep_research.html",
        {
            "active_page": "deep_research",
            "today": datetime.now().strftime("%Y-%m-%d"),
        },
    )


@app.get("/api/run-stream")
async def run_stream(
    brief_type: str = Query("morning"),
    run_date: str = Query(..., alias="date"),
) -> StreamingResponse:
    validate_brief_type(brief_type)
    date = normalize_date(run_date)
    env_status = get_env_status()
    provider = env_status["llm_provider"] or "local"
    command = [
        "uv",
        "run",
        "orchestrator",
        "run",
        "--type",
        "full",
        "--brief-type",
        brief_type,
        "--date",
        date,
    ]
    return stream_command_response(command, {"LLM_PROVIDER": provider})


@app.get("/api/agent-stream")
async def agent_stream(
    agent: str = Query(...),
    brief_type: str = Query("morning"),
    run_date: str = Query(..., alias="date"),
    no_llm: bool = Query(False),
) -> StreamingResponse:
    validate_brief_type(brief_type)
    date = normalize_date(run_date)
    command = build_agent_command(agent, brief_type, date, no_llm)
    return stream_command_response(command, {})


@app.get("/api/report")
def api_report(
    run_date: str = Query(..., alias="date"),
    brief_type: str = Query("morning"),
) -> dict[str, Any]:
    validate_brief_type(brief_type)
    date = normalize_date(run_date)
    compact = date.replace("-", "")
    suffix = BRIEF_TYPES[brief_type]

    brief_path = find_report_file(DATA_DIR / "briefs" / compact, f"BRIEF-{compact}-{suffix}")
    audit_path = find_report_file(
        DATA_DIR / "red_team_audits" / compact,
        f"AUDIT-{compact}-{suffix}",
    )
    return {
        "date": date,
        "brief_type": brief_type,
        "brief": read_markdown_result(brief_path),
        "audit": read_markdown_result(audit_path),
    }


@app.get("/api/history")
def api_history(tail: int = Query(10, ge=1, le=100)) -> dict[str, Any]:
    command = ["uv", "run", "orchestrator", "history", "--data-dir", "data", "--tail", str(tail)]
    try:
        result = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            env=build_child_env(),
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail="找不到 uv，请先安装 uv。") from exc
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=504, detail="读取运行历史超时。") from exc

    if result.returncode != 0:
        return {
            "ok": False,
            "rows": [],
            "error": (result.stderr or result.stdout or "读取运行历史失败").strip(),
        }
    try:
        raw_rows = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        raw_rows = []
    return {"ok": True, "rows": [shape_history_row(row) for row in raw_rows], "error": ""}


@app.get("/api/stock-pool")
def api_stock_pool() -> dict[str, Any]:
    if not STOCK_POOL_PATH.exists():
        raise HTTPException(status_code=404, detail=f"股池文件不存在：{STOCK_POOL_PATH}")
    data = yaml.safe_load(STOCK_POOL_PATH.read_text(encoding="utf-8")) or {}
    stock_pool = normalize_stock_pool(data)
    return {"ok": True, "path": relative_path(STOCK_POOL_PATH), "stock_pool": stock_pool}


@app.post("/api/stock-pool")
def api_save_stock_pool(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    existing_data = load_stock_pool_yaml()
    stock_pool = merge_stock_pool(existing_data, payload)
    STOCK_POOL_PATH.parent.mkdir(parents=True, exist_ok=True)
    STOCK_POOL_PATH.write_text(dump_stock_pool_yaml(stock_pool), encoding="utf-8")
    return {"ok": True, "message": "股池已保存", "stock_pool": stock_pool}


@app.get("/api/env")
def api_env() -> dict[str, Any]:
    return {"ok": True, "env": get_env_status()}


@app.post("/api/env")
def api_save_env(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    provider = str(payload.get("llm_provider") or "local").strip()
    model = str(payload.get("llm_model") or "").strip()
    api_key = str(payload.get("openai_api_key") or "")
    clear_api_key = bool(payload.get("clear_api_key"))
    if provider not in {"local", "openai"}:
        raise HTTPException(status_code=400, detail="LLM Provider 只能是 local 或 openai。")
    write_env_file(provider, model, api_key, clear_api_key)
    return {"ok": True, "message": ".env 已保存", "env": get_env_status()}


@app.get("/api/deep-research/prompts")
def api_deep_research_prompts(
    run_date: str | None = Query(None, alias="date"),
    status: str = Query("all"),
) -> dict[str, Any]:
    date = normalize_date(run_date) if run_date else None
    if status not in DEEP_RESEARCH_STATUSES:
        raise HTTPException(status_code=400, detail="状态只能是 all、pending、filled 或 skipped。")
    prompts = load_deep_research_prompts(date_filter=date, status_filter=status)
    return {"ok": True, "prompts": prompts}


@app.post("/api/deep-research/fill")
def api_fill_deep_research(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    prompt_id = safe_prompt_id(str(payload.get("prompt_id") or ""))
    prompt = find_pull_request(prompt_id)
    answer_text = str(payload.get("answer_text") or "").strip()
    if not answer_text:
        raise HTTPException(status_code=400, detail="Perplexity 答案不能为空。")

    result = {
        "prompt_id": prompt_id,
        "related_signal_id": prompt.get("related_signal_id", ""),
        "priority": prompt.get("priority", ""),
        "status": "filled",
        "source": "perplexity",
        "filled_at": datetime.now().isoformat(timespec="seconds"),
        "prompt_text": prompt.get("prompt_text", ""),
        "answer_text": answer_text,
    }
    result_path = DATA_DIR / "perplexity_results" / f"{prompt_id}_filled.yaml"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(yaml.safe_dump(result, allow_unicode=True, sort_keys=False), encoding="utf-8")

    skipped_path = DATA_DIR / "perplexity_results" / f"{prompt_id}_skipped.yaml"
    if skipped_path.exists():
        skipped_path.unlink()
    return {"ok": True, "message": "Perplexity 答案已保存", "prompt": shape_prompt_record(prompt["path"])}


@app.post("/api/deep-research/skip")
def api_skip_deep_research(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    prompt_id = safe_prompt_id(str(payload.get("prompt_id") or ""))
    prompt = find_pull_request(prompt_id)
    reason = str(payload.get("reason") or "").strip()
    result = {
        "prompt_id": prompt_id,
        "related_signal_id": prompt.get("related_signal_id", ""),
        "priority": prompt.get("priority", ""),
        "status": "skipped",
        "skipped_at": datetime.now().isoformat(timespec="seconds"),
        "prompt_text": prompt.get("prompt_text", ""),
        "reason": reason or "Nepha 在 Web UI 中标记跳过。",
    }
    result_path = DATA_DIR / "perplexity_results" / f"{prompt_id}_skipped.yaml"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(yaml.safe_dump(result, allow_unicode=True, sort_keys=False), encoding="utf-8")

    filled_path = DATA_DIR / "perplexity_results" / f"{prompt_id}_filled.yaml"
    if filled_path.exists():
        filled_path.unlink()
    return {"ok": True, "message": "Prompt 已标记跳过", "prompt": shape_prompt_record(prompt["path"])}


@app.get("/api/deep-research/rerun-stream")
async def deep_research_rerun_stream(
    brief_type: str = Query("morning"),
    run_date: str = Query(..., alias="date"),
    no_llm: bool = Query(True),
) -> StreamingResponse:
    validate_brief_type(brief_type)
    date = normalize_date(run_date)
    commands = build_deep_research_rerun_commands(brief_type, date, no_llm)
    return stream_command_sequence_response(commands, {})


@app.post("/api/cleanup")
def api_cleanup(run_date: str | None = Query(None, alias="date")) -> dict[str, Any]:
    date = normalize_date(run_date or datetime.now().strftime("%Y-%m-%d"))
    removed = cleanup_date_artifacts(date)
    message = f"{date} 的运行结果已清理，股池和其他日期未删除。"
    return {"ok": True, "date": date, "removed": removed, "message": message}


def stream_command_response(
    command: list[str],
    env_overrides: dict[str, str],
) -> StreamingResponse:
    return StreamingResponse(
        stream_command(command, env_overrides),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def stream_command_sequence_response(
    commands: list[tuple[str, list[str]]],
    env_overrides: dict[str, str],
) -> StreamingResponse:
    return StreamingResponse(
        stream_command_sequence(commands, env_overrides),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def stream_command(command: list[str], env_overrides: dict[str, str]):
    if run_lock.locked():
        yield sse("status", {"status": "busy", "message": "已有任务正在运行。"})
        return

    async with run_lock:
        env = build_child_env(env_overrides)
        display_command = format_display_command(command, env_overrides)
        yield sse("start", {"command": display_command, "status": "running"})
        status_from_output = ""
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=PROJECT_ROOT,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except FileNotFoundError:
            yield sse("error", {"status": "failed", "message": "找不到 uv，请先安装 uv。"})
            yield sse("done", {"status": "failed", "return_code": 127})
            return

        assert process.stdout is not None
        while True:
            line = await process.stdout.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace").rstrip()
            match = re.search(r"status=([A-Za-z0-9_]+)", text)
            if match:
                status_from_output = match.group(1)
            yield sse("log", {"line": text})

        return_code = await process.wait()
        if status_from_output:
            final_status = status_from_output
        else:
            final_status = "completed" if return_code == 0 else "failed"
        yield sse("done", {"status": final_status, "return_code": return_code})


async def stream_command_sequence(
    commands: list[tuple[str, list[str]]],
    env_overrides: dict[str, str],
):
    if run_lock.locked():
        yield sse("status", {"status": "busy", "message": "已有任务正在运行。"})
        return

    async with run_lock:
        env = build_child_env(env_overrides)
        for index, (label, command) in enumerate(commands, start=1):
            display_command = format_display_command(command, env_overrides)
            yield sse(
                "start",
                {
                    "command": display_command,
                    "status": "running",
                    "step": label,
                    "index": index,
                    "total": len(commands),
                },
            )
            try:
                process = await asyncio.create_subprocess_exec(
                    *command,
                    cwd=PROJECT_ROOT,
                    env=env,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
            except FileNotFoundError:
                yield sse("error", {"status": "failed", "message": "找不到 uv，请先安装 uv。"})
                yield sse("done", {"status": "failed", "return_code": 127, "step": label})
                return

            assert process.stdout is not None
            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").rstrip()
                yield sse("log", {"line": text, "step": label})

            return_code = await process.wait()
            if return_code != 0:
                yield sse("done", {"status": "failed", "return_code": return_code, "step": label})
                return
        yield sse("done", {"status": "completed", "return_code": 0})


def sse(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def build_deep_research_rerun_commands(
    brief_type: str,
    date: str,
    no_llm: bool,
) -> list[tuple[str, list[str]]]:
    trading_commands = [
        ("冯柳 Agent", ["uv", "run", "trading-fengliu", "run", "--data-dir", "data"]),
        ("万木 Agent", ["uv", "run", "trading-wanmu", "run", "--data-dir", "data"]),
        ("李国飞 Agent", ["uv", "run", "trading-liguofei", "run", "--data-dir", "data"]),
    ]
    if no_llm:
        for _, command in trading_commands:
            command.append("--no-llm")

    chairman_command = [
        "uv",
        "run",
        "chairman",
        "generate-brief",
        "--type",
        brief_type,
        "--date",
        date,
        "--data-dir",
        "data",
    ]
    red_team_command = [
        "uv",
        "run",
        "red-team",
        "audit",
        "--type",
        brief_type,
        "--date",
        date,
        "--data-dir",
        "data",
    ]
    if no_llm:
        chairman_command.append("--no-llm")
        red_team_command.append("--no-llm")

    return [
        *trading_commands,
        ("Chairman", chairman_command),
        ("Red Team", red_team_command),
    ]


def build_agent_command(agent: str, brief_type: str, date: str, no_llm: bool) -> list[str]:
    if agent in AGENT_COMMANDS:
        command = list(AGENT_COMMANDS[agent])
        if no_llm:
            command.append("--no-llm")
        return command
    if agent == "chairman":
        command = [
            "uv",
            "run",
            "chairman",
            "generate-brief",
            "--type",
            brief_type,
            "--date",
            date,
            "--data-dir",
            "data",
        ]
        if no_llm:
            command.append("--no-llm")
        return command
    if agent == "red-team":
        command = [
            "uv",
            "run",
            "red-team",
            "audit",
            "--type",
            brief_type,
            "--date",
            date,
            "--data-dir",
            "data",
        ]
        if no_llm:
            command.append("--no-llm")
        return command
    raise HTTPException(status_code=400, detail="未知 Agent。")


def validate_brief_type(brief_type: str) -> None:
    if brief_type not in BRIEF_TYPES:
        raise HTTPException(status_code=400, detail="报告类型只能是 morning 或 evening。")


def normalize_date(value: str) -> str:
    text = value.strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    try:
        return datetime.strptime(text, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="日期格式必须是 YYYY-MM-DD。") from exc


def find_report_file(directory: Path, basename: str) -> Path | None:
    exact = directory / f"{basename}.md"
    if exact.exists():
        return exact
    candidates = sorted(directory.glob(f"{basename}*.md")) if directory.exists() else []
    return candidates[-1] if candidates else None


def read_markdown_result(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {"exists": False, "path": "", "content": ""}
    return {
        "exists": True,
        "path": relative_path(path),
        "content": path.read_text(encoding="utf-8"),
    }


def load_deep_research_prompts(
    date_filter: str | None = None,
    status_filter: str = "all",
) -> list[dict[str, Any]]:
    prompt_dir = DATA_DIR / "pull_requests"
    if not prompt_dir.exists():
        return []
    prompts = [shape_prompt_record(path) for path in sorted(prompt_dir.glob("*.y*ml"))]
    if date_filter:
        prompts = [prompt for prompt in prompts if prompt_matches_date(prompt, date_filter)]
    if status_filter != "all":
        prompts = [prompt for prompt in prompts if prompt["status"] == status_filter]
    return prompts


def shape_prompt_record(path: Path) -> dict[str, Any]:
    data = read_yaml_file(path)
    prompt = data.get("prompt", data) if isinstance(data, dict) else {}
    prompt_id = str(prompt.get("prompt_id") or path.stem)
    related_signal_id = str(prompt.get("related_signal_id") or "")
    priority = str(prompt.get("priority") or "")
    prompt_text = str(prompt.get("prompt_text") or "")
    status_payload = deep_research_status(prompt_id)
    record = {
        "prompt_id": prompt_id,
        "related_signal_id": related_signal_id,
        "priority": priority,
        "prompt_text": prompt_text,
        "prompt_markdown": build_prompt_markdown(prompt_id, related_signal_id, priority, prompt_text),
        "path_display": relative_path(path),
    }
    record.update(status_payload)
    return record


def build_prompt_markdown(
    prompt_id: str,
    related_signal_id: str,
    priority: str,
    prompt_text: str,
) -> str:
    lines = [
        "# Perplexity 深度研究 Prompt",
        "",
        f"- prompt_id: {prompt_id}",
        f"- related_signal_id: {related_signal_id or 'unknown'}",
        f"- priority: {priority or 'unknown'}",
        "",
        "## 研究问题",
        "",
        prompt_text,
    ]
    return "\n".join(lines).strip() + "\n"


def prompt_matches_date(prompt: dict[str, Any], date: str) -> bool:
    compact = date.replace("-", "")
    haystack = " ".join(
        str(prompt.get(key) or "")
        for key in ("prompt_id", "related_signal_id", "path_display", "prompt_text")
    )
    return compact in haystack or date in haystack


def deep_research_status(prompt_id: str) -> dict[str, Any]:
    results_dir = DATA_DIR / "perplexity_results"
    filled_path = results_dir / f"{prompt_id}_filled.yaml"
    skipped_path = results_dir / f"{prompt_id}_skipped.yaml"
    if filled_path.exists():
        data = read_yaml_file(filled_path)
        return {
            "status": "filled",
            "status_label": "已回填",
            "result_path": relative_path(filled_path),
            "answer_text": extract_answer_text(data),
            "updated_at": str(data.get("filled_at") or data.get("created_at") or ""),
            "skip_reason": "",
        }
    if skipped_path.exists():
        data = read_yaml_file(skipped_path)
        return {
            "status": "skipped",
            "status_label": "已跳过",
            "result_path": relative_path(skipped_path),
            "answer_text": "",
            "updated_at": str(data.get("skipped_at") or data.get("created_at") or ""),
            "skip_reason": str(data.get("reason") or data.get("skip_reason") or ""),
        }
    return {
        "status": "pending",
        "status_label": "待回填",
        "result_path": "",
        "answer_text": "",
        "updated_at": "",
        "skip_reason": "",
    }


def find_pull_request(prompt_id: str) -> dict[str, Any]:
    prompt_dir = DATA_DIR / "pull_requests"
    for path in sorted(prompt_dir.glob("*.y*ml")) if prompt_dir.exists() else []:
        data = read_yaml_file(path)
        prompt = data.get("prompt", data) if isinstance(data, dict) else {}
        current_id = str(prompt.get("prompt_id") or path.stem)
        if current_id == prompt_id:
            return {
                "path": path,
                "prompt_id": current_id,
                "related_signal_id": str(prompt.get("related_signal_id") or ""),
                "priority": str(prompt.get("priority") or ""),
                "prompt_text": str(prompt.get("prompt_text") or ""),
            }
    raise HTTPException(status_code=404, detail=f"找不到 Prompt：{prompt_id}")


def safe_prompt_id(prompt_id: str) -> str:
    value = prompt_id.strip()
    if not value or not re.fullmatch(r"[A-Za-z0-9_.-]+", value):
        raise HTTPException(status_code=400, detail="prompt_id 格式不合法。")
    return value


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


def read_yaml_file(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def cleanup_date_artifacts(date: str) -> list[str]:
    compact = date.replace("-", "")
    removed: list[str] = []
    dated_dirs = [
        DATA_DIR / "briefs" / compact,
        DATA_DIR / "red_team_audits" / compact,
        DATA_DIR / "recommendations" / compact,
        DATA_DIR / "notifications" / compact,
    ]
    for path in dated_dirs:
        remove_path(path, removed)

    for dirname in ("research_signals", "pull_requests", "perplexity_results", "agent_logs", "errors"):
        remove_matching_children(DATA_DIR / dirname, date, compact, removed)

    remove_matching_children(DATA_DIR / "orchestrator" / "logs", date, compact, removed)
    for run_id in cleanup_run_history(date, compact):
        remove_path(DATA_DIR / "orchestrator" / "logs" / run_id, removed)
    return removed


def remove_matching_children(root: Path, date: str, compact: str, removed: list[str]) -> None:
    if not root.exists():
        return
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if not path.exists():
            continue
        if compact in path.name or date in path.name:
            remove_path(path, removed)


def remove_path(path: Path, removed: list[str]) -> None:
    if not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    removed.append(relative_path(path))


def cleanup_run_history(date: str, compact: str) -> list[str]:
    db_path = DATA_DIR / "orchestrator" / "runs.db"
    if not db_path.exists():
        return []
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT run_id
            FROM pipeline_runs
            WHERE started_at LIKE ?
               OR run_id LIKE ?
               OR metadata_json LIKE ?
               OR metadata_json LIKE ?
            """,
            (f"{date}%", f"RUN-{compact}-%", f'%"date": "{date}"%', f'%"date":"{date}"%'),
        ).fetchall()
        run_ids = [row[0] for row in rows]
        for run_id in run_ids:
            conn.execute("DELETE FROM step_executions WHERE run_id = ?", (run_id,))
            conn.execute("DELETE FROM notifications_sent WHERE run_id = ?", (run_id,))
            conn.execute("DELETE FROM pipeline_runs WHERE run_id = ?", (run_id,))
        return run_ids


def build_child_env(overrides: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(PROJECT_ROOT)
        if not existing_pythonpath
        else f"{PROJECT_ROOT}{os.pathsep}{existing_pythonpath}"
    )
    env_values = read_env_values(ENV_PATH)
    for key, value in env_values.items():
        env[key] = value
    env.setdefault("LLM_PROVIDER", "local")
    for key, value in (overrides or {}).items():
        env[key] = value
    return env


def format_display_command(command: list[str], env_overrides: dict[str, str]) -> str:
    prefix = " ".join(f"{key}={shlex.quote(value)}" for key, value in env_overrides.items())
    rendered = " ".join(shlex.quote(part) for part in command)
    return f"{prefix} {rendered}".strip()


def read_env_values(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def get_env_status() -> dict[str, Any]:
    values = read_env_values(ENV_PATH)
    api_key = values.get("OPENAI_API_KEY", "")
    return {
        "has_env": ENV_PATH.exists(),
        "llm_provider": values.get("LLM_PROVIDER", "local"),
        "llm_model": values.get("LLM_MODEL", ""),
        "openai_api_key_masked": mask_secret(api_key),
        "openai_api_key_set": bool(api_key),
    }


def write_env_file(provider: str, model: str, api_key: str, clear_api_key: bool) -> None:
    base_path = ENV_PATH if ENV_PATH.exists() else ENV_EXAMPLE_PATH
    lines = base_path.read_text(encoding="utf-8").splitlines() if base_path.exists() else []
    updates = {"LLM_PROVIDER": provider, "LLM_MODEL": model}
    if clear_api_key:
        updates["OPENAI_API_KEY"] = ""
    elif api_key:
        updates["OPENAI_API_KEY"] = api_key.strip()
    elif "OPENAI_API_KEY" not in read_env_values(base_path):
        updates["OPENAI_API_KEY"] = ""

    seen: set[str] = set()
    rendered: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            rendered.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in updates:
            rendered.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            rendered.append(line)
    for key, value in updates.items():
        if key not in seen:
            rendered.append(f"{key}={value}")
    ENV_PATH.write_text("\n".join(rendered).rstrip() + "\n", encoding="utf-8")


def mask_secret(value: str) -> str:
    if not value:
        return "未设置"
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}****{value[-4:]}"


def shape_history_row(row: dict[str, Any]) -> dict[str, Any]:
    metadata = {}
    try:
        metadata = json.loads(row.get("metadata_json") or "{}")
    except json.JSONDecodeError:
        metadata = {}
    started_at = row.get("started_at") or ""
    return {
        "run_id": row.get("run_id", ""),
        "date": metadata.get("date") or started_at[:10],
        "brief_type": metadata.get("brief_type") or metadata.get("step") or "",
        "status": row.get("status", ""),
        "started_at": started_at,
        "ended_at": row.get("ended_at") or "",
    }


def load_stock_pool_yaml() -> dict[str, Any]:
    if not STOCK_POOL_PATH.exists():
        return {"stock_pool": {}}
    return yaml.safe_load(STOCK_POOL_PATH.read_text(encoding="utf-8")) or {"stock_pool": {}}


def normalize_stock_pool(data: dict[str, Any]) -> dict[str, Any]:
    root = data.get("stock_pool", data)
    stock_pool: dict[str, Any] = {
        "version": root.get("version", 1),
        "last_updated_by_nepha": root.get("last_updated_by_nepha", ""),
    }
    for category in STOCK_CATEGORIES:
        items = root.get(category) or []
        stock_pool[category] = [normalize_stock_item(category, item) for item in items]
    return stock_pool


def merge_stock_pool(existing_data: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    existing_root = existing_data.get("stock_pool", existing_data) if isinstance(existing_data, dict) else {}
    submitted = normalize_stock_pool(payload)
    merged = dict(existing_root)
    merged["version"] = submitted.get("version", 1)
    merged["last_updated_by_nepha"] = submitted.get("last_updated_by_nepha", "")
    for category in STOCK_CATEGORIES:
        existing_items = existing_root.get(category) or []
        merged[category] = merge_stock_items(
            category,
            [item for item in existing_items if isinstance(item, dict)],
            submitted.get(category) or [],
        )
    return merged


def merge_stock_items(
    category: str,
    existing_items: list[dict[str, Any]],
    submitted_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_ticker: dict[str, list[dict[str, Any]]] = {}
    for item in existing_items:
        ticker = str(item.get("ticker") or "").strip()
        by_ticker.setdefault(ticker, []).append(item)

    merged: list[dict[str, Any]] = []
    for index, submitted in enumerate(submitted_items):
        ticker = str(submitted.get("ticker") or "").strip()
        if ticker and by_ticker.get(ticker):
            base = dict(by_ticker[ticker].pop(0))
        elif index < len(existing_items):
            base = dict(existing_items[index])
        else:
            base = {}
        base.update(normalize_stock_item(category, submitted))
        merged.append(base)
    return merged


def normalize_stock_item(category: str, item: dict[str, Any]) -> dict[str, Any]:
    normalized = {
        "ticker": str(item.get("ticker") or "").strip(),
        "name": str(item.get("name") or "").strip(),
    }
    if category == "watchlist":
        normalized["reason_to_watch"] = str(item.get("reason_to_watch") or "").strip()
    else:
        tags = item.get("tags") or []
        if isinstance(tags, str):
            tags = [tag.strip() for tag in tags.split(",") if tag.strip()]
        normalized["tags"] = [str(tag).strip() for tag in tags if str(tag).strip()]
    return normalized


def dump_stock_pool_yaml(stock_pool: dict[str, Any]) -> str:
    lines = [
        "stock_pool:",
        f"  version: {stock_pool.get('version', 1)}",
        f"  last_updated_by_nepha: {quote_yaml_string(stock_pool.get('last_updated_by_nepha', ''))}",
    ]
    for key, value in stock_pool.items():
        if key not in {"version", "last_updated_by_nepha", *STOCK_CATEGORIES}:
            lines.extend(yaml_block_lines({key: value}, indent=2))
    for category in STOCK_CATEGORIES:
        items = stock_pool.get(category) or []
        if not items:
            lines.append(f"  {category}: []")
            continue
        lines.append(f"  {category}:")
        for item in items:
            lines.append(f"    - ticker: {quote_yaml_string(item.get('ticker', ''))}")
            lines.append(f"      name: {quote_yaml_string(item.get('name', ''))}")
            if category == "watchlist":
                reason = item.get("reason_to_watch", "")
                lines.append(f"      reason_to_watch: {quote_yaml_string(reason)}")
                known_keys = {"ticker", "name", "reason_to_watch"}
            else:
                tags = item.get("tags") or []
                tag_text = ", ".join(quote_yaml_string(tag) for tag in tags)
                lines.append(f"      tags: [{tag_text}]")
                known_keys = {"ticker", "name", "tags"}
            for key, value in item.items():
                if key not in known_keys:
                    lines.extend(yaml_block_lines({key: value}, indent=6))
    return "\n".join(lines) + "\n"


def yaml_block_lines(data: dict[str, Any], indent: int) -> list[str]:
    dumped = yaml.safe_dump(data, allow_unicode=True, sort_keys=False).strip()
    return [f"{' ' * indent}{line}" for line in dumped.splitlines()]


def quote_yaml_string(value: Any) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def relative_path(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("webui:app", host="127.0.0.1", port=7777, reload=False)
