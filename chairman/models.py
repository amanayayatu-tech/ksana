"""Pydantic contracts for Chairman Agent v0.1."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class ChairmanModel(BaseModel):
    """Base model that keeps method-specific fields instead of discarding them."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class Direction(str, Enum):
    """Unified direction enum. DEC-005."""

    LONG = "long"
    SHORT = "short"
    WATCH = "watch"
    AVOID = "avoid"
    ABSTAIN = "abstain"


class AgentId(str, Enum):
    """Trading agent identifiers."""

    FENGLIU = "fengliu_reverse_odds"
    WANMU = "wanmu_single_sided"
    LIGUOFEI = "liguofei_zen_value"


class ConsensusLevel(str, Enum):
    """Direction consensus patterns used by Chairman."""

    FULL_CONSENSUS_LONG = "full_consensus_long"
    FULL_CONSENSUS_AVOID = "full_consensus_avoid"
    MAJORITY_LONG = "majority_long"
    MAJORITY_AVOID = "majority_avoid"
    SPLIT_LONG_VS_AVOID = "split_long_vs_avoid"
    MIXED_LONG_WATCH = "mixed_long_watch"
    MOSTLY_ABSTAIN = "mostly_abstain"
    ALL_ABSTAIN = "all_abstain"
    OTHER = "other"


class DisagreementType(str, Enum):
    """Five disagreement classes from chairman_design_draft.md Section 3.3."""

    METHODOLOGY_DNA = "methodology_dna"
    DATA_INPUT_DIFFERENCE = "data_input_difference"
    UPSTREAM_SIGNAL_CONSUMPTION = "upstream_signal_consumption"
    EVIDENCE_UNVERIFIED_PROPAGATION = "evidence_unverified_propagation"
    POTENTIAL_AGENT_ERROR = "potential_agent_error"


