"""Assemble Red Team audit outputs."""

from __future__ import annotations

import os
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from business_agents._common.knowledge_store import get_recent_knowledge_summary
from chairman.llm.narrative_generator import LLMClient
from chairman.models import Recommendation, ResearchSignal
from red_team import RED_TEAM_VERSION
from red_team.core.consensus_risk import assess_consensus_risk
from red_team.core.risk_completeness_evaluator import evaluate_risk_completeness
from red_team.core.rule_auditor import audit_rules, findings_by_recommendation
from red_team.llm.methodology_challenger import generate_challenges
from red_team.models import ChairmanAlignment, RedTeamAudit, RuleAuditFinding, SubstantiveObjection

DECISIONS_APPLIED = [
    "DEC-002",
    "DEC-004",
    "DEC-008",
    "DEC-011",
    "DEC-014",
    "TRIAL-001",
    "SCHEMA-REPAIR-001",
]


def assemble_audit(
    *,
    chairman_brief: dict[str, Any],
    recommendations: list[Recommendation],
    research_signals: list[ResearchSignal],
    audit_type: str,
    date: str,
    llm_client: LLMClient | None = None,
    use_llm: bool = True,
    rules_only: bool = False,
    data_dir: str | Path | None = None,
) -> RedTeamAudit:
    """Build a RedTeamAudit from Chairman metadata and raw inputs."""

    started_at = time.perf_counter()
    rule_findings = audit_rules(recommendations, research_signals, chairman_brief)
    risks = evaluate_risk_completeness(recommendations)
    challenges = []
    if not rules_only:
        signal_by_id = {s.research_signal_id: s for s in research_signals}
        for rec in recommendations:
            signal = _find_signal(rec, signal_by_id)
            challenges.append(generate_challenges(rec, signal, llm_client, use_llm=use_llm))

    alignment = build_chairman_alignment(chairman_brief, rule_findings, risks)
    substantive_objections = build_substantive_objections(
        chairman_brief,
        recommendations,
        rule_findings,
        date=date,
        data_dir=data_dir,
    )
    summary = build_executive_summary(recommendations, rule_findings, risks, substantive_objections)
    return RedTeamAudit(
        audit_id=build_audit_id(date, audit_type),
        generated_at=datetime.now().astimezone(),
        audit_type=audit_type,  # type: ignore[arg-type]
        chairman_brief_consumed=chairman_brief.get("brief_id", "UNKNOWN-BRIEF"),
        executive_summary=summary,
        rule_audit_findings=rule_findings,
        methodology_challenges=challenges,
        risk_completeness_findings=risks,
        substantive_objections=substantive_objections,
        chairman_alignment=alignment,
        red_team_version=RED_TEAM_VERSION,
        decisions_applied=DECISIONS_APPLIED,
        llm_used=bool(use_llm and llm_client and not rules_only),
        llm_model=os.getenv("LLM_MODEL") if use_llm and llm_client and not rules_only else None,
        processing_time_seconds=round(time.perf_counter() - started_at, 4),
        rules_only=rules_only,
    )


def build_audit_id(date: str, audit_type: str) -> str:
    compact = date.replace("-", "")
    suffix = {
        "morning": "AM",
        "evening": "PM",
        "ad_hoc": "ADHOC",
        "escalation_response": "ESC",
    }[audit_type]
    return f"AUDIT-{compact}-{suffix}"


def build_executive_summary(
    recommendations: list[Recommendation],
    findings: list[RuleAuditFinding],
    risks: list[Any],
    substantive_objections: list[SubstantiveObjection] | None = None,
) -> dict[str, Any]:
    grouped = findings_by_recommendation(findings)
    strongly = []
    reservations = []
    no_major = []
    for rec in recommendations:
        rec_findings = grouped.get(rec.recommendation_id, [])
        severities = {finding.severity for finding in rec_findings}
        if "critical" in severities:
            strongly.append(rec.recommendation_id)
        elif "high" in severities:
            reservations.append(rec.recommendation_id)
        else:
            no_major.append(rec.recommendation_id)
    return {
        "total_recommendations_audited": len(recommendations),
        "strongly_oppose": strongly,
        "with_reservations": reservations,
        "no_major_issues": no_major,
        "systemic_risks_count": len(risks),
        "substantive_objections_count": len(substantive_objections or []),
        "red_team_verdicts": {
            objection.ticker: objection.red_team_verdict for objection in substantive_objections or []
        },
    }


