from __future__ import annotations

import json

from chairman.core.brief_assembler import assemble_brief
from chairman.persistence.archive import archive_brief
from orchestrator.core.decision_verification import OBJECTIVES
from tests.conftest import make_f_partner, make_g_partner, make_signal, make_w_partner


def test_decision_verification_cases_are_created_on_brief_archive(tmp_path):
    data_dir = tmp_path / "data"
    brief = assemble_brief(
        research_signals=[make_signal()],
        recommendations=[make_f_partner("long"), make_w_partner("watch"), make_g_partner("watch")],
        brief_type="morning",
        date="2026-05-13",
        use_llm=False,
    )

    archive_brief(brief, data_dir)

    queue_path = data_dir / "decision_verification" / "pending_cases.json"
    cases = json.loads(queue_path.read_text(encoding="utf-8"))
    assert cases[0]["case_id"] == "DV-BRIEF-20260513-AM-MOCK"
    assert cases[0]["verification_windows_days"] == [1, 7, 30, 90]
    assert cases[0]["status"] == "pending"
    assert cases[0]["objective"] == OBJECTIVES[cases[0]["decision_direction"]]
    assert cases[0]["decision_direction"] == "watch"


def test_decision_verification_preserves_manual_status_on_rearchive(tmp_path):
    data_dir = tmp_path / "data"
    brief = assemble_brief(
        research_signals=[make_signal()],
        recommendations=[make_f_partner("long"), make_w_partner("watch"), make_g_partner("watch")],
        brief_type="morning",
        date="2026-05-13",
        use_llm=False,
    )
    archive_brief(brief, data_dir)
    queue_path = data_dir / "decision_verification" / "pending_cases.json"
    cases = json.loads(queue_path.read_text(encoding="utf-8"))
    cases[0]["status"] = "validated"
    cases[0]["evidence_url"] = "https://example.com/validation"
    cases[0]["verification_notes"] = "manual review"
    queue_path.write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding="utf-8")

    archive_brief(brief, data_dir)

    updated = json.loads(queue_path.read_text(encoding="utf-8"))
    assert updated[0]["status"] == "validated"
    assert updated[0]["evidence_url"] == "https://example.com/validation"
    assert updated[0]["verification_notes"] == "manual review"


def test_verification_objectives_define_non_price_only_outcomes():
    assert "core_thesis_confirmed_by_public_evidence" in OBJECTIVES["long"]["validated_if"]
    assert "open_questions_remain_material" in OBJECTIVES["watch"]["validated_if"]
    assert "stated_risk_materializes" in OBJECTIVES["avoid"]["validated_if"]
    assert "evidence_remains_insufficient_or_conflicting" in OBJECTIVES["abstain"]["validated_if"]
