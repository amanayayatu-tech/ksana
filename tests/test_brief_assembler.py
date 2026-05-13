from __future__ import annotations

from chairman.core.brief_assembler import (
    assemble_brief,
    build_individual_view,
    classify_fengliu_logic_kill_routing,
    classify_fengliu_outsider_handling,
    summarize_wanmu_collaborative_validation,
)
from chairman.output.json_metadata_renderer import render_json_metadata
from chairman.output.markdown_renderer import render_markdown
from tests.conftest import make_fengliu, make_liguofei, make_signal, make_wanmu


def test_wanmu_4_1_counted_as_validator():
    rec = make_wanmu("long")

    summary = summarize_wanmu_collaborative_validation(rec)

    assert summary["four_one_counted_as_validator"] is True
    assert summary["upstream_4_1_signals_counted"] == 1


def test_outsider_three_cases_displayed():
    case_1 = make_fengliu("long", circle_status="outsider")
    case_2 = make_fengliu(
        "abstain",
        circle_status="outsider",
        abstain_reason="circle_status_outsider",
    )
    case_3 = make_fengliu("avoid", circle_status="outsider")

    assert classify_fengliu_outsider_handling(case_1)["case"] == (
        "case_1_outsider_with_clear_trend_signal"
    )
    assert classify_fengliu_outsider_handling(case_2)["case"] == "case_2_outsider_no_trend_signal"
    assert classify_fengliu_outsider_handling(case_3)["case"] == (
        "case_3_outsider_with_logic_break"
    )


def test_logic_kill_confidence_routing_displayed():
    rec = make_fengliu(
        "avoid",
        kill_type_heuristic={"logic_kill": {"confidence": 0.66}},
    )

    result = classify_fengliu_logic_kill_routing(rec)

    assert result["route"] == "avoid_expected"


def test_nepha_validation_requires_evidence_url():
    rec = make_wanmu(
        "long",
        collaborative_validation={
            "independent_validators_count": 2,
            "validators_breakdown": {
                "upstream_4_1_signals_counted": 1,
                "nepha_manual_validation_entries": [
                    {"evidence_url": "", "counts_as_validator": True},
                    {"evidence_url": "https://example.com/evidence", "counts_as_validator": True},
                ],
            },
        },
    )

    summary = summarize_wanmu_collaborative_validation(rec)

    assert summary["nepha_manual_validation_with_evidence_url"] == 1
    assert summary["nepha_manual_validation_without_evidence_url"] == 1
    assert summary["all_counted_nepha_entries_have_evidence_url"] is False


def test_render_markdown_and_json_metadata():
    brief = assemble_brief(
        research_signals=[make_signal()],
        recommendations=[make_fengliu("long"), make_wanmu("watch"), make_liguofei("watch")],
        brief_type="morning",
        date="2026-05-13",
        use_llm=False,
    )

    markdown = render_markdown(brief)
    metadata = render_json_metadata(brief)

    assert "投研委员会简报" in markdown
    assert "Chairman 不替你做决策" in markdown
    assert '"brief_id": "BRIEF-20260513-AM"' in metadata
    assert build_individual_view(make_wanmu("long"))["collaborative_validation_summary"]
