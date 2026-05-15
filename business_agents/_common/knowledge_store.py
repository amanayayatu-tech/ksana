"""Persistent knowledge extracted from manually filled Perplexity reports."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from business_agents._common.perplexity_results import extract_answer_text, read_yaml

KNOWLEDGE_DIRNAME = "knowledge_store"
DB_FILENAME = "knowledge.db"
CARD_DIRNAME = "cards"
SCHEMA_VERSION = 3

DEFAULT_SAME_TICKER_DAYS = 90
DEFAULT_THEME_DAYS = 90
DEFAULT_THEME_LIMIT = 5
DEFAULT_CONTEXT_ENTRY_LIMIT = 3
DEFAULT_EXPIRES_AFTER_DAYS = 90

SECTION_STOP_RE = re.compile(r"^\s*(#{1,3}\s+|---|\*\*\*)")
HEADING_RE = re.compile(r"^\s*#{1,3}\s+(.+?)\s*$")
MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
DATE_RE = re.compile(r"(20\d{2})[-年/.](\d{1,2})[-月/.](\d{1,2})")
TICKER_RE = re.compile(r"\b[A-Z]{1,6}(?:\.[A-Z]{1,3})?\b")

TICKER_TAGS = {
    "BABA": ["china_internet", "ai_cloud", "ecommerce", "geopolitical_catalyst"],
    "9988.HK": ["china_internet", "ai_cloud", "ecommerce", "geopolitical_catalyst"],
    "META": ["social_media", "ai_capex", "regulation", "advertising"],
    "GOOGL": ["search", "ai_cloud", "advertising", "big_tech"],
    "MSFT": ["software", "ai_cloud", "big_tech"],
    "NVDA": ["semiconductor", "ai_infrastructure", "export_control"],
    "AMD": ["semiconductor", "ai_infrastructure", "cpu_gpu"],
    "LLY": ["pharma", "glp1", "obesity", "healthcare"],
}

KEYWORD_TAGS = {
    "AI": "ai",
    "人工智能": "ai",
    "云": "cloud",
    "Cloud": "cloud",
    "财报": "earnings",
    "earnings": "earnings",
    "CapEx": "capex",
    "资本支出": "capex",
    "监管": "regulation",
    "诉讼": "litigation",
    "罚款": "regulation",
    "股息": "dividend",
    "关税": "tariff",
    "峰会": "geopolitics",
    "贸易": "geopolitics",
    "半导体": "semiconductor",
    "芯片": "semiconductor",
    "GLP-1": "glp1",
    "Mounjaro": "glp1",
    "Zepbound": "glp1",
}


@dataclass(frozen=True)
class KnowledgeEntry:
    """One reusable investment-memory card extracted from a filled report."""

    entry_id: str
    source_pr_id: str
    stock_code: str
    prompt_id: str
    related_signal_id: str
    ticker: str
    company_name: str
    research_date: str
    event_date: str
    title: str
    confidence_label: str
    event_summary: list[str]
    primary_catalysts: list[str]
    counter_evidence: list[str]
    unresolved_questions: list[str]
    company_conclusions: list[str]
    industry_conclusions: list[str]
    unverified_claims: list[str]
    open_questions: list[str]
    closed_questions: list[str]
    historical_conflicts: list[str]
    evidence_quality: dict[str, Any]
    sector_tags: list[str]
    narrative_tags: list[str]
    reusable_tags: list[str]
    source_urls: list[str]
    prompt_text: str
    raw_result_path: str
    prompt_path: str
    answer_sha256: str
    created_at: str
    expires_at: str


def ingest_filled_result(
    data_dir: str | Path,
    prompt_id: str,
    *,
    result_path: str | Path | None = None,
) -> KnowledgeEntry | None:
    """Extract and persist a knowledge entry for one filled Perplexity result."""

    root = Path(data_dir)
    result_file = Path(result_path) if result_path else root / "perplexity_results" / f"{prompt_id}_filled.yaml"
    if not result_file.exists():
        return None
    result = read_yaml(result_file)
    if not isinstance(result, dict):
        return None
    if str(result.get("status") or "filled") != "filled":
        return None

    prompt = load_prompt_record(root, prompt_id)
    answer_text = extract_answer_text(result)
    if not answer_text.strip():
        return None

    entry = extract_knowledge_entry(
        result=result,
        prompt=prompt,
        answer_text=answer_text,
        result_file=result_file,
    )
    upsert_entry(root, entry)
    write_ticker_card(root, entry.ticker)
    return entry


def rebuild_knowledge_store(data_dir: str | Path, *, reset: bool = False) -> list[KnowledgeEntry]:
    """Rebuild the knowledge store from all local *_filled.yaml files."""

    root = Path(data_dir)
    store_dir = root / KNOWLEDGE_DIRNAME
    if reset and store_dir.exists():
        shutil.rmtree(store_dir)

    entries: list[KnowledgeEntry] = []
    for path in sorted((root / "perplexity_results").glob("*_filled.y*ml")):
        prompt_id = path.name.rsplit("_filled.", 1)[0]
        entry = ingest_filled_result(root, prompt_id, result_path=path)
        if entry:
            entries.append(entry)
    return entries


def delete_entry_for_prompt(data_dir: str | Path, prompt_id: str) -> None:
    """Remove a knowledge entry when a filled result is deleted or replaced by skip."""

    root = Path(data_dir)
    db_path = knowledge_db_path(root)
    if not db_path.exists():
        return
    with sqlite3.connect(db_path) as conn:
        ensure_schema(conn)
        row = conn.execute(
            "SELECT ticker FROM knowledge_entries WHERE prompt_id = ?",
            (prompt_id,),
        ).fetchone()
        conn.execute("DELETE FROM knowledge_entries WHERE prompt_id = ?", (prompt_id,))
        conn.commit()
    if row:
        write_ticker_card(root, str(row[0]))


def get_recent_knowledge_context(
    data_dir: str | Path,
    ticker: str,
    *,
    as_of_date: str | None = None,
    same_ticker_days: int = DEFAULT_SAME_TICKER_DAYS,
    theme_days: int = DEFAULT_THEME_DAYS,
    theme_limit: int = DEFAULT_THEME_LIMIT,
) -> str:
    """Return compact YAML context for Trading Agent prompts."""

    summary = get_recent_knowledge_summary(
        data_dir,
        ticker,
        as_of_date=as_of_date,
        same_ticker_days=same_ticker_days,
        theme_days=theme_days,
        theme_limit=theme_limit,
    )
    if not (summary.get("entries") or summary.get("similar_cases")):
        return "无"
    return yaml.safe_dump(
        {"historical_investment_knowledge": summary},
        allow_unicode=True,
        sort_keys=False,
    ).strip()


def get_recent_knowledge_summary(
    data_dir: str | Path,
    ticker: str,
    *,
    as_of_date: str | None = None,
    same_ticker_days: int = DEFAULT_SAME_TICKER_DAYS,
    theme_days: int = DEFAULT_THEME_DAYS,
    theme_limit: int = DEFAULT_THEME_LIMIT,
) -> dict[str, Any]:
    """Return structured recent knowledge for one ticker."""

    root = Path(data_dir)
    entries = query_entries(root, ticker=ticker)
    filtered = filter_entries_by_days(entries, as_of_date=as_of_date, days=same_ticker_days)
    shaped = [shape_entry_for_context(entry) for entry in filtered[:DEFAULT_CONTEXT_ENTRY_LIMIT]]
    reusable_tags = collect_reusable_tags(shaped) or infer_tags(ticker, ticker)
    similar_cases = query_similar_entries(
        root,
        ticker=ticker,
        tags=reusable_tags,
        as_of_date=as_of_date,
        days=theme_days,
        limit=theme_limit,
    )
    return {
        "ticker": ticker,
        "window_days": same_ticker_days,
        "max_entries": DEFAULT_CONTEXT_ENTRY_LIMIT,
        "retrieval_policy": {
            "same_ticker_window_days": same_ticker_days,
            "max_entries": DEFAULT_CONTEXT_ENTRY_LIMIT,
            "selection": "most_recent_unexpired_same_ticker_plus_open_questions",
            "always_include": ["open_questions", "unverified_claims"],
            "never_include": ["full_raw_perplexity_answer_text"],
        },
        "entries": shaped,
        "similar_cases": [shape_entry_for_context(entry) for entry in similar_cases],
        "open_questions": collect_open_questions(shaped),
        "closed_questions": collect_closed_questions(shaped),
        "historical_conflicts": collect_historical_conflicts(shaped),
        "reusable_tags": reusable_tags,
        "cards_path": str(root / KNOWLEDGE_DIRNAME / CARD_DIRNAME / f"{safe_filename(ticker)}.md"),
    }


def build_research_planning_context(
    data_dir: str | Path,
    ticker: str,
    *,
    as_of_date: str | None = None,
    signal_fingerprint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build compact history-aware context for Research Agent prompt planning."""

    root = Path(data_dir)
    summary = get_recent_knowledge_summary(root, ticker, as_of_date=as_of_date)
    raw_entries = [shape_entry_for_context(entry) for entry in query_entries(root, ticker=ticker)]
    entries = summary.get("entries", []) or []
    similar_cases = summary.get("similar_cases", []) or []
    answered_facts = collect_answered_facts(entries)
    open_questions = summary.get("open_questions", []) or []
    closed_questions = summary.get("closed_questions", []) or []
    conflicts = summary.get("historical_conflicts", []) or []
    expired_entries = collect_expired_entries(raw_entries, as_of_date=as_of_date)
    trigger_tags = set((signal_fingerprint or {}).get("trigger_rules") or [])
    trigger_tags.update((signal_fingerprint or {}).get("tags") or [])
    questions_to_refresh = build_questions_to_refresh(
        open_questions=open_questions,
        conflicts=conflicts,
        expired_entries=expired_entries,
        trigger_tags=sorted(trigger_tags),
    )
    return {
        "context_version": "research_planning_context_v1",
        "ticker": ticker,
        "as_of_date": as_of_date,
        "retrieval_policy": summary.get("retrieval_policy", {}),
        "history_found": bool(entries or similar_cases),
        "same_ticker_entries": entries,
        "similar_cases": similar_cases[:DEFAULT_THEME_LIMIT],
        "answered_facts": answered_facts[:8],
        "closed_questions": closed_questions[:6],
        "open_questions": open_questions[:8],
        "historical_conflicts": conflicts[:6],
        "expired_entries": expired_entries[:5],
        "questions_to_refresh": questions_to_refresh[:10],
        "do_not_repeat": build_do_not_repeat_items(answered_facts, closed_questions)[:8],
        "prompt_directives": build_research_prompt_directives(
            has_history=bool(entries),
            open_questions=open_questions,
            conflicts=conflicts,
            expired_entries=expired_entries,
            similar_cases=similar_cases,
        ),
    }


