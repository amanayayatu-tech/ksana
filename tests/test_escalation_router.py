from __future__ import annotations

from chairman.core.consensus_calculator import calculate_direction_consensus
from chairman.core.disagreement_classifier import classify_disagreement
from chairman.core.escalation_router import determine_escalation
from chairman.models import Priority
from tests.conftest import make_f_partner, make_g_partner, make_signal, make_w_partner


def test_dec_011_case_3_escalation():
    recs = [
        make_f_partner("long"),
        make_w_partner("watch"),
        make_g_partner("avoid", dual_gate="anomaly_review_required"),
    ]
    consensus = calculate_direction_consensus(recs)
    disagreement = classify_disagreement(recs, make_signal(), consensus)

    result = determine_escalation(recs, consensus, disagreement)

    assert any(item.priority == Priority.HIGH and item.dual_gate_anomaly for item in result.escalations)


def test_evidence_unverified_long_escalation():
    recs = [
        make_f_partner("long", evidence_unverified=True),
        make_w_partner("watch"),
        make_g_partner("watch"),
    ]
    consensus = calculate_direction_consensus(recs)
    disagreement = classify_disagreement(recs, make_signal(), consensus)

    result = determine_escalation(recs, consensus, disagreement)

    assert any(
        item.priority == Priority.HIGH and item.evidence_unverified_inherited
        for item in result.escalations
    )


def test_no_escalation_on_full_consensus(three_long_recommendations):
    consensus = calculate_direction_consensus(three_long_recommendations)
    disagreement = classify_disagreement(three_long_recommendations, make_signal(), consensus)

    result = determine_escalation(three_long_recommendations, consensus, disagreement)

    assert result.escalations == []
