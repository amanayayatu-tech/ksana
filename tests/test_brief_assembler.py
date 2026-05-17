from __future__ import annotations

from chairman.core.brief_assembler import (
    assemble_brief,
    build_individual_view,
    classify_f_partner_logic_kill_routing,
    classify_f_partner_outsider_handling,
    summarize_w_partner_collaborative_validation,
)
from chairman.output.json_metadata_renderer import render_json_metadata
from chairman.output.markdown_renderer import render_markdown
from business_agents._common.knowledge_store import ingest_filled_result
from tests.conftest import make_f_partner, make_g_partner, make_signal, make_w_partner


def test_w_partner_k_deep_counted_as_validator():
    rec = make_w_partner("long")

    summary = summarize_w_partner_collaborative_validation(rec)

    assert summary["four_one_counted_as_validator"] is True
    assert summary["upstream_k_deep_signals_counted"] == 1


def test_outsider_three_cases_displayed():
    case_1 = make_f_partner("long", circle_status="outsider")
    case_2 = make_f_partner(
        "abstain",
        circle_status="outsider",
        abstain_reason="circle_status_outsider",
    )
    case_3 = make_f_partner("avoid", circle_status="outsider")

    assert classify_f_partner_outsider_handling(case_1)["case"] == (
        "case_1_outsider_with_clear_trend_signal"
    )
    assert classify_f_partner_outsider_handling(case_2)["case"] == "case_2_outsider_no_trend_signal"
    assert classify_f_partner_outsider_handling(case_3)["case"] == (
        "case_3_outsider_with_logic_break"
    )


def test_logic_kill_confidence_routing_displayed():
    rec = make_f_partner(
        "avoid",
        kill_type_heuristic={"logic_kill": {"confidence": 0.66}},
    )

    result = classify_f_partner_logic_kill_routing(rec)

    assert result["route"] == "avoid_expected"


def test_nepha_validation_requires_evidence_url():
    rec = make_w_partner(
        "long",
        collaborative_validation={
            "independent_validators_count": 2,
            "validators_breakdown": {
                "upstream_k_deep_signals_counted": 1,
                "nepha_manual_validation_entries": [
                    {"evidence_url": "", "counts_as_validator": True},
                    {"evidence_url": "https://example.com/evidence", "counts_as_validator": True},
                ],
            },
        },
    )

    summary = summarize_w_partner_collaborative_validation(rec)

    assert summary["nepha_manual_validation_with_evidence_url"] == 1
    assert summary["nepha_manual_validation_without_evidence_url"] == 1
    assert summary["all_counted_nepha_entries_have_evidence_url"] is False


def test_render_markdown_and_json_metadata():
    brief = assemble_brief(
        research_signals=[make_signal()],
        recommendations=[make_f_partner("long"), make_w_partner("watch"), make_g_partner("watch")],
        brief_type="morning",
        date="2026-05-13",
        use_llm=False,
    )

    markdown = render_markdown(brief)
    metadata = render_json_metadata(brief)

    assert "投研委员会简报" in markdown
    assert "Chairman 不替你做决策" in markdown
    assert "Opportunity Memo" in markdown
    assert "操作建议汇总" in markdown
    assert "建议动作" in markdown
    assert "仓位建议汇总" not in markdown
    assert '"brief_id": "BRIEF-20260513-AM"' in metadata
    assert build_individual_view(make_w_partner("long"))["collaborative_validation_summary"]


