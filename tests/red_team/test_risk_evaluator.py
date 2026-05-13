from __future__ import annotations

from red_team.core.risk_completeness_evaluator import evaluate_risk_completeness
from tests.conftest import make_fengliu, make_liguofei, make_wanmu


def test_industry_concentration_across_agents():
    recs = [
        make_fengliu("long", position_size_pct=15, industry="AI"),
        make_wanmu("long", position_size_pct=15, industry="AI"),
        make_liguofei("long", position_size_pct=15, industry="AI"),
    ]

    findings = evaluate_risk_completeness(recs)

    assert any(f.risk_type == "industry_concentration" for f in findings)


def test_three_agents_shared_upstream_signal():
    recs = [make_fengliu("watch"), make_wanmu("watch"), make_liguofei("watch")]

    findings = evaluate_risk_completeness(recs)

    assert any(f.risk_type == "shared_upstream_signal" for f in findings)
