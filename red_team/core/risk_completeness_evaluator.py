"""Risk completeness evaluation across all agents."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from chairman.models import Direction, Recommendation
from red_team.models import RiskCompletenessFinding


def evaluate_risk_completeness(
    recommendations: list[Recommendation],
) -> list[RiskCompletenessFinding]:
    """Detect systemic risks that individual agents can miss."""

    findings: list[RiskCompletenessFinding] = []
    findings.extend(_industry_concentration(recommendations))
    findings.extend(_shared_upstream_signal(recommendations))
    findings.extend(_liquidity_drift(recommendations))
    findings.extend(_near_event_missing_catalyst(recommendations))
    findings.extend(_us_long_weekend_gap(recommendations))
    return findings


def _industry_concentration(recommendations: list[Recommendation]) -> list[RiskCompletenessFinding]:
    exposure_by_industry: defaultdict[str, float] = defaultdict(float)
    recs_by_industry: defaultdict[str, list[str]] = defaultdict(list)
    for rec in recommendations:
        industry = _extra(rec, "industry") or _extra(rec, "sector")
        if not industry or rec.position_size_pct is None:
            continue
        exposure_by_industry[str(industry)] += float(rec.position_size_pct)
        recs_by_industry[str(industry)].append(rec.recommendation_id)

    return [
        RiskCompletenessFinding(
            risk_type="industry_concentration",
            affected_recommendations=recs_by_industry[industry],
            finding_text=f"{industry} 合并行业敞口为 {exposure}%，超过 40%。",
            severity="high",
        )
        for industry, exposure in exposure_by_industry.items()
        if exposure > 40
    ]


def _shared_upstream_signal(recommendations: list[Recommendation]) -> list[RiskCompletenessFinding]:
    counter: Counter[str] = Counter()
    recs_by_signal: defaultdict[str, list[str]] = defaultdict(list)
    for rec in recommendations:
        for signal in rec.upstream_research_signals:
            counter[signal.research_signal_id] += 1
            recs_by_signal[signal.research_signal_id].append(rec.recommendation_id)

    return [
        RiskCompletenessFinding(
            risk_type="shared_upstream_signal",
            affected_recommendations=recs_by_signal[signal_id],
            finding_text=f"3 个 Agent 都依赖同一个上游信号 {signal_id}，存在上游错则全错的集中风险。",
            severity="medium",
        )
        for signal_id, count in counter.items()
        if count >= 3
    ]


def _liquidity_drift(recommendations: list[Recommendation]) -> list[RiskCompletenessFinding]:
    findings: list[RiskCompletenessFinding] = []
    for rec in recommendations:
        drift = _extra(rec, "adv_decline_pct")
        if drift is not None and float(drift) > 30:
            findings.append(
                RiskCompletenessFinding(
                    risk_type="liquidity_drift",
                    affected_recommendations=[rec.recommendation_id],
                    finding_text=f"{rec.ticker} 20 日 ADV 较入池下限下降 {drift}%，存在流动性恶化漂移。",
                    severity="medium",
                )
            )
    return findings


def _near_event_missing_catalyst(recommendations: list[Recommendation]) -> list[RiskCompletenessFinding]:
    findings: list[RiskCompletenessFinding] = []
    for rec in recommendations:
        days = _extra(rec, "days_to_company_event")
        catalysts = _extra(rec, "catalysts")
        if rec.direction == Direction.LONG and days is not None and int(days) <= 7 and not catalysts:
            findings.append(
                RiskCompletenessFinding(
                    risk_type="near_event_missing_catalyst",
                    affected_recommendations=[rec.recommendation_id],
                    finding_text=f"{rec.ticker} 7 天内有公司事件，但 long 建议未在 catalysts 中说明。",
                    severity="medium",
                )
            )
    return findings


def _us_long_weekend_gap(recommendations: list[Recommendation]) -> list[RiskCompletenessFinding]:
    findings: list[RiskCompletenessFinding] = []
    for rec in recommendations:
        if rec.market == "US" and rec.direction == Direction.LONG and _extra(rec, "crosses_hk_monday_open"):
            findings.append(
                RiskCompletenessFinding(
                    risk_type="hk_us_session_mismatch",
                    affected_recommendations=[rec.recommendation_id],
                    finding_text=f"{rec.ticker} 为美股 long 且持有跨港股周一开盘，存在周末缺口风险。",
                    severity="low",
                )
            )
    return findings


def _extra(rec: Recommendation, name: str) -> Any:
    return getattr(rec, name, None)
