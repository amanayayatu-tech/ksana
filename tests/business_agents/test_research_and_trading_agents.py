from __future__ import annotations

import json

import yaml
from click.testing import CliRunner

from business_agents.research_agent.agent import ResearchAgent
from business_agents._common.llm_client import LLMError
from business_agents._common.perplexity_results import collect_perplexity_context
from business_agents.research_agent.cli import cli as research_cli
from business_agents.trading_fengliu.agent import FengliuTradingAgent
from business_agents.trading_fengliu.cli import cli as fengliu_cli
from business_agents.trading_liguofei.agent import LiguofeiTradingAgent
from business_agents.trading_liguofei.cli import cli as liguofei_cli
from business_agents.trading_wanmu.agent import WanmuTradingAgent
from business_agents.trading_wanmu.cli import cli as wanmu_cli
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
    result = FengliuTradingAgent(data_dir=data_dir).run(no_llm=True)

    assert result.output_files
    content = result.output_files[0].read_text(encoding="utf-8")
    assert "upstream_research_signals" in content


def test_trading_agent_only_consumes_selected_run_date_signals(tmp_path):
    data_dir = tmp_path / "data"
    write_stock_pool(data_dir)
    ResearchAgent(data_dir=data_dir, market_client=TriggerMarketClient(), run_date="2026-05-13").run(no_llm=True)
    ResearchAgent(data_dir=data_dir, market_client=TriggerMarketClient(), run_date="2026-05-14").run(no_llm=True)

    signals = FengliuTradingAgent(data_dir=data_dir, run_date="2026-05-14").load_research_signals()

    assert len(signals) == 2
    assert all(signal.research_signal_id.startswith("RS-20260514-") for signal in signals)


