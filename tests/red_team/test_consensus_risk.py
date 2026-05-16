from __future__ import annotations

from red_team.core.consensus_risk import assess_consensus_risk
from tests.conftest import make_f_partner, make_g_partner, make_w_partner


def test_consensus_risk_flags_perplexity_overlap_without_edge():
    recs = [
        make_f_partner("long", thesis="AI cloud revenue acceleration and ecommerce margin improvement"),
        make_w_partner("long", thesis="AI cloud revenue acceleration supports ecommerce margin improvement"),
        make_g_partner("long", thesis="AI cloud revenue acceleration improves ecommerce margin structure"),
    ]
    knowledge = {
        "entries": [
            {
                "event_summary": ["AI cloud revenue acceleration and ecommerce margin improvement"],
                "company_conclusions": ["AI cloud revenue acceleration supports margin improvement"],
            }
        ],
        "open_questions": [],
        "historical_conflicts": [],
    }

    risk = assess_consensus_risk("BABA", recs, {"final_verdict": "act"}, knowledge)

    assert risk["risk_level"] == "high"
    assert risk["same_direction_cluster"] is True
    assert risk["required_questions"]


def test_consensus_risk_drops_when_partner_states_variant_edge():
    recs = [
        make_f_partner("watch", thesis="反共识 预期差 is not yet priced by margin consensus"),
        make_w_partner("avoid", thesis="variant evidence is weak and counter evidence matters"),
        make_g_partner("watch", thesis="mispricing requires further falsification"),
    ]

    risk = assess_consensus_risk("BABA", recs, {"final_verdict": "wait"}, {"entries": []})

    assert risk["risk_level"] in {"low", "medium"}
    assert risk["non_consensus_marker_hits"]