def extract_knowledge_entry(
    *,
    result: dict[str, Any],
    prompt: dict[str, Any],
    answer_text: str,
    result_file: Path,
) -> KnowledgeEntry:
    """Extract a deterministic first-pass knowledge entry from a raw report."""

    prompt_id = str(result.get("prompt_id") or prompt.get("prompt_id") or result_file.stem.replace("_filled", ""))
    prompt_text = str(result.get("prompt_text") or prompt.get("prompt_text") or "")
    ticker, company_name = infer_ticker_and_company(prompt_id, prompt_text, answer_text)
    title = extract_title(answer_text) or f"{ticker} Perplexity 深度研究"
    related_signal_id = str(
        result.get("related_signal_id")
        or prompt.get("related_signal_id")
        or infer_related_signal_id(prompt_id, answer_text)
    )
    research_date = (
        normalize_date_string(str(result.get("filled_at") or ""))
        or find_labeled_date(answer_text, ("研究日期", "分析截止日期"))
        or datetime.now().date().isoformat()
    )
    event_date = (
        find_labeled_date(answer_text, ("触发事件日期", "触发日期", "触发信号日", "事件日期"))
        or first_date_from_text(prompt_text)
        or research_date
    )
    event_summary = extract_event_summary(answer_text)
    primary_catalysts = extract_primary_catalysts(answer_text)
    counter_evidence = extract_counter_evidence(answer_text)
    unresolved_questions = extract_unresolved_questions(answer_text)
    confidence_label = extract_confidence_label(answer_text)
    source_urls = extract_source_urls(answer_text)
    sector_tags, narrative_tags = infer_schema_tags(ticker, prompt_text + "\n" + answer_text)
    tags = unique_clean_items([ticker.lower(), *sector_tags, *narrative_tags], max_items=16)
    industry_conclusions = extract_industry_conclusions(answer_text)
    company_conclusions = extract_company_conclusions(answer_text, event_summary, primary_catalysts)
    closed_questions = extract_closed_questions(answer_text)
    historical_conflicts = extract_historical_conflicts(answer_text)
    evidence_quality = build_evidence_quality(
        confidence_label=confidence_label,
        source_urls=source_urls,
        counter_evidence=counter_evidence,
        open_questions=unresolved_questions,
    )
    created_at = datetime.now().astimezone().isoformat(timespec="seconds")
    expires_at = calculate_expires_at(event_date)

    return KnowledgeEntry(
        entry_id=f"KE-{prompt_id.removeprefix('PR-')}",
        source_pr_id=prompt_id,
        stock_code=ticker,
        prompt_id=prompt_id,
        related_signal_id=related_signal_id,
        ticker=ticker,
        company_name=company_name,
        research_date=research_date,
        event_date=event_date,
        title=clean_markdown_text(title)[:160],
        confidence_label=confidence_label,
        event_summary=event_summary,
        primary_catalysts=primary_catalysts,
        counter_evidence=counter_evidence,
        unresolved_questions=unresolved_questions,
        company_conclusions=company_conclusions,
        industry_conclusions=industry_conclusions,
        unverified_claims=unresolved_questions,
        open_questions=unresolved_questions,
        closed_questions=closed_questions,
        historical_conflicts=historical_conflicts,
        evidence_quality=evidence_quality,
        sector_tags=sector_tags,
        narrative_tags=narrative_tags,
        reusable_tags=tags,
        source_urls=source_urls[:20],
        prompt_text=prompt_text,
        raw_result_path=str(result_file),
        prompt_path=str(prompt.get("path") or ""),
        answer_sha256=hashlib.sha256(answer_text.encode("utf-8")).hexdigest(),
        created_at=created_at,
        expires_at=expires_at,
    )