def test_trading_agent_evidence_unverified_propagates(tmp_path):
    data_dir = tmp_path / "data"
    write_stock_pool(data_dir)
    ResearchAgent(data_dir=data_dir, market_client=TriggerMarketClient()).run(no_llm=True)
    result = WanmuTradingAgent(data_dir=data_dir).run(no_llm=True)
    content = result.output_files[0].read_text(encoding="utf-8")

    assert "evidence_unverified_inherited: true" in content
    assert "confidence: 62" in content


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

    result = FengliuTradingAgent(data_dir=data_dir).run(no_llm=True)
    content = result.output_files[0].read_text(encoding="utf-8")
    log_content = next((data_dir / "agent_logs").glob("*/trading_fengliu/*.llm.log")).read_text(
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

    result = FengliuTradingAgent(data_dir=data_dir, run_date="2026-05-14").run(no_llm=True)
    content = result.output_files[0].read_text(encoding="utf-8")
    log_content = next((data_dir / "agent_logs").glob("*/trading_fengliu/*.llm.log")).read_text(
        encoding="utf-8"
    )

    assert "used_perplexity_results: false" in content
    assert "ignored_result_reason" in log_content
    assert "这段旧回填不应该进入交易 Agent" not in log_content


def test_perplexity_context_truncates_long_answer_for_llm_prompt(tmp_path):
    data_dir = tmp_path / "data"
    write_stock_pool(data_dir)
    ResearchAgent(data_dir=data_dir, market_client=TriggerMarketClient(), run_date="2026-05-14").run(no_llm=True)
    agent = FengliuTradingAgent(data_dir=data_dir, run_date="2026-05-14")
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
    agent = FengliuTradingAgent(data_dir=data_dir, run_date="2026-05-14")
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
    stale_dir = data_dir / "recommendations" / "20260514" / "fengliu"
    stale_dir.mkdir(parents=True)
    (stale_dir / "FRO-20260514-BABA.yaml").write_text(
        yaml.safe_dump(
            {"recommendation": {"recommendation_id": "FRO-20260514-BABA", "ticker": "BABA"}},
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    FengliuTradingAgent(data_dir=data_dir, run_date="2026-05-14").run(no_llm=True)

    assert (stale_dir / "R-FL-20260514-BABA.yaml").exists()
    assert not (stale_dir / "FRO-20260514-BABA.yaml").exists()


def test_three_trading_agent_schema_differences(tmp_path):
    data_dir = tmp_path / "data"
    write_stock_pool(data_dir)
    ResearchAgent(data_dir=data_dir, market_client=TriggerMarketClient()).run(no_llm=True)

    fengliu = FengliuTradingAgent(data_dir=data_dir).run(no_llm=True).output_files[0].read_text(encoding="utf-8")
    wanmu = WanmuTradingAgent(data_dir=data_dir).run(no_llm=True).output_files[0].read_text(encoding="utf-8")
    liguofei = LiguofeiTradingAgent(data_dir=data_dir).run(no_llm=True).output_files[0].read_text(encoding="utf-8")

    assert "fengliu_specific_framework" in fengliu
    assert "wanmu_rating" in wanmu
    assert "dual_gate_consistency" in liguofei


def test_llm_schema_failure_is_abstain_and_auditable(tmp_path):
    data_dir = tmp_path / "data"
    write_stock_pool(data_dir)
    ResearchAgent(data_dir=data_dir, market_client=TriggerMarketClient()).run(no_llm=True)

    result = FengliuTradingAgent(data_dir=data_dir, llm_client=AlwaysInvalidTradingLLM()).run()
    content = result.output_files[0].read_text(encoding="utf-8")

    assert "direction: abstain" in content
    assert "schema_validation_failed" in content
    assert "validation_failure" in content


def test_llm_repair_then_long_is_downgraded_to_watch(tmp_path):
    data_dir = tmp_path / "data"
    write_stock_pool(data_dir)
    ResearchAgent(data_dir=data_dir, market_client=TriggerMarketClient()).run(no_llm=True)
    agent = FengliuTradingAgent(data_dir=data_dir)
    signal = agent.load_research_signals()[0]
    payload = agent.build_debug_recommendation(signal, "0700.HK", 1)
    payload["direction"] = "long"
    payload["confidence"] = 88
    fake_llm = InvalidThenLongTradingLLM(payload)

    result = FengliuTradingAgent(data_dir=data_dir, llm_client=fake_llm).run()
    content = result.output_files[0].read_text(encoding="utf-8")

    assert fake_llm.calls >= 2
    assert "direction: watch" in content
    assert "original_direction: long" in content
    assert "first_phase_long_disabled" in content


def test_llm_long_with_non_integer_confidence_is_schema_failure(tmp_path):
    data_dir = tmp_path / "data"
    write_stock_pool(data_dir)
    ResearchAgent(data_dir=data_dir, market_client=TriggerMarketClient()).run(no_llm=True)
    agent = FengliuTradingAgent(data_dir=data_dir)
    signal = agent.load_research_signals()[0]
    payload = agent.build_debug_recommendation(signal, "0700.HK", 1)
    payload["direction"] = "long"
    payload["confidence"] = "high"
    fake_llm = InvalidThenLongTradingLLM(payload)

    result = FengliuTradingAgent(data_dir=data_dir, llm_client=fake_llm).run()
    content = result.output_files[0].read_text(encoding="utf-8")

    assert fake_llm.calls >= 3
    assert "direction: abstain" in content
    assert "schema_validation_failed" in content
    assert "confidence must be integer-like" in content


def test_llm_missing_identity_fields_are_normalized_before_schema_repair(tmp_path):
    data_dir = tmp_path / "data"
    write_stock_pool(data_dir)
    ResearchAgent(data_dir=data_dir, market_client=TriggerMarketClient(), run_date="2026-05-14").run(no_llm=True)
    agent = FengliuTradingAgent(data_dir=data_dir, run_date="2026-05-14")
    signal = agent.load_research_signals()[0]
    ticker = signal.candidate_targets[0].ticker
    payload = agent.build_debug_recommendation(signal, ticker, 1)
    payload.pop("recommendation_id")
    payload.pop("agent_id")
    fake_llm = OneShotTradingLLM(payload)

    result = FengliuTradingAgent(data_dir=data_dir, llm_client=fake_llm, run_date="2026-05-14").run()

    assert fake_llm.calls == 2
    assert any(path.name == "R-FL-20260514-BABA.yaml" for path in result.output_files)


def test_llm_common_format_noise_is_normalized_before_schema_repair(tmp_path):
    data_dir = tmp_path / "data"
    write_stock_pool(data_dir)
    ResearchAgent(data_dir=data_dir, market_client=TriggerMarketClient(), run_date="2026-05-14").run(no_llm=True)
    agent = FengliuTradingAgent(data_dir=data_dir, run_date="2026-05-14")
    signal = agent.load_research_signals()[0]
    ticker = signal.candidate_targets[0].ticker
    payload = agent.build_debug_recommendation(signal, ticker, 1)
    payload["direction"] = "long"
    payload["confidence"] = "60%"
    payload["entry_zone"] = [None, None]
    fake_llm = OneShotTradingLLM(payload)

    result = FengliuTradingAgent(data_dir=data_dir, llm_client=fake_llm, run_date="2026-05-14").run()
    content = result.output_files[0].read_text(encoding="utf-8")

    assert fake_llm.calls == 2
    assert "direction: watch" in content
    assert "confidence: 60" in content
    assert "entry_zone: null" in content


def test_llm_upstream_signal_dict_is_normalized(tmp_path):
    data_dir = tmp_path / "data"
    write_stock_pool(data_dir)
    ResearchAgent(data_dir=data_dir, market_client=TriggerMarketClient(), run_date="2026-05-14").run(no_llm=True)
    agent = FengliuTradingAgent(data_dir=data_dir, run_date="2026-05-14")
    signal = agent.load_research_signals()[0]
    ticker = signal.candidate_targets[0].ticker
    payload = agent.build_debug_recommendation(signal, ticker, 1)
    payload["upstream_research_signals"] = {
        "research_signal_id": signal.research_signal_id,
        "my_methodology_verdict": "partial",
    }
    fake_llm = OneShotTradingLLM(payload)

    result = FengliuTradingAgent(data_dir=data_dir, llm_client=fake_llm, run_date="2026-05-14").run()
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

    result = FengliuTradingAgent(data_dir=data_dir, llm_client=fake_llm, run_date="2026-05-14").run()
    content = result.output_files[0].read_text(encoding="utf-8")

    assert fake_llm.calls == 2
    assert "LLM 只补判断" in content
    assert "fengliu_specific_framework" in content
    assert "upstream_research_signals" in content
    assert "data_points" in content


def test_llm_runtime_error_is_auditable_abstain_not_debug_fallback(tmp_path):
    data_dir = tmp_path / "data"
    write_stock_pool(data_dir)
    ResearchAgent(data_dir=data_dir, market_client=TriggerMarketClient()).run(no_llm=True)

    result = FengliuTradingAgent(data_dir=data_dir, llm_client=FailingTradingLLM()).run()
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

    fengliu_result = runner.invoke(fengliu_cli, ["run", "--no-llm", "--data-dir", str(data_dir)])
    assert fengliu_result.exit_code == 0, fengliu_result.output

    wanmu_result = runner.invoke(wanmu_cli, ["run", "--no-llm", "--data-dir", str(data_dir)])
    assert wanmu_result.exit_code == 0, wanmu_result.output

    liguofei_result = runner.invoke(liguofei_cli, ["run", "--no-llm", "--data-dir", str(data_dir)])
    assert liguofei_result.exit_code == 0, liguofei_result.output
