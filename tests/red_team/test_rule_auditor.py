from __future__ import annotations

from red_team.core.rule_auditor import audit_rules
from tests.conftest import deployment, make_f_partner, make_g_partner, make_signal, make_w_partner


def rule_ids(findings):
    return {finding.rule_id for finding in findings}


def test_ar_001_dual_gate_anomaly_detected():
    rec = make_g_partner("watch", dual_gate="anomaly_review_required")
    findings = audit_rules([rec], [make_signal()], {})
    assert "AR-001" in rule_ids(findings)
    assert [f for f in findings if f.rule_id == "AR-001"][0].severity == "critical"


def test_ar_002_deployment_failure_not_abstain():
    rec = make_w_partner("long", deployment_compliance=deployment(any_failure=True))
    findings = audit_rules([rec], [make_signal()], {})
    assert "AR-002" in rule_ids(findings)


def test_ar_003_abstain_reason_or_thesis_missing():
    rec = make_f_partner("abstain", abstain_reason="insufficient_data", thesis="太短")
    findings = audit_rules([rec], [make_signal()], {})
    assert "AR-003" in rule_ids(findings)


def test_ar_004_evidence_unverified_high_confidence():
    rec = make_w_partner("watch", confidence=80, evidence_unverified=True)
    findings = audit_rules([rec], [make_signal()], {})
    assert "AR-004" in rule_ids(findings)


def test_ar_005_split_long_vs_avoid_from_chairman():
    brief = {
        "per_recommendation_summary": [
            {
                "ticker": "MOCK",
                "direction_consensus": {"consensus_level": "split_long_vs_avoid"},
            }
        ]
    }
    findings = audit_rules([], [], brief)
    assert "AR-005" in rule_ids(findings)


def test_ar_006_unverified_signal_skipped_twice():
    signal = make_signal()
    signal.perplexity_research["prompts_skipped_by_nepha"] = ["P1", "P2"]
    findings = audit_rules([], [signal], {})
    assert "AR-006" in rule_ids(findings)


def test_ar_007_fuzzy_thesis():
    rec = make_f_partner("watch", thesis="可能大概或许看起来估计是这样")
    findings = audit_rules([rec], [make_signal()], {})
    assert "AR-007" in rule_ids(findings)


def test_ar_008_data_points_without_source_url():
    rec = make_g_partner("watch", data_points=[{"date": "2026-05-01"}, {"source_url": ""}])
    findings = audit_rules([rec], [make_signal()], {})
    assert "AR-008" in rule_ids(findings)


def test_ar_009_long_without_catalysts():
    rec = make_w_partner("long", catalysts=[])
    findings = audit_rules([rec], [make_signal()], {})
    assert "AR-009" in rule_ids(findings)


def test_ar_010_long_without_thesis_kill_criteria():
    rec = make_g_partner("long", catalysts=["earnings"], thesis_kill_criteria=[])
    findings = audit_rules([rec], [make_signal()], {})
    assert "AR-010" in rule_ids(findings)


def test_ar_011_f_partner_logic_kill_not_avoid():
    rec = make_f_partner(
        "watch",
        kill_type_heuristic={"logic_kill": {"confidence": 0.66}},
    )
    findings = audit_rules([rec], [make_signal()], {})
    assert "AR-011" in rule_ids(findings)


def test_dec_008_r5_r6_r7_audit_only():
    rec = make_g_partner(
        "watch",
        authority_resolution={
            "r5_time_box_resolution": {"decision": "reduce"},
            "r6_false_stop_loss_review_triggered": True,
            "r7_dual_gate_status": {"consistency": "aligned"},
        },
    )
    before = rec.model_dump(mode="json")
    audit_rules([rec], [make_signal()], {})
    after = rec.model_dump(mode="json")
    assert before == after
