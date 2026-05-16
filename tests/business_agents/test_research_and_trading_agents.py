from __future__ import annotations

import json

import yaml
from click.testing import CliRunner

from business_agents.research_agent.agent import ResearchAgent
from business_agents._common.llm_client import LLMError
from business_agents._common.perplexity_results import collect_perplexity_context
from business_agents.research_agent.cli import cli as research_cli
from business_agents.trading_f_partner.agent import FPartnerTradingAgent
from business_agents.trading_f_partner.cli import cli as f_partner_cli
from business_agents.trading_g_partner.agent import GPartnerTradingAgent
from business_agents.trading_g_partner.cli import cli as g_partner_cli
from business_agents.trading_w_partner.agent import WPartnerTradingAgent
from business_agents.trading_w_partner.cli import cli as w_partner_cli
from tests.conftest import QuietMarketClient, TriggerMarketClient, write_stock_pool


class AlwaysInvalidTradingLLM:
    def complete(self, **_):
        return '{"bad": true}'


class InvalidThenLongTradingLLM:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def complete(self, **_):
        self.calls += 1
        if self.calls == 1:
            return '{"bad": true}'
        return json.dumps(self.payload, ensure_ascii=False)


class OneShotTradingLLM:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def complete(self, **_):
        self.calls += 1
        return json.dumps(self.payload, ensure_ascii=False)


class FailingTradingLLM:
    def complete(self, **_):
        raise LLMError("codex timed out")


class ColdStartResearchLLM:
    def complete(self, **_):
        return json.dumps(
            {
                "cold_start_prompts": [
                    {
                        "title": "商业模式补课",
                        "research_horizon": "12m",
                        "research_dimension": "business_model",
                        "priority_order": 1,
                        "cold_start_rationale": "新股票没有历史档案，先补收入结构和利润率变化。",
                        "prompt_text": "请研究 BABA Alibaba 过去 12 个月收入结构、毛利率和经营杠杆变化，提供来源、反证和结论可信度。",
                    },
                    {
                        "title": "竞争格局补课",
                        "research_horizon": "6m",
                        "research_dimension": "competitive_position",
                        "priority_order": 2,
                        "cold_start_rationale": "需要确认竞争者动作是否改变护城河。",
                        "prompt_text": "请研究 BABA Alibaba 过去 6 个月竞争格局、竞品动作和市场份额变化，提供来源、反证和结论可信度。",
                    },
                    {
                        "title": "预期差补课",
                        "research_horizon": "9m",
                        "research_dimension": "capital_market_expectation",
                        "priority_order": 3,
                        "cold_start_rationale": "需要识别卖方和机构持仓是否已经形成一致叙事。",
                        "prompt_text": "请研究 BABA Alibaba 过去 9 个月卖方预期、机构持仓和主流叙事变化，提供来源、反证和结论可信度。",
                    },
                ]
            },
            ensure_ascii=False,
        )


class MalformedColdStartResearchLLM:
    def complete(self, **_):
        return "not json"


def test_research_agent_scans_all_main_pool_tickers_when_triggered(tmp_path):
    data_dir = tmp_path / "data"
    write_stock_pool(data_dir)
    result = ResearchAgent(data_dir=data_dir, market_client=TriggerMarketClient()).run(no_llm=True)

    assert any(path.parent.name == "pull_requests" for path in result.output_files)
    assert any(path.parent.name == "research_signals" for path in result.output_files)
    assert len(list((data_dir / "research_signals").glob("*.yaml"))) == 2


def test_research_prompt_ids_include_ticker_to_avoid_rerun_collisions(tmp_path):
    data_dir = tmp_path / "data"
    write_stock_pool(data_dir)

    ResearchAgent(
        data_dir=data_dir,
        market_client=TriggerMarketClient(),
        run_date="2026-05-14",
    ).run(no_llm=True)

    prompt_names = {path.name for path in (data_dir / "pull_requests").glob("*.yaml")}
    signal_names = {path.name for path in (data_dir / "research_signals").glob("*.yaml")}

    assert "PR-20260514-0700-HK.yaml" in prompt_names
    assert "PR-20260514-BABA.yaml" in prompt_names
    assert "RS-20260514-0700-HK.yaml" in signal_names
    assert "RS-20260514-BABA.yaml" in signal_names


