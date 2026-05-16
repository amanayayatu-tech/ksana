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
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml
from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from business_agents._common.knowledge_store import delete_entry_for_prompt, ingest_filled_result
from business_agents._common.llm_client import build_llm_client_from_env
from business_agents._common.perplexity_results import sync_signal_file_perplexity_status
from orchestrator.core.learning import (
    load_learning_overview,
    load_stock_timeline,
    rebuild_stock_timelines,
    refresh_outcome_snapshots,
    write_monthly_review,
)
from orchestrator.core.models import StepResult
from orchestrator.persistence.run_log import RunLog
from orchestrator.reporting.html_renderer import (
    ReportPresentation,
    productize_report_text,
    render_report_html,
)

PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
ENV_PATH = PROJECT_ROOT / ".env"
ENV_EXAMPLE_PATH = PROJECT_ROOT / ".env.example"
STOCK_POOL_PATH = DATA_DIR / "stock_pool" / "master_pool.yaml"

BRIEF_TYPES = {"morning": "AM", "evening": "PM"}
AGENT_COMMANDS = {
    "research": ["uv", "run", "research-agent", "run", "--type", "scan", "--data-dir", "data"],
    "f_partner": ["uv", "run", "trading-f_partner", "run", "--data-dir", "data"],
    "w_partner": ["uv", "run", "trading-w_partner", "run", "--data-dir", "data"],
    "g_partner": ["uv", "run", "trading-g_partner", "run", "--data-dir", "data"],
}
STOCK_CATEGORIES = (
    "hk_stocks",
    "us_stocks",
    "a_stocks_reference_only",
    "watchlist",
)
DEEP_RESEARCH_STATUSES = {"all", "pending", "filled", "skipped"}
LLM_PROVIDERS = {"local", "openai", "codex_cli"}
CODEX_LOGIN_TIMEOUT_SECONDS = 300
RUNNING_RUN_STALE_SECONDS = 300
RERUN_STEP_NAMES = {
    "Value Partner Agent": "trading_f_partner",
    "Momentum Partner Agent": "trading_w_partner",
    "Quality Partner Agent": "trading_g_partner",
    "CIO Agent": "chairman",
    "Risk Auditor": "red_team",
}
FULL_RUN_STEP_PLAN = [
    {
        "step_name": "research_scan",
        "label": "异常扫描 Agent 编排研究任务",
        "estimate_seconds": 120,
        "stage": "research",
    },
    {
        "step_name": "trading_f_partner",
        "label": "Value Partner 策略分析",
        "estimate_seconds": 240,
        "stage": "investment_committee",
    },
    {
        "step_name": "trading_w_partner",
        "label": "Momentum Partner 策略分析",
        "estimate_seconds": 240,
        "stage": "investment_committee",
    },
    {
        "step_name": "trading_g_partner",
        "label": "Quality Partner 策略分析",
        "estimate_seconds": 240,
        "stage": "investment_committee",
    },
    {
        "step_name": "perplexity_wait",
        "label": "Deep Research Inbox 检查",
        "estimate_seconds": 15,
        "stage": "research_gate",
    },
    {
        "step_name": "chairman",
        "label": "CIO Agent 生成投委会报告",
        "estimate_seconds": 90,
        "stage": "cio",
    },
    {
        "step_name": "red_team",
        "label": "Risk Auditor 生成风险审计",
        "estimate_seconds": 90,
        "stage": "red_team",
    },
    {
        "step_name": "notify",
        "label": "归档与通知",
        "estimate_seconds": 10,
        "stage": "archive",
    },
]
TRADING_STEP_NAMES = {"trading_f_partner", "trading_w_partner", "trading_g_partner"}
RERUN_RUN_STEP_PLAN = [
    {
        "step_name": "trading_f_partner",
        "label": "Value Partner 重新分析",
        "estimate_seconds": 240,
        "stage": "investment_committee",
    },
    {
        "step_name": "trading_w_partner",
        "label": "Momentum Partner 重新分析",
        "estimate_seconds": 240,
        "stage": "investment_committee",
    },
    {
        "step_name": "trading_g_partner",
        "label": "Quality Partner 重新分析",
        "estimate_seconds": 240,
        "stage": "investment_committee",
    },
    {
        "step_name": "chairman",
        "label": "CIO Agent 二次报告",
        "estimate_seconds": 120,
        "stage": "cio",
    },
    {
        "step_name": "red_team",
        "label": "Risk Auditor 二次风险审计",
        "estimate_seconds": 120,
        "stage": "red_team",
    },
]
RESEARCH_SCAN_STEP_PLAN = [
    {
        "step_name": "research_scan",
        "label": "异常扫描 Agent 编排研究任务",
        "estimate_seconds": 120,
        "stage": "research",
    },
]

app = FastAPI(title="ResearchOS")
templates = Jinja2Templates(directory=str(PROJECT_ROOT / "templates"))
run_lock = asyncio.Lock()
background_tasks: set[asyncio.Task[Any]] = set()


@app.get("/")
def index(request: Request) -> Any:
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "active_page": "index",
            "today": datetime.now().strftime("%Y-%m-%d"),
            "env_status": get_env_status(),
            "trial_status": get_trial_status(),
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


@app.get("/learning")
def learning_page(request: Request) -> Any:
    return templates.TemplateResponse(
        request,
        "learning.html",
        {"active_page": "learning"},
    )


@app.get("/timeline/{ticker}")
def stock_timeline_page(request: Request, ticker: str) -> Any:
    return templates.TemplateResponse(
        request,
        "timeline.html",
        {"active_page": "learning", "ticker": ticker.upper()},
    )


@app.get("/guide")
def guide_page(request: Request) -> Any:
    return templates.TemplateResponse(
        request,
        "guide.html",
        {"active_page": "guide"},
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
    return stream_background_command_response(
        command,
        {"LLM_PROVIDER": provider},
        expected_history={
            "pipeline_type": "full",
            "date": date,
            "brief_type": brief_type,
        },
    )


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


@app.get("/api/research-scan-stream")
async def research_scan_stream(
    brief_type: str = Query("morning"),
    run_date: str = Query(..., alias="date"),
    no_llm: bool = Query(False),
) -> StreamingResponse:
    validate_brief_type(brief_type)
    date = normalize_date(run_date)
    command = build_agent_command("research", brief_type, date, no_llm)
    return stream_background_command_sequence_response(
        [("research_scan", command)],
        {},
        history={
            "pipeline_type": "research_scan",
            "trigger_source": "manual",
            "date": date,
            "brief_type": brief_type,
            "source": "research_scan",
            "no_llm": no_llm,
        },
    )


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
        "brief": read_markdown_result(brief_path, humanize_investment_terms=True),
        "audit": read_markdown_result(audit_path, humanize_investment_terms=True),
    }


@app.get("/api/artifact")
def api_artifact(path: str = Query(...)) -> dict[str, Any]:
    artifact_path = resolve_artifact_path(path)
    return read_markdown_result(artifact_path)


@app.get("/artifact/view", response_class=HTMLResponse)
def artifact_view(path: str = Query(...)) -> HTMLResponse:
    artifact_path = resolve_artifact_path(path)
    markdown_source = markdown_source_for_artifact(artifact_path)
    if markdown_source:
        return HTMLResponse(render_artifact_markdown(markdown_source, presentation_path=artifact_path))
    html_content = artifact_path.read_text(encoding="utf-8")
    return HTMLResponse(productize_report_text(html_content))


def markdown_source_for_artifact(path: Path) -> Path | None:
    if path.suffix.lower() == ".md":
        return path
    if path.suffix.lower() == ".html":
        sibling = path.with_suffix(".md")
        if sibling.exists():
            return sibling
    return None


def render_artifact_markdown(path: Path, *, presentation_path: Path | None = None) -> str:
    presentation_path = presentation_path or path
    markdown = path.read_text(encoding="utf-8")
    report_label = artifact_label_from_path(presentation_path)
    if report_label in {"IC Brief", "Risk Audit"}:
        markdown = humanize_investment_report(markdown)
    return render_report_html(
        markdown,
        ReportPresentation(
            title=path.stem,
            report_label=report_label,
            eyebrow="RESEARCHOS REPORT VIEW",
            source_path=relative_path(presentation_path),
        ),
    )


@app.get("/api/history")
def api_history(tail: int = Query(10, ge=1, le=100)) -> dict[str, Any]:
    reconcile_stale_running_runs()
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


@app.get("/api/learning")
def api_learning() -> dict[str, Any]:
    return {"ok": True, "learning": get_learning_overview()}


@app.get("/api/learning/timeline/{ticker}")
def api_learning_timeline(ticker: str) -> dict[str, Any]:
    return {"ok": True, "timeline": load_stock_timeline(DATA_DIR, ticker.upper())}