def upsert_entry(data_dir: str | Path, entry: KnowledgeEntry) -> None:
    root = Path(data_dir)
    db_path = knowledge_db_path(root)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(entry)
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    with sqlite3.connect(db_path) as conn:
        ensure_schema(conn)
        conn.execute(
            """
            INSERT INTO knowledge_entries (
                entry_id, source_pr_id, stock_code,
                prompt_id, related_signal_id, ticker, company_name, research_date, event_date,
                title, confidence_label, event_summary_json, primary_catalysts_json,
                counter_evidence_json, unresolved_questions_json, company_conclusions_json,
                industry_conclusions_json, unverified_claims_json, open_questions_json,
                closed_questions_json, historical_conflicts_json, evidence_quality_json,
                sector_tags_json, narrative_tags_json, reusable_tags_json,
                source_urls_json, prompt_text, raw_result_path, prompt_path, answer_sha256,
                created_at, expires_at, updated_at
            ) VALUES (
                :entry_id, :source_pr_id, :stock_code,
                :prompt_id, :related_signal_id, :ticker, :company_name, :research_date, :event_date,
                :title, :confidence_label, :event_summary_json, :primary_catalysts_json,
                :counter_evidence_json, :unresolved_questions_json, :company_conclusions_json,
                :industry_conclusions_json, :unverified_claims_json, :open_questions_json,
                :closed_questions_json, :historical_conflicts_json, :evidence_quality_json,
                :sector_tags_json, :narrative_tags_json, :reusable_tags_json,
                :source_urls_json, :prompt_text, :raw_result_path, :prompt_path, :answer_sha256,
                :created_at, :expires_at, :updated_at
            )
            ON CONFLICT(prompt_id) DO UPDATE SET
                entry_id = excluded.entry_id,
                source_pr_id = excluded.source_pr_id,
                stock_code = excluded.stock_code,
                related_signal_id = excluded.related_signal_id,
                ticker = excluded.ticker,
                company_name = excluded.company_name,
                research_date = excluded.research_date,
                event_date = excluded.event_date,
                title = excluded.title,
                confidence_label = excluded.confidence_label,
                event_summary_json = excluded.event_summary_json,
                primary_catalysts_json = excluded.primary_catalysts_json,
                counter_evidence_json = excluded.counter_evidence_json,
                unresolved_questions_json = excluded.unresolved_questions_json,
                company_conclusions_json = excluded.company_conclusions_json,
                industry_conclusions_json = excluded.industry_conclusions_json,
                unverified_claims_json = excluded.unverified_claims_json,
                open_questions_json = excluded.open_questions_json,
                closed_questions_json = excluded.closed_questions_json,
                historical_conflicts_json = excluded.historical_conflicts_json,
                evidence_quality_json = excluded.evidence_quality_json,
                sector_tags_json = excluded.sector_tags_json,
                narrative_tags_json = excluded.narrative_tags_json,
                reusable_tags_json = excluded.reusable_tags_json,
                source_urls_json = excluded.source_urls_json,
                prompt_text = excluded.prompt_text,
                raw_result_path = excluded.raw_result_path,
                prompt_path = excluded.prompt_path,
                answer_sha256 = excluded.answer_sha256,
                expires_at = excluded.expires_at,
                updated_at = excluded.updated_at
            """,
            {
                **payload,
                "event_summary_json": json.dumps(entry.event_summary, ensure_ascii=False),
                "primary_catalysts_json": json.dumps(entry.primary_catalysts, ensure_ascii=False),
                "counter_evidence_json": json.dumps(entry.counter_evidence, ensure_ascii=False),
                "unresolved_questions_json": json.dumps(entry.unresolved_questions, ensure_ascii=False),
                "company_conclusions_json": json.dumps(entry.company_conclusions, ensure_ascii=False),
                "industry_conclusions_json": json.dumps(entry.industry_conclusions, ensure_ascii=False),
                "unverified_claims_json": json.dumps(entry.unverified_claims, ensure_ascii=False),
                "open_questions_json": json.dumps(entry.open_questions, ensure_ascii=False),
                "closed_questions_json": json.dumps(entry.closed_questions, ensure_ascii=False),
                "historical_conflicts_json": json.dumps(entry.historical_conflicts, ensure_ascii=False),
                "evidence_quality_json": json.dumps(entry.evidence_quality, ensure_ascii=False),
                "sector_tags_json": json.dumps(entry.sector_tags, ensure_ascii=False),
                "narrative_tags_json": json.dumps(entry.narrative_tags, ensure_ascii=False),
                "reusable_tags_json": json.dumps(entry.reusable_tags, ensure_ascii=False),
                "source_urls_json": json.dumps(entry.source_urls, ensure_ascii=False),
                "created_at": entry.created_at or now,
                "updated_at": now,
            },
        )
        conn.commit()


