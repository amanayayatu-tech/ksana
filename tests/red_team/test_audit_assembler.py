from __future__ import annotations

from red_team.core.audit_assembler import assemble_audit
from red_team.output.json_metadata_renderer import render_json_metadata
from red_team.output.markdown_renderer import render_markdown
from tests.conftest import make_f_partner, make_g_partner, make_signal, make_w_partner


def test_red_team_disagrees_with_chairman_full_consensus():
    recs = [
        make_f_partner("long", data_points=[{"date": "2026-05-01"}], catalysts=["x"], thesis_kill_criteria=["y"]),
        make_w_partner("long", data_points=[{"date": "2026-05-01"}], catalysts=["x"], thesis_kill_criteria=["y"]),
        make_g_partner("long", data_points=[{"date": "2026-05-01"}], catalysts=["x"], thesis_kill_criteria=["y"]),
    ]
    brief = {
        "brief_id": "BRIEF-20260513-AM",
        "red_team_queue": {"high_priority": [], "medium_priority": []},
        "per_recommendation_summary": [
            {
                "ticker": "MOCK",
                "direction_consensus": {"consensus_level": "full_consensus_long"},
            }
        ],
    }

    audit = assemble_audit(
        chairman_brief=brief,
        recommendations=recs,
        research_signals=[make_signal()],
        audit_type="morning",
        date="2026-05-13",
        use_llm=False,
    )

    assert audit.chairman_alignment.disagreements
    assert any(f.rule_id == "AR-008" for f in audit.rule_audit_findings)
    assert audit.substantive_objections
    assert audit.substantive_objections[0].red_team_verdict in {"block", "challenge", "monitor"}


def test_render_red_team_markdown_and_json():
    audit = assemble_audit(
        chairman_brief={"brief_id": "BRIEF-20260513-AM", "red_team_queue": {}},
        recommendations=[make_f_partner("watch")],
        research_signals=[make_signal()],
        audit_type="morning",
        date="2026-05-13",
        use_llm=False,
    )

    markdown = render_markdown(audit)
    metadata = render_json_metadata(audit)

    assert "Red Team Audit" in markdown
    assert "实质性反对意见" in markdown
    assert "建议 Chairman 二次裁决" in markdown
    assert "Red Team 不替 Nepha 做决策" in markdown
    assert '"audit_id": "AUDIT-20260513-AM"' in metadata
    assert '"substantive_objections"' in metadata
    assert audit.substantive_objections[0].chairman_second_review["second_review_required"] is True