@app.post("/api/learning/refresh")
def api_learning_refresh(
    mode: str = Body("timelines"),
    as_of_date: str | None = Body(None),
    month: str | None = Body(None),
) -> dict[str, Any]:
    if mode == "outcomes":
        path = refresh_outcome_snapshots(DATA_DIR, as_of_date=normalize_date(as_of_date) if as_of_date else None)
        return {"ok": True, "paths": [str(path)]}
    if mode == "monthly":
        paths = write_monthly_review(DATA_DIR, month=month)
        return {"ok": True, "paths": [str(path) for path in paths] if paths else []}
    paths = rebuild_stock_timelines(DATA_DIR)
    return {"ok": True, "paths": [str(path) for path in paths]}


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


@app.get("/api/llm/health")
def api_llm_health() -> dict[str, Any]:
    return {"ok": True, "health": check_llm_health()}


@app.get("/api/trial-status")
def api_trial_status() -> dict[str, Any]:
    return {"ok": True, "trial_status": get_trial_status()}


@app.get("/api/ops-dashboard")
def api_ops_dashboard() -> dict[str, Any]:
    reconcile_stale_running_runs()
    return {"ok": True, "dashboard": build_ops_dashboard()}


@app.get("/api/run-progress")
def api_run_progress(run_id: str = Query(...)) -> dict[str, Any]:
    progress = build_run_progress(run_id)
    if not progress:
        raise HTTPException(status_code=404, detail=f"找不到运行档案：{run_id}")
    return {"ok": True, "progress": progress}