class Priority(str, Enum):
    """Red Team queue priority."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class BriefType(str, Enum):
    """Supported brief types."""

    MORNING = "morning"
    EVENING = "evening"
    AD_HOC = "ad_hoc"


class HardRulesPassed(ChairmanModel):
    """Deployment hard-rule checks from deployment_layer.md Section 10.1."""

    position_size_pct: bool = True
    industry_exposure_pct: bool = True
    cash_floor_pct: bool = True
    liquidity_three_locks: bool = True
    market_cap_minimum: bool = True
    forbidden_actions_check: bool = True
    cooldown_check: bool = True


class DeploymentCompliance(ChairmanModel):
    """Shared deployment compliance block."""

    deployment_layer_version: str | float | None = None
    hard_rules_passed: HardRulesPassed = Field(default_factory=HardRulesPassed)
    any_failure_must_abstain: bool = False
    failure_details: list[Any] = Field(default_factory=list)
    abstain_reason: str | None = None
    dual_gate_consistency: (
        Literal["aligned", "independent_not_yet_ready", "anomaly_review_required", "both_failed"]
        | None
    ) = None


class AuthorityResolution(ChairmanModel):
    """Shared Layered Authority resolution block."""

    overridden_by_deployment: bool = False
    overridden_principle: str | None = None
    philosophy_deferred: bool = False
    kill_log: list[Any] = Field(default_factory=list)
    upstream_signal_disagreement: bool = False
    disagreement_reason: str | None = None


class UpstreamSignalRef(ChairmanModel):
    """Reference from a trading recommendation to a 4.1 research signal."""

    research_signal_id: str
    signal_summary: str | None = None
    my_methodology_verdict: Literal["accepted", "rejected", "partial"] = "partial"
    verdict_reason: str | None = None
    relevance_score: int | None = Field(default=None, ge=0, le=100)
    pull_request_id: str | None = None
    used_perplexity_results: bool = False
    perplexity_prompt_ids_consumed: list[str] = Field(default_factory=list)
    evidence_unverified_inherited: bool = False
    confidence_ceiling_applied: int | None = Field(default=None, ge=0, le=100)
    red_team_priority_flag: Literal["low", "medium", "high"] | None = None
    chairman_weight_multiplier: float | None = Field(default=None, ge=0, le=1)
    mapped_to_three_models: dict[str, Any] | None = None
    contributes_to_collaborative_validation: bool | None = None
    mapped_to_three_powers: dict[str, Any] | None = None


class BaseRecommendation(ChairmanModel):
    """Fields shared by the three trading agents."""

    recommendation_id: str
    agent_id: AgentId
    ticker: str
    market: Literal["HK", "US"]
    direction: Direction
    confidence: int = Field(ge=0, le=100)
    entry_zone: list[float] | None = None
    target_price: float | str | None = None
    stop_loss: float | str | dict[str, Any] | None = None
    position_size_pct: float | None = None
    deployment_compliance: DeploymentCompliance = Field(default_factory=DeploymentCompliance)
    authority_resolution: AuthorityResolution = Field(default_factory=AuthorityResolution)
    upstream_research_signals: list[UpstreamSignalRef] = Field(default_factory=list)
    thesis: str = ""
    one_liner_thesis: str | None = None
    abstain_reason: str | None = None
    data_points: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_abstain_reason(self) -> BaseRecommendation:
        """Keep abstain explicit because it is a meaningful signal. DEC-003."""

        if (
            self.direction == Direction.ABSTAIN
            and not self.abstain_reason
            and not self.deployment_compliance.abstain_reason
        ):
            raise ValueError("direction=abstain requires abstain_reason")
        return self


class FengliuRecommendation(BaseRecommendation):
    """Fengliu-specific recommendation fields."""

    agent_id: Literal[AgentId.FENGLIU] = AgentId.FENGLIU
    fengliu_specific_framework: dict[str, Any] = Field(default_factory=dict)
    kill_type_heuristic: dict[str, Any] | None = None
    circle_status: str | None = None
    kill_type: str | None = None


class WanmuRecommendation(BaseRecommendation):
    """Wanmu-specific recommendation fields."""

    agent_id: Literal[AgentId.WANMU] = AgentId.WANMU
    three_selection: dict[str, Any] = Field(default_factory=dict)
    three_models: dict[str, Any] = Field(default_factory=dict)
    three_cuts: dict[str, Any] = Field(default_factory=dict)
    three_rates: dict[str, Any] = Field(default_factory=dict)
    wanmu_rating: dict[str, Any] = Field(default_factory=dict)
    collaborative_validation: dict[str, Any] = Field(default_factory=dict)
    safety_margin: dict[str, Any] = Field(default_factory=dict)


class LiguofeiRecommendation(BaseRecommendation):
    """Liguofei-specific recommendation fields."""

    agent_id: Literal[AgentId.LIGUOFEI] = AgentId.LIGUOFEI
    moat_assessment: dict[str, Any] = Field(default_factory=dict)
    evolution_power: dict[str, Any] = Field(default_factory=dict)
    entropy_reduction: dict[str, Any] = Field(default_factory=dict)
    bayesian_update: dict[str, Any] = Field(default_factory=dict)
    key_point_data: list[dict[str, Any]] = Field(default_factory=list)
    time_box: dict[str, Any] = Field(default_factory=dict)
    red_team: dict[str, Any] = Field(default_factory=dict)
    portfolio_drawdown_guard: dict[str, Any] = Field(default_factory=dict)
    action: Literal["buy", "add", "reduce", "sell", "watch", "avoid", "abstain"] = "watch"


class CandidateTarget(ChairmanModel):
    """Target mentioned by research_signal."""

    ticker: str
    market: Literal["HK", "US"] | str
    company_name: str | None = None
    relevance_score: int | None = Field(default=None, ge=0, le=100)
    role: Literal["primary", "secondary", "comparable"] | None = None


class ResearchSignal(ChairmanModel):
    """4.1 research upstream signal. Only Chairman-used fields are strict."""

    research_signal_id: str
    emitted_at: datetime | str | None = None
    emitter: str = "4.1_research_system"
    signal_status: Literal["active", "superseded", "invalidated", "resolved"] = "active"
    signal_type: Literal["discontinuity", "event", "mispricing", "bayesian_shift", "abstain"]
    research_stage: Literal["daily_scan", "special_attention", "deep_research", "trade_ready"]
    signal_summary: str
    candidate_targets: list[CandidateTarget] = Field(default_factory=list)
    discontinuity_assessment: dict[str, Any] = Field(default_factory=dict)
    bayesian_update: dict[str, Any] = Field(default_factory=dict)
    routing_recommendation: dict[str, Any] = Field(default_factory=dict)
    perplexity_research: dict[str, Any] = Field(default_factory=dict)
    data_points: list[dict[str, Any]] = Field(default_factory=list)
    downstream_responses: list[dict[str, Any]] = Field(default_factory=list)


class DirectionConsensus(ChairmanModel):
    """Structured output of direction consensus calculation."""

    ticker: str | None = None
    market: str | None = None
    vote_distribution: dict[str, list[str]]
    consensus_level: ConsensusLevel
    weighted_long_strength: float
    agents_voted: int
    long_count: int
    short_count: int
    avoid_count: int
    watch_count: int
    abstain_count: int


class DisagreementAnalysis(ChairmanModel):
    """Structured disagreement analysis."""

    primary_type: DisagreementType | None = None
    narrative: str
    red_team_escalation_required: bool = False
    escalation_reason: str | None = None


class Escalation(ChairmanModel):
    """One Red Team escalation item."""

    priority: Priority
    reason: str
    recommendation_id: str | None = None
    agent_id: AgentId | str | None = None
    ticker: str | None = None
    disagreement_type: DisagreementType | str | None = None
    evidence_unverified_inherited: bool = False
    dual_gate_anomaly: bool = False


class RedTeamEscalation(ChairmanModel):
    """Red Team escalation result."""

    escalations: list[Escalation] = Field(default_factory=list)

    @property
    def high_priority(self) -> list[Escalation]:
        return [e for e in self.escalations if e.priority in {Priority.CRITICAL, Priority.HIGH}]

    @property
    def medium_priority(self) -> list[Escalation]:
        return [e for e in self.escalations if e.priority == Priority.MEDIUM]


class ChairmanBrief(ChairmanModel):
    """Structured metadata for Markdown and JSON brief outputs."""

    brief_id: str
    generated_at: datetime
    brief_type: BriefType
    executive_summary: dict[str, Any]
    per_recommendation_summary: list[dict[str, Any]]
    upstream_coverage_status: dict[str, Any]
    red_team_queue: dict[str, Any]
    chairman_observations: list[dict[str, Any]] = Field(default_factory=list)
    chairman_version: str = "0.1"
    decisions_applied: list[str] = Field(default_factory=list)
    llm_used: bool = False
    llm_model: str | None = None
    processing_time_seconds: float = 0.0
    input_files_consumed: list[str] = Field(default_factory=list)


class ValidationResult(ChairmanModel):
    """Human-readable schema validation result."""

    valid: bool
    item: Any | None = None
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


Recommendation = FengliuRecommendation | WanmuRecommendation | LiguofeiRecommendation


def format_validation_error(error: ValidationError) -> list[str]:
    """Convert Pydantic errors into short, readable messages."""

    messages: list[str] = []
    for err in error.errors():
        loc = ".".join(str(part) for part in err.get("loc", ())) or "<root>"
        messages.append(f"{loc}: {err.get('msg', 'invalid value')}")
    return messages