def test_research_agent_generates_cold_start_prompts_for_new_ticker(tmp_path):
    data_dir = tmp_path / "data"
    write_stock_pool(data_dir)

    result = ResearchAgent(
        data_dir=data_dir,
        market_client=TriggerMarketClient(),
        llm_client=ColdStartResearchLLM(),
        run_date="2026-05-14",
    ).run()

    prompt_names = {path.name for path in result.output_files if path.parent.name == "pull_requests"}
    assert "PR-20260514-BABA-COLDSTART-1.yaml" in prompt_names
    assert "PR-20260514-BABA-COLDSTART-2.yaml" in prompt_names
    assert "PR-20260514-BABA-COLDSTART-3.yaml" in prompt_names

    cold_prompt = yaml.safe_load(
        (data_dir / "pull_requests" / "PR-20260514-BABA-COLDSTART-1.yaml").read_text(encoding="utf-8")
    )
    assert cold_prompt["status"] == "pending_cold_start"
    assert cold_prompt["cold_start"] is True
    assert cold_prompt["research_dimension"] == "business_model"
    assert "过去 12 个月" in cold_prompt["prompt_text"]

    signal_data = yaml.safe_load(
        (data_dir / "research_signals" / "RS-20260514-BABA.yaml").read_text(encoding="utf-8")
    )["research_signal"]
    assert "PR-20260514-BABA-COLDSTART-1" in signal_data["perplexity_research"]["prompts_pending"]
    assert len(signal_data["research_planning_context"]["cold_start_pending"]) == 3
    assert "置信度不得超过 50%" in "\n".join(signal_data["research_planning_context"]["prompt_directives"])

    llm_log = next((data_dir / "agent_logs").glob("*/research_agent/*.llm.log"))
    assert "cold_start_research_planning" in llm_log.read_text(encoding="utf-8")


def test_research_agent_falls_back_when_cold_start_llm_returns_bad_json(tmp_path):
    data_dir = tmp_path / "data"
    write_stock_pool(data_dir)

    ResearchAgent(
        data_dir=data_dir,
        market_client=TriggerMarketClient(),
        llm_client=MalformedColdStartResearchLLM(),
        run_date="2026-05-14",
    ).run()

    cold_prompts = sorted((data_dir / "pull_requests").glob("PR-20260514-BABA-COLDSTART-*.yaml"))

    assert len(cold_prompts) == 3
    first_prompt = yaml.safe_load(cold_prompts[0].read_text(encoding="utf-8"))
    assert first_prompt["generation_source"] == "fallback_template_after_llm_parse_error"
    assert first_prompt["status"] == "pending_cold_start"


def test_research_prompt_uses_k_deep_question_framework(tmp_path):
    data_dir = tmp_path / "data"
    write_stock_pool(data_dir)

    ResearchAgent(
        data_dir=data_dir,
        market_client=TriggerMarketClient(),
        run_date="2026-05-14",
    ).run(no_llm=True)

    prompt_data = yaml.safe_load((data_dir / "pull_requests" / "PR-20260514-BABA.yaml").read_text(encoding="utf-8"))
    signal_data = yaml.safe_load((data_dir / "research_signals" / "RS-20260514-BABA.yaml").read_text(encoding="utf-8"))

    question_set = prompt_data["research_question_set"]
    assert question_set["framework"] == "k_deep_research_questions_v1"
    assert question_set["methodology_source"] == "research_system_v0.3.md"
    assert question_set["methodology_version"] == "0.3"
    assert len(question_set["question_groups"]) == 7
    assert [group["gate_id"] for group in question_set["question_groups"]] == [
        "Gate 1",
        "Gate 2",
        "Gate 3",
        "Gate 4",
        "Gate 5",
        "Gate 6",
        "Gate 7",
    ]
    assert "K deep 研究问题组" in prompt_data["prompt_text"]
    assert "research_system_v0.3.md" in prompt_data["prompt_text"]
    assert "human_in_the_loop" in prompt_data["prompt_text"]
    assert "竞争格局" in prompt_data["prompt_text"]
    assert "非共识 Screener 要求" in prompt_data["prompt_text"]
    assert "可进入知识库的结构化要点" in prompt_data["prompt_text"]
    assert signal_data["research_signal"]["k_deep_research_questions"]["question_groups"]
    assert signal_data["research_signal"]["non_consensus_screener"]["screener_version"] == "non_consensus_screener_v1"
    assert signal_data["research_signal"]["research_methodology_profile"]["methodology_source"] == "research_system_v0.3.md"
    fingerprint = signal_data["research_signal"]["signal_fingerprint"]
    assert fingerprint["fingerprint_version"] == "signal_fingerprint_v1"
    assert fingerprint["methodology"]["methodology_source"] == "research_system_v0.3.md"
    assert "single_day_move_ge_7pct" in fingerprint["trigger_rules"]
    assert "non_consensus_screener" in fingerprint["tags"]


