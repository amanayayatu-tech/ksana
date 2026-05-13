"""Disagreement classification for Chairman."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from chairman.models import (
    AgentId,
    ConsensusLevel,
    DirectionConsensus,
    DisagreementAnalysis,
    DisagreementType,
    Recommendation,
    ResearchSignal,
)


def classify_disagreement(
    recommendations: list[Recommendation],
    research_signal: ResearchSignal | None,
    consensus: DirectionConsensus,
) -> DisagreementAnalysis:
    """Classify disagreement into the five types from the design draft."""

    if consensus.consensus_level in {
        ConsensusLevel.FULL_CONSENSUS_LONG,
        ConsensusLevel.FULL_CONSENSUS_AVOID,
        ConsensusLevel.ALL_ABSTAIN,
    }:
        return DisagreementAnalysis(primary_type=None, narrative="3 个 Agent 完全一致，无需分析分歧")

    if _check_dual_gate_anomaly(recommendations):
        return DisagreementAnalysis(
            primary_type=DisagreementType.POTENTIAL_AGENT_ERROR,
            narrative="李国飞 dual_gate_consistency 触发 anomaly_review_required。",
            red_team_escalation_required=True,
            escalation_reason="李国飞 dual_gate_consistency 触发 anomaly_review_required",
        )

    if _check_evidence_unverified_split(recommendations):
        return DisagreementAnalysis(
            primary_type=DisagreementType.EVIDENCE_UNVERIFIED_PROPAGATION,
            narrative="部分 Agent 依赖未验证上游证据，Chairman 已自动降权。",
        )

    if _check_upstream_signal_split(recommendations, research_signal):
        return DisagreementAnalysis(
            primary_type=DisagreementType.UPSTREAM_SIGNAL_CONSUMPTION,
            narrative="Agent 对同一 4.1 研究信号的采纳结论不同。",
        )

    if _check_data_input_difference(recommendations):
        return DisagreementAnalysis(
            primary_type=DisagreementType.DATA_INPUT_DIFFERENCE,
            narrative="Agent 引用的数据时效跨度超过 30 天。",
            red_team_escalation_required=True,
            escalation_reason="数据时效差异超过 30 天",
        )

    return DisagreementAnalysis(
        primary_type=DisagreementType.METHODOLOGY_DNA,
        narrative="分歧来源是方法论 DNA 差异，不是格式错误。",
    )


def _check_dual_gate_anomaly(recommendations: list[Recommendation]) -> bool:
    """Return true for DEC-011 case_3 anomaly."""

    for rec in recommendations:
        if (
            rec.agent_id == AgentId.LIGUOFEI
            and rec.deployment_compliance.dual_gate_consistency == "anomaly_review_required"
        ):
            return True
    return False


def _check_evidence_unverified_split(recommendations: list[Recommendation]) -> bool:
    """Check whether some agents inherited unverified evidence and others did not. DEC-004."""

    statuses = [
        any(signal.evidence_unverified_inherited for signal in rec.upstream_research_signals)
        for rec in recommendations
        if rec.upstream_research_signals
    ]
    return bool(statuses) and len(set(statuses)) > 1


def _check_upstream_signal_split(
    recommendations: list[Recommendation],
    research_signal: ResearchSignal | None,
) -> bool:
    """Check whether agents disagree on accepting the same research signal."""

    if not research_signal:
        return False
    verdicts: list[str] = []
    for rec in recommendations:
        for signal_ref in rec.upstream_research_signals:
            if signal_ref.research_signal_id == research_signal.research_signal_id:
                verdicts.append(signal_ref.my_methodology_verdict)
                break
    return len(set(verdicts)) > 1


def _check_data_input_difference(recommendations: list[Recommendation]) -> bool:
    """Check whether referenced data dates span more than 30 days."""

    dates: list[date] = []
    for rec in recommendations:
        for data_point in rec.data_points:
            parsed = _parse_date(data_point.get("date"))
            if parsed:
                dates.append(parsed)
    if len(dates) < 2:
        return False
    return (max(dates) - min(dates)).days > 30


def _parse_date(value: Any) -> date | None:
    """Parse common date formats from data_points."""

    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(text[:10] if fmt != "%Y%m%d" else text[:8], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None
