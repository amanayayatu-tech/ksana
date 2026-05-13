from __future__ import annotations

from typing import Any

import pytest

from chairman.models import (
    DeploymentCompliance,
    Direction,
    FengliuRecommendation,
    HardRulesPassed,
    LiguofeiRecommendation,
    ResearchSignal,
    UpstreamSignalRef,
    WanmuRecommendation,
)


def upstream_ref(
    signal_id: str = "RS-20260513-001",
    *,
    verdict: str = "accepted",
    evidence_unverified: bool = False,
    contributes: bool | None = None,
) -> UpstreamSignalRef:
    return UpstreamSignalRef(
        research_signal_id=signal_id,
        signal_summary="mock signal",
        my_methodology_verdict=verdict,
        evidence_unverified_inherited=evidence_unverified,
        contributes_to_collaborative_validation=contributes,
    )


def deployment(
    *,
    any_failure: bool = False,
    forbidden_actions_check: bool = True,
    dual_gate: str | None = None,
    abstain_reason: str | None = None,
) -> DeploymentCompliance:
    return DeploymentCompliance(
        hard_rules_passed=HardRulesPassed(forbidden_actions_check=forbidden_actions_check),
        any_failure_must_abstain=any_failure,
        dual_gate_consistency=dual_gate,
        abstain_reason=abstain_reason,
    )


def make_fengliu(
    direction: str = "long",
    *,
    confidence: int = 80,
    evidence_unverified: bool = False,
    data_date: str | None = None,
    **overrides: Any,
) -> FengliuRecommendation:
    abstain_reason = overrides.pop("abstain_reason", None)
    if direction == "abstain" and not abstain_reason:
        abstain_reason = "insufficient_data"
    return FengliuRecommendation(
        recommendation_id=overrides.pop("recommendation_id", "R-FL-20260513-001"),
        ticker=overrides.pop("ticker", "MOCK"),
        market=overrides.pop("market", "US"),
        direction=Direction(direction),
        confidence=confidence,
        thesis=overrides.pop("thesis", "赔率和概率匹配"),
        abstain_reason=abstain_reason,
        upstream_research_signals=[
            upstream_ref(evidence_unverified=evidence_unverified)
        ],
        data_points=overrides.pop("data_points", [{"date": data_date or "2026-05-01"}]),
        fengliu_specific_framework=overrides.pop(
            "fengliu_specific_framework",
            {"odds_score": 80, "probability_score": 70, "dislocation_score": 75},
        ),
        **overrides,
    )


def make_wanmu(
    direction: str = "long",
    *,
    confidence: int = 75,
    evidence_unverified: bool = False,
    data_date: str | None = None,
    **overrides: Any,
) -> WanmuRecommendation:
    abstain_reason = overrides.pop("abstain_reason", None)
    if direction == "abstain" and not abstain_reason:
        abstain_reason = "insufficient_data"
    return WanmuRecommendation(
        recommendation_id=overrides.pop("recommendation_id", "R-WM-20260513-001"),
        ticker=overrides.pop("ticker", "MOCK"),
        market=overrides.pop("market", "US"),
        direction=Direction(direction),
        confidence=confidence,
        thesis=overrides.pop("thesis", "三型命中但核心问题需复核"),
        abstain_reason=abstain_reason,
        upstream_research_signals=[
            upstream_ref(evidence_unverified=evidence_unverified, contributes=True)
        ],
        data_points=overrides.pop("data_points", [{"date": data_date or "2026-05-02"}]),
        collaborative_validation=overrides.pop(
            "collaborative_validation",
            {
                "independent_validators_count": 2,
                "validators_breakdown": {
                    "upstream_4_1_signals_counted": 1,
                    "nepha_manual_validation_entries": [],
                },
            },
        ),
        **overrides,
    )


def make_liguofei(
    direction: str = "long",
    *,
    confidence: int = 90,
    evidence_unverified: bool = False,
    data_date: str | None = None,
    dual_gate: str | None = None,
    **overrides: Any,
) -> LiguofeiRecommendation:
    abstain_reason = overrides.pop("abstain_reason", None)
    if direction == "abstain" and not abstain_reason:
        abstain_reason = "win_rate_below_95"
    return LiguofeiRecommendation(
        recommendation_id=overrides.pop("recommendation_id", "R-LF-20260513-001"),
        ticker=overrides.pop("ticker", "MOCK"),
        market=overrides.pop("market", "US"),
        direction=Direction(direction),
        action=overrides.pop("action", "buy" if direction == "long" else direction),
        confidence=confidence,
        thesis=overrides.pop("thesis", "高确定性变量成立"),
        abstain_reason=abstain_reason,
        deployment_compliance=overrides.pop(
            "deployment_compliance",
            deployment(dual_gate=dual_gate),
        ),
        upstream_research_signals=[
            upstream_ref(evidence_unverified=evidence_unverified)
        ],
        data_points=overrides.pop("data_points", [{"date": data_date or "2026-05-03"}]),
        **overrides,
    )


def make_signal(signal_id: str = "RS-20260513-001", *, stage: str = "trade_ready") -> ResearchSignal:
    return ResearchSignal(
        research_signal_id=signal_id,
        emitted_at="2026-05-13T08:00:00+08:00",
        signal_type="event",
        research_stage=stage,
        signal_summary="mock research signal",
        candidate_targets=[
            {"ticker": "MOCK", "market": "US", "company_name": "Mock Inc", "relevance_score": 90}
        ],
        perplexity_research={"prompts_pending": ["P-001"]},
    )


@pytest.fixture
def three_long_recommendations():
    return [make_fengliu("long"), make_wanmu("long"), make_liguofei("long")]