def test_brief_includes_historical_knowledge_memory(tmp_path):
    data_dir = tmp_path / "data"
    pull_dir = data_dir / "pull_requests"
    result_dir = data_dir / "perplexity_results"
    pull_dir.mkdir(parents=True)
    result_dir.mkdir(parents=True)
    (pull_dir / "PR-20260514-BABA.yaml").write_text(
        """
prompt_id: PR-20260514-BABA
related_signal_id: RS-20260514-BABA
priority: P1
prompt_text: |
  请研究 BABA Alibaba ADR 最近 7-10 个交易日公开价量异动背后的真实原因。
  触发规则：single_day_move_ge_7pct: 8.18 (2026-05-13)
""",
        encoding="utf-8",
    )
    (result_dir / "PR-20260514-BABA_filled.yaml").write_text(
        """
prompt_id: PR-20260514-BABA
related_signal_id: RS-20260514-BABA
status: filled
filled_at: '2026-05-14T13:05:08'
answer_text: |
  # BABA 异动深度研究

  ## 执行摘要
  2026年5月13日 BABA 大涨，核心催化剂为：①云/AI 数据超预期；②股息上调。结论可信度：高。

  ## 仍未验证的信息
  1. 机构资金流向需要等待 13F。
""",
        encoding="utf-8",
    )
    (pull_dir / "PR-20260513-9988.HK.yaml").write_text(
        """
prompt_id: PR-20260513-9988.HK
related_signal_id: RS-20260513-9988.HK
priority: P1
prompt_text: |
  请研究 9988.HK Alibaba HK 最近 7-10 个交易日公开价量异动背后的真实原因。
""",
        encoding="utf-8",
    )
    (result_dir / "PR-20260513-9988.HK_filled.yaml").write_text(
        """
prompt_id: PR-20260513-9988.HK
related_signal_id: RS-20260513-9988.HK
status: filled
filled_at: '2026-05-13T13:05:08'
answer_text: |
  # 9988.HK 异动深度研究

  ## 执行摘要
  2026年5月13日 9988.HK 同样受云/AI 叙事驱动，结论可信度：中。

  ## 反证
  - 港股流动性修复可能放大了短期 beta。
""",
        encoding="utf-8",
    )
    ingest_filled_result(data_dir, "PR-20260514-BABA")
    ingest_filled_result(data_dir, "PR-20260513-9988.HK")
    signal = make_signal("RS-20260514-BABA")
    signal.candidate_targets[0].ticker = "BABA"
    recs = [
        make_f_partner("watch", ticker="BABA", recommendation_id="R-FP-20260514-BABA"),
        make_w_partner("watch", ticker="BABA", recommendation_id="R-WP-20260514-BABA"),
        make_g_partner("watch", ticker="BABA", recommendation_id="R-GP-20260514-BABA"),
    ]

    brief = assemble_brief(
        research_signals=[signal],
        recommendations=recs,
        brief_type="morning",
        date="2026-05-14",
        use_llm=False,
        data_dir=data_dir,
    )
    markdown = render_markdown(brief)

    assert "历史研究记忆" in markdown
    assert "相似历史案例" in markdown
    assert "PR-20260514-BABA" in markdown
    assert "PR-20260513-9988.HK" in markdown
    assert "机构资金流向需要等待 13F" in markdown


def test_brief_keeps_similar_cases_without_same_ticker_history(tmp_path):
    data_dir = tmp_path / "data"
    pull_dir = data_dir / "pull_requests"
    result_dir = data_dir / "perplexity_results"
    pull_dir.mkdir(parents=True)
    result_dir.mkdir(parents=True)
    (pull_dir / "PR-20260514-BABA.yaml").write_text(
        """
prompt_id: PR-20260514-BABA
related_signal_id: RS-20260514-BABA
priority: P1
prompt_text: |
  请研究 BABA Alibaba ADR 最近 7-10 个交易日公开价量异动背后的真实原因。
""",
        encoding="utf-8",
    )
    (result_dir / "PR-20260514-BABA_filled.yaml").write_text(
        """
prompt_id: PR-20260514-BABA
related_signal_id: RS-20260514-BABA
status: filled
filled_at: '2026-05-14T13:05:08'
answer_text: |
  # BABA 异动深度研究

  ## 执行摘要
  2026年5月13日 BABA 受云/AI 叙事驱动，结论可信度：高。
""",
        encoding="utf-8",
    )
    ingest_filled_result(data_dir, "PR-20260514-BABA")
    signal = make_signal("RS-20260514-9988.HK")
    signal.candidate_targets[0].ticker = "9988.HK"
    recs = [
        make_f_partner("watch", ticker="9988.HK", market="HK", recommendation_id="R-FP-20260514-9988"),
        make_w_partner("watch", ticker="9988.HK", market="HK", recommendation_id="R-WP-20260514-9988"),
        make_g_partner("watch", ticker="9988.HK", market="HK", recommendation_id="R-GP-20260514-9988"),
    ]

    brief = assemble_brief(
        research_signals=[signal],
        recommendations=recs,
        brief_type="morning",
        date="2026-05-14",
        use_llm=False,
        data_dir=data_dir,
    )
    markdown = render_markdown(brief)

    assert brief.knowledge_memory["9988.HK"]["entries"] == []
    assert brief.knowledge_memory["9988.HK"]["similar_cases"]
    assert "相似历史案例" in markdown
    assert "PR-20260514-BABA" in markdown


