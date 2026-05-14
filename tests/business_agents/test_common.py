from __future__ import annotations

import json

import pytest

from business_agents._common.methodology_loader import MethodologyLoader
from business_agents._common.output_validator import (
    OutputValidationError,
    OutputValidator,
    validate_research_agent_output,
    validate_trading_recommendation_output,
)
from business_agents._common.stock_pool import StockPool
from business_agents.research_agent.agent import ResearchAgent
from tests.conftest import QuietMarketClient, TriggerMarketClient, make_fengliu, write_stock_pool


def test_methodology_loader():
    prompt = MethodologyLoader(".").load("research_system_event_bayesian")
    assert "4.1 研究体系" in prompt
    assert "你的工作约束" in prompt
    assert "公开价量" in prompt
    assert "research_signals" in prompt


def test_user_prompt_renders_with_market_data(tmp_path):
    data_dir = tmp_path / "data"
    write_stock_pool(data_dir)
    prompt = ResearchAgent(data_dir=data_dir).render_user_prompt(StockPool.load(data_dir), "scan")
    assert "股池" in prompt
    assert "最近 7 天市场变化" in prompt


def test_valid_llm_output_passes_validation(tmp_path):
    data_dir = tmp_path / "data"
    write_stock_pool(data_dir)
    payload = ResearchAgent(data_dir=data_dir, market_client=TriggerMarketClient()).build_debug_payload(
        StockPool.load(data_dir)
    )
    result = validate_research_agent_output(payload, StockPool.load(data_dir))
    assert len(result.research_signals) == 2


def test_no_trigger_scan_does_not_emit_fake_signal(tmp_path):
    data_dir = tmp_path / "data"
    write_stock_pool(data_dir)
    payload = ResearchAgent(data_dir=data_dir, market_client=QuietMarketClient()).build_debug_payload(
        StockPool.load(data_dir)
    )
    result = validate_research_agent_output(payload, StockPool.load(data_dir))
    assert result.research_signals == []
    assert payload["run_summary"]["signals_generated"] == 0


def test_invalid_json_triggers_retry():
    validator = OutputValidator(max_retries=2)
    outputs = iter(["not-json", json.dumps({"ok": True})])

    result = validator.validate_with_retry(
        lambda: next(outputs),
        lambda value: json.loads(value),
        lambda errors: json.dumps({"fallback": errors}),
    )

    assert result == {"ok": True}
    assert validator.attempts == 2


def test_missing_field_triggers_retry(tmp_path):
    data_dir = tmp_path / "data"
    write_stock_pool(data_dir)
    stock_pool = StockPool.load(data_dir)
    valid = ResearchAgent(data_dir=data_dir, market_client=TriggerMarketClient()).build_debug_payload(stock_pool)
    outputs = iter([{"research_signals": []}, valid])
    validator = OutputValidator(max_retries=2)

    result = validator.validate_with_retry(
        lambda: next(outputs),
        lambda value: validate_research_agent_output(value, stock_pool),
        lambda errors: valid,
    )

    assert result.research_signals
    assert validator.attempts == 2


def test_max_retries_falls_back_to_abstain(tmp_path):
    data_dir = tmp_path / "data"
    write_stock_pool(data_dir)
    stock_pool = StockPool.load(data_dir)
    fallback = make_fengliu("abstain", ticker="0700.HK", market="HK", abstain_reason="insufficient_data").model_dump(mode="json")
    validator = OutputValidator(max_retries=1)

    result = validator.validate_with_retry(
        lambda: {"bad": "payload"},
        lambda value: validate_trading_recommendation_output(value, agent_id="fengliu_reverse_odds", stock_pool=stock_pool),
        lambda errors: {"recommendation": fallback},
    )

    assert result.direction.value == "abstain"


def test_only_stock_pool_tickers_allowed(tmp_path):
    data_dir = tmp_path / "data"
    write_stock_pool(data_dir)
    stock_pool = StockPool.load(data_dir)
    payload = ResearchAgent(data_dir=data_dir, market_client=TriggerMarketClient()).build_debug_payload(stock_pool)
    payload["research_signals"][0]["candidate_targets"][0]["ticker"] = "OUTSIDE"

    with pytest.raises(OutputValidationError):
        validate_research_agent_output(payload, stock_pool)


def test_a_share_ticker_blocked(tmp_path):
    data_dir = tmp_path / "data"
    write_stock_pool(data_dir)
    stock_pool = StockPool.load(data_dir)
    payload = ResearchAgent(data_dir=data_dir, market_client=TriggerMarketClient()).build_debug_payload(stock_pool)
    payload["research_signals"][0]["candidate_targets"][0]["ticker"] = "600519.SH"
    payload["research_signals"][0]["candidate_targets"][0]["market"] = "A"

    with pytest.raises(OutputValidationError):
        validate_research_agent_output(payload, stock_pool)


def test_watchlist_ticker_only_watch_or_abstain(tmp_path):
    data_dir = tmp_path / "data"
    write_stock_pool(data_dir)
    stock_pool = StockPool.load(data_dir)
    rec = make_fengliu("long", ticker="3690.HK", market="HK").model_dump(mode="json")

    with pytest.raises(OutputValidationError):
        validate_trading_recommendation_output({"recommendation": rec}, agent_id="fengliu_reverse_odds", stock_pool=stock_pool)


def test_any_failure_must_abstain_enforced(tmp_path):
    data_dir = tmp_path / "data"
    write_stock_pool(data_dir)
    stock_pool = StockPool.load(data_dir)
    rec = make_fengliu("long", ticker="0700.HK", market="HK").model_dump(mode="json")
    rec["deployment_compliance"]["any_failure_must_abstain"] = True

    with pytest.raises(OutputValidationError):
        validate_trading_recommendation_output({"recommendation": rec}, agent_id="fengliu_reverse_odds", stock_pool=stock_pool)


def test_research_agent_routing_recommendation_required(tmp_path):
    data_dir = tmp_path / "data"
    write_stock_pool(data_dir)
    stock_pool = StockPool.load(data_dir)
    payload = ResearchAgent(data_dir=data_dir, market_client=TriggerMarketClient()).build_debug_payload(stock_pool)
    payload["research_signals"][0]["routing_recommendation"] = {}

    with pytest.raises(OutputValidationError):
        validate_research_agent_output(payload, stock_pool)
