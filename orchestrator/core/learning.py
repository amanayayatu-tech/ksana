"""Time-safe learning records built from archived investment-committee outputs."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from business_agents._common.market_data.yfinance_client import YFinanceClient
from chairman.models import ChairmanBrief
from orchestrator.core.decision_verification import DEFAULT_WINDOWS, OBJECTIVES, map_chairman_verdict_to_direction

LEARNING_DIRNAME = "learning"
DECISION_CASES_FILENAME = "decision_cases.json"
OUTCOME_SNAPSHOTS_FILENAME = "outcome_snapshots.json"
TIMELINE_DIRNAME = "stock_timelines"
MONTHLY_REVIEW_DIRNAME = "monthly_reviews"


def append_learning_from_brief(brief: ChairmanBrief, data_dir: str | Path) -> dict[str, Path]:
    """Upsert decision cases from a Chairman brief and rebuild derived learning views."""

    root = Path(data_dir)
    learning_dir = root / LEARNING_DIRNAME
    learning_dir.mkdir(parents=True, exist_ok=True)
    decision_cases_path = learning_dir / DECISION_CASES_FILENAME
    cases = load_json_list(decision_cases_path)
    by_id = {case["case_id"]: case for case in cases if case.get("case_id")}
    for summary in brief.per_recommendation_summary:
        case = build_decision_case_from_summary(brief, summary)
        by_id[case["case_id"]] = merge_decision_case(by_id.get(case["case_id"]), case)

    write_json_list(decision_cases_path, list(by_id.values()))
    timeline_paths = rebuild_stock_timelines(root)
    month_paths = write_monthly_review(root, month=month_from_brief_id(brief.brief_id))
    result = {"decision_cases": decision_cases_path}
    if timeline_paths:
        result["stock_timelines_dir"] = root / LEARNING_DIRNAME / TIMELINE_DIRNAME
    if month_paths:
        result["monthly_review_md"] = month_paths[0]
        result["monthly_review_json"] = month_paths[1]
    return result


def rebuild_learning_from_archived_briefs(data_dir: str | Path) -> Path:
    """Backfill learning cases from already archived Chairman brief JSON files."""

    root = Path(data_dir)
    for path in sorted((root / "briefs").glob("**/BRIEF-*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8") or "{}")
            brief = ChairmanBrief.model_validate(payload)
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        append_learning_from_brief(brief, root)
    return root / LEARNING_DIRNAME / DECISION_CASES_FILENAME


def build_decision_case_from_summary(brief: ChairmanBrief, summary: dict[str, Any]) -> dict[str, Any]:
    """Build one case with the information available at the decision time only."""

    verdict = summary.get("chairman_verdict", {}) or {}
    direction = map_chairman_verdict_to_direction(verdict)
    ticker = str(summary.get("ticker") or "UNKNOWN")
    as_of_date = date_from_brief_id(brief.brief_id)
    historical = summary.get("historical_knowledge") or {}
    learning_context = summary.get("learning_context") or verdict.get("learning_context") or {}
    return {
        "case_id": f"DC-{brief.brief_id}-{ticker}",
        "source_brief_id": brief.brief_id,
        "source_signal_id": summary.get("research_signal_id"),
        "ticker": ticker,
        "market": summary.get("market") or "",
        "as_of_date": as_of_date,
        "available_context_cutoff": as_of_date,
        "future_data_allowed": False,
        "decision_direction": direction,
        "chairman_final_verdict": verdict.get("final_verdict") or "wait",
        "action_route": verdict.get("action_route") or "watchlist_monitor",
        "chairman_confidence": verdict.get("confidence"),
        "consensus_level": (summary.get("direction_consensus") or {}).get("consensus_level"),
        "lead_agent": verdict.get("lead_agent") or {},
        "partner_views": summary.get("individual_views") or [],
        "operation_summary": summary.get("operation_summary") or {},
        "opportunity_screener": summary.get("opportunity_screener")
        or verdict.get("opportunity_screener")
        or {},
        "opportunity_evaluation_snapshot": build_opportunity_evaluation_snapshot(
            summary,
            verdict,
            as_of_date=as_of_date,
        ),
        "human_decision_checklist": verdict.get("human_decision_checklist") or [],
        "decision_chain": verdict.get("decision_chain") or [],
        "history_context": verdict.get("history_context") or {},
        "learning_context": shape_learning_case_context(learning_context),
        "open_questions_at_decision": historical.get("open_questions", []) or [],
        "historical_conflicts_at_decision": historical.get("historical_conflicts", []) or [],
        "similar_cases_at_decision": [
            {
                "prompt_id": item.get("prompt_id"),
                "ticker": item.get("ticker") or item.get("stock_code"),
                "event_date": item.get("event_date") or item.get("research_date"),
                "summary": first_text(
                    item.get("event_summary"),
                    item.get("company_conclusions"),
                    item.get("open_questions"),
                ),
            }
            for item in (historical.get("similar_cases") or [])[:5]
        ],
        "verification_windows_days": DEFAULT_WINDOWS,
        "objective": OBJECTIVES[direction],
        "status": "pending",
        "evidence_url": "",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def build_opportunity_evaluation_snapshot(
    summary: dict[str, Any],
    verdict: dict[str, Any] | None = None,
    *,
    as_of_date: str | None = None,
) -> dict[str, Any]:
    """Create a stable decision-time score snapshot for later outcome calibration."""

    verdict = verdict or summary.get("chairman_verdict") or {}
    screener = summary.get("opportunity_screener") or verdict.get("opportunity_screener") or {}
    memo_date = as_of_date or str(summary.get("memo_date") or summary.get("decision_date") or "")
    return {
        "snapshot_version": "opportunity_evaluation_snapshot_v1",
        "ticker": summary.get("ticker") or screener.get("ticker") or "",
        "decision_date": memo_date,
        "memo_date": memo_date,
        "price_at_memo": summary.get("price_at_memo"),
        "price_at_decision": summary.get("price_at_decision"),
        "opportunity_score": screener.get("opportunity_score"),
        "raw_opportunity_score": screener.get("raw_opportunity_score"),
        "business_quality_score": screener.get("business_quality_score"),
        "investment_attractiveness_score": screener.get("investment_attractiveness_score"),
        "expectation_gap_score": screener.get("expectation_gap_score"),
        "valuation_score": screener.get("valuation_score"),
        "catalyst_score": screener.get("catalyst_score"),
        "risk_pressure_score": screener.get("risk_pressure_score", screener.get("risk_score")),
        "positioning_score": screener.get("positioning_score"),
        "final_verdict": verdict.get("final_verdict"),
        "legacy_verdict": verdict.get("legacy_verdict"),
        "human_decision": verdict.get("human_decision") or summary.get("human_decision"),
        "1m_return": None,
        "3m_return": None,
        "6m_return": None,
        "max_drawdown": None,
        "thesis_hit": None,
        "kill_condition_triggered": None,
        "future_data_allowed": False,
    }


def shape_learning_case_context(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "prior_cases_count": int(context.get("prior_cases_count") or 0),
        "outcome_status_counts": context.get("outcome_status_counts") or {},
        "latest_case_id": context.get("latest_case_id") or "",
        "recent_pattern_notes": (context.get("pattern_notes") or [])[:5],
        "timeline_path": context.get("timeline_path") or "",
    }


def merge_decision_case(existing: dict[str, Any] | None, generated: dict[str, Any]) -> dict[str, Any]:
    """Preserve manual verification annotations when a brief is regenerated."""

    if not existing:
        return generated
    merged = {**existing, **generated}
    for key in (
        "status",
        "evidence_url",
        "verification_notes",
        "verified_at",
        "verified_by",
        "verification_results",
        "manual_label",
        "manual_label_reason",
    ):
        if existing.get(key) and existing.get(key) != "pending":
            merged[key] = existing[key]
    if existing.get("evidence_url"):
        merged["evidence_url"] = existing["evidence_url"]
    merged["created_at"] = existing.get("created_at") or generated.get("created_at")
    return merged


def refresh_outcome_snapshots(
    data_dir: str | Path,
    *,
    market_client: Any | None = None,
    as_of_date: str | None = None,
) -> Path:
    """Generate price-only outcome snapshots without reading past the supplied as-of date."""

    root = Path(data_dir)
    learning_dir = root / LEARNING_DIRNAME
    learning_dir.mkdir(parents=True, exist_ok=True)
    output_path = learning_dir / OUTCOME_SNAPSHOTS_FILENAME
    cases = load_decision_cases(root)
    existing = load_json_list(output_path)
    by_id = {item["snapshot_id"]: item for item in existing if item.get("snapshot_id")}
    client = market_client or YFinanceClient()
    cutoff = parse_date(as_of_date) or date.today()
    histories: dict[str, list[dict[str, Any]]] = {}
    for case in cases:
        ticker = str(case.get("ticker") or "")
        if not ticker:
            continue
        if ticker not in histories:
            histories[ticker] = client.get_history(ticker, period="1y")
        for snapshot in build_outcome_snapshots_for_case(case, histories[ticker], outcome_as_of=cutoff):
            by_id[snapshot["snapshot_id"]] = merge_outcome_snapshot(by_id.get(snapshot["snapshot_id"]), snapshot)
    write_json_list(output_path, list(by_id.values()))
    rebuild_stock_timelines(root)
    return output_path


def build_outcome_snapshots_for_case(
    case: dict[str, Any],
    history: list[dict[str, Any]],
    *,
    outcome_as_of: date,
) -> list[dict[str, Any]]:
    decision_date = parse_date(case.get("as_of_date") or case.get("available_context_cutoff"))
    if decision_date is None:
        return []
    rows = sorted(
        [row for row in history if parse_date(row.get("date")) and parse_date(row.get("date")) <= outcome_as_of],
        key=lambda row: str(row.get("date")),
    )
    start = first_row_on_or_after(rows, decision_date)
    snapshots = []
    for window in case.get("verification_windows_days") or DEFAULT_WINDOWS:
        end_date = decision_date + timedelta(days=int(window))
        snapshot_id = f"OS-{case.get('case_id')}-{window}D"
        end = first_row_on_or_after(rows, end_date)
        if end_date > outcome_as_of or not start or not end:
            snapshots.append(
                {
                    "snapshot_id": snapshot_id,
                    "case_id": case.get("case_id"),
                    "ticker": case.get("ticker"),
                    "decision_direction": case.get("decision_direction"),
                    "decision_date": decision_date.isoformat(),
                    "window_days": int(window),
                    "window_end_date": end_date.isoformat(),
                    "outcome_as_of": outcome_as_of.isoformat(),
                    "status": "pending",
                    "price_signal": "not_due",
                    "future_data_allowed": False,
                }
            )
            continue
        change_pct = calculate_change_pct(start.get("close"), end.get("close"))
        price_signal = classify_price_signal(case.get("decision_direction"), change_pct)
        snapshots.append(
            {
                "snapshot_id": snapshot_id,
                "case_id": case.get("case_id"),
                "ticker": case.get("ticker"),
                "decision_direction": case.get("decision_direction"),
                "decision_date": decision_date.isoformat(),
                "window_days": int(window),
                "window_end_date": end_date.isoformat(),
                "outcome_as_of": outcome_as_of.isoformat(),
                "status": snapshot_status_from_price_signal(price_signal),
                "price_signal": price_signal,
                "price_start": start.get("close"),
                "price_end": end.get("close"),
                "price_change_pct": change_pct,
                "start_source_url": start.get("source_url"),
                "end_source_url": end.get("source_url"),
                "future_data_allowed": False,
                "note": "价格只做 outcome snapshot，不自动覆盖人工 verification 结论。",
            }
        )
    return snapshots


def merge_outcome_snapshot(existing: dict[str, Any] | None, generated: dict[str, Any]) -> dict[str, Any]:
    if not existing:
        return generated
    merged = {**existing, **generated}
    for key in ("manual_status", "manual_notes", "evidence_url", "verified_at", "verified_by"):
        if existing.get(key):
            merged[key] = existing[key]
    return merged


def load_chairman_learning_context(
    data_dir: str | Path | None,
    ticker: str,
    *,
    as_of_date: str | None = None,
) -> dict[str, Any]:
    """Return only learning records created on or before as-of date."""

    if data_dir is None:
        return {}
    root = Path(data_dir)
    cutoff = parse_date(as_of_date) or date.today()
    cases = [
        case
        for case in load_decision_cases(root)
        if str(case.get("ticker")) == ticker and case_date(case) and case_date(case) <= cutoff
    ]
    cases.sort(key=lambda item: str(item.get("as_of_date") or ""), reverse=True)
    current_brief_id = ""
    if cases and str(cases[0].get("as_of_date")) == cutoff.isoformat():
        current_brief_id = str(cases[0].get("source_brief_id") or "")
    prior_cases = [case for case in cases if str(case.get("source_brief_id")) != current_brief_id]
    snapshots = [
        item
        for item in load_outcome_snapshots(root)
        if str(item.get("ticker")) == ticker
        and parse_date(item.get("outcome_as_of"))
        and parse_date(item.get("outcome_as_of")) <= cutoff
    ]
    status_counts = Counter(str(item.get("status")) for item in snapshots)
    return {
        "context_version": "chairman_learning_context_v1",
        "ticker": ticker,
        "as_of_date": cutoff.isoformat(),
        "prior_cases_count": len(prior_cases),
        "latest_case_id": prior_cases[0].get("case_id") if prior_cases else "",
        "recent_cases": [shape_case_for_context(case) for case in prior_cases[:5]],
        "outcome_status_counts": dict(status_counts),
        "pattern_notes": build_learning_pattern_notes(prior_cases, snapshots),
        "timeline_path": str(stock_timeline_json_path(root, ticker)) if stock_timeline_json_path(root, ticker).exists() else "",
    }


def build_learning_pattern_notes(cases: list[dict[str, Any]], snapshots: list[dict[str, Any]]) -> list[str]:
    notes: list[str] = []
    direction_counts = Counter(str(case.get("decision_direction")) for case in cases)
    if direction_counts:
        notes.append(f"历史决策方向分布：{dict(direction_counts)}。")
    status_counts = Counter(str(item.get("status")) for item in snapshots if item.get("status") != "pending")
    if status_counts:
        notes.append(f"已有价格 outcome snapshot：{dict(status_counts)}。")
    unresolved = sum(len(case.get("open_questions_at_decision") or []) for case in cases[:5])
    if unresolved:
        notes.append(f"最近历史案例累计 {unresolved} 个未关闭问题，Chairman 需要解释本次是否已关闭。")
    if not notes:
        notes.append("尚无可用历史 outcome；本次只记录，不做权重上调。")
    return notes[:5]


def shape_case_for_context(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_id": case.get("case_id"),
        "source_brief_id": case.get("source_brief_id"),
        "ticker": case.get("ticker"),
        "as_of_date": case.get("as_of_date"),
        "decision_direction": case.get("decision_direction"),
        "chairman_final_verdict": case.get("chairman_final_verdict"),
        "consensus_level": case.get("consensus_level"),
        "open_questions_count": len(case.get("open_questions_at_decision") or []),
        "lead_agent": (case.get("lead_agent") or {}).get("agent_id"),
    }


def rebuild_stock_timelines(data_dir: str | Path, *, ticker: str | None = None) -> list[Path]:
    root = Path(data_dir)
    tickers = {str(case.get("ticker")) for case in load_decision_cases(root) if case.get("ticker")}
    tickers.update(str(entry.get("ticker")) for entry in load_knowledge_entries(root) if entry.get("ticker"))
    if ticker:
        tickers = {ticker}
    written: list[Path] = []
    for current in sorted(tickers):
        payload = build_stock_timeline(root, current)
        json_path = stock_timeline_json_path(root, current)
        md_path = stock_timeline_markdown_path(root, current)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        md_path.write_text(render_stock_timeline_markdown(payload), encoding="utf-8")
        written.extend([json_path, md_path])
    return written


def build_stock_timeline(data_dir: str | Path, ticker: str) -> dict[str, Any]:
    root = Path(data_dir)
    cases = [case for case in load_decision_cases(root) if str(case.get("ticker")) == ticker]
    snapshots = [item for item in load_outcome_snapshots(root) if str(item.get("ticker")) == ticker]
    knowledge = [entry for entry in load_knowledge_entries(root) if str(entry.get("ticker")) == ticker]
    events: list[dict[str, Any]] = []
    for entry in knowledge:
        events.append(
            {
                "event_type": "perplexity_knowledge",
                "date": entry.get("event_date") or entry.get("research_date"),
                "title": entry.get("title") or entry.get("prompt_id"),
                "source_id": entry.get("prompt_id"),
                "summary": first_text(entry.get("event_summary"), entry.get("company_conclusions")),
                "open_questions": entry.get("open_questions") or [],
                "confidence_label": entry.get("confidence_label"),
            }
        )
    for case in cases:
        events.append(
            {
                "event_type": "chairman_decision",
                "date": case.get("as_of_date"),
                "title": f"{case.get('source_brief_id')} / {case.get('chairman_final_verdict')}",
                "source_id": case.get("case_id"),
                "summary": first_text(case.get("decision_chain")) or f"direction={case.get('decision_direction')}",
                "open_questions": case.get("open_questions_at_decision") or [],
                "consensus_level": case.get("consensus_level"),
            }
        )
    for snapshot in snapshots:
        if snapshot.get("status") == "pending":
            continue
        events.append(
            {
                "event_type": "outcome_snapshot",
                "date": snapshot.get("window_end_date"),
                "title": f"{snapshot.get('window_days')}D outcome / {snapshot.get('price_signal')}",
                "source_id": snapshot.get("snapshot_id"),
                "summary": f"price_change_pct={snapshot.get('price_change_pct')}%, status={snapshot.get('status')}",
                "price_change_pct": snapshot.get("price_change_pct"),
            }
        )
    events.sort(key=lambda item: str(item.get("date") or ""))
    return {
        "timeline_version": "stock_timeline_v1",
        "ticker": ticker,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "case_count": len(cases),
        "knowledge_count": len(knowledge),
        "outcome_count": len([item for item in snapshots if item.get("status") != "pending"]),
        "open_questions_count": sum(len(item.get("open_questions") or []) for item in events),
        "events": events,
    }


def render_stock_timeline_markdown(timeline: dict[str, Any]) -> str:
    lines = [
        f"# {timeline.get('ticker')} Stock Timeline",
        "",
        f"- generated_at: {timeline.get('generated_at')}",
        f"- case_count: {timeline.get('case_count')}",
        f"- knowledge_count: {timeline.get('knowledge_count')}",
        f"- outcome_count: {timeline.get('outcome_count')}",
        "",
        "## Events",
    ]
    for event in timeline.get("events") or []:
        lines.extend(
            [
                "",
                f"### {event.get('date') or 'unknown'} · {event.get('event_type')}",
                f"- source_id: `{event.get('source_id') or ''}`",
                f"- title: {event.get('title') or ''}",
                f"- summary: {event.get('summary') or ''}",
            ]
        )
        questions = event.get("open_questions") or []
        if questions:
            lines.append("- open_questions:")
            lines.extend(f"  - {item}" for item in questions[:5])
    lines.append("")
    return "\n".join(lines)


def write_monthly_review(data_dir: str | Path, *, month: str | None = None) -> tuple[Path, Path] | None:
    root = Path(data_dir)
    review = generate_monthly_review(root, month=month)
    if not review.get("month"):
        return None
    output_dir = root / LEARNING_DIRNAME / MONTHLY_REVIEW_DIRNAME
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"LEARNING-REVIEW-{review['month'].replace('-', '')}.json"
    md_path = output_dir / f"LEARNING-REVIEW-{review['month'].replace('-', '')}.md"
    json_path.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_monthly_review_markdown(review), encoding="utf-8")
    return md_path, json_path


def generate_monthly_review(data_dir: str | Path, *, month: str | None = None) -> dict[str, Any]:
    root = Path(data_dir)
    cases = load_decision_cases(root)
    if not month:
        month = latest_case_month(cases)
    if not month:
        return {"month": "", "cases": []}
    month_cases = [case for case in cases if str(case.get("as_of_date") or "").startswith(month)]
    snapshots = load_outcome_snapshots(root)
    case_ids = {case.get("case_id") for case in month_cases}
    month_snapshots = [item for item in snapshots if item.get("case_id") in case_ids]
    direction_counts = Counter(str(case.get("decision_direction")) for case in month_cases)
    verdict_counts = Counter(str(case.get("chairman_final_verdict")) for case in month_cases)
    outcome_counts = Counter(str(item.get("status")) for item in month_snapshots)
    open_questions = sum(len(case.get("open_questions_at_decision") or []) for case in month_cases)
    tickers = sorted({str(case.get("ticker")) for case in month_cases if case.get("ticker")})
    return {
        "review_version": "learning_monthly_review_v1",
        "month": month,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "case_count": len(month_cases),
        "tickers": tickers,
        "direction_counts": dict(direction_counts),
        "chairman_verdict_counts": dict(verdict_counts),
        "outcome_status_counts": dict(outcome_counts),
        "open_questions_at_decision_count": open_questions,
        "system_observations": build_monthly_observations(month_cases, month_snapshots),
        "cases": [shape_case_for_context(case) for case in month_cases],
    }


def build_monthly_observations(cases: list[dict[str, Any]], snapshots: list[dict[str, Any]]) -> list[str]:
    observations: list[str] = []
    if not cases:
        return ["本月尚无 decision case。"]
    open_questions = sum(len(case.get("open_questions_at_decision") or []) for case in cases)
    if open_questions:
        observations.append(f"本月进入决策时仍带有 {open_questions} 个未关闭问题，说明研究复用仍有追问压力。")
    outcome_counts = Counter(str(item.get("status")) for item in snapshots if item.get("status") != "pending")
    if outcome_counts:
        observations.append(f"已到期 outcome snapshot 分布：{dict(outcome_counts)}。")
    else:
        observations.append("本月 outcome 多数未到验证窗口；暂不调整方法论。")
    direction_counts = Counter(str(case.get("decision_direction")) for case in cases)
    if direction_counts.get("watch", 0) > max(1, len(cases) // 2):
        observations.append("watch 占比较高；需要检查 Screener 是否只是把价量异动转交给投委会，而不是筛出非共识问题。")
    return observations


def render_monthly_review_markdown(review: dict[str, Any]) -> str:
    lines = [
        f"# Learning Review {review.get('month')}",
        "",
        f"- generated_at: {review.get('generated_at')}",
        f"- case_count: {review.get('case_count')}",
        f"- tickers: {', '.join(review.get('tickers') or [])}",
        f"- direction_counts: {review.get('direction_counts')}",
        f"- chairman_verdict_counts: {review.get('chairman_verdict_counts')}",
        f"- outcome_status_counts: {review.get('outcome_status_counts')}",
        "",
        "## System Observations",
    ]
    lines.extend(f"- {item}" for item in review.get("system_observations") or [])
    lines.append("")
    lines.append("## Cases")
    for case in review.get("cases") or []:
        lines.append(
            f"- {case.get('as_of_date')} {case.get('ticker')} {case.get('chairman_final_verdict')} "
            f"/ {case.get('decision_direction')} / open_questions={case.get('open_questions_count')}"
        )
    lines.append("")
    return "\n".join(lines)


def load_learning_overview(data_dir: str | Path) -> dict[str, Any]:
    root = Path(data_dir)
    cases = load_decision_cases(root)
    snapshots = load_outcome_snapshots(root)
    timelines = sorted((root / LEARNING_DIRNAME / TIMELINE_DIRNAME).glob("*.json"))
    monthly_reviews = sorted((root / LEARNING_DIRNAME / MONTHLY_REVIEW_DIRNAME).glob("LEARNING-REVIEW-*.json"))
    status_counts = Counter(str(case.get("status")) for case in cases)
    outcome_counts = Counter(str(item.get("status")) for item in snapshots)
    ticker_counts = Counter(str(case.get("ticker")) for case in cases)
    return {
        "decision_cases": len(cases),
        "outcome_snapshots": len(snapshots),
        "stock_timelines": len(timelines),
        "monthly_reviews": len(monthly_reviews),
        "status_counts": dict(status_counts),
        "outcome_status_counts": dict(outcome_counts),
        "top_tickers": ticker_counts.most_common(8),
        "latest_cases": sorted(cases, key=lambda item: str(item.get("as_of_date") or ""), reverse=True)[:10],
        "latest_monthly_review": str(monthly_reviews[-1]) if monthly_reviews else "",
    }


def load_stock_timeline(data_dir: str | Path, ticker: str) -> dict[str, Any]:
    path = stock_timeline_json_path(Path(data_dir), ticker)
    if not path.exists():
        return build_stock_timeline(data_dir, ticker)
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
    except json.JSONDecodeError:
        return build_stock_timeline(data_dir, ticker)
    return data if isinstance(data, dict) else {}


def load_decision_cases(root: Path) -> list[dict[str, Any]]:
    return load_json_list(root / LEARNING_DIRNAME / DECISION_CASES_FILENAME)


def load_outcome_snapshots(root: Path) -> list[dict[str, Any]]:
    return load_json_list(root / LEARNING_DIRNAME / OUTCOME_SNAPSHOTS_FILENAME)


def load_knowledge_entries(root: Path) -> list[dict[str, Any]]:
    db_path = root / "knowledge_store" / "knowledge.db"
    if not db_path.exists():
        return []
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM knowledge_entries").fetchall()
    except sqlite3.DatabaseError:
        return []
    return [decode_knowledge_row(dict(row)) for row in rows]


def decode_knowledge_row(row: dict[str, Any]) -> dict[str, Any]:
    decoded = dict(row)
    for key, out_key in (
        ("event_summary_json", "event_summary"),
        ("company_conclusions_json", "company_conclusions"),
        ("open_questions_json", "open_questions"),
    ):
        decoded[out_key] = parse_json_list(row.get(key))
    return decoded


def load_json_list(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "[]")
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def write_json_list(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def first_row_on_or_after(rows: list[dict[str, Any]], target: date) -> dict[str, Any] | None:
    for row in rows:
        row_date = parse_date(row.get("date"))
        if row_date and row_date >= target:
            return row
    return None


def calculate_change_pct(start: Any, end: Any) -> float | None:
    try:
        start_value = float(start)
        end_value = float(end)
    except (TypeError, ValueError):
        return None
    if start_value == 0:
        return None
    return round((end_value - start_value) / start_value * 100, 4)


def classify_price_signal(direction: Any, change_pct: float | None) -> str:
    if change_pct is None:
        return "no_price_data"
    direction = str(direction or "watch")
    if direction == "long":
        if change_pct >= 5:
            return "supports_direction"
        if change_pct <= -5:
            return "against_direction"
    if direction == "avoid":
        if change_pct <= -5:
            return "supports_direction"
        if change_pct >= 5:
            return "against_direction"
    if direction in {"watch", "abstain"}:
        if abs(change_pct) >= 15:
            return "large_move_requires_manual_review"
        return "neutral_for_non_directional_decision"
    return "neutral"


def snapshot_status_from_price_signal(price_signal: str) -> str:
    if price_signal == "supports_direction":
        return "price_supports"
    if price_signal == "against_direction":
        return "price_against"
    if price_signal == "large_move_requires_manual_review":
        return "requires_manual_review"
    if price_signal == "not_due":
        return "pending"
    return "inconclusive"


def case_date(case: dict[str, Any]) -> date | None:
    return parse_date(case.get("as_of_date") or case.get("available_context_cutoff"))


def parse_date(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    if len(text) >= 10:
        text = text[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        if len(text) == 8 and text.isdigit():
            try:
                return datetime.strptime(text, "%Y%m%d").date()
            except ValueError:
                return None
    return None


def date_from_brief_id(brief_id: str) -> str:
    parts = brief_id.split("-")
    for part in parts:
        if len(part) == 8 and part.isdigit():
            return f"{part[:4]}-{part[4:6]}-{part[6:]}"
    return datetime.now().date().isoformat()


def month_from_brief_id(brief_id: str) -> str:
    return date_from_brief_id(brief_id)[:7]


def latest_case_month(cases: list[dict[str, Any]]) -> str:
    months = sorted({str(case.get("as_of_date") or "")[:7] for case in cases if case.get("as_of_date")})
    return months[-1] if months else ""


def stock_timeline_json_path(root: Path, ticker: str) -> Path:
    return root / LEARNING_DIRNAME / TIMELINE_DIRNAME / f"{safe_filename(ticker)}.json"


def stock_timeline_markdown_path(root: Path, ticker: str) -> Path:
    return root / LEARNING_DIRNAME / TIMELINE_DIRNAME / f"{safe_filename(ticker)}.md"


def safe_filename(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in value)


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


def first_text(*candidates: Any) -> str:
    for candidate in candidates:
        if isinstance(candidate, list):
            for item in candidate:
                if item:
                    return str(item)
        elif candidate:
            return str(candidate)
    return ""