def query_entries(data_dir: str | Path, *, ticker: str) -> list[dict[str, Any]]:
    db_path = knowledge_db_path(data_dir)
    if not db_path.exists():
        return []
    with sqlite3.connect(db_path) as conn:
        ensure_schema(conn)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT * FROM knowledge_entries
            WHERE ticker = ?
            ORDER BY COALESCE(event_date, research_date) DESC, research_date DESC, prompt_id DESC
            """,
            (ticker,),
        ).fetchall()
    return [decode_entry_row(dict(row)) for row in rows]


def query_similar_entries(
    data_dir: str | Path,
    *,
    ticker: str,
    tags: list[str],
    as_of_date: str | None = None,
    days: int = DEFAULT_THEME_DAYS,
    limit: int = DEFAULT_THEME_LIMIT,
) -> list[dict[str, Any]]:
    """Return cross-ticker entries sharing reusable tags for historical analogy."""

    db_path = knowledge_db_path(data_dir)
    if not db_path.exists() or not tags:
        return []
    with sqlite3.connect(db_path) as conn:
        ensure_schema(conn)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT * FROM knowledge_entries
            WHERE ticker != ?
            ORDER BY COALESCE(event_date, research_date) DESC, research_date DESC, prompt_id DESC
            """,
            (ticker,),
        ).fetchall()
    candidates = filter_entries_by_days(
        [decode_entry_row(dict(row)) for row in rows],
        as_of_date=as_of_date,
        days=days,
    )
    wanted = set(tags)
    scored: list[tuple[int, dict[str, Any]]] = []
    for entry in candidates:
        entry_tags = set(entry.get("reusable_tags") or [])
        entry_tags.update(entry.get("sector_tags") or [])
        entry_tags.update(entry.get("narrative_tags") or [])
        score = len(wanted & entry_tags)
        if score:
            scored.append((score, entry))
    scored.sort(
        key=lambda item: (
            item[0],
            str(item[1].get("event_date") or item[1].get("research_date") or ""),
        ),
        reverse=True,
    )
    return [entry for _score, entry in scored[:limit]]


def write_ticker_card(data_dir: str | Path, ticker: str) -> Path:
    root = Path(data_dir)
    cards_dir = root / KNOWLEDGE_DIRNAME / CARD_DIRNAME
    cards_dir.mkdir(parents=True, exist_ok=True)
    card_path = cards_dir / f"{safe_filename(ticker)}.md"
    entries = query_entries(root, ticker=ticker)
    if not entries:
        if card_path.exists():
            card_path.unlink()
        return card_path

    lines = [
        f"# {ticker} Knowledge Card",
        "",
        "> 自动从 Perplexity 回填生成。用于后续 Trading Agent、Chairman 和 Red Team 复用。",
        "",
    ]
    for entry in entries:
        lines.extend(render_entry_markdown(entry))
    card_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return card_path