def build_substantive_objections(
    chairman_brief: dict[str, Any],
    recommendations: list[Recommendation],
    findings: list[RuleAuditFinding],
    *,
    date: str,
    data_dir: str | Path | None = None,
) -> list[SubstantiveObjection]:
    """Build strongest investment objections using Chairman verdicts and memory."""

    recs_by_ticker: dict[str, list[Recommendation]] = defaultdict(list)
    finding_ids_by_ticker: dict[str, list[str]] = defaultdict(list)
    for rec in recommendations:
        recs_by_ticker[rec.ticker].append(rec)
    rec_ticker_by_id = {rec.recommendation_id: rec.ticker for rec in recommendations}
    for finding in findings:
        if finding.target_recommendation_id in rec_ticker_by_id:
            finding_ids_by_ticker[rec_ticker_by_id[finding.target_recommendation_id]].append(finding.rule_id)

    summary_by_ticker = {
        str(summary.get("ticker")): summary for summary in chairman_brief.get("per_recommendation_summary", [])
    }
    objections: list[SubstantiveObjection] = []
    for ticker, recs in sorted(recs_by_ticker.items()):
        summary = summary_by_ticker.get(ticker, {})
        knowledge = (
            summary.get("historical_knowledge")
            or chairman_brief.get("knowledge_memory", {}).get(ticker)
            or load_memory_from_store(data_dir, ticker, date)
            or {}
        )
        verdict = summary.get("chairman_verdict", {}) or chairman_brief.get("final_verdicts", {}).get("by_ticker", {}).get(ticker, {})
        open_questions = knowledge.get("open_questions", []) or []
        entries = knowledge.get("entries", []) or []
        similar_cases = knowledge.get("similar_cases", []) or []
        historical_conflicts = knowledge.get("historical_conflicts", []) or []
        counter_evidence = collect_counter_evidence(entries, open_questions, historical_conflicts)
        has_perplexity = any(
            ref.used_perplexity_results for rec in recs for ref in rec.upstream_research_signals
        )
        rule_ids = finding_ids_by_ticker.get(ticker, [])
        final_verdict = str(verdict.get("final_verdict") or "unknown")
        consensus_risk = assess_consensus_risk(ticker, recs, verdict, knowledge)
        red_team_verdict = choose_red_team_verdict(
            final_verdict=final_verdict,
            has_perplexity=has_perplexity,
            open_questions=open_questions,
            historical_conflicts=historical_conflicts,
            rule_ids=rule_ids,
            consensus_risk=consensus_risk,
        )
        objections.append(
            SubstantiveObjection(
                ticker=ticker,
                red_team_verdict=red_team_verdict,
                strongest_objection=build_strongest_objection(
                    ticker,
                    final_verdict=final_verdict,
                    has_perplexity=has_perplexity,
                    open_questions=open_questions,
                    historical_conflicts=historical_conflicts,
                    similar_cases=similar_cases,
                    rule_ids=rule_ids,
                    consensus_risk=consensus_risk,
                ),
                evidence_chain_risk=build_evidence_chain_risk(
                    has_perplexity=has_perplexity,
                    entries_count=len(entries),
                    rule_ids=rule_ids,
                    consensus_risk=consensus_risk,
                ),
                missed_counter_evidence=counter_evidence,
                historical_failure_pattern=build_historical_failure_pattern(
                    entries,
                    open_questions,
                    historical_conflicts,
                    similar_cases,
                ),
                similar_case_risks=build_similar_case_risks(similar_cases),
                consensus_risk=consensus_risk,
                what_must_be_true_for_chairman_to_be_right=build_must_be_true(verdict, recs),
                what_would_invalidate_this_decision=build_invalidation_points(
                    final_verdict=final_verdict,
                    open_questions=open_questions,
                    historical_conflicts=historical_conflicts,
                    rule_ids=rule_ids,
                    consensus_risk=consensus_risk,
                ),
                chairman_second_review=build_second_review_recommendation(
                    final_verdict=final_verdict,
                    red_team_verdict=red_team_verdict,
                    open_questions=open_questions,
                    historical_conflicts=historical_conflicts,
                    rule_ids=rule_ids,
                ),
                referenced_knowledge_entries=[str(entry.get("prompt_id")) for entry in entries if entry.get("prompt_id")],
            )
        )
    return objections


