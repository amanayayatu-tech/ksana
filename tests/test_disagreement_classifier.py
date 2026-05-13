from __future__ import annotations

from chairman.core.consensus_calculator import calculate_direction_consensus
from chairman.core.disagreement_classifier import classify_disagreement
from chairman.models import DisagreementType
from tests.conftest import make_fengliu, make_liguofei, make_signal, make_wanmu


def test_methodology_dna_classification():
    recs = [
        make_fengliu("long", thesis="赔率好"),
        make_wanmu("avoid", thesis="核心问题太多"),
        make_liguofei("watch"),
    ]
    consensus = calculate_direction_consensus(recs)

    analysis = classify_disagreement(recs, make_signal(), consensus)

    assert analysis.primary_type == DisagreementType.METHODOLOGY_DNA
    assert not analysis.red_team_escalation_required


def test_anomaly_classification():
    recs = [
        make_fengliu("long"),
        make_wanmu("avoid"),
        make_liguofei("watch", dual_gate="anomaly_review_required"),
    ]
    consensus = calculate_direction_consensus(recs)

    analysis = classify_disagreement(recs, make_signal(), consensus)

    assert analysis.primary_type == DisagreementType.POTENTIAL_AGENT_ERROR
    assert analysis.red_team_escalation_required


def test_data_freshness_classification():
    recs = [
        make_fengliu("long", data_date="2026-01-01"),
        make_wanmu("avoid", data_date="2026-05-10"),
        make_liguofei("watch", data_date="2026-05-11"),
    ]
    consensus = calculate_direction_consensus(recs)

    analysis = classify_disagreement(recs, make_signal(), consensus)

    assert analysis.primary_type == DisagreementType.DATA_INPUT_DIFFERENCE
    assert analysis.red_team_escalation_required
