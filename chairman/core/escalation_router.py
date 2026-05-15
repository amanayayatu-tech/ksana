"""Red Team escalation routing for Chairman."""

from __future__ import annotations

from chairman.models import (
    AgentId,
    ConsensusLevel,
    Direction,
    DirectionConsensus,
    DisagreementAnalysis,
    Escalation,
    Priority,
    Recommendation,
    RedTeamEscalation,
)


def determine_escalation(
    recommendations: list[Recommendation],
    consensus: DirectionConsensus,
    disagreement: DisagreementAnalysis,
) -> RedTeamEscalation:
    """Determine Red Team escalation items.

    Implements DEC-004 and DEC-011 plus deployment permission double-checks.
    """

    escalations: list[Escalation] = []

    for rec in recommendations:
        if (
            rec.agent_id == AgentId.G_PARTNER
            and rec.deployment_compliance.dual_gate_consistency == "anomaly_review_required"
        ):
            escalations.append(
                Escalation(
                    priority=Priority.HIGH,
                    recommendation_id=rec.recommendation_id,
                    reason="DEC-011 case_3: dual_gate anomaly",
                    agent_id=rec.agent_id,
                    dual_gate_anomaly=True,
                )
            )

        if rec.direction == Direction.LONG and any(
            signal.evidence_unverified_inherited for signal in rec.upstream_research_signals
        ):
            escalations.append(
                Escalation(
                    priority=Priority.HIGH,
                    recommendation_id=rec.recommendation_id,
                    reason="DEC-004: long 建议依赖未验证证据",
                    agent_id=rec.agent_id,
                    evidence_unverified_inherited=True,
                )
            )

        if not rec.deployment_compliance.hard_rules_passed.forbidden_actions_check:
            escalations.append(
                Escalation(
                    priority=Priority.CRITICAL,
                    recommendation_id=rec.recommendation_id,
                    reason="违反 deployment_layer 权限边界",
                    agent_id=rec.agent_id,
                )
            )

    if consensus.consensus_level == ConsensusLevel.SPLIT_LONG_VS_AVOID:
        escalations.append(
            Escalation(
                priority=Priority.MEDIUM,
                reason="方向完全相反，建议 Red Team 复核分歧来源",
                ticker=consensus.ticker,
            )
        )

    if disagreement.red_team_escalation_required:
        escalations.append(
            Escalation(
                priority=Priority.MEDIUM,
                reason=disagreement.escalation_reason or "分歧分析要求 Red Team 复核",
                disagreement_type=disagreement.primary_type,
            )
        )

    return RedTeamEscalation(escalations=escalations)