@app.post("/api/env")
def api_save_env(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    provider = str(payload.get("llm_provider") or "local").strip()
    model = str(payload.get("llm_model") or "").strip()
    api_key = str(payload.get("openai_api_key") or "")
    clear_api_key = bool(payload.get("clear_api_key"))
    if provider not in LLM_PROVIDERS:
        raise HTTPException(status_code=400, detail="模型通道只能是本地、OpenAI 或 Codex。")
    write_env_file(provider, model, api_key, clear_api_key)
    return {"ok": True, "message": ".env 已保存", "env": get_env_status()}


@app.get("/api/codex/login-status")
def api_codex_login_status() -> dict[str, Any]:
    return {"ok": True, "codex": get_codex_status()}


@app.get("/api/codex/login-stream")
def api_codex_login_stream() -> StreamingResponse:
    return StreamingResponse(
        stream_codex_login(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
        raise HTTPException(status_code=400, detail="Deep Research 结果不能为空。")

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
    synced = sync_signal_file_perplexity_status(DATA_DIR, prompt_id)
    knowledge_entry = ingest_filled_result(DATA_DIR, prompt_id, result_path=result_path)
    return {
        "ok": True,
        "message": "Deep Research 结果已保存",
        "prompt": shape_prompt_record(prompt["path"]),
        "synced_research_signals": [relative_path(path) for path in synced],
        "knowledge_entry": shape_knowledge_entry(knowledge_entry),
    }


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
        "reason": reason or "用户在 Web UI 中标记跳过。",
    }
    result_path = DATA_DIR / "perplexity_results" / f"{prompt_id}_skipped.yaml"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(yaml.safe_dump(result, allow_unicode=True, sort_keys=False), encoding="utf-8")

    filled_path = DATA_DIR / "perplexity_results" / f"{prompt_id}_filled.yaml"
    if filled_path.exists():
        filled_path.unlink()
    delete_entry_for_prompt(DATA_DIR, prompt_id)
    synced = sync_signal_file_perplexity_status(DATA_DIR, prompt_id)
    return {
        "ok": True,
        "message": "Prompt 已标记跳过",
        "prompt": shape_prompt_record(prompt["path"]),
        "synced_research_signals": [relative_path(path) for path in synced],
    }


@app.get("/api/deep-research/rerun-stream")
async def deep_research_rerun_stream(
    brief_type: str = Query("morning"),
    run_date: str = Query(..., alias="date"),
    no_llm: bool = Query(False),
) -> StreamingResponse:
    validate_brief_type(brief_type)
    date = normalize_date(run_date)
    commands = build_deep_research_rerun_commands(brief_type, date, no_llm)
    return stream_background_command_sequence_response(
        commands,
        {},
        history={
            "pipeline_type": "deep_research_rerun",
            "trigger_source": "manual",
            "date": date,
            "brief_type": brief_type,
            "no_llm": no_llm,
        },
    )


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


def stream_background_command_response(
    command: list[str],
    env_overrides: dict[str, str],
    expected_history: dict[str, Any] | None = None,
) -> StreamingResponse:
    return StreamingResponse(
        stream_background_command_start(command, env_overrides, expected_history=expected_history),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def stream_command_sequence_response(
    commands: list[tuple[str, list[str]]],
    env_overrides: dict[str, str],
    history: dict[str, Any] | None = None,
) -> StreamingResponse:
    return StreamingResponse(
        stream_command_sequence(commands, env_overrides, history=history),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def stream_background_command_start(
    command: list[str],
    env_overrides: dict[str, str],
    expected_history: dict[str, Any] | None = None,
):
    if run_lock.locked():
        yield sse("status", {"status": "busy", "message": "已有任务正在运行。"})
        yield sse("done", {"status": "busy", "return_code": 1})
        return
    if not shutil.which(command[0]):
        yield sse("error", {"status": "failed", "message": f"找不到 {command[0]}，请先安装。"})
        yield sse("done", {"status": "failed", "return_code": 127})
        return

    existing_run_ids = current_run_ids()
    await run_lock.acquire()
    try:
        task = asyncio.create_task(run_background_command(command, env_overrides))
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)
    except Exception as exc:
        if run_lock.locked():
            run_lock.release()
        yield sse("error", {"status": "failed", "message": f"后台任务创建失败：{exc}"})
        yield sse("done", {"status": "failed", "return_code": 1})
        return

    display_command = format_display_command(command, env_overrides)
    yield sse("start", {"command": display_command, "status": "running"})
    run_id = await wait_for_new_history_run(existing_run_ids, expected_history)
    message = f"已创建后台任务：{run_id}" if run_id else "已创建后台任务，稍后刷新运行历史查看。"
    yield sse(
        "status",
        {
            "status": "running",
            "message": message,
            "run_id": run_id,
        },
    )
    yield sse(
        "done",
        {
            "status": "running",
            "return_code": 0,
            "run_id": run_id,
            "history_path": "/history",
        },
    )


async def run_background_command(command: list[str], env_overrides: dict[str, str]) -> None:
    env = build_child_env(env_overrides)
    process: Any | None = None
    logs_dir = DATA_DIR / "webui_background_logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = logs_dir / f"command-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.out"
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=PROJECT_ROOT,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        assert process.stdout is not None
        with stdout_path.open("w", encoding="utf-8") as output:
            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                output.write(line.decode("utf-8", errors="replace"))
        await process.wait()
    except asyncio.CancelledError:
        await stop_process(process)
        raise
    finally:
        await stop_process(process)
        if run_lock.locked():
            run_lock.release()


def current_run_ids() -> set[str]:
    run_log = RunLog(DATA_DIR / "orchestrator" / "runs.db")
    return {str(row.get("run_id", "")) for row in run_log.list_runs(tail=100)}


async def wait_for_new_history_run(
    existing_run_ids: set[str],
    expected_history: dict[str, Any] | None,
    timeout_seconds: float = 5.0,
) -> str:
    if not expected_history:
        return ""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    while loop.time() < deadline:
        run_id = find_new_history_run(existing_run_ids, expected_history)
        if run_id:
            return run_id
        await asyncio.sleep(0.2)
    return ""


def find_new_history_run(existing_run_ids: set[str], expected_history: dict[str, Any]) -> str:
    run_log = RunLog(DATA_DIR / "orchestrator" / "runs.db")
    for row in run_log.list_runs(tail=50):
        run_id = str(row.get("run_id", ""))
        if run_id in existing_run_ids:
            continue
        if expected_history.get("pipeline_type") and row.get("pipeline_type") != expected_history["pipeline_type"]:
            continue
        metadata = parse_metadata_json(row.get("metadata_json", ""))
        if expected_history.get("date") and metadata.get("date") != expected_history["date"]:
            continue
        if expected_history.get("brief_type") and metadata.get("brief_type") != expected_history["brief_type"]:
            continue
        return run_id
    return ""


def stream_background_command_sequence_response(
    commands: list[tuple[str, list[str]]],
    env_overrides: dict[str, str],
    history: dict[str, Any],
) -> StreamingResponse:
    return StreamingResponse(
        stream_background_command_sequence_start(commands, env_overrides, history=history),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def stream_background_command_sequence_start(
    commands: list[tuple[str, list[str]]],
    env_overrides: dict[str, str],
    history: dict[str, Any],
):
    if run_lock.locked():
        yield sse("status", {"status": "busy", "message": "已有任务正在运行。"})
        yield sse("done", {"status": "busy", "return_code": 1})
        return

    await run_lock.acquire()
    lock_transferred = False
    try:
        run_log, run_id, history_metadata, logs_dir = create_background_history(history)
        task = asyncio.create_task(
            run_background_command_sequence(
                commands,
                env_overrides,
                run_log,
                run_id,
                history_metadata,
                logs_dir,
            )
        )
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)
        lock_transferred = True
    except Exception as exc:
        if not lock_transferred and run_lock.locked():
            run_lock.release()
        yield sse("error", {"status": "failed", "message": f"后台任务创建失败：{exc}"})
        yield sse("done", {"status": "failed", "return_code": 1})
        return

    yield sse(
        "status",
        {
            "status": "running",
            "message": f"已创建后台任务：{run_id}",
            "run_id": run_id,
        },
    )
    yield sse(
        "done",
        {
            "status": "running",
            "return_code": 0,
            "run_id": run_id,
            "history_path": "/history",
        },
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
    history: dict[str, Any] | None = None,
):
    if run_lock.locked():
        yield sse("status", {"status": "busy", "message": "已有任务正在运行。"})
        return

    async with run_lock:
        env = build_child_env(env_overrides)
        run_log: RunLog | None = None
        run_id = ""
        history_metadata: dict[str, Any] = {}
        logs_dir: Path | None = None
        active_process: Any | None = None
        active_step_name = ""
        active_stdout_lines: list[str] = []
        run_finished = False
        try:
            if history:
                run_log = RunLog(DATA_DIR / "orchestrator" / "runs.db")
                history_metadata = {
                    "brief_type": history["brief_type"],
                    "date": history["date"],
                    "source": "deep_research_rerun",
                    "no_llm": history["no_llm"],
                }
                run_id = run_log.create_run(
                    pipeline_type=history["pipeline_type"],
                    trigger_source=history["trigger_source"],
                    metadata=history_metadata,
                )
                logs_dir = DATA_DIR / "orchestrator" / "logs" / run_id
                logs_dir.mkdir(parents=True, exist_ok=True)
                yield sse(
                    "status",
                    {
                        "status": "running",
                        "message": f"已写入运行历史：{run_id}",
                        "run_id": run_id,
                    },
                )

            for index, (label, command) in enumerate(commands, start=1):
                display_command = format_display_command(command, env_overrides)
                step_name = RERUN_STEP_NAMES.get(
                    label,
                    re.sub(r"[^A-Za-z0-9_]+", "_", label).strip("_").lower(),
                )
                active_step_name = step_name
                active_stdout_lines = []
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
                    active_process = await asyncio.create_subprocess_exec(
                        *command,
                        cwd=PROJECT_ROOT,
                        env=env,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.STDOUT,
                    )
                except FileNotFoundError:
                    if run_log:
                        failed_metadata = dict(history_metadata)
                        failed_metadata["failed_step"] = step_name
                        run_log.finish_run(run_id, "failed", failed_metadata)
                        run_finished = True
                    active_step_name = ""
                    yield sse("error", {"status": "failed", "message": "找不到 uv，请先安装 uv。"})
                    yield sse(
                        "done",
                        {
                            "status": "failed",
                            "return_code": 127,
                            "step": label,
                            "run_id": run_id,
                            "history_path": "/history" if run_id else "",
                        },
                    )
                    return

                assert active_process.stdout is not None
                while True:
                    line = await active_process.stdout.readline()
                    if not line:
                        break
                    text = line.decode("utf-8", errors="replace").rstrip()
                    active_stdout_lines.append(text)
                    yield sse("log", {"line": text, "step": label})

                return_code = await active_process.wait()
                active_process = None
                if run_log and logs_dir:
                    stdout_path = logs_dir / f"{step_name}-1.out"
                    stderr_path = logs_dir / f"{step_name}-1.err"
                    stdout_path.write_text(
                        "\n".join(active_stdout_lines) + ("\n" if active_stdout_lines else ""),
                        encoding="utf-8",
                    )
                    stderr_path.write_text("", encoding="utf-8")
                    step_status = "success" if return_code == 0 else "failed"
                    run_log.record_step(
                        run_id,
                        StepResult(
                            step_name=step_name,
                            status=step_status,
                            exit_code=return_code,
                            attempts=1,
                            stdout_path=stdout_path,
                            stderr_path=stderr_path,
                            output_files=output_files_for_rerun_step(
                                step_name,
                                history_metadata.get("date", ""),
                                history_metadata.get("brief_type", ""),
                            ),
                        ),
                    )
                if return_code != 0:
                    active_step_name = ""
                    if run_log:
                        failed_metadata = dict(history_metadata)
                        failed_metadata["failed_step"] = step_name
                        run_log.finish_run(run_id, "failed", failed_metadata)
                        run_finished = True
                    yield sse(
                        "done",
                        {
                            "status": "failed",
                            "return_code": return_code,
                            "step": label,
                            "run_id": run_id,
                            "history_path": "/history" if run_id else "",
                        },
                    )
                    return
                active_step_name = ""
                active_stdout_lines = []
            if run_log:
                run_log.finish_run(run_id, "completed", history_metadata)
                run_finished = True
            yield sse(
                "done",
                {
                    "status": "completed",
                    "return_code": 0,
                    "run_id": run_id,
                    "history_path": "/history" if run_id else "",
                },
            )
        except (asyncio.CancelledError, GeneratorExit):
            await stop_process(active_process)
            if run_log and not run_finished:
                cancelled_metadata = dict(history_metadata)
                cancelled_metadata["cancelled"] = True
                if active_step_name:
                    cancelled_metadata["failed_step"] = active_step_name
                    if logs_dir:
                        record_cancelled_rerun_step(
                            run_log,
                            run_id,
                            logs_dir,
                            active_step_name,
                            active_stdout_lines,
                            history_metadata,
                            active_process.returncode if active_process else None,
                        )
                run_log.finish_run(run_id, "cancelled", cancelled_metadata)
            raise
        finally:
            await stop_process(active_process)


def create_background_history(history: dict[str, Any]) -> tuple[RunLog, str, dict[str, Any], Path]:
    run_log = RunLog(DATA_DIR / "orchestrator" / "runs.db")
    history_metadata = {
        "brief_type": history["brief_type"],
        "date": history["date"],
        "source": history.get("source") or history["pipeline_type"],
        "background": True,
    }
    if "no_llm" in history:
        history_metadata["no_llm"] = history["no_llm"]
    run_id = run_log.create_run(
        pipeline_type=history["pipeline_type"],
        trigger_source=history["trigger_source"],
        metadata=history_metadata,
    )
    logs_dir = DATA_DIR / "orchestrator" / "logs" / run_id
    logs_dir.mkdir(parents=True, exist_ok=True)
    return run_log, run_id, history_metadata, logs_dir


def create_rerun_history(history: dict[str, Any]) -> tuple[RunLog, str, dict[str, Any], Path]:
    history = {**history, "source": "deep_research_rerun"}
    return create_background_history(history)


async def run_background_command_sequence(
    commands: list[tuple[str, list[str]]],
    env_overrides: dict[str, str],
    run_log: RunLog,
    run_id: str,
    history_metadata: dict[str, Any],
    logs_dir: Path,
) -> None:
    env = build_child_env(env_overrides)
    active_process: Any | None = None
    active_step_name = ""
    active_stdout_lines: list[str] = []
    run_finished = False
    try:
        if history_metadata.get("source") == "deep_research_rerun":
            cleanup_removed = cleanup_deep_research_rerun_outputs(
                history_metadata.get("date", ""),
                history_metadata.get("brief_type", ""),
            )
            history_metadata["cleanup_removed_count"] = len(cleanup_removed)
        for label, command in commands:
            step_name = RERUN_STEP_NAMES.get(
                label,
                re.sub(r"[^A-Za-z0-9_]+", "_", label).strip("_").lower(),
            )
            active_step_name = step_name
            active_stdout_lines = []
            try:
                active_process = await asyncio.create_subprocess_exec(
                    *command,
                    cwd=PROJECT_ROOT,
                    env=env,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
            except FileNotFoundError:
                record_background_rerun_step(
                    run_log,
                    run_id,
                    logs_dir,
                    step_name,
                    active_stdout_lines,
                    "找不到 uv，请先安装 uv。\n",
                    "failed",
                    127,
                    history_metadata,
                )
                failed_metadata = dict(history_metadata)
                failed_metadata["failed_step"] = step_name
                run_log.finish_run(run_id, "failed", failed_metadata)
                run_finished = True
                return

            assert active_process.stdout is not None
            while True:
                line = await active_process.stdout.readline()
                if not line:
                    break
                active_stdout_lines.append(line.decode("utf-8", errors="replace").rstrip())

            return_code = await active_process.wait()
            active_process = None
            step_status = "success" if return_code == 0 else "failed"
            record_background_rerun_step(
                run_log,
                run_id,
                logs_dir,
                step_name,
                active_stdout_lines,
                "",
                step_status,
                return_code,
                history_metadata,
            )
            if return_code != 0:
                failed_metadata = dict(history_metadata)
                failed_metadata["failed_step"] = step_name
                run_log.finish_run(run_id, "failed", failed_metadata)
                run_finished = True
                return
            active_step_name = ""
            active_stdout_lines = []

        run_log.finish_run(run_id, "completed", history_metadata)
        run_finished = True
    except asyncio.CancelledError:
        await stop_process(active_process)
        if not run_finished:
            cancelled_metadata = dict(history_metadata)
            cancelled_metadata["cancelled"] = True
            if active_step_name:
                cancelled_metadata["failed_step"] = active_step_name
                record_cancelled_rerun_step(
                    run_log,
                    run_id,
                    logs_dir,
                    active_step_name,
                    active_stdout_lines,
                    history_metadata,
                    active_process.returncode if active_process else None,
                )
            run_log.finish_run(run_id, "cancelled", cancelled_metadata)
        raise
    except Exception as exc:
        await stop_process(active_process)
        if not run_finished:
            failed_metadata = dict(history_metadata)
            failed_metadata["failed_step"] = active_step_name or "unknown"
            failed_metadata["error"] = str(exc)[:500]
            run_log.finish_run(run_id, "failed", failed_metadata)
    finally:
        await stop_process(active_process)
        if run_lock.locked():
            run_lock.release()


def record_background_rerun_step(
    run_log: RunLog,
    run_id: str,
    logs_dir: Path,
    step_name: str,
    stdout_lines: list[str],
    stderr_text: str,
    status: str,
    exit_code: int | None,
    history_metadata: dict[str, Any],
) -> None:
    stdout_path = logs_dir / f"{step_name}-1.out"
    stderr_path = logs_dir / f"{step_name}-1.err"
    stdout_path.write_text("\n".join(stdout_lines) + ("\n" if stdout_lines else ""), encoding="utf-8")
    stderr_path.write_text(stderr_text, encoding="utf-8")
    run_log.record_step(
        run_id,
        StepResult(
            step_name=step_name,
            status=status,
            exit_code=exit_code,
            attempts=1,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            output_files=output_files_for_rerun_step(
                step_name,
                history_metadata.get("date", ""),
                history_metadata.get("brief_type", ""),
            ),
        ),
    )


def record_cancelled_rerun_step(
    run_log: RunLog,
    run_id: str,
    logs_dir: Path,
    step_name: str,
    stdout_lines: list[str],
    history_metadata: dict[str, Any],
    exit_code: int | None,
) -> None:
    stdout_path = logs_dir / f"{step_name}-1.out"
    stderr_path = logs_dir / f"{step_name}-1.err"
    stdout_path.write_text("\n".join(stdout_lines) + ("\n" if stdout_lines else ""), encoding="utf-8")
    stderr_path.write_text("cancelled\n", encoding="utf-8")
    run_log.record_step(
        run_id,
        StepResult(
            step_name=step_name,
            status="cancelled",
            exit_code=exit_code,
            attempts=1,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            output_files=output_files_for_rerun_step(
                step_name,
                history_metadata.get("date", ""),
                history_metadata.get("brief_type", ""),
            ),
        ),
    )


async def stream_codex_login():
    if not shutil.which("codex"):
        yield sse("error", {"status": "failed", "message": "找不到 codex CLI，请先安装 Codex。"})
        yield sse("done", {"status": "failed", "return_code": 127})
        return

    command = ["codex", "login", "--device-auth"]
    yield sse("start", {"command": format_display_command(command, {}), "status": "running"})
    process = None
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=PROJECT_ROOT,
            env=build_child_env(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except FileNotFoundError:
        yield sse("error", {"status": "failed", "message": "找不到 codex CLI，请先安装 Codex。"})
        yield sse("done", {"status": "failed", "return_code": 127})
        return

    try:
        assert process.stdout is not None
        loop = asyncio.get_running_loop()
        deadline = loop.time() + CODEX_LOGIN_TIMEOUT_SECONDS
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                await stop_process(process)
                yield sse("error", {"status": "failed", "message": "Codex 登录超时，请重新启动登录。"})
                yield sse("done", {"status": "failed", "return_code": 124})
                return
            try:
                line = await asyncio.wait_for(process.stdout.readline(), timeout=remaining)
            except asyncio.TimeoutError:
                await stop_process(process)
                yield sse("error", {"status": "failed", "message": "Codex 登录超时，请重新启动登录。"})
                yield sse("done", {"status": "failed", "return_code": 124})
                return
            if not line:
                break
            yield sse("log", {"line": line.decode("utf-8", errors="replace").rstrip()})

        return_code = await process.wait()
        status = "completed" if return_code == 0 else "failed"
        yield sse("done", {"status": status, "return_code": return_code, "codex": get_codex_status()})
    except asyncio.CancelledError:
        await stop_process(process)
        raise
    finally:
        await stop_process(process)


async def stop_process(process: Any) -> None:
    if process is None or process.returncode is not None:
        return
    process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=5)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()


def sse(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def build_deep_research_rerun_commands(
    brief_type: str,
    date: str,
    no_llm: bool,
) -> list[tuple[str, list[str]]]:
    trading_commands = [
        (
            "Value Partner Agent",
            ["uv", "run", "trading-f_partner", "run", "--date", date, "--data-dir", "data"],
        ),
        (
            "Momentum Partner Agent",
            ["uv", "run", "trading-w_partner", "run", "--date", date, "--data-dir", "data"],
        ),
        (
            "Quality Partner Agent",
            ["uv", "run", "trading-g_partner", "run", "--date", date, "--data-dir", "data"],
        ),
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
        ("CIO Agent", chairman_command),
        ("Risk Auditor", red_team_command),
    ]


def output_files_for_rerun_step(step_name: str, date: str, brief_type: str) -> list[Path]:
    if not date or not brief_type:
        return []
    compact = date.replace("-", "")
    suffix = BRIEF_TYPES.get(brief_type)
    if not suffix:
        return []
    if step_name == "chairman":
        return [
            path
            for path in (
                DATA_DIR / "briefs" / compact / f"BRIEF-{compact}-{suffix}.md",
                DATA_DIR / "briefs" / compact / f"BRIEF-{compact}-{suffix}.html",
                DATA_DIR / "briefs" / compact / f"BRIEF-{compact}-{suffix}.json",
            )
            if path.exists()
        ]
    if step_name == "red_team":
        return [
            path
            for path in (
                DATA_DIR / "red_team_audits" / compact / f"AUDIT-{compact}-{suffix}.md",
                DATA_DIR / "red_team_audits" / compact / f"AUDIT-{compact}-{suffix}.html",
                DATA_DIR / "red_team_audits" / compact / f"AUDIT-{compact}-{suffix}.json",
            )
            if path.exists()
        ]
    return []


def build_agent_command(agent: str, brief_type: str, date: str, no_llm: bool) -> list[str]:
    if agent in AGENT_COMMANDS:
        command = list(AGENT_COMMANDS[agent])
        if agent == "research":
            command.extend(["--date", date])
        elif agent in {"f_partner", "w_partner", "g_partner"}:
            command.extend(["--date", date])
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
    for suffix in (".html", ".md"):
        exact = directory / f"{basename}{suffix}"
        if exact.exists():
            return exact
    if not directory.exists():
        return None
    for suffix in (".html", ".md"):
        candidates = sorted(directory.glob(f"{basename}*{suffix}"))
        if candidates:
            return candidates[-1]
    return None


def read_markdown_result(
    path: Path | None,
    *,
    humanize_investment_terms: bool = False,
) -> dict[str, Any]:
    if not path or not path.exists():
        return {"exists": False, "path": "", "content": "", "format": ""}
    content = path.read_text(encoding="utf-8")
    file_format = "html" if path.suffix.lower() == ".html" else "markdown"
    if file_format == "html":
        content = productize_report_text(content)
    elif humanize_investment_terms:
        content = humanize_investment_report(content)
    return {
        "exists": True,
        "path": relative_path(path),
        "content": content,
        "format": file_format,
    }


def artifact_label_from_path(path: Path) -> str:
    parts = set(path.parts)
    if "red_team_audits" in parts:
        return "Risk Audit"
    if "briefs" in parts:
        return "IC Brief"
    return "Report"


def humanize_investment_report(content: str) -> str:
    """Convert internal direction/verdict labels into user-facing advice labels."""

    replacements = [
        ("第一阶段禁止输出 long/short/leverage/put/hedge", "当前不展示杠杆、衍生品或内部方向标签"),
        ("第一阶段禁止 long/short/leverage/put/hedge", "当前不展示杠杆、衍生品或内部方向标签"),
        ("三方一致 long", "三方一致买入候选"),
        ("三方一致 avoid", "三方一致回避"),
        ("多数 abstain", "多数暂不判断"),
        ("多数 avoid", "多数回避"),
        ("多数 long", "多数买入候选"),
        ("全员 abstain", "全员暂不判断"),
        ("long / avoid 分歧", "买入候选 / 回避分歧"),
        ("long / watch 混合", "买入候选 / 观察混合"),
        ("| Agent | direction |", "| Agent | 投资建议 |"),
        ("**final_verdict**", "**CIO 裁决**"),
        ("first_phase_long_disabled", "证据未闭环降级"),
        ("final_verdict", "CIO 裁决"),
        ("试运行期禁用 long", "证据闭环不足，暂不升级为买入候选"),
        ("long/short/leverage/put/hedge", "买入候选/反向风险/杠杆/期权/对冲"),
        ("第一阶段 long 禁用", "证据闭环不足，暂不升级为买入候选"),
        ("第一阶段禁止 long", "证据闭环不足，暂不升级为买入候选"),
        ("禁止 long", "禁止直接给出买入候选"),
        ("不能升级为 long", "不能升级为买入候选"),
        ("输出 long", "输出买入候选"),
        ("只能保守 watch", "只能保守观察"),
        ("只能输出 watch", "只能输出观察"),
        ("只能 watch", "只能观察"),
        ("更保守的 abstain", "更保守的暂不判断"),
        ("维持 watch 或 abstain", "维持观察或暂不判断"),
        ("watch 或 abstain", "观察或暂不判断"),
    ]
    rendered = content
    for old, new in replacements:
        rendered = rendered.replace(old, new)
    direction_labels = {
        "long": "买入候选",
        "short": "反向风险",
        "watch": "观察",
        "avoid": "回避",
        "abstain": "暂不判断",
        "act": "行动候选",
        "wait": "等待观察",
        "reject": "否决",
        "research_more": "补充研究",
    }

    def replace_bold(match: re.Match[str]) -> str:
        return f"**{direction_labels.get(match.group(1), match.group(1))}**"

    def replace_inline_code(match: re.Match[str]) -> str:
        return direction_labels.get(match.group(1), match.group(1))

    rendered = re.sub(r"\*\*(long|short|watch|avoid|abstain)\*\*", replace_bold, rendered)
    rendered = re.sub(r"`(act|wait|reject|research_more)`", replace_inline_code, rendered)
    rendered = re.sub(
        r"\b(f_partner|w_partner|g_partner):(long|short|watch|avoid|abstain)\b",
        lambda match: f"{match.group(1)}:{direction_labels[match.group(2)]}",
        rendered,
    )
    rendered = re.sub(
        r"\b方向为 (long|short|watch|avoid|abstain)\b",
        lambda match: f"投资建议为 {direction_labels[match.group(1)]}",
        rendered,
    )
    rendered = re.sub(
        r"\b/ (long|short|watch|avoid|abstain)\b",
        lambda match: f"/ {direction_labels[match.group(1)]}",
        rendered,
    )
    rendered = re.sub(
        r"\|\s*(long|short|watch|avoid|abstain)\s*\|",
        lambda match: f"| {direction_labels[match.group(1)]} |",
        rendered,
    )
    rendered = re.sub(
        r"\b只能 (long|short|watch|avoid|abstain)\b",
        lambda match: f"只能 {direction_labels[match.group(1)]}",
        rendered,
    )
    rendered = re.sub(
        r"\b(direction|selected_direction|final_direction|action)=("
        r"long|short|watch|avoid|abstain)\b",
        lambda match: f"{match.group(1)}={direction_labels[match.group(2)]}",
        rendered,
    )
    return productize_report_text(rendered)


def resolve_artifact_path(path_text: str) -> Path:
    if not path_text.strip():
        raise HTTPException(status_code=400, detail="报告路径不能为空。")
    if Path(path_text).is_absolute():
        raise HTTPException(status_code=400, detail="只能读取项目内产物。")
    candidate = (PROJECT_ROOT / path_text).resolve()
    data_root = DATA_DIR.resolve()
    if not candidate.is_relative_to(data_root):
        raise HTTPException(status_code=400, detail="只能读取 data 目录下的产物。")
    if candidate.suffix.lower() not in {".md", ".html"}:
        raise HTTPException(status_code=400, detail="当前只支持查看 Markdown / HTML 产物。")
    if not candidate.exists():
        raise HTTPException(status_code=404, detail="产物文件不存在。")
    return candidate


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
    status_payload = deep_research_status(prompt_id, prompt_text=prompt_text, related_signal_id=related_signal_id)
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


def shape_knowledge_entry(entry: Any) -> dict[str, Any] | None:
    if entry is None:
        return None
    return {
        "entry_id": entry.entry_id,
        "source_pr_id": entry.source_pr_id,
        "stock_code": entry.stock_code,
        "prompt_id": entry.prompt_id,
        "ticker": entry.ticker,
        "related_signal_id": entry.related_signal_id,
        "research_date": entry.research_date,
        "event_date": entry.event_date,
        "expires_at": entry.expires_at,
        "cards_path": relative_path(
            DATA_DIR / "knowledge_store" / "cards" / f"{entry.ticker}.md"
        ),
        "company_conclusions_count": len(entry.company_conclusions),
        "industry_conclusions_count": len(entry.industry_conclusions),
        "unverified_claims_count": len(entry.unverified_claims),
        "open_questions_count": len(entry.open_questions),
    }


def build_prompt_markdown(
    prompt_id: str,
    related_signal_id: str,
    priority: str,
    prompt_text: str,
) -> str:
    lines = [
        "# Deep Research Prompt",
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


def deep_research_status(
    prompt_id: str,
    *,
    prompt_text: str = "",
    related_signal_id: str = "",
) -> dict[str, Any]:
    results_dir = DATA_DIR / "perplexity_results"
    filled_path = results_dir / f"{prompt_id}_filled.yaml"
    skipped_path = results_dir / f"{prompt_id}_skipped.yaml"
    if filled_path.exists():
        data = read_yaml_file(filled_path)
        mismatch = deep_research_result_mismatch(data, prompt_id, prompt_text, related_signal_id)
        if mismatch:
            return {
                "status": "pending",
                "status_label": "待回填",
                "result_path": "",
                "answer_text": "",
                "updated_at": "",
                "skip_reason": "",
                "ignored_result_path": relative_path(filled_path),
                "ignored_result_reason": mismatch,
            }
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
        mismatch = deep_research_result_mismatch(data, prompt_id, prompt_text, related_signal_id)
        if mismatch:
            return {
                "status": "pending",
                "status_label": "待回填",
                "result_path": "",
                "answer_text": "",
                "updated_at": "",
                "skip_reason": "",
                "ignored_result_path": relative_path(skipped_path),
                "ignored_result_reason": mismatch,
            }
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


def deep_research_result_mismatch(
    data: Any,
    prompt_id: str,
    prompt_text: str,
    related_signal_id: str,
) -> str:
    if not isinstance(data, dict):
        return ""
    actual_prompt_id = str(data.get("prompt_id") or "")
    if actual_prompt_id and actual_prompt_id != prompt_id:
        return "prompt_id 不一致，已忽略旧回填。"
    actual_signal_id = str(data.get("related_signal_id") or "")
    if actual_signal_id and related_signal_id and actual_signal_id != related_signal_id:
        return "related_signal_id 不一致，已忽略旧回填。"
    actual_prompt_text = " ".join(str(data.get("prompt_text") or "").split())
    expected_prompt_text = " ".join(prompt_text.split())
    if actual_prompt_text and expected_prompt_text and actual_prompt_text != expected_prompt_text:
        return "prompt 文本不一致，已忽略旧回填。"
    return ""


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


def read_yaml_file_safely(path: Path) -> Any:
    try:
        return read_yaml_file(path)
    except (OSError, yaml.YAMLError):
        return {}


def reconcile_stale_running_runs(max_age_seconds: int = RUNNING_RUN_STALE_SECONDS) -> list[str]:
    run_log = RunLog(DATA_DIR / "orchestrator" / "runs.db")
    rows = run_log.list_runs(status="running", tail=100)
    if not rows:
        return []

    now = datetime.now().astimezone()
    cancelled_run_ids: list[str] = []
    tracked_rows: list[tuple[dict[str, Any], dict[str, Any], str]] = []
    for row in rows:
        metadata = parse_metadata_json(row.get("metadata_json", ""))
        tracked_type = resumable_background_run_type(row, metadata)
        if not tracked_type:
            continue
        tracked_rows.append((row, metadata, tracked_type))

    duplicate_groups: dict[tuple[str, str, str], list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    for row, metadata, tracked_type in tracked_rows:
        key = (
            tracked_type,
            str(metadata.get("date") or row.get("started_at", "")[:10]),
            str(metadata.get("brief_type") or ""),
        )
        duplicate_groups.setdefault(key, []).append((row, metadata))

    for group in duplicate_groups.values():
        if len(group) <= 1:
            continue
        group.sort(
            key=lambda item: parse_datetime(item[0].get("started_at", ""))
            or datetime.min.replace(tzinfo=now.tzinfo),
            reverse=True,
        )
        keeper = group[0][0]
        for row, metadata in group[1:]:
            cancelled_metadata = dict(metadata)
            cancelled_metadata["cancelled"] = True
            cancelled_metadata.setdefault("failed_step", "superseded")
            cancelled_metadata["cancelled_reason"] = "superseded_by_newer_running_run"
            cancelled_metadata["superseded_by_run_id"] = keeper.get("run_id", "")
            run_log.finish_run(row["run_id"], "cancelled", cancelled_metadata)
            cancelled_run_ids.append(row["run_id"])

    stale_rows: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for row, metadata, _tracked_type in tracked_rows:
        if row["run_id"] in cancelled_run_ids:
            continue
        started_at = parse_datetime(row.get("started_at", ""))
        if started_at and now - started_at < timedelta(seconds=max_age_seconds):
            continue
        stale_rows.append((row, metadata))

    if not stale_rows or has_active_background_rerun_task() or has_active_rerun_process():
        return cancelled_run_ids

    for row, metadata in stale_rows:
        cancelled_metadata = dict(metadata)
        cancelled_metadata["cancelled"] = True
        cancelled_metadata.setdefault("failed_step", "unknown")
        cancelled_metadata["cancelled_reason"] = "stale_running_without_backend_process"
        run_log.finish_run(row["run_id"], "cancelled", cancelled_metadata)
        cancelled_run_ids.append(row["run_id"])
    return cancelled_run_ids


def resumable_background_run_type(row: dict[str, Any], metadata: dict[str, Any]) -> str:
    pipeline_type = str(row.get("pipeline_type") or "")
    source = str(metadata.get("source") or "")
    for tracked_type in ("deep_research_rerun", "research_scan"):
        if pipeline_type == tracked_type or source == tracked_type:
            return tracked_type
    return ""


def has_active_background_rerun_task() -> bool:
    return any(not task.done() for task in background_tasks)


def parse_metadata_json(value: str) -> dict[str, Any]:
    try:
        metadata = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return metadata if isinstance(metadata, dict) else {}


def parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return parsed


def has_active_rerun_process() -> bool:
    process_markers = (
        ("research-agent", "run", "--type", "scan", "--data-dir"),
        ("trading-f_partner", "run", "--data-dir"),
        ("trading-w_partner", "run", "--data-dir"),
        ("trading-g_partner", "run", "--data-dir"),
        ("chairman", "generate-brief"),
        ("red-team", "audit"),
        ("Codex CLI acting as an LLM provider for worldpay77",),
    )
    try:
        result = subprocess.run(
            ["ps", "-axo", "command"],
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return True
    if result.returncode != 0:
        return True
    return any(
        process_command_matches(line, marker_tokens)
        for line in result.stdout.splitlines()
        for marker_tokens in process_markers
    )


def process_command_matches(command_line: str, marker_tokens: tuple[str, ...]) -> bool:
    return all(token in command_line for token in marker_tokens)


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

    for dirname in (
        "research_signals",
        "research_runs",
        "pull_requests",
        "perplexity_results",
        "agent_logs",
        "errors",
    ):
        remove_matching_children(DATA_DIR / dirname, date, compact, removed)

    remove_matching_children(DATA_DIR / "orchestrator" / "logs", date, compact, removed)
    for run_id in cleanup_run_history(date, compact):
        remove_path(DATA_DIR / "orchestrator" / "logs" / run_id, removed)
    return removed


def cleanup_deep_research_rerun_outputs(date: str, brief_type: str) -> list[str]:
    """Remove downstream outputs that would otherwise mix old and new reruns."""

    if not date or brief_type not in BRIEF_TYPES:
        return []
    compact = date.replace("-", "")
    suffix = BRIEF_TYPES[brief_type]
    removed: list[str] = []
    for path in (
        DATA_DIR / "recommendations" / compact,
        DATA_DIR / "agent_logs" / compact,
        DATA_DIR / "briefs" / compact / f"BRIEF-{compact}-{suffix}.md",
        DATA_DIR / "briefs" / compact / f"BRIEF-{compact}-{suffix}.html",
        DATA_DIR / "briefs" / compact / f"BRIEF-{compact}-{suffix}.json",
        DATA_DIR / "red_team_audits" / compact / f"AUDIT-{compact}-{suffix}.md",
        DATA_DIR / "red_team_audits" / compact / f"AUDIT-{compact}-{suffix}.html",
        DATA_DIR / "red_team_audits" / compact / f"AUDIT-{compact}-{suffix}.json",
    ):
        remove_path(path, removed)
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
        "codex": get_codex_status(),
    }


def check_llm_health() -> dict[str, Any]:
    values = read_env_values(ENV_PATH)
    provider = values.get("LLM_PROVIDER", "local")
    model = values.get("LLM_MODEL", "")
    started = datetime.now()
    try:
        client = build_llm_client_from_env()
        text = client.complete(
            system_prompt="You are a health check endpoint. Return exactly OK.",
            user_prompt="Return exactly OK.",
            max_tokens=20,
            timeout_seconds=60,
            temperature=0,
        )
    except Exception as exc:
        return {
            "status": "failed",
            "ok": False,
            "provider": provider,
            "model": model,
            "latency_seconds": round((datetime.now() - started).total_seconds(), 2),
            "detail": str(exc)[:500],
        }
    normalized = text.strip().upper()
    ok = normalized == "OK"
    return {
        "status": "ok" if ok else "unexpected_output",
        "ok": ok,
        "provider": provider,
        "model": model,
        "latency_seconds": round((datetime.now() - started).total_seconds(), 2),
        "detail": text[:500],
    }


def get_codex_status() -> dict[str, Any]:
    if not shutil.which("codex"):
        return {
            "available": False,
            "status": "unavailable",
            "label": "codex 不可用",
            "detail": "PATH 中未找到 codex CLI。",
        }
    try:
        completed = subprocess.run(
            ["codex", "login", "status"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            cwd=PROJECT_ROOT,
        )
    except FileNotFoundError:
        return {
            "available": False,
            "status": "unavailable",
            "label": "codex 不可用",
            "detail": "PATH 中未找到 codex CLI。",
        }
    except subprocess.TimeoutExpired:
        return {
            "available": True,
            "status": "unknown",
            "label": "状态未知",
            "detail": "codex login status 超时。",
        }

    detail = "\n".join(part for part in (completed.stdout.strip(), completed.stderr.strip()) if part)
    if completed.returncode != 0:
        return {
            "available": True,
            "status": "logged_out",
            "label": "未登录",
            "detail": detail,
        }
    label = classify_codex_login_label(detail)
    return {
        "available": True,
        "status": "logged_in",
        "label": label,
        "detail": detail,
    }


def classify_codex_login_label(detail: str) -> str:
    lowered = detail.lower()
    if "chatgpt" in lowered:
        return "ChatGPT 登录"
    if "api key" in lowered or "api-key" in lowered:
        return "API key 登录"
    return "已登录"


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
    date = metadata.get("date") or started_at[:10]
    brief_type = metadata.get("brief_type") or metadata.get("step") or ""
    return {
        "run_id": row.get("run_id", ""),
        "date": date,
        "brief_type": brief_type,
        "pipeline_type": row.get("pipeline_type", ""),
        "source": metadata.get("source") or row.get("trigger_source", ""),
        "status": row.get("status", ""),
        "failed_step": metadata.get("failed_step", ""),
        "artifacts": find_run_artifacts_for_row(row, date, brief_type),
        "schema_repair_or_fallback": run_has_schema_repair_or_fallback(date, metadata),
        "started_at": started_at,
        "ended_at": row.get("ended_at") or "",
    }


def run_has_schema_repair_or_fallback(date: str, metadata: dict[str, Any]) -> bool:
    if metadata.get("schema_repair") or metadata.get("failed_step"):
        return True
    compact = compact_date(date)
    if not compact:
        return False

    rec_root = DATA_DIR / "recommendations" / compact
    if rec_root.exists():
        for path in sorted([*rec_root.rglob("*.yaml"), *rec_root.rglob("*.yml")]):
            if recommendation_has_repair_or_fallback(read_yaml_file_safely(path)):
                return True

    log_root = DATA_DIR / "agent_logs" / compact
    if log_root.exists():
        for path in sorted(log_root.rglob("*.json")):
            if json_file_has_repair_marker(path):
                return True
    return False


def compact_date(date: str) -> str:
    compact = re.sub(r"\D", "", date or "")
    return compact if len(compact) == 8 else ""


def recommendation_has_repair_or_fallback(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    payload = data.get("recommendation", data)
    if not isinstance(payload, dict):
        return False
    if truthy_schema_repair(payload.get("schema_repair")) or payload.get("validation_failure"):
        return True
    policy = payload.get("trial_run_policy")
    return isinstance(policy, dict) and bool(policy.get("fallback_reason"))


def truthy_schema_repair(value: Any) -> bool:
    if not value:
        return False
    if not isinstance(value, dict):
        return True
    return bool(value.get("attempts") or value.get("errors"))


def json_file_has_repair_marker(path: Path) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return contains_repair_marker(payload)


def contains_repair_marker(value: Any) -> bool:
    if isinstance(value, dict):
        if truthy_schema_repair(value.get("schema_repair")) or value.get("validation_failure"):
            return True
        if value.get("fallback_reason"):
            return True
        return any(contains_repair_marker(item) for item in value.values())
    if isinstance(value, list):
        return any(contains_repair_marker(item) for item in value)
    return False


def find_run_artifacts(date: str, brief_type: str) -> dict[str, str]:
    if not date or brief_type not in BRIEF_TYPES:
        return {}
    compact = date.replace("-", "")
    suffix = BRIEF_TYPES[brief_type]
    brief = find_report_file(DATA_DIR / "briefs" / compact, f"BRIEF-{compact}-{suffix}")
    audit = find_report_file(DATA_DIR / "red_team_audits" / compact, f"AUDIT-{compact}-{suffix}")
    artifacts: dict[str, str] = {}
    if brief:
        artifacts["brief"] = relative_path(brief)
    if audit:
        artifacts["audit"] = relative_path(audit)
    return artifacts


def find_run_artifacts_for_row(row: dict[str, Any], date: str, brief_type: str) -> dict[str, str]:
    """Prefer artifacts recorded for this run; never show stale files for running rows."""

    status = str(row.get("status") or "")
    if status == "running":
        return {}
    run_id = str(row.get("run_id") or "")
    artifacts = find_recorded_run_artifacts(run_id)
    if artifacts:
        return artifacts
    if status in {"completed", "partial_success"}:
        return find_run_artifacts(date, brief_type)
    return {}


def find_recorded_run_artifacts(run_id: str) -> dict[str, str]:
    if not run_id:
        return {}
    db_path = DATA_DIR / "orchestrator" / "runs.db"
    if not db_path.exists():
        return {}
    artifacts: dict[str, str] = {}
    try:
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                """
                SELECT output_files_json
                FROM step_executions
                WHERE run_id = ?
                ORDER BY ended_at ASC
                """,
                (run_id,),
            ).fetchall()
    except sqlite3.Error:
        return {}
    for (value,) in rows:
        try:
            paths = json.loads(value or "[]")
        except json.JSONDecodeError:
            continue
        if not isinstance(paths, list):
            continue
        for path_text in paths:
            path = Path(str(path_text))
            if path.suffix.lower() not in {".md", ".html"}:
                continue
            path_parts = set(path.parts)
            if "briefs" in path_parts:
                record_artifact_path(artifacts, "brief", path)
            elif "red_team_audits" in path_parts:
                record_artifact_path(artifacts, "audit", path)
    return artifacts


def record_artifact_path(artifacts: dict[str, str], key: str, path: Path) -> None:
    current = artifacts.get(key)
    if current and not (Path(current).suffix.lower() == ".md" and path.suffix.lower() == ".html"):
        return
    artifacts[key] = relative_path(path)


def build_run_progress(run_id: str) -> dict[str, Any]:
    run_log = RunLog(DATA_DIR / "orchestrator" / "runs.db")
    row = run_log.get_run(run_id)
    if not row:
        return {}
    metadata = parse_metadata_json(row.get("metadata_json", ""))
    step_plan = run_step_plan(row, metadata)
    step_rows = load_run_step_rows(run_id)
    steps = shape_run_progress_steps(row, step_rows, step_plan)
    active_steps = [step for step in steps if step["state"] == "running"]
    finished_steps = [
        step
        for step in steps
        if step["state"] in {"completed", "failed", "cancelled", "skipped"}
    ]
    total_estimate = sum(int(step["estimate_seconds"] or 0) for step in steps)
    remaining_estimate = sum(
        int(step["estimate_seconds"] or 0)
        for step in steps
        if step["state"] in {"running", "pending"}
    )
    progress_percent = 100 if row.get("status") == "completed" else round(len(finished_steps) / len(steps) * 100)
    started_at = parse_datetime(row.get("started_at", ""))
    ended_at = parse_datetime(row.get("ended_at", ""))
    return {
        "run_id": run_id,
        "status": row.get("status") or "unknown",
        "pipeline_type": row.get("pipeline_type") or "",
        "date": metadata.get("date") or "",
        "brief_type": metadata.get("brief_type") or "",
        "started_at": row.get("started_at") or "",
        "ended_at": row.get("ended_at") or "",
        "elapsed_seconds": elapsed_between(started_at, ended_at),
        "progress_percent": max(0, min(100, progress_percent)),
        "estimated_total_seconds": total_estimate,
        "estimated_remaining_seconds": remaining_estimate,
        "current_step_label": " / ".join(step["label"] for step in active_steps),
        "message": build_run_progress_message(
            row.get("status") or "",
            active_steps,
            row.get("pipeline_type") or "",
        ),
        "steps": steps,
    }


def run_step_plan(
    run_row: dict[str, Any],
    metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    pipeline_type = str(run_row.get("pipeline_type") or "")
    if pipeline_type == "research_scan" or metadata.get("source") == "research_scan":
        return RESEARCH_SCAN_STEP_PLAN
    if pipeline_type == "deep_research_rerun" or metadata.get("source") == "deep_research_rerun":
        return RERUN_RUN_STEP_PLAN
    return FULL_RUN_STEP_PLAN


def load_run_step_rows(run_id: str) -> dict[str, dict[str, Any]]:
    db_path = DATA_DIR / "orchestrator" / "runs.db"
    if not db_path.exists():
        return {}
    try:
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
    except sqlite3.DatabaseError:
        return {}
    return {str(row["step_name"]): dict(row) for row in rows}


def shape_run_progress_steps(
    run_row: dict[str, Any],
    step_rows: dict[str, dict[str, Any]],
    step_plan: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    active_step_names = infer_active_step_names(run_row, step_rows, step_plan)
    shaped: list[dict[str, Any]] = []
    for index, item in enumerate(step_plan, start=1):
        step_name = item["step_name"]
        row = step_rows.get(step_name)
        if row:
            state = map_step_status(row.get("status"))
            started_at = parse_datetime(row.get("started_at", ""))
            ended_at = parse_datetime(row.get("ended_at", ""))
            elapsed_seconds = elapsed_between(started_at, ended_at)
            attempts = row.get("attempt")
            exit_code = row.get("exit_code")
        elif step_name in active_step_names:
            state = "running"
            started_at = infer_running_step_started_at(step_name, step_plan, step_rows, run_row)
            ended_at = None
            elapsed_seconds = elapsed_between(started_at, ended_at)
            attempts = None
            exit_code = None
        elif str(run_row.get("status") or "") in {"completed", "failed", "partial_success", "cancelled"}:
            state = "skipped"
            started_at = None
            ended_at = None
            elapsed_seconds = None
            attempts = None
            exit_code = None
        else:
            state = "pending"
            started_at = None
            ended_at = None
            elapsed_seconds = None
            attempts = None
            exit_code = None
        shaped.append(
            {
                "index": index,
                "step_name": step_name,
                "label": item["label"],
                "stage": item["stage"],
                "state": state,
                "state_label": run_step_state_label(state),
                "estimate_seconds": item["estimate_seconds"],
                "elapsed_seconds": elapsed_seconds,
                "started_at": row.get("started_at", "") if row else "",
                "ended_at": row.get("ended_at", "") if row else "",
                "attempts": attempts,
                "exit_code": exit_code,
            }
        )
    return shaped


def infer_running_step_started_at(
    step_name: str,
    step_plan: list[dict[str, Any]],
    step_rows: dict[str, dict[str, Any]],
    run_row: dict[str, Any],
) -> datetime | None:
    """Estimate a current step start from the latest prior recorded step."""

    started_at = parse_datetime(run_row.get("started_at", ""))
    previous_times: list[datetime] = []
    for item in step_plan:
        planned_name = str(item["step_name"])
        if planned_name == step_name:
            break
        row = step_rows.get(planned_name)
        if not row:
            continue
        ended_at = parse_datetime(row.get("ended_at", ""))
        row_started_at = parse_datetime(row.get("started_at", ""))
        if ended_at:
            previous_times.append(ended_at)
        elif row_started_at:
            previous_times.append(row_started_at)
    if previous_times:
        return max(previous_times)
    return started_at


def infer_active_step_names(
    run_row: dict[str, Any],
    step_rows: dict[str, dict[str, Any]],
    step_plan: list[dict[str, Any]],
) -> set[str]:
    if str(run_row.get("status") or "") != "running":
        return set()
    recorded = set(step_rows)
    plan_names = [str(item["step_name"]) for item in step_plan]
    if plan_names == [str(item["step_name"]) for item in RERUN_RUN_STEP_PLAN]:
        for step_name in plan_names:
            if step_name not in recorded:
                return {step_name}
        return set()
    if "research_scan" not in recorded:
        return {"research_scan"}
    missing_trading = TRADING_STEP_NAMES - recorded
    if missing_trading:
        return missing_trading
    for item in step_plan:
        step_name = item["step_name"]
        if step_name not in recorded:
            return {step_name}
    return set()


def map_step_status(status: Any) -> str:
    normalized = str(status or "").lower()
    if normalized == "success":
        return "completed"
    if normalized in {"failed", "cancelled", "skipped", "pending", "running"}:
        return normalized
    return "completed" if normalized else "pending"


def run_step_state_label(state: str) -> str:
    mapping = {
        "completed": "完成",
        "running": "运行中",
        "pending": "等待",
        "failed": "失败",
        "cancelled": "已取消",
        "skipped": "未执行",
    }
    return mapping.get(state, state)


def elapsed_between(started_at: datetime | None, ended_at: datetime | None) -> int | None:
    if not started_at:
        return None
    end = ended_at or datetime.now().astimezone()
    return max(0, round((end - started_at).total_seconds()))


def build_run_progress_message(
    status: str,
    active_steps: list[dict[str, Any]],
    pipeline_type: str = "",
) -> str:
    if status == "completed":
        if pipeline_type == "research_scan":
            return "研究任务已生成，请继续回填 Deep Research。"
        return "本轮投委会已完成，报告可读取。"
    if status in {"failed", "partial_success"}:
        return "本轮运行未完全成功，请查看运行档案和步骤状态。"
    if status == "cancelled":
        return "本轮运行已取消。"
    if active_steps:
        return f"正在执行：{' / '.join(step['label'] for step in active_steps)}"
    return "等待步骤写入运行档案。"


def get_trial_status() -> dict[str, Any]:
    prompts = load_deep_research_prompts(status_filter="all")
    pending = [prompt for prompt in prompts if prompt["status"] == "pending"]
    filled = [prompt for prompt in prompts if prompt["status"] == "filled"]
    skipped = [prompt for prompt in prompts if prompt["status"] == "skipped"]
    return {
        "mode": "ResearchOS",
        "long_disabled": False,
        "allowed_directions": "投资建议 / 观察 / 回避 / 暂不判断",
        "recommendation_output": "直接输出操作建议，不展示内部方向标签",
        "data_scope": "公开异动扫描 + Deep Research Inbox",
        "total_perplexity": len(prompts),
        "pending_perplexity": len(pending),
        "filled_perplexity": len(filled),
        "skipped_perplexity": len(skipped),
    }


def build_ops_dashboard() -> dict[str, Any]:
    trial = get_trial_status()
    latest_runs = load_recent_history_rows(tail=3)
    latest_run = latest_runs[0] if latest_runs else {}
    return {
        "trial_status": trial,
        "stock_pool": get_stock_pool_overview(),
        "knowledge": get_knowledge_overview(),
        "latest_run": latest_run,
        "recent_runs": latest_runs,
        "verification": get_verification_overview(),
        "company_flow": build_company_flow(trial),
    }


def load_recent_history_rows(*, tail: int = 3) -> list[dict[str, Any]]:
    run_log = RunLog(DATA_DIR / "orchestrator" / "runs.db")
    return [shape_history_row(row) for row in run_log.list_runs(tail=tail)]


def get_stock_pool_overview() -> dict[str, Any]:
    pool = normalize_stock_pool(load_stock_pool_yaml())
    counts = {category: len(pool.get(category) or []) for category in STOCK_CATEGORIES}
    return {
        "total": sum(counts.values()),
        "counts": counts,
        "version": pool.get("version", 1),
        "last_updated_by_nepha": pool.get("last_updated_by_nepha", ""),
    }


def get_knowledge_overview() -> dict[str, Any]:
    db_path = DATA_DIR / "knowledge_store" / "knowledge.db"
    empty = {
        "entries": 0,
        "tickers": 0,
        "latest_created_at": "",
        "recent_entries": [],
        "open_questions": 0,
        "unverified_claims": 0,
    }
    if not db_path.exists():
        return empty
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            totals = conn.execute(
                """
                SELECT COUNT(*) AS entries,
                       COUNT(DISTINCT ticker) AS tickers,
                       MAX(created_at) AS latest_created_at
                FROM knowledge_entries
                """
            ).fetchone()
            rows = conn.execute(
                """
                SELECT ticker, prompt_id, title, confidence_label, research_date,
                       event_date, expires_at, open_questions_json,
                       unverified_claims_json, sector_tags_json, narrative_tags_json
                FROM knowledge_entries
                ORDER BY created_at DESC, research_date DESC, prompt_id DESC
                LIMIT 5
                """
            ).fetchall()
    except sqlite3.DatabaseError:
        return empty

    recent_entries = [shape_knowledge_dashboard_row(dict(row)) for row in rows]
    return {
        "entries": int(totals["entries"] or 0),
        "tickers": int(totals["tickers"] or 0),
        "latest_created_at": totals["latest_created_at"] or "",
        "recent_entries": recent_entries,
        "open_questions": sum(item["open_questions_count"] for item in recent_entries),
        "unverified_claims": sum(item["unverified_claims_count"] for item in recent_entries),
    }


def shape_knowledge_dashboard_row(row: dict[str, Any]) -> dict[str, Any]:
    open_questions = parse_json_list(row.get("open_questions_json"))
    unverified_claims = parse_json_list(row.get("unverified_claims_json"))
    sector_tags = parse_json_list(row.get("sector_tags_json"))
    narrative_tags = parse_json_list(row.get("narrative_tags_json"))
    return {
        "ticker": row.get("ticker") or "",
        "prompt_id": row.get("prompt_id") or "",
        "title": row.get("title") or "",
        "confidence_label": row.get("confidence_label") or "未抽取",
        "research_date": row.get("research_date") or "",
        "event_date": row.get("event_date") or "",
        "expires_at": row.get("expires_at") or "",
        "open_questions_count": len(open_questions),
        "unverified_claims_count": len(unverified_claims),
        "tags": [*sector_tags[:3], *narrative_tags[:3]][:5],
    }


def parse_json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if not value:
        return []
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def get_verification_overview() -> dict[str, Any]:
    decision_cases = read_json_list(DATA_DIR / "decision_verification" / "pending_cases.json")
    partner_snapshots = read_json_list(DATA_DIR / "partner_performance" / "recommendation_log.json")
    return {
        "decision_cases": len(decision_cases),
        "partner_snapshots": len(partner_snapshots),
        "resolved_decision_cases": sum(1 for case in decision_cases if case.get("status") != "pending"),
        "resolved_partner_snapshots": sum(
            1 for item in partner_snapshots if item.get("verification_status") != "pending"
        ),
    }


def get_learning_overview() -> dict[str, Any]:
    overview = load_learning_overview(DATA_DIR)
    overview["top_tickers"] = [
        {"ticker": ticker, "count": count, "timeline_url": f"/timeline/{ticker}"}
        for ticker, count in overview.get("top_tickers", [])
    ]
    overview["latest_cases"] = [
        {
            **case,
            "timeline_url": f"/timeline/{case.get('ticker')}",
        }
        for case in overview.get("latest_cases", [])
    ]
    return overview


def read_json_list(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "[]")
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def build_company_flow(trial: dict[str, Any]) -> list[dict[str, Any]]:
    pending = int(trial.get("pending_perplexity") or 0)
    filled = int(trial.get("filled_perplexity") or 0)
    return [
        {"label": "异常扫描", "metric": "Stock Pool", "state": "发现异动"},
        {"label": "Deep Research Inbox", "metric": f"{pending} 待补充", "state": "质量门"},
        {"label": "知识库", "metric": f"{filled} 已沉淀", "state": "复用记忆"},
        {"label": "策略 Agent", "metric": "Value / Momentum / Quality", "state": "并行分析"},
        {"label": "CIO Agent", "metric": "投委会报告", "state": "裁决导航"},
        {"label": "Risk Auditor", "metric": "风险审计", "state": "反证检查"},
    ]


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