def load_memory_from_store(data_dir: str | Path | None, ticker: str, date: str) -> dict[str, Any]:
    if data_dir is None:
        return {}
    return get_recent_knowledge_summary(data_dir, ticker, as_of_date=date)


def collect_counter_evidence(
    entries: list[dict[str, Any]],
    open_questions: list[str],
    historical_conflicts: list[str],
) -> list[str]:
    items: list[str] = []
    for entry in entries:
        items.extend(entry.get("counter_evidence", []) or [])
    items.extend(open_questions)
    items.extend(historical_conflicts)
    deduped = []
    for item in items:
        if item and item not in deduped:
            deduped.append(str(item))
    return deduped[:6]


def choose_red_team_verdict(
    *,
    final_verdict: str,
    has_perplexity: bool,
    open_questions: list[str],
    historical_conflicts: list[str],
    rule_ids: list[str],
    consensus_risk: dict[str, Any] | None = None,
) -> str:
    consensus_risk = consensus_risk or {}
    if final_verdict == "act" and rule_ids:
        return "block"
    if final_verdict == "act" and consensus_risk.get("risk_level") == "high":
        return "challenge"
    if final_verdict == "act" and (open_questions or historical_conflicts or not has_perplexity):
        return "challenge"
    if consensus_risk.get("risk_level") == "high":
        return "monitor"
    if rule_ids or open_questions or historical_conflicts or not has_perplexity:
        return "monitor"
    return "no_major_objection"


def build_strongest_objection(
    ticker: str,
    *,
    final_verdict: str,
    has_perplexity: bool,
    open_questions: list[str],
    historical_conflicts: list[str],
    similar_cases: list[dict[str, Any]],
    rule_ids: list[str],
    consensus_risk: dict[str, Any] | None = None,
) -> str:
    if rule_ids:
        return f"{ticker} 的裁决仍有规则/合规审计问题：{', '.join(rule_ids)}。"
    if (consensus_risk or {}).get("risk_level") == "high":
        return f"{ticker} 的三位 partner 观点可能过度接近市场共识：{consensus_risk.get('reason')}"
    if historical_conflicts:
        return f"知识库存在与本次裁决冲突的历史反例：{historical_conflicts[0]}"
    if open_questions:
        return f"历史研究仍有未关闭问题，可能直接削弱 Chairman 的 {final_verdict} 裁决：{open_questions[0]}"
    if similar_cases:
        return f"存在 {len(similar_cases)} 条相似历史案例；Chairman 必须说明这次为什么不是同类失败路径。"
    if not has_perplexity:
        return "本次判断缺少 Perplexity 深度研究背书，证据链仍停留在价量和 Agent 推断层。"
    return "未发现单一阻断点，但仍需确认 Chairman 没有把短期事件过度外推为长期 thesis。"


def build_evidence_chain_risk(
    *,
    has_perplexity: bool,
    entries_count: int,
    rule_ids: list[str],
    consensus_risk: dict[str, Any] | None = None,
) -> str:
    risks = []
    if not has_perplexity:
        risks.append("缺少 Perplexity 原始研究消费记录")
    if entries_count == 0:
        risks.append("知识库没有同标的历史研究可比")
    if rule_ids:
        risks.append(f"存在规则审计发现 {', '.join(rule_ids)}")
    if (consensus_risk or {}).get("risk_level") in {"medium", "high"}:
        risks.append(f"共识风险 {consensus_risk.get('risk_level')}：{consensus_risk.get('reason')}")
    return "；".join(risks) if risks else "证据链暂未发现结构性缺口。"


def build_historical_failure_pattern(
    entries: list[dict[str, Any]],
    open_questions: list[str],
    historical_conflicts: list[str],
    similar_cases: list[dict[str, Any]],
) -> str:
    if historical_conflicts:
        return f"知识库直接记录了 {len(historical_conflicts)} 条历史冲突/反例，不能跳过解释。"
    if similar_cases:
        sample = similar_cases[0]
        return (
            f"存在 {len(similar_cases)} 条相似案例；最近样本是 "
            f"{sample.get('stock_code')} / {sample.get('prompt_id')}，需要防止错误类比。"
        )
    if entries and open_questions:
        return f"该标的已有 {len(entries)} 条历史研究，但仍遗留 {len(open_questions)} 个未关闭问题。"
    if entries:
        return f"该标的已有 {len(entries)} 条历史研究；需要继续验证历史催化剂是否被后续事实确认。"
    return "暂无同标的历史失败样本，主要风险是没有纵向对照。"