def test_research_agent_no_trigger_writes_summary_only(tmp_path):
    data_dir = tmp_path / "data"
    write_stock_pool(data_dir)
    result = ResearchAgent(data_dir=data_dir, market_client=QuietMarketClient()).run(no_llm=True)

    assert not any(path.parent.name == "pull_requests" for path in result.output_files)
    assert not any(path.parent.name == "research_signals" for path in result.output_files)
    assert any(path.parent.name == "research_runs" for path in result.output_files)


def test_trading_agent_consumes_upstream_signal(tmp_path):
    data_dir = tmp_path / "data"
    write_stock_pool(data_dir)
    ResearchAgent(data_dir=data_dir, market_client=TriggerMarketClient()).run(no_llm=True)
    result = FPartnerTradingAgent(data_dir=data_dir).run(no_llm=True)

    assert result.output_files
    content = result.output_files[0].read_text(encoding="utf-8")
    assert "upstream_research_signals" in content


def test_trading_agent_only_consumes_selected_run_date_signals(tmp_path):
    data_dir = tmp_path / "data"
    write_stock_pool(data_dir)
    ResearchAgent(data_dir=data_dir, market_client=TriggerMarketClient(), run_date="2026-05-13").run(no_llm=True)
    ResearchAgent(data_dir=data_dir, market_client=TriggerMarketClient(), run_date="2026-05-14").run(no_llm=True)

    signals = FPartnerTradingAgent(data_dir=data_dir, run_date="2026-05-14").load_research_signals()

    assert len(signals) == 2
    assert all(signal.research_signal_id.startswith("RS-20260514-") for signal in signals)


def test_trading_agent_evidence_unverified_propagates(tmp_path):
    data_dir = tmp_path / "data"
    write_stock_pool(data_dir)
    ResearchAgent(data_dir=data_dir, market_client=TriggerMarketClient()).run(no_llm=True)
    result = WPartnerTradingAgent(data_dir=data_dir).run(no_llm=True)
    content = result.output_files[0].read_text(encoding="utf-8")

    assert "evidence_unverified_inherited: true" in content
    assert "confidence: 62" in content


def test_trading_agent_caps_confidence_when_cold_start_pending(tmp_path):
    data_dir = tmp_path / "data"
    write_stock_pool(data_dir)
    ResearchAgent(
        data_dir=data_dir,
        market_client=TriggerMarketClient(),
        llm_client=ColdStartResearchLLM(),
        run_date="2026-05-14",
    ).run()

    result = FPartnerTradingAgent(data_dir=data_dir, run_date="2026-05-14").run(no_llm=True)
    baba_path = next(path for path in result.output_files if path.name == "R-FP-20260514-BABA.yaml")
    content = baba_path.read_text(encoding="utf-8")

    assert "confidence: 50" in content
    assert "confidence_ceiling_applied: 50" in content
    assert "waiting_conditions" in content
    assert "PR-20260514-BABA-COLDSTART-1" in content