def test_brief_includes_chairman_final_verdict_navigation():
    brief = assemble_brief(
        research_signals=[make_signal()],
        recommendations=[make_f_partner("long"), make_w_partner("watch"), make_g_partner("watch")],
        brief_type="morning",
        date="2026-05-13",
        use_llm=False,
    )
    markdown = render_markdown(brief)
    summary = brief.per_recommendation_summary[0]

    assert summary["chairman_verdict"]["final_verdict"] in {
        "discard",
        "watch",
        "research_priority",
        "trial_candidate",
        "conviction_candidate",
        "human_override_required",
    }
    assert summary["chairman_verdict"]["legacy_verdict"] in {"act", "wait", "reject", "research_more"}
    assert summary["opportunity_screener"]["opportunity_score"] >= 0
    assert summary["chairman_verdict"]["human_decision_checklist"]
    assert summary["chairman_verdict"]["decision_chain"]
    assert summary["chairman_verdict"]["red_team_rebuttal_policy"]["second_chairman_review_required"] is True
    assert "Chairman 裁决导航" in markdown
    assert "Human Decision Checklist" in markdown
    assert "Red Team 后二次裁决规则" in markdown


def test_split_signal_becomes_human_override_when_opportunity_is_high():
    signal = make_signal()
    signal.signal_type = "mispricing"
    signal.signal_summary = "预期差和错定价明显，市场尚未定价核心催化。"
    brief = assemble_brief(
        research_signals=[signal],
        recommendations=[
            make_f_partner(
                "long",
                thesis="预期差和 valuation reset 同时存在",
                catalysts=["回购和利润率修复"],
            ),
            make_w_partner("avoid", thesis="风险仍未验证"),
            make_g_partner("long", thesis="质量恢复和叙事拐点成立"),
        ],
        brief_type="morning",
        date="2026-05-13",
        use_llm=False,
    )

    summary = brief.per_recommendation_summary[0]

    assert summary["chairman_verdict"]["final_verdict"] == "human_override_required"
    assert "expectation_gap" in summary["opportunity_screener"]["reason_type"]
    assert '"final_verdicts"' in render_json_metadata(brief)


def test_brief_operation_summary_uses_nepha_decision_language():
    brief = assemble_brief(
        research_signals=[make_signal()],
        recommendations=[
            make_f_partner(
                "watch",
                thesis="事件催化成立但还需要等待机构资金验证",
                analysis_gaps=["机构净买入 | 尚未验证"],
                thesis_kill_criteria=["若后续披露显示只是期权 Gamma 推动，则降级"],
            ),
            make_w_partner("avoid", thesis="赔率不足且关键问题未关闭"),
            make_g_partner("abstain", thesis="缺少估值证据", abstain_reason="valuation_missing"),
        ],
        brief_type="morning",
        date="2026-05-13",
        use_llm=False,
    )

    summary = brief.per_recommendation_summary[0]["operation_summary"]
    markdown = render_markdown(brief)

    assert summary["rows"][0]["suggested_action"] == "继续观察，等待证据闭环"
    assert summary["rows"][0]["waiting_condition"] == "机构净买入 | 尚未验证"
    assert summary["rows"][0]["risk_trigger"] == "若后续披露显示只是期权 Gamma 推动，则降级"
    assert summary["rows"][2]["nepha_decision_label"] == "是，确认补资料后是否重跑"
    assert "仓位分歧度" not in markdown
    assert "机构净买入 \\| 尚未验证" in markdown
    assert "Nepha 是否需要人工拍板" in markdown
