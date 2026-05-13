from __future__ import annotations

from chairman.core.consensus_calculator import calculate_direction_consensus
from chairman.core.weight_applier import get_chairman_weight_multiplier
from chairman.models import ConsensusLevel


def test_full_consensus_long(three_long_recommendations):
    consensus = calculate_direction_consensus(three_long_recommendations)

    assert consensus.consensus_level == ConsensusLevel.FULL_CONSENSUS_LONG
    assert consensus.long_count == 3


def test_split_long_vs_avoid():
    from tests.conftest import make_fengliu, make_liguofei, make_wanmu

    consensus = calculate_direction_consensus(
        [make_fengliu("long"), make_wanmu("avoid"), make_liguofei("watch")]
    )

    assert consensus.consensus_level == ConsensusLevel.SPLIT_LONG_VS_AVOID


def test_abstain_not_counted_against():
    from tests.conftest import make_fengliu, make_liguofei, make_wanmu

    consensus = calculate_direction_consensus(
        [make_fengliu("long"), make_wanmu("abstain"), make_liguofei("abstain")]
    )

    assert consensus.consensus_level == ConsensusLevel.MAJORITY_LONG
    assert consensus.avoid_count == 0
    assert consensus.abstain_count == 2


def test_evidence_unverified_weight():
    from tests.conftest import make_fengliu

    rec = make_fengliu("long", evidence_unverified=True, confidence=80)
    consensus = calculate_direction_consensus([rec])

    assert get_chairman_weight_multiplier(rec) == 0.7
    assert consensus.weighted_long_strength == 56


def test_dec_008_r5r6r7_not_in_voting():
    from tests.conftest import make_fengliu, make_liguofei, make_wanmu

    rec = make_liguofei(
        "long",
        authority_resolution={
            "r5_time_box_resolution": {"decision": "exit"},
            "r6_false_stop_loss_review_triggered": True,
            "r7_dual_gate_status": {"consistency": "both_failed"},
        },
    )

    consensus = calculate_direction_consensus([make_fengliu("long"), make_wanmu("long"), rec])

    assert consensus.consensus_level == ConsensusLevel.FULL_CONSENSUS_LONG


def test_no_cross_methodology_mapping():
    from tests.conftest import make_fengliu, make_liguofei, make_wanmu

    liguofei = make_liguofei("watch", action="buy")
    consensus = calculate_direction_consensus([make_fengliu("long"), make_wanmu("watch"), liguofei])

    assert consensus.watch_count == 2
    assert consensus.long_count == 1
