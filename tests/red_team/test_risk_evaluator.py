from __future__ import annotations

from red_team.core.risk_completeness_evaluator import evaluate_risk_completeness
from tests.conftest import make_f_partner, make_g_partner, make_w_partner


def test_industry_concentration_across_agents():
    recs = [
        make_f_partner("long", position_size_pct=15, industry="AI"),
        make_w_partner("long", position_size_pct=15, industry="AI"),
        make_g_partner("long", position_size_pct=15, industry="AI"),
    ]

    findings = evaluate_risk_completeness(recs)

    assert any(f.risk_type == "industry_concentration" for f in findings)


def test_three_agents_shared_upstream_signal():
    recs = [make_f_partner("watch"), make_w_partner("watch"), make_g_partner("watch")]

    findings = evaluate_risk_completeness(recs)

    assert any(f.risk_type == "shared_upstream_signal" for f in findings)