def test_existing_cold_start_pending_carries_into_next_scan(tmp_path):
    data_dir = tmp_path / "data"
    write_stock_pool(data_dir)
    ResearchAgent(
        data_dir=data_dir,
        market_client=TriggerMarketClient(),
        llm_client=ColdStartResearchLLM(),
        run_date="2026-05-14",
    ).run()

    ResearchAgent(
        data_dir=data_dir,
        market_client=TriggerMarketClient(),
        run_date="2026-05-15",
    ).run(no_llm=True)

    signal_data = yaml.safe_load(
        (data_dir / "research_signals" / "RS-20260515-BABA.yaml").read_text(encoding="utf-8")
    )["research_signal"]
    pending = signal_data["perplexity_research"]["prompts_pending"]
    assert "PR-20260515-BABA" in pending
    assert "PR-20260514-BABA-COLDSTART-1" in pending

    result = FPartnerTradingAgent(data_dir=data_dir, run_date="2026-05-15").run(no_llm=True)
    baba_path = next(path for path in result.output_files if path.name == "R-FP-20260515-BABA.yaml")
    content = baba_path.read_text(encoding="utf-8")

    assert "confidence: 50" in content
    assert "confidence_ceiling_applied: 50" in content
    assert "PR-20260514-BABA-COLDSTART-1" in content


