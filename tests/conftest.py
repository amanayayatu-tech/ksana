from __future__ import annotations

from typing import Any

import pytest
import yaml

from chairman.models import (
    DeploymentCompliance,
    Direction,
    FPartnerRecommendation,
    HardRulesPassed,
    GPartnerRecommendation,
    ResearchSignal,
    UpstreamSignalRef,
    WPartnerRecommendation,
)


@pytest.fixture(autouse=True)
def deterministic_llm_environment(monkeypatch: pytest.MonkeyPatch):
    """Keep local .env LLM settings from leaking into tests."""

    monkeypatch.setenv("LLM_PROVIDER", "local")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)


class TriggerMarketClient:
    """Deterministic market client with real rule-triggering HK/US histories."""

    def get_history(self, ticker: str, period: str = "1mo"):
        del period
        closes = [100, 101, 102, 103, 104, 105, 106, 107, 108, 118]
        rows = []
        previous = None
        for index, close in enumerate(closes, start=1):
            volume = 100 if index < 10 else 500
            change_pct = None if previous is None else round((close - previous) / previous * 100, 4)
            rows.append(
                {
                    "ticker": ticker,
                    "date": f"2026-05-{index:02d}",
                    "open": close - 1,
                    "high": close + 1,
                    "low": close - 2,
                    "close": close,
                    "previous_close": previous,
                    "change_pct": change_pct,
                    "gap_pct": 0.5 if previous else None,
                    "volume": volume,
                    "source_url": f"https://finance.yahoo.com/quote/{ticker}",
                    "evidence_unverified": False,
                }
            )
            previous = close
        return rows

    def get_quote(self, ticker: str):
        class Quote:
            price = 118
            source_url = f"https://finance.yahoo.com/quote/{ticker}"
            evidence_unverified = False

        return Quote()


class QuietMarketClient(TriggerMarketClient):
    """Deterministic market client that should not trigger research signals."""

    def get_history(self, ticker: str, period: str = "1mo"):
        del period
        closes = [100, 100.2, 100.1, 100.3, 100.2, 100.4, 100.3, 100.5, 100.4, 100.6]
        rows = []
        previous = None
        for index, close in enumerate(closes, start=1):
            change_pct = None if previous is None else round((close - previous) / previous * 100, 4)
            rows.append(
                {
                    "ticker": ticker,
                    "date": f"2026-05-{index:02d}",
                    "open": close,
                    "high": close + 0.2,
                    "low": close - 0.2,
                    "close": close,
                    "previous_close": previous,
                    "change_pct": change_pct,
                    "gap_pct": 0,
                    "volume": 100,
                    "source_url": f"https://finance.yahoo.com/quote/{ticker}",
                    "evidence_unverified": False,
                }
            )
            previous = close
        return rows


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


def make_f_partner(
    direction: str = "long",
    *,
    confidence: int = 80,
    evidence_unverified: bool = False,
    data_date: str | None = None,
    **overrides: Any,
) -> FPartnerRecommendation:
    abstain_reason = overrides.pop("abstain_reason", None)
    if direction == "abstain" and not abstain_reason:
        abstain_reason = "insufficient_data"
    return FPartnerRecommendation(
        recommendation_id=overrides.pop("recommendation_id", "R-FP-20260513-001"),
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
        f_partner_specific_framework=overrides.pop(
            "f_partner_specific_framework",
            {"odds_score": 80, "probability_score": 70, "dislocation_score": 75},
        ),
        **overrides,
    )


def make_w_partner(
    direction: str = "long",
    *,
    confidence: int = 75,
    evidence_unverified: bool = False,
    data_date: str | None = None,
    **overrides: Any,
) -> WPartnerRecommendation:
    abstain_reason = overrides.pop("abstain_reason", None)
    if direction == "abstain" and not abstain_reason:
        abstain_reason = "insufficient_data"
    return WPartnerRecommendation(
        recommendation_id=overrides.pop("recommendation_id", "R-WP-20260513-001"),
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
                    "upstream_k_deep_signals_counted": 1,
                    "nepha_manual_validation_entries": [],
                },
            },
        ),
        **overrides,
    )


def make_g_partner(
    direction: str = "long",
    *,
    confidence: int = 90,
    evidence_unverified: bool = False,
    data_date: str | None = None,
    dual_gate: str | None = None,
    **overrides: Any,
) -> GPartnerRecommendation:
    abstain_reason = overrides.pop("abstain_reason", None)
    if direction == "abstain" and not abstain_reason:
        abstain_reason = "win_rate_below_95"
    return GPartnerRecommendation(
        recommendation_id=overrides.pop("recommendation_id", "R-GP-20260513-001"),
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


def write_stock_pool(data_dir):
    stock_dir = data_dir / "stock_pool"
    stock_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "stock_pool": {
            "version": 1,
            "last_updated_by_nepha": "2026-05-13",
            "hk_stocks": [
                {"ticker": "0700.HK", "name": "腾讯控股", "tags": ["互联网"]},
            ],
            "us_stocks": [
                {"ticker": "BABA", "name": "Alibaba ADR", "tags": ["互联网"]},
            ],
            "a_stocks_reference_only": [
                {"ticker": "600519.SH", "name": "贵州茅台", "tags": ["案例"]},
            ],
            "watchlist": [
                {"ticker": "3690.HK", "name": "美团", "reason_to_watch": "等待财报"},
            ],
        }
    }
    (stock_dir / "master_pool.yaml").write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


@pytest.fixture
def three_long_recommendations():
    return [make_f_partner("long"), make_w_partner("long"), make_g_partner("long")]