def build_must_be_true(verdict: dict[str, Any], recs: list[Recommendation]) -> str:
    lead_agent = (verdict.get("lead_agent") or {}).get("agent_id")
    directions = ", ".join(f"{rec.agent_id.value}:{rec.direction.value}" for rec in recs)
    return (
        f"要让 Chairman 裁决成立，{lead_agent or '主导 Agent'} 的关键 thesis 必须比其他分歧更能解释事实；"
        f"同时当前 Agent 分布（{directions}）不能是由同一上游错误信号共同驱动。"
    )


def build_invalidation_points(
    *,
    final_verdict: str,
    open_questions: list[str],
    historical_conflicts: list[str],
    rule_ids: list[str],
    consensus_risk: dict[str, Any] | None = None,
) -> list[str]:
    points = [
        "后续公开信息显示本次异动只是指数、期权或短期流动性驱动，而非公司或行业基本面变化。",
        "Perplexity 报告中的核心催化剂无法被财报、监管文件、管理层电话会或主流媒体交叉验证。",
    ]
    if final_verdict == "act":
        points.append("Red Team 发现的未关闭问题在后续 7-30 天内被验证为真实风险。")
    if (consensus_risk or {}).get("risk_level") in {"medium", "high"}:
        points.extend((consensus_risk or {}).get("required_questions") or [])
    points.extend(open_questions[:3])
    points.extend(historical_conflicts[:3])
    points.extend(f"规则审计 {rule_id} 未关闭。" for rule_id in rule_ids[:3])
    return points[:8]


def build_similar_case_risks(similar_cases: list[dict[str, Any]]) -> list[str]:
    risks: list[str] = []
    for case in similar_cases[:5]:
        risks.append(
            f"{case.get('stock_code')} / {case.get('prompt_id')}: "
            f"{(case.get('counter_evidence') or case.get('open_questions') or case.get('event_summary') or ['未抽取风险'])[0]}"
        )
    return risks


def build_second_review_recommendation(
    *,
    final_verdict: str,
    red_team_verdict: str,
    open_questions: list[str],
    historical_conflicts: list[str],
    rule_ids: list[str],
) -> dict[str, Any]:
    if red_team_verdict == "block":
        revised = "reject"
    elif red_team_verdict == "challenge":
        revised = "research_more"
    elif red_team_verdict == "monitor" and final_verdict == "act":
        revised = "wait"
    else:
        revised = final_verdict
    return {
        "second_review_required": red_team_verdict in {"block", "challenge", "monitor"},
        "recommended_revised_verdict": revised,
        "reason": {
            "red_team_verdict": red_team_verdict,
            "open_questions_count": len(open_questions),
            "historical_conflicts_count": len(historical_conflicts),
            "rule_findings_count": len(rule_ids),
        },
    }


def build_chairman_alignment(
    chairman_brief: dict[str, Any],
    findings: list[RuleAuditFinding],
    risks: list[Any],
) -> ChairmanAlignment:
    chairman_ids = set()
    for bucket in ("high_priority", "medium_priority"):
        for item in chairman_brief.get("red_team_queue", {}).get(bucket, []) or []:
            if item.get("recommendation_id"):
                chairman_ids.add(item["recommendation_id"])

    finding_ids = {f.target_recommendation_id for f in findings if f.target_recommendation_id}
    agreements = sorted(chairman_ids & finding_ids)
    additions = sorted(finding_ids - chairman_ids)
    disagreements = []

    if risks and not chairman_ids:
        disagreements.append("Chairman 未标注 escalation，但 Red Team 发现系统级风险。")
    for summary in chairman_brief.get("per_recommendation_summary", []):
        if (
            summary.get("direction_consensus", {}).get("consensus_level") == "full_consensus_long"
            and findings
        ):
            disagreements.append(
                f"{summary.get('ticker')} Chairman 标注全员一致，但 Red Team 发现规则审计问题。"
            )
            break

    return ChairmanAlignment(agreements=agreements, disagreements=disagreements, additions=additions)


def _find_signal(
    rec: Recommendation,
    signal_by_id: dict[str, ResearchSignal],
) -> ResearchSignal | None:
    for ref in rec.upstream_research_signals:
        if ref.research_signal_id in signal_by_id:
            return signal_by_id[ref.research_signal_id]
    return None
