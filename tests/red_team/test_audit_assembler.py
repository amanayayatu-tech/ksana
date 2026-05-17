from __future__ import annotations

from red_team.core.audit_assembler import assemble_audit, build_risk_budget, choose_red_team_verdict
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
    assert audit.substantive_objections[0].risk_budget
    assert audit.substantive_objections[0].kill_conditions


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
    assert "风险预算边界" in markdown
    assert "Fatal flaw" in markdown
    assert "建议 Chairman 二次裁决" in markdown
    assert "Red Team 不替 Nepha 做决策" in markdown
    assert '"audit_id": "AUDIT-20260513-AM"' in metadata
    assert '"substantive_objections"' in metadata
    assert audit.substantive_objections[0].chairman_second_review["second_review_required"] is True


def test_risk_budget_respects_non_action_opportunity_states():
    for final_verdict in ("discard", "watch", "research_priority"):
        budget = build_risk_budget(
            final_verdict=final_verdict,
            red_team_verdict="no_major_objection",
            fatal_flaw=False,
            consensus_risk={},
        )

        assert budget["risk_budget_allowed_pct"] == 0
        assert budget["max_initial_position_pct"] == 0
        assert budget["budget_scope"] in {
            "not_eligible_for_position",
            "watchlist_or_paper_tracking_only",
            "deep_research_only",
        }


def test_human_override_required_is_a_red_team_action_candidate():
    verdict = choose_red_team_verdict(
        final_verdict="human_override_required",
        has_perplexity=False,
        open_questions=[],
        historical_conflicts=[],
        rule_ids=[],
        consensus_risk={},
    )

    assert verdict == "challenge"

    budget = build_risk_budget(
        final_verdict="human_override_required",
        red_team_verdict="challenge",
        fatal_flaw=False,
        consensus_risk={},
    )

    assert budget["risk_budget_allowed_pct"] == 0.5
    assert budget["max_initial_position_pct"] == 0.25
    assert budget["budget_scope"] == "human_override_only"


def test_custom_risk_budget_policy_changes_budget():
    budget = build_risk_budget(
        final_verdict="trial_candidate",
        red_team_verdict="monitor",
        fatal_flaw=False,
        consensus_risk={},
        policy={
            "red_team_verdicts": {
                "monitor": {
                    "risk_budget_allowed_pct": 1.25,
                    "max_initial_position_pct": 0.4,
                    "budget_scope": "custom_monitor_scope",
                }
            },
            "must_not_buy_if": ["custom blocker"],
            "position_requires": ["custom requirement"],
        },
    )

    assert budget["risk_budget_allowed_pct"] == 1.25
    assert budget["max_initial_position_pct"] == 0.4
    assert budget["budget_scope"] == "custom_monitor_scope"
    assert budget["must_not_buy_if"] == ["custom blocker"]
    assert budget["position_requires"] == ["custom requirement"]


def test_fatal_flaw_policy_scope_is_configurable_but_budget_is_always_zero(tmp_path):
    policy_path = tmp_path / "risk_budget_policy.yaml"
    policy_path.write_text(
        """
fatal_flaw:
  risk_budget_allowed_pct: 9
  max_initial_position_pct: 9
  budget_scope: custom_fatal_scope
""",
        encoding="utf-8",
    )

    budget = build_risk_budget(
        final_verdict="conviction_candidate",
        red_team_verdict="no_major_objection",
        fatal_flaw=True,
        consensus_risk={},
        policy_path=policy_path,
    )

    assert budget["risk_budget_allowed_pct"] == 0
    assert budget["max_initial_position_pct"] == 0
    assert budget["budget_scope"] == "custom_fatal_scope"