def test_closed_cold_start_prompts_are_removed_from_planning_context(tmp_path):
    data_dir = tmp_path / "data"
    write_stock_pool(data_dir)
    ResearchAgent(
        data_dir=data_dir,
        market_client=TriggerMarketClient(),
        llm_client=ColdStartResearchLLM(),
        run_date="2026-05-14",
    ).run()
    results_dir = data_dir / "perplexity_results"
    results_dir.mkdir(parents=True)
    for index in range(1, 4):
        prompt_id = f"PR-20260514-BABA-COLDSTART-{index}"
        (results_dir / f"{prompt_id}_skipped.yaml").write_text(
            yaml.safe_dump(
                {
                    "prompt_id": prompt_id,
                    "related_signal_id": "RS-20260514-BABA",
                    "status": "skip_cold_start",
                    "prompt_text": yaml.safe_load(
                        (data_dir / "pull_requests" / f"{prompt_id}.yaml").read_text(encoding="utf-8")
                    )["prompt_text"],
                },
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )

    signals = FPartnerTradingAgent(data_dir=data_dir, run_date="2026-05-14").load_research_signals()
    baba_signal = next(signal for signal in signals if signal.research_signal_id == "RS-20260514-BABA")

    assert baba_signal.research_planning_context["cold_start_pending"] == []
    assert "置信度不得超过 50%" not in "\n".join(baba_signal.research_planning_context["prompt_directives"])


def test_trading_agent_consumes_filled_perplexity_result(tmp_path):
    data_dir = tmp_path / "data"
    write_stock_pool(data_dir)
    ResearchAgent(data_dir=data_dir, market_client=TriggerMarketClient()).run(no_llm=True)
    prompt_path = sorted((data_dir / "pull_requests").glob("*.yaml"))[0]
    prompt_id = prompt_path.stem
    results_dir = data_dir / "perplexity_results"
    results_dir.mkdir(parents=True)
    (results_dir / f"{prompt_id}_filled.yaml").write_text(
        f"""
prompt_id: {prompt_id}
status: filled
source: perplexity
answer_text: |
  Perplexity 深入研究结论：腾讯最近 7 天出现非连续变化证据。
""",
        encoding="utf-8",
    )

    result = FPartnerTradingAgent(data_dir=data_dir).run(no_llm=True)
    content = result.output_files[0].read_text(encoding="utf-8")
    log_content = next((data_dir / "agent_logs").glob("*/trading_f_partner/*.llm.log")).read_text(
        encoding="utf-8"
    )

    assert "used_perplexity_results: true" in content
    assert f"- {prompt_id}" in content
    assert "evidence_unverified_inherited: false" in content
    assert "Perplexity 深入研究结论" in log_content


def test_stale_perplexity_result_prompt_text_mismatch_is_ignored(tmp_path):
    data_dir = tmp_path / "data"
    write_stock_pool(data_dir)
    ResearchAgent(data_dir=data_dir, market_client=TriggerMarketClient(), run_date="2026-05-14").run(no_llm=True)
    prompt_path = sorted((data_dir / "pull_requests").glob("*.yaml"))[0]
    prompt_id = prompt_path.stem
    results_dir = data_dir / "perplexity_results"
    results_dir.mkdir(parents=True)
    (results_dir / f"{prompt_id}_filled.yaml").write_text(
        f"""
prompt_id: {prompt_id}
related_signal_id: RS-20260514-0700-HK
status: filled
source: perplexity
prompt_text: 这是旧的、不匹配的 prompt 文本
answer_text: |
  这段旧回填不应该进入交易 Agent。
""",
        encoding="utf-8",
    )

    result = FPartnerTradingAgent(data_dir=data_dir, run_date="2026-05-14").run(no_llm=True)
    content = result.output_files[0].read_text(encoding="utf-8")
    log_content = next((data_dir / "agent_logs").glob("*/trading_f_partner/*.llm.log")).read_text(
        encoding="utf-8"
    )

    assert "used_perplexity_results: false" in content
    assert "ignored_result_reason" in log_content
    assert "这段旧回填不应该进入交易 Agent" not in log_content


def test_perplexity_context_truncates_long_answer_for_llm_prompt(tmp_path):
    data_dir = tmp_path / "data"
    write_stock_pool(data_dir)
    ResearchAgent(data_dir=data_dir, market_client=TriggerMarketClient(), run_date="2026-05-14").run(no_llm=True)
    agent = FPartnerTradingAgent(data_dir=data_dir, run_date="2026-05-14")
    signal = agent.load_research_signals()[0]
    prompt_path = data_dir / "pull_requests" / f"PR-20260514-{signal.candidate_targets[0].ticker.replace('.', '-')}.yaml"
    result_dir = data_dir / "perplexity_results"
    result_dir.mkdir(parents=True)
    prompt_id = prompt_path.stem
    (result_dir / f"{prompt_id}_filled.yaml").write_text(
        yaml.safe_dump({"prompt_id": prompt_id, "status": "filled", "answer_text": "A" * 5000}),
        encoding="utf-8",
    )

    context = collect_perplexity_context(data_dir, signal)

    assert "answer_text_truncated: true" in context.yaml_text
    assert "完整回填内容请查看 result_path" in context.yaml_text
    assert len(context.yaml_text) < 4500


def test_trading_agent_normalizes_data_point_url_aliases(tmp_path):
    data_dir = tmp_path / "data"
    write_stock_pool(data_dir)
    ResearchAgent(data_dir=data_dir, market_client=TriggerMarketClient(), run_date="2026-05-14").run(no_llm=True)
    agent = FPartnerTradingAgent(data_dir=data_dir, run_date="2026-05-14")
    signal = agent.load_research_signals()[0]

    payload = agent.normalize_payload_data_points(
        {
            "data_points": [
                {"label": "alias", "value": "has url", "url": "https://example.com/source"},
                {"label": "fallback", "value": "needs fallback"},
            ]
        },
        signal,
        signal.candidate_targets[0].ticker,
    )

    assert payload["data_points"][0]["source_url"] == "https://example.com/source"
    assert payload["data_points"][1]["source_url"].startswith("https://finance.yahoo.com/quote/")


def test_trading_agent_uses_stable_recommendation_id_and_removes_same_ticker_stale_file(tmp_path):
    data_dir = tmp_path / "data"
    write_stock_pool(data_dir)
    ResearchAgent(data_dir=data_dir, market_client=TriggerMarketClient(), run_date="2026-05-14").run(no_llm=True)
    stale_dir = data_dir / "recommendations" / "20260514" / "f_partner"
    stale_dir.mkdir(parents=True)
    (stale_dir / "FRO-20260514-BABA.yaml").write_text(
        yaml.safe_dump(
            {"recommendation": {"recommendation_id": "FRO-20260514-BABA", "ticker": "BABA"}},
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    FPartnerTradingAgent(data_dir=data_dir, run_date="2026-05-14").run(no_llm=True)

    assert (stale_dir / "R-FP-20260514-BABA.yaml").exists()
    assert not (stale_dir / "FRO-20260514-BABA.yaml").exists()


def test_three_trading_agent_schema_differences(tmp_path):
    data_dir = tmp_path / "data"
    write_stock_pool(data_dir)
    ResearchAgent(data_dir=data_dir, market_client=TriggerMarketClient()).run(no_llm=True)

    f_partner = FPartnerTradingAgent(data_dir=data_dir).run(no_llm=True).output_files[0].read_text(encoding="utf-8")
    w_partner = WPartnerTradingAgent(data_dir=data_dir).run(no_llm=True).output_files[0].read_text(encoding="utf-8")
    g_partner = GPartnerTradingAgent(data_dir=data_dir).run(no_llm=True).output_files[0].read_text(encoding="utf-8")

    assert "f_partner_specific_framework" in f_partner
    assert "w_partner_rating" in w_partner
    assert "dual_gate_consistency" in g_partner


def test_llm_schema_failure_is_abstain_and_auditable(tmp_path):
    data_dir = tmp_path / "data"
    write_stock_pool(data_dir)
    ResearchAgent(data_dir=data_dir, market_client=TriggerMarketClient()).run(no_llm=True)

    result = FPartnerTradingAgent(data_dir=data_dir, llm_client=AlwaysInvalidTradingLLM()).run()
    content = result.output_files[0].read_text(encoding="utf-8")

    assert "direction: abstain" in content
    assert "schema_validation_failed" in content
    assert "validation_failure" in content


def test_llm_repair_then_long_is_downgraded_to_watch(tmp_path):
    data_dir = tmp_path / "data"
    write_stock_pool(data_dir)
    ResearchAgent(data_dir=data_dir, market_client=TriggerMarketClient()).run(no_llm=True)
    agent = FPartnerTradingAgent(data_dir=data_dir)
    signal = agent.load_research_signals()[0]
    payload = agent.build_debug_recommendation(signal, "0700.HK", 1)
    payload["direction"] = "long"
    payload["confidence"] = 88
    fake_llm = InvalidThenLongTradingLLM(payload)

    result = FPartnerTradingAgent(data_dir=data_dir, llm_client=fake_llm).run()
    content = result.output_files[0].read_text(encoding="utf-8")

    assert fake_llm.calls >= 2
    assert "direction: watch" in content
    assert "original_direction: long" in content
    assert "first_phase_long_disabled" in content


def test_llm_long_with_non_integer_confidence_is_schema_failure(tmp_path):
    data_dir = tmp_path / "data"
    write_stock_pool(data_dir)
    ResearchAgent(data_dir=data_dir, market_client=TriggerMarketClient()).run(no_llm=True)
    agent = FPartnerTradingAgent(data_dir=data_dir)
    signal = agent.load_research_signals()[0]
    payload = agent.build_debug_recommendation(signal, "0700.HK", 1)
    payload["direction"] = "long"
    payload["confidence"] = "high"
    fake_llm = InvalidThenLongTradingLLM(payload)

    result = FPartnerTradingAgent(data_dir=data_dir, llm_client=fake_llm).run()
    content = result.output_files[0].read_text(encoding="utf-8")

    assert fake_llm.calls >= 3
    assert "direction: abstain" in content
    assert "schema_validation_failed" in content
    assert "confidence must be integer-like" in content


def test_llm_missing_identity_fields_are_normalized_before_schema_repair(tmp_path):
    data_dir = tmp_path / "data"
    write_stock_pool(data_dir)
    ResearchAgent(data_dir=data_dir, market_client=TriggerMarketClient(), run_date="2026-05-14").run(no_llm=True)
    agent = FPartnerTradingAgent(data_dir=data_dir, run_date="2026-05-14")
    signal = agent.load_research_signals()[0]
    ticker = signal.candidate_targets[0].ticker
    payload = agent.build_debug_recommendation(signal, ticker, 1)
    payload.pop("recommendation_id")
    payload.pop("agent_id")
    fake_llm = OneShotTradingLLM(payload)

    result = FPartnerTradingAgent(data_dir=data_dir, llm_client=fake_llm, run_date="2026-05-14").run()

    assert fake_llm.calls == 2
    assert any(path.name == "R-FP-20260514-BABA.yaml" for path in result.output_files)


def test_llm_common_format_noise_is_normalized_before_schema_repair(tmp_path):
    data_dir = tmp_path / "data"
    write_stock_pool(data_dir)
    ResearchAgent(data_dir=data_dir, market_client=TriggerMarketClient(), run_date="2026-05-14").run(no_llm=True)
    agent = FPartnerTradingAgent(data_dir=data_dir, run_date="2026-05-14")
    signal = agent.load_research_signals()[0]
    ticker = signal.candidate_targets[0].ticker
    payload = agent.build_debug_recommendation(signal, ticker, 1)
    payload["direction"] = "long"
    payload["confidence"] = "60%"
    payload["entry_zone"] = [None, None]
    fake_llm = OneShotTradingLLM(payload)

    result = FPartnerTradingAgent(data_dir=data_dir, llm_client=fake_llm, run_date="2026-05-14").run()
    content = result.output_files[0].read_text(encoding="utf-8")

    assert fake_llm.calls == 2
    assert "direction: watch" in content
    assert "confidence: 60" in content
    assert "entry_zone: null" in content


def test_llm_upstream_signal_dict_is_normalized(tmp_path):
    data_dir = tmp_path / "data"
    write_stock_pool(data_dir)
    ResearchAgent(data_dir=data_dir, market_client=TriggerMarketClient(), run_date="2026-05-14").run(no_llm=True)
    agent = FPartnerTradingAgent(data_dir=data_dir, run_date="2026-05-14")
    signal = agent.load_research_signals()[0]
    ticker = signal.candidate_targets[0].ticker
    payload = agent.build_debug_recommendation(signal, ticker, 1)
    payload["upstream_research_signals"] = {
        "research_signal_id": signal.research_signal_id,
        "my_methodology_verdict": "partial",
    }
    fake_llm = OneShotTradingLLM(payload)

    result = FPartnerTradingAgent(data_dir=data_dir, llm_client=fake_llm, run_date="2026-05-14").run()
    content = result.output_files[0].read_text(encoding="utf-8")

    assert "agent_runtime_failed" not in content
    assert "used_perplexity_results: false" in content


def test_llm_minimal_judgment_uses_deterministic_schema_backbone(tmp_path):
    data_dir = tmp_path / "data"
    write_stock_pool(data_dir)
    ResearchAgent(data_dir=data_dir, market_client=TriggerMarketClient(), run_date="2026-05-14").run(no_llm=True)
    fake_llm = OneShotTradingLLM(
        {
            "direction": "watch",
            "confidence": 55,
            "thesis": "LLM 只补判断，结构字段由 Agent 骨架补齐。",
        }
    )

    result = FPartnerTradingAgent(data_dir=data_dir, llm_client=fake_llm, run_date="2026-05-14").run()
    content = result.output_files[0].read_text(encoding="utf-8")

    assert fake_llm.calls == 2
    assert "LLM 只补判断" in content
    assert "f_partner_specific_framework" in content
    assert "upstream_research_signals" in content
    assert "data_points" in content


def test_llm_runtime_error_is_auditable_abstain_not_debug_fallback(tmp_path):
    data_dir = tmp_path / "data"
    write_stock_pool(data_dir)
    ResearchAgent(data_dir=data_dir, market_client=TriggerMarketClient()).run(no_llm=True)

    result = FPartnerTradingAgent(data_dir=data_dir, llm_client=FailingTradingLLM()).run()
    content = result.output_files[0].read_text(encoding="utf-8")

    assert "direction: abstain" in content
    assert "llm_runtime_failed" in content
    assert "codex timed out" in content


def test_business_agent_clis(tmp_path):
    data_dir = tmp_path / "data"
    write_stock_pool(data_dir)
    runner = CliRunner()

    research_result = runner.invoke(research_cli, ["run", "--type", "scan", "--no-llm", "--data-dir", str(data_dir)])
    assert research_result.exit_code == 0, research_result.output

    f_partner_result = runner.invoke(f_partner_cli, ["run", "--no-llm", "--data-dir", str(data_dir)])
    assert f_partner_result.exit_code == 0, f_partner_result.output

    w_partner_result = runner.invoke(w_partner_cli, ["run", "--no-llm", "--data-dir", str(data_dir)])
    assert w_partner_result.exit_code == 0, w_partner_result.output

    g_partner_result = runner.invoke(g_partner_cli, ["run", "--no-llm", "--data-dir", str(data_dir)])
    assert g_partner_result.exit_code == 0, g_partner_result.output
