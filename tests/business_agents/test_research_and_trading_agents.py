from __future__ import annotations

from click.testing import CliRunner

from business_agents.research_agent.agent import ResearchAgent
from business_agents.research_agent.cli import cli as research_cli
from business_agents.trading_fengliu.agent import FengliuTradingAgent
from business_agents.trading_fengliu.cli import cli as fengliu_cli
from business_agents.trading_liguofei.agent import LiguofeiTradingAgent
from business_agents.trading_liguofei.cli import cli as liguofei_cli
from business_agents.trading_wanmu.agent import WanmuTradingAgent
from business_agents.trading_wanmu.cli import cli as wanmu_cli
from tests.conftest import write_stock_pool


class InvalidResearchLLM:
    def complete(self, **_):
        return '{"research_signals": [{"bad": true}], "perplexity_prompt_brief": {"brief_id": "bad", "prompts": []}}'


def test_research_agent_outputs_pull_request_when_uncertain(tmp_path):
    data_dir = tmp_path / "data"
    write_stock_pool(data_dir)
    result = ResearchAgent(data_dir=data_dir).run(no_llm=True)

    assert any(path.parent.name == "pull_requests" for path in result.output_files)
    assert any(path.parent.name == "research_signals" for path in result.output_files)


def test_research_agent_invalid_llm_output_falls_back(tmp_path):
    data_dir = tmp_path / "data"
    write_stock_pool(data_dir)
    result = ResearchAgent(data_dir=data_dir, llm_client=InvalidResearchLLM()).run()

    assert any(path.parent.name == "pull_requests" for path in result.output_files)
    assert list((data_dir / "errors").glob("*.json"))


def test_trading_agent_consumes_upstream_signal(tmp_path):
    data_dir = tmp_path / "data"
    write_stock_pool(data_dir)
    ResearchAgent(data_dir=data_dir).run(no_llm=True)
    result = FengliuTradingAgent(data_dir=data_dir).run(no_llm=True)

    assert result.output_files
    content = result.output_files[0].read_text(encoding="utf-8")
    assert "upstream_research_signals" in content


def test_trading_agent_evidence_unverified_propagates(tmp_path):
    data_dir = tmp_path / "data"
    write_stock_pool(data_dir)
    ResearchAgent(data_dir=data_dir).run(no_llm=True)
    result = WanmuTradingAgent(data_dir=data_dir).run(no_llm=True)
    content = result.output_files[0].read_text(encoding="utf-8")

    assert "evidence_unverified_inherited: true" in content
    assert "confidence: 60" in content


def test_trading_agent_consumes_filled_perplexity_result(tmp_path):
    data_dir = tmp_path / "data"
    write_stock_pool(data_dir)
    ResearchAgent(data_dir=data_dir).run(no_llm=True)
    prompt_path = next((data_dir / "pull_requests").glob("*.yaml"))
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
    ResearchAgent(data_dir=data_dir).run(no_llm=True)

    fengliu = FengliuTradingAgent(data_dir=data_dir).run(no_llm=True).output_files[0].read_text(encoding="utf-8")
    wanmu = WanmuTradingAgent(data_dir=data_dir).run(no_llm=True).output_files[0].read_text(encoding="utf-8")
    liguofei = LiguofeiTradingAgent(data_dir=data_dir).run(no_llm=True).output_files[0].read_text(encoding="utf-8")

    assert "fengliu_specific_framework" in fengliu
    assert "wanmu_rating" in wanmu
    assert "dual_gate_consistency" in liguofei


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