def render_entry_markdown(entry: dict[str, Any]) -> list[str]:
    lines = [
        f"## {entry['prompt_id']} | {entry.get('event_date') or 'unknown date'}",
        "",
        f"- entry_id: `{entry.get('entry_id') or ''}`",
        f"- stock_code: `{entry.get('stock_code') or entry.get('ticker') or ''}`",
        f"- related_signal_id: `{entry.get('related_signal_id') or ''}`",
        f"- research_date: {entry.get('research_date') or ''}",
        f"- expires_at: {entry.get('expires_at') or ''}",
        f"- confidence: {entry.get('confidence_label') or '未抽取'}",
        f"- raw_result_path: `{entry.get('raw_result_path') or ''}`",
        f"- sector_tags: {', '.join(entry.get('sector_tags') or [])}",
        f"- narrative_tags: {', '.join(entry.get('narrative_tags') or [])}",
        "",
    ]
    lines.extend(render_list_section("公司结论", entry.get("company_conclusions") or []))
    lines.extend(render_list_section("行业/主题结论", entry.get("industry_conclusions") or []))
    lines.extend(render_list_section("未验证声明", entry.get("unverified_claims") or []))
    lines.extend(render_list_section("未关闭问题", entry.get("open_questions") or []))
    lines.extend(render_list_section("已关闭问题", entry.get("closed_questions") or []))
    lines.extend(render_list_section("历史冲突/反例", entry.get("historical_conflicts") or []))
    lines.append("")
    return lines


