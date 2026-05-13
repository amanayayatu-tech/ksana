"""Assemble Red Team audit outputs."""

from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Any

from chairman.llm.narrative_generator import LLMClient
from chairman.models import Recommendation, ResearchSignal
from red_team import RED_TEAM_VERSION
from red_team.core.risk_completeness_evaluator import evaluate_risk_completeness
from red_team.core.rule_auditor import audit_rules, findings_by_recommendation
from red_team.llm.methodology_challenger import generate_challenges
from red_team.models import ChairmanAlignment, RedTeamAudit, RuleAuditFinding

DECISIONS_APPLIED = ["DEC-002", "DEC-004", "DEC-008", "DEC-011", "DEC-014"]


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
    summary = build_executive_summary(recommendations, rule_findings, risks)
    return RedTeamAudit(
        audit_id=build_audit_id(date, audit_type),
        generated_at=datetime.now().astimezone(),
        audit_type=audit_type,  # type: ignore[arg-type]
        chairman_brief_consumed=chairman_brief.get("brief_id", "UNKNOWN-BRIEF"),
        executive_summary=summary,
        rule_audit_findings=rule_findings,
        methodology_challenges=challenges,
        risk_completeness_findings=risks,
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
