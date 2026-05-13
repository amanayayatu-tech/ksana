"""Pydantic models for Red Team Agent v0.1."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class RedTeamModel(BaseModel):
    """Base model preserving audit context."""

    model_config = ConfigDict(extra="allow")


class RuleAuditFinding(RedTeamModel):
    """One hard-rule audit finding."""

    rule_id: str
    severity: Literal["critical", "high", "medium", "low", "info"]
    target_recommendation_id: str | None = None
    target_agent_id: str | None = None
    finding_text: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    referenced_decisions: list[str] = Field(default_factory=list)


class Challenge(RedTeamModel):
    """One Red Team challenge question."""

    text: str
    referenced_fields: list[str] = Field(default_factory=list)


class MethodologyChallenge(RedTeamModel):
    """Challenge set for one recommendation."""

    recommendation_id: str
    agent_id: str
    ticker: str
    challenges: list[Challenge]
    agent_response_required: bool = False


class RiskCompletenessFinding(RedTeamModel):
    """Systemic risk found outside one agent's local view."""

    risk_type: str
    affected_recommendations: list[str]
    finding_text: str
    severity: Literal["critical", "high", "medium", "low", "info"]


class ChairmanAlignment(RedTeamModel):
    """Agreement, disagreement, and additions versus Chairman findings."""

    agreements: list[str] = Field(default_factory=list)
    disagreements: list[str] = Field(default_factory=list)
    additions: list[str] = Field(default_factory=list)


class RedTeamAudit(RedTeamModel):
    """Structured Red Team audit output."""

    audit_id: str
    generated_at: datetime
    audit_type: Literal["morning", "evening", "ad_hoc", "escalation_response"]
    chairman_brief_consumed: str
    executive_summary: dict[str, Any]
    rule_audit_findings: list[RuleAuditFinding]
    methodology_challenges: list[MethodologyChallenge]
    risk_completeness_findings: list[RiskCompletenessFinding]
    chairman_alignment: ChairmanAlignment
    red_team_version: str = "0.1"
    decisions_applied: list[str] = Field(default_factory=list)
    llm_used: bool = False
    llm_model: str | None = None
    processing_time_seconds: float = 0.0
    rules_only: bool = False
