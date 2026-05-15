from __future__ import annotations

import json

from chairman.core.brief_assembler import assemble_brief
from chairman.persistence.archive import archive_brief
from orchestrator.core.partner_performance import load_partner_performance_context
from tests.conftest import make_f_partner, make_g_partner, make_signal, make_w_partner


def test_partner_performance_snapshots_are_chairman_only(tmp_path):
    data_dir = tmp_path / "data"
    brief = assemble_brief(
        research_signals=[make_signal()],
        recommendations=[make_f_partner("long"), make_w_partner("watch"), make_g_partner("watch")],
        brief_type="morning",
        date="2026-05-13",
        use_llm=False,
    )

    archive_brief(brief, data_dir)

    path = data_dir / "partner_performance" / "recommendation_log.json"
    snapshots = json.loads(path.read_text(encoding="utf-8"))
    assert len(snapshots) == 3
    assert snapshots[0]["verification_status"] == "pending"
    snapshots[0]["verification_status"] = "validated"
    snapshots[1]["verification_status"] = "invalidated"
    path.write_text(json.dumps(snapshots, ensure_ascii=False, indent=2), encoding="utf-8")

    context = load_partner_performance_context(data_dir)
    assert context["visibility"] == "chairman_only"
    assert "f_partner" in context["profiles"]
    assert context["profiles"]["f_partner"]["verified_outcomes_available"] is True
    assert context["profiles"]["f_partner"]["performance_weight_multiplier"] > 1
    assert context["profiles"]["w_partner"]["performance_weight_multiplier"] < 1
    assert (data_dir / "partner_performance" / "reviews").exists()


def test_partner_performance_preserves_manual_status_on_rearchive(tmp_path):
    data_dir = tmp_path / "data"
    brief = assemble_brief(
        research_signals=[make_signal()],
        recommendations=[make_f_partner("long"), make_w_partner("watch"), make_g_partner("watch")],
        brief_type="morning",
        date="2026-05-13",
        use_llm=False,
    )
    archive_brief(brief, data_dir)
    path = data_dir / "partner_performance" / "recommendation_log.json"
    snapshots = json.loads(path.read_text(encoding="utf-8"))
    snapshots[0]["verification_status"] = "validated"
    snapshots[0]["evidence_url"] = "https://example.com/partner-validation"
    snapshots[0]["verification_notes"] = "manual partner review"
    path.write_text(json.dumps(snapshots, ensure_ascii=False, indent=2), encoding="utf-8")

    archive_brief(brief, data_dir)

    updated = json.loads(path.read_text(encoding="utf-8"))
    assert updated[0]["verification_status"] == "validated"
    assert updated[0]["evidence_url"] == "https://example.com/partner-validation"
    assert updated[0]["verification_notes"] == "manual partner review"
