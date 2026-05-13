from __future__ import annotations

import json

from click.testing import CliRunner

from business_agents.research_agent.agent import ResearchAgent
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


def test_research_agent_scans_all_main_pool_tickers_when_triggered(tmp_path):
    data_dir = tmp_path / "data"
    write_stock_pool(data_dir)
    result = ResearchAgent(data_dir=data_dir, market_client=TriggerMarketClient()).run(no_llm=True)

    assert any(path.parent.name == "pull_requests" for path in result.output_files)
    assert any(path.parent.name == "research_signals" for path in result.output_files)
    assert len(list((data_dir / "research_signals").glob("*.yaml"))) == 2


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