def render_list_section(title: str, items: list[str]) -> list[str]:
    lines = [f"### {title}"]
    if not items:
        lines.append("- 未抽取")
    else:
        lines.extend(f"- {item}" for item in items[:8])
    lines.append("")
    return lines


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_entries (
            entry_id TEXT NOT NULL,
            source_pr_id TEXT NOT NULL,
            stock_code TEXT NOT NULL,
            prompt_id TEXT PRIMARY KEY,
            related_signal_id TEXT,
            ticker TEXT NOT NULL,
            company_name TEXT,
            research_date TEXT,
            event_date TEXT,
            title TEXT,
            confidence_label TEXT,
            event_summary_json TEXT NOT NULL,
            primary_catalysts_json TEXT NOT NULL,
            counter_evidence_json TEXT NOT NULL,
            unresolved_questions_json TEXT NOT NULL,
            company_conclusions_json TEXT NOT NULL,
            industry_conclusions_json TEXT NOT NULL,
            unverified_claims_json TEXT NOT NULL,
            open_questions_json TEXT NOT NULL,
            closed_questions_json TEXT NOT NULL,
            historical_conflicts_json TEXT NOT NULL,
            evidence_quality_json TEXT NOT NULL,
            sector_tags_json TEXT NOT NULL,
            narrative_tags_json TEXT NOT NULL,
            reusable_tags_json TEXT NOT NULL,
            source_urls_json TEXT NOT NULL,
            prompt_text TEXT,
            raw_result_path TEXT,
            prompt_path TEXT,
            answer_sha256 TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    ensure_knowledge_columns(conn)
    conn.execute(
        "INSERT OR REPLACE INTO knowledge_meta(key, value) VALUES('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )


def ensure_knowledge_columns(conn: sqlite3.Connection) -> None:
    existing = {
        row[1]
        for row in conn.execute("PRAGMA table_info(knowledge_entries)").fetchall()
    }
    columns: dict[str, str] = {
        "entry_id": "TEXT NOT NULL DEFAULT ''",
        "source_pr_id": "TEXT NOT NULL DEFAULT ''",
        "stock_code": "TEXT NOT NULL DEFAULT ''",
        "company_conclusions_json": "TEXT NOT NULL DEFAULT '[]'",
        "industry_conclusions_json": "TEXT NOT NULL DEFAULT '[]'",
        "unverified_claims_json": "TEXT NOT NULL DEFAULT '[]'",
        "open_questions_json": "TEXT NOT NULL DEFAULT '[]'",
        "closed_questions_json": "TEXT NOT NULL DEFAULT '[]'",
        "historical_conflicts_json": "TEXT NOT NULL DEFAULT '[]'",
        "evidence_quality_json": "TEXT NOT NULL DEFAULT '{}'",
        "sector_tags_json": "TEXT NOT NULL DEFAULT '[]'",
        "narrative_tags_json": "TEXT NOT NULL DEFAULT '[]'",
        "expires_at": "TEXT NOT NULL DEFAULT ''",
    }
    for name, definition in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE knowledge_entries ADD COLUMN {name} {definition}")


def knowledge_db_path(data_dir: str | Path) -> Path:
    return Path(data_dir) / KNOWLEDGE_DIRNAME / DB_FILENAME


def load_prompt_record(root: Path, prompt_id: str) -> dict[str, Any]:
    for suffix in (".yaml", ".yml"):
        path = root / "pull_requests" / f"{prompt_id}{suffix}"
        if path.exists():
            data = read_yaml(path)
            prompt = data.get("prompt", data) if isinstance(data, dict) else {}
            return {**prompt, "path": str(path)}
    return {"prompt_id": prompt_id, "path": ""}


def decode_entry_row(row: dict[str, Any]) -> dict[str, Any]:
    decoded = dict(row)
    for column in (
        "event_summary_json",
        "primary_catalysts_json",
        "counter_evidence_json",
        "unresolved_questions_json",
        "company_conclusions_json",
        "industry_conclusions_json",
        "unverified_claims_json",
        "open_questions_json",
        "closed_questions_json",
        "historical_conflicts_json",
        "evidence_quality_json",
        "sector_tags_json",
        "narrative_tags_json",
        "reusable_tags_json",
        "source_urls_json",
    ):
        target = column.removesuffix("_json")
        decoded[target] = json.loads(str(decoded.pop(column) or "[]"))
    return decoded


def filter_entries_by_days(
    entries: list[dict[str, Any]],
    *,
    as_of_date: str | None,
    days: int,
) -> list[dict[str, Any]]:
    if not as_of_date:
        return entries
    as_of = parse_date(as_of_date)
    if not as_of:
        return entries
    filtered = []
    for entry in entries:
        entry_date = parse_date(str(entry.get("event_date") or entry.get("research_date") or ""))
        expires_at = parse_date(str(entry.get("expires_at") or ""))
        if expires_at and expires_at < as_of:
            continue
        if not entry_date:
            filtered.append(entry)
            continue
        age_days = (as_of - entry_date).days
        if 0 <= age_days <= days:
            filtered.append(entry)
    return filtered


def shape_entry_for_context(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "entry_id": entry.get("entry_id"),
        "source_pr_id": entry.get("source_pr_id") or entry["prompt_id"],
        "stock_code": entry.get("stock_code") or entry.get("ticker"),
        "prompt_id": entry["prompt_id"],
        "related_signal_id": entry.get("related_signal_id"),
        "research_date": entry.get("research_date"),
        "event_date": entry.get("event_date"),
        "expires_at": entry.get("expires_at"),
        "confidence_label": entry.get("confidence_label"),
        "company_conclusions": entry.get("company_conclusions", [])[:5],
        "industry_conclusions": entry.get("industry_conclusions", [])[:3],
        "unverified_claims": entry.get("unverified_claims", [])[:5],
        "open_questions": entry.get("open_questions", [])[:8],
        "closed_questions": entry.get("closed_questions", [])[:6],
        "historical_conflicts": entry.get("historical_conflicts", [])[:6],
        "evidence_quality": entry.get("evidence_quality") or {},
        "sector_tags": entry.get("sector_tags", [])[:6],
        "narrative_tags": entry.get("narrative_tags", [])[:8],
        "event_summary": entry.get("event_summary", [])[:2],
        "primary_catalysts": entry.get("primary_catalysts", [])[:3],
        "counter_evidence": entry.get("counter_evidence", [])[:3],
        "unresolved_questions": entry.get("unresolved_questions", [])[:5],
        "raw_result_path": entry.get("raw_result_path"),
    }


def collect_open_questions(entries: list[dict[str, Any]]) -> list[str]:
    questions: list[str] = []
    for entry in entries:
        for item in (entry.get("open_questions") or entry.get("unresolved_questions") or []):
            if item not in questions:
                questions.append(item)
    return questions[:8]


def collect_closed_questions(entries: list[dict[str, Any]]) -> list[str]:
    questions: list[str] = []
    for entry in entries:
        for item in entry.get("closed_questions") or []:
            if item not in questions:
                questions.append(item)
    return questions[:8]


def collect_historical_conflicts(entries: list[dict[str, Any]]) -> list[str]:
    conflicts: list[str] = []
    for entry in entries:
        for item in entry.get("historical_conflicts") or []:
            if item not in conflicts:
                conflicts.append(item)
    return conflicts[:8]


def collect_reusable_tags(entries: list[dict[str, Any]]) -> list[str]:
    tags: list[str] = []
    for entry in entries:
        tags.extend(entry.get("sector_tags") or [])
        tags.extend(entry.get("narrative_tags") or [])
    return unique_clean_items(tags, max_items=12)


def collect_answered_facts(entries: list[dict[str, Any]]) -> list[str]:
    facts: list[str] = []
    for entry in entries:
        facts.extend(entry.get("company_conclusions") or [])
        facts.extend(entry.get("industry_conclusions") or [])
    return unique_clean_items(facts, max_items=12)


def collect_expired_entries(entries: list[dict[str, Any]], *, as_of_date: str | None) -> list[dict[str, Any]]:
    as_of = parse_date(as_of_date or "")
    if not as_of:
        return []
    expired: list[dict[str, Any]] = []
    for entry in entries:
        expires_at = parse_date(str(entry.get("expires_at") or ""))
        if expires_at and expires_at < as_of:
            expired.append(
                {
                    "prompt_id": entry.get("prompt_id"),
                    "expires_at": entry.get("expires_at"),
                    "reason": "knowledge_entry_expired",
                    "last_conclusion": (entry.get("company_conclusions") or entry.get("event_summary") or [""])[0],
                }
            )
    return expired


def build_questions_to_refresh(
    *,
    open_questions: list[str],
    conflicts: list[str],
    expired_entries: list[dict[str, Any]],
    trigger_tags: list[str],
) -> list[str]:
    questions = list(open_questions)
    questions.extend(f"历史冲突需要复核：{item}" for item in conflicts)
    questions.extend(
        f"{entry.get('prompt_id')} 已过期，需要刷新其核心结论：{entry.get('last_conclusion')}"
        for entry in expired_entries
    )
    if trigger_tags:
        questions.append(f"本次触发标签 {', '.join(trigger_tags[:6])} 是否改变既有结论？")
    return unique_clean_items(questions, max_items=12)


def build_do_not_repeat_items(answered_facts: list[str], closed_questions: list[str]) -> list[str]:
    items = []
    items.extend(f"已回答事实：{fact}" for fact in answered_facts)
    items.extend(f"已关闭问题：{question}" for question in closed_questions)
    return unique_clean_items(items, max_items=10)


def build_research_prompt_directives(
    *,
    has_history: bool,
    open_questions: list[str],
    conflicts: list[str],
    expired_entries: list[dict[str, Any]],
    similar_cases: list[dict[str, Any]],
) -> list[str]:
    directives = [
        "先复用历史知识，再提出新问题；不要重复询问已确认事实。",
        "把价量异动只当作触发器，真正输出 K deep 研究任务编排。",
    ]
    if not has_history:
        directives.append("知识库没有同标的历史研究，必须建立第一份可复用股票档案。")
    if open_questions:
        directives.append("优先追问历史未关闭问题，并判断是否已经被新公开信息关闭。")
    if conflicts:
        directives.append("必须检查本次解释是否和历史冲突或反例相矛盾。")
    if expired_entries:
        directives.append("历史结论已过期时，优先刷新有效期而不是追加重复材料。")
    if similar_cases:
        directives.append("参考相似历史案例，但必须说明相似点和不相似点。")
    return directives


def infer_ticker_and_company(prompt_id: str, prompt_text: str, answer_text: str) -> tuple[str, str]:
    prompt_match = re.search(r"请研究\s+([A-Z0-9.]+)\s+([^最近\n]+)?", prompt_text)
    if prompt_match:
        return prompt_match.group(1).strip(), clean_markdown_text(prompt_match.group(2) or "").strip()

    id_match = re.search(r"PR-\d{8}-([A-Z0-9.]+)", prompt_id)
    if id_match:
        ticker = id_match.group(1)
        return ticker, ""

    for text in (answer_text, prompt_text):
        for match in TICKER_RE.finditer(text):
            token = match.group(0)
            if token not in {"AI", "Q1", "Q2", "Q3", "Q4", "CEO", "CFO", "EPS", "ARR", "SEC"}:
                return token, ""
    return "UNKNOWN", ""


def infer_related_signal_id(prompt_id: str, answer_text: str) -> str:
    match = re.search(r"RS-\d{8}-[A-Z0-9.-]+", answer_text)
    if match:
        return match.group(0)
    if prompt_id.startswith("PR-"):
        return "RS-" + prompt_id.removeprefix("PR-")
    return ""


def extract_title(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def extract_event_summary(text: str) -> list[str]:
    section = extract_section(text, ("执行摘要",))
    candidates = split_into_items(section, max_items=5)
    if candidates:
        return candidates[:4]
    paragraph = clean_markdown_text(text).split("\n\n", 1)[0]
    return split_long_text(paragraph, max_items=3)


def extract_primary_catalysts(text: str) -> list[str]:
    items: list[str] = []
    summary = extract_section(text, ("执行摘要",))
    items.extend(split_chinese_numbered_causes(summary))
    for title in (
        "核心触发原因",
        "核心触发因素",
        "核心触发",
        "财报触发",
        "财报面触发因子",
        "综合结论",
        "结论可信度评估",
    ):
        section = extract_section(text, (title,))
        items.extend(split_into_items(section, max_items=8))
    return unique_clean_items(items, max_items=8)


def extract_counter_evidence(text: str) -> list[str]:
    items: list[str] = []
    for title in ("反证", "风险提示", "反证与风险", "已识别的反证", "对涨幅持怀疑态度的反证"):
        section = extract_section(text, (title,))
        items.extend(split_into_items(section, max_items=10))
    return unique_clean_items(items, max_items=8)


def extract_unresolved_questions(text: str) -> list[str]:
    items: list[str] = []
    for title in ("仍未验证", "尚未验证", "未验证的信息", "尚未验证的问题", "仍未验证的信息"):
        section = extract_section(text, (title,))
        items.extend(split_into_items(section, max_items=10))
    return unique_clean_items(items, max_items=8)


def extract_industry_conclusions(text: str) -> list[str]:
    items: list[str] = []
    for title in ("行业", "行业与监管", "监管背景", "竞争", "宏观", "指数层面", "行业结构"):
        section = extract_section(text, (title,))
        items.extend(split_into_items(section, max_items=6))
    return unique_clean_items(items, max_items=6)


def extract_company_conclusions(
    text: str,
    event_summary: list[str],
    primary_catalysts: list[str],
) -> list[str]:
    items: list[str] = []
    for title in (
        "公司结论",
        "事件摘要",
        "结论摘要",
        "综合结论",
        "K deep 关键判断",
        "可进入知识库的结构化要点",
        "可沉淀记忆",
    ):
        section = extract_section(text, (title,))
        items.extend(split_into_items(section, max_items=8))
    items.extend(event_summary)
    items.extend(primary_catalysts)
    return unique_clean_items(items, max_items=10)


def extract_closed_questions(text: str) -> list[str]:
    items: list[str] = []
    for title in ("已关闭问题", "已验证", "已确认", "可以关闭的问题", "已被验证"):
        section = extract_section(text, (title,))
        items.extend(split_into_items(section, max_items=8))
    return unique_clean_items(items, max_items=8)


def extract_historical_conflicts(text: str) -> list[str]:
    items: list[str] = []
    for title in ("历史冲突", "历史反例", "历史失败", "与历史研究冲突", "冲突点", "反例"):
        section = extract_section(text, (title,))
        items.extend(split_into_items(section, max_items=8))
    return unique_clean_items(items, max_items=8)


def build_evidence_quality(
    *,
    confidence_label: str,
    source_urls: list[str],
    counter_evidence: list[str],
    open_questions: list[str],
) -> dict[str, Any]:
    score = 45
    if confidence_label:
        if "高" in confidence_label or "high" in confidence_label.lower():
            score += 20
        elif "中" in confidence_label or "medium" in confidence_label.lower():
            score += 10
    score += min(15, len(source_urls) * 2)
    score += min(10, len(counter_evidence) * 2)
    score -= min(20, len(open_questions) * 3)
    return {
        "confidence_label": confidence_label,
        "source_url_count": len(source_urls),
        "counter_evidence_count": len(counter_evidence),
        "open_question_count": len(open_questions),
        "score": max(0, min(95, score)),
    }


def extract_confidence_label(text: str) -> str:
    patterns = (
        r"整体结论可信度[：:]\s*([^\n。]+)",
        r"结论可信度[：:]\s*([^\n。]+)",
        r"可信度[：:]\s*([^\n。]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return normalize_confidence_label(clean_markdown_text(match.group(1)).strip())[:80]
    if "可信度：高" in text or "可信度: 高" in text:
        return "高"
    return ""


def extract_source_urls(text: str) -> list[str]:
    urls = [url.strip() for _, url in MARKDOWN_LINK_RE.findall(text)]
    bare_urls = re.findall(r"https?://[^\s)]+", text)
    return unique_clean_items(urls + bare_urls, max_items=30)


def extract_section(text: str, title_keywords: tuple[str, ...]) -> str:
    lines = text.splitlines()
    start: int | None = None
    for index, line in enumerate(lines):
        heading = HEADING_RE.match(line)
        if heading and any(keyword in heading.group(1) for keyword in title_keywords):
            start = index + 1
            break
    if start is None:
        return ""
    collected: list[str] = []
    for line in lines[start:]:
        if SECTION_STOP_RE.match(line) and collected:
            break
        collected.append(line)
    return "\n".join(collected).strip()


def split_chinese_numbered_causes(text: str) -> list[str]:
    match = re.search(r"核心催化剂为[：:](.+?)(?:。|\n)", text, flags=re.S)
    if not match:
        return []
    raw = match.group(1)
    parts = re.split(r"[①②③④⑤⑥⑦⑧⑨]|\s*[；;]\s*", raw)
    return [clean_markdown_text(part) for part in parts if clean_markdown_text(part)]


def split_into_items(text: str, *, max_items: int) -> list[str]:
    if not text:
        return []
    items: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped in {"***", "---"}:
            continue
        if stripped.startswith("|") and stripped.count("|") >= 2:
            table_item = clean_table_row(stripped)
            if table_item:
                items.append(table_item)
            continue
        if stripped.startswith(("-", "*")) or re.match(r"^\d+[.、]\s+", stripped):
            items.append(clean_markdown_text(re.sub(r"^[-*]\s+|^\d+[.、]\s+", "", stripped)))
            continue
        if len(stripped) > 40 and not stripped.startswith("#"):
            items.extend(split_long_text(stripped, max_items=2))
        if len(items) >= max_items:
            break
    return unique_clean_items(items, max_items=max_items)


def split_long_text(text: str, *, max_items: int) -> list[str]:
    clean = clean_markdown_text(text)
    parts = [part.strip() for part in re.split(r"(?<=[。！？])", clean) if part.strip()]
    if not parts and clean:
        parts = [clean]
    return [part[:260] for part in parts[:max_items]]


def clean_table_row(line: str) -> str:
    cells = [clean_markdown_text(cell) for cell in line.strip("|").split("|")]
    cells = [cell for cell in cells if cell and not set(cell) <= {"-", ":"}]
    if len(cells) < 2:
        return ""
    if any(header in cells[0] for header in ("指标", "原因", "驱动因素")):
        return ""
    return " | ".join(cells[:4])


def unique_clean_items(items: list[str], *, max_items: int) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in items:
        value = clean_markdown_text(item)
        if not value or value in seen or len(value) < 4:
            continue
        seen.add(value)
        cleaned.append(value[:260])
        if len(cleaned) >= max_items:
            break
    return cleaned


def clean_markdown_text(text: str) -> str:
    value = MARKDOWN_LINK_RE.sub(r"\1", str(text))
    value = value.replace("\ufffd", "")
    value = re.sub(r"\[\^?\d+\]", "", value)
    value = re.sub(r"[*_`#>]", "", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip(" -:：|")


def normalize_confidence_label(value: str) -> str:
    label = value.strip()
    if label.endswith("）") and "（" not in label:
        label = label[:-1].strip()
    if label.endswith(")") and "(" not in label:
        label = label[:-1].strip()
    return label


def find_labeled_date(text: str, labels: tuple[str, ...]) -> str:
    for label in labels:
        match = re.search(rf"{re.escape(label)}[：:\s]*([^\n|]+)", text)
        if match:
            normalized = normalize_date_string(match.group(1))
            if normalized:
                return normalized
    return ""


def first_date_from_text(text: str) -> str:
    match = DATE_RE.search(text)
    if not match:
        return ""
    return f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"


def normalize_date_string(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    iso_match = re.search(r"(20\d{2})-(\d{2})-(\d{2})", text)
    if iso_match:
        return iso_match.group(0)
    return first_date_from_text(text)


def parse_date(value: str):
    normalized = normalize_date_string(value)
    if not normalized:
        return None
    try:
        return datetime.strptime(normalized, "%Y-%m-%d").date()
    except ValueError:
        return None


def infer_tags(ticker: str, text: str) -> list[str]:
    tags = [ticker.lower()]
    tags.extend(TICKER_TAGS.get(ticker.upper(), []))
    for keyword, tag in KEYWORD_TAGS.items():
        if keyword in text:
            tags.append(tag)
    return unique_clean_items(tags, max_items=16)


def infer_schema_tags(ticker: str, text: str) -> tuple[list[str], list[str]]:
    sector_tags = TICKER_TAGS.get(ticker.upper(), [])
    narrative_tags = []
    for keyword, tag in KEYWORD_TAGS.items():
        if keyword in text and tag not in sector_tags:
            narrative_tags.append(tag)
    return (
        unique_clean_items(sector_tags, max_items=8),
        unique_clean_items(narrative_tags, max_items=12),
    )


def calculate_expires_at(event_date: str, *, days: int = DEFAULT_EXPIRES_AFTER_DAYS) -> str:
    parsed = parse_date(event_date)
    if not parsed:
        parsed = datetime.now().date()
    return (parsed + timedelta(days=days)).isoformat()


def safe_filename(value: str) -> str:
    token = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    return token or "UNKNOWN"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Manage worldpay77 knowledge store")
    subparsers = parser.add_subparsers(dest="command", required=True)
    rebuild = subparsers.add_parser("rebuild", help="Rebuild from local Perplexity filled files")
    rebuild.add_argument("--data-dir", default="data")
    rebuild.add_argument("--reset", action="store_true")
    args = parser.parse_args(argv)

    if args.command == "rebuild":
        entries = rebuild_knowledge_store(args.data_dir, reset=args.reset)
        print(f"rebuilt knowledge entries: {len(entries)}")
        for entry in entries:
            print(f"- {entry.prompt_id} {entry.ticker}")


if __name__ == "__main__":
    main()
