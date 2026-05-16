from __future__ import annotations

import sqlite3
from pathlib import Path

import yaml

from business_agents._common.knowledge_store import (
    build_research_planning_context,
    filter_entries_by_days,
    get_recent_knowledge_context,
    ingest_filled_result,
    rebuild_knowledge_store,
)
from business_agents.research_agent.agent import ResearchAgent
from tests.conftest import TriggerMarketClient, write_stock_pool


def write_prompt_and_result(data_dir: Path, prompt_id: str = "PR-20260514-BABA") -> None:
    pull_dir = data_dir / "pull_requests"
    result_dir = data_dir / "perplexity_results"
    pull_dir.mkdir(parents=True)
    result_dir.mkdir(parents=True)
    prompt_text = """请研究 BABA Alibaba ADR 最近 7-10 个交易日公开价量异动背后的真实原因。
触发规则：
- single_day_move_ge_7pct: 8.1837 (2026-05-13)
输出请包含来源链接、结论可信度、反证和仍未验证的地方。
"""
    (pull_dir / f"{prompt_id}.yaml").write_text(
        yaml.safe_dump(
            {
                "prompt_id": prompt_id,
                "related_signal_id": "RS-20260514-BABA",
                "priority": "P1",
                "prompt_text": prompt_text,
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (result_dir / f"{prompt_id}_filled.yaml").write_text(
        yaml.safe_dump(
            {
                "prompt_id": prompt_id,
                "related_signal_id": "RS-20260514-BABA",
                "status": "filled",
                "source": "perplexity",
                "filled_at": "2026-05-14T13:05:08",
                "prompt_text": prompt_text,
                "answer_text": """# BABA 异动深度研究

## 执行摘要

2026年5月13日 BABA 单日大涨 8.18%，成交量显著放大。结论可信度：高。核心催化剂为：①云/AI 数据超预期；②中美关系边际改善；③年度股息上调。

## 反证与风险提示

- 盈利端严重低于预期，调整后 EBITA 大幅下降。
- 自由现金流为净流出。

## 仍未验证的信息

1. 机构资金流向需要等待 13F。
2. 期权市场是否存在 Gamma 挤压尚无法确认。

## 已关闭问题

- 本次异动不是单纯指数调仓导致。

## 历史冲突

- 2025 年同类云业务乐观叙事后来被利润率下滑证伪。
""",
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def test_ingest_filled_result_writes_sqlite_and_card(tmp_path):
    data_dir = tmp_path / "data"
    write_prompt_and_result(data_dir)

    entry = ingest_filled_result(data_dir, "PR-20260514-BABA")

    assert entry is not None
    assert entry.entry_id == "KE-20260514-BABA"
    assert entry.source_pr_id == "PR-20260514-BABA"
    assert entry.stock_code == "BABA"
    assert entry.ticker == "BABA"
    assert any("云/AI 数据超预期" in item for item in entry.company_conclusions)
    assert "机构资金流向需要等待 13F" in entry.open_questions[0]
    assert entry.expires_at == "2026-08-11"
    assert "本次异动不是单纯指数调仓导致" in entry.closed_questions[0]
    assert "利润率下滑证伪" in entry.historical_conflicts[0]
    assert entry.evidence_quality["open_question_count"] == 2

    db_path = data_dir / "knowledge_store" / "knowledge.db"
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT stock_code, event_date, expires_at FROM knowledge_entries WHERE prompt_id = ?",
            ("PR-20260514-BABA",),
        ).fetchone()
    assert row == ("BABA", "2026-05-13", "2026-08-11")

    card = data_dir / "knowledge_store" / "cards" / "BABA.md"
    content = card.read_text(encoding="utf-8")
    assert "BABA Knowledge Card" in content
    assert "未关闭问题" in content


def test_recent_knowledge_context_is_prompt_ready_yaml(tmp_path):
    data_dir = tmp_path / "data"
    write_prompt_and_result(data_dir)
    rebuild_knowledge_store(data_dir, reset=True)

    context = get_recent_knowledge_context(data_dir, "BABA", as_of_date="2026-05-14")

    assert "historical_investment_knowledge" in context
    assert "same_ticker_window_days: 90" in context
    assert "max_entries: 3" in context
    assert "PR-20260514-BABA" in context
    assert "Gamma 挤压" in context


def test_knowledge_window_does_not_include_future_entries():
    entries = [
        {"prompt_id": "PR-20260514-BABA", "event_date": "2026-05-14", "expires_at": "2026-08-12"},
        {"prompt_id": "PR-20260515-BABA", "event_date": "2026-05-15", "expires_at": "2026-08-13"},
    ]

    filtered = filter_entries_by_days(entries, as_of_date="2026-05-14", days=90)

    assert [entry["prompt_id"] for entry in filtered] == ["PR-20260514-BABA"]


def test_research_planning_context_reopens_history_gaps(tmp_path):
    data_dir = tmp_path / "data"
    write_prompt_and_result(data_dir)
    rebuild_knowledge_store(data_dir, reset=True)

    context = build_research_planning_context(
        data_dir,
        "BABA",
        as_of_date="2026-05-15",
        signal_fingerprint={"trigger_rules": ["single_day_move_ge_7pct"], "tags": ["k_deep"]},
    )

    assert context["history_found"] is True
    assert any("13F" in item for item in context["open_questions"])
    assert any("已回答事实" in item for item in context["do_not_repeat"])
    assert any("历史冲突" in item for item in context["questions_to_refresh"])


def test_research_planning_context_reports_pending_cold_start_prompts(tmp_path):
    data_dir = tmp_path / "data"
    pull_dir = data_dir / "pull_requests"
    pull_dir.mkdir(parents=True)
    (pull_dir / "PR-20260516-BABA-COLDSTART-1.yaml").write_text(
        yaml.safe_dump(
            {
                "prompt_id": "PR-20260516-BABA-COLDSTART-1",
                "related_signal_id": "RS-20260516-BABA",
                "status": "pending_cold_start",
                "cold_start": True,
                "ticker": "BABA",
                "research_dimension": "business_model",
                "research_dimension_label": "商业模式",
                "research_horizon": "12m",
                "priority_order": 1,
                "prompt_text": "请研究 BABA 过去 12 个月商业模式变化。",
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    context = build_research_planning_context(data_dir, "BABA", as_of_date="2026-05-16")

    assert context["history_found"] is False
    assert context["cold_start_pending"][0]["prompt_id"] == "PR-20260516-BABA-COLDSTART-1"
    assert any("置信度不得超过 50%" in item for item in context["prompt_directives"])


def test_research_agent_prompt_uses_history_before_new_questions(tmp_path):
    data_dir = tmp_path / "data"
    write_stock_pool(data_dir)
    write_prompt_and_result(data_dir)
    rebuild_knowledge_store(data_dir, reset=True)

    ResearchAgent(
        data_dir=data_dir,
        market_client=TriggerMarketClient(),
        run_date="2026-05-15",
    ).run(no_llm=True)

    prompt_data = yaml.safe_load((data_dir / "pull_requests" / "PR-20260515-BABA.yaml").read_text(encoding="utf-8"))
    signal_data = yaml.safe_load((data_dir / "research_signals" / "RS-20260515-BABA.yaml").read_text(encoding="utf-8"))

    assert "历史知识复用要求" in prompt_data["prompt_text"]
    assert "机构资金流向需要等待 13F" in prompt_data["prompt_text"]
    assert "非共识 Screener 要求" in prompt_data["prompt_text"]
    assert prompt_data["research_task_plan"]["k_deep_director_mode"] is True
    assert prompt_data["research_task_plan"]["non_consensus_screener"]["required_evidence"]
    assert prompt_data["research_task_plan"]["memory_reuse_policy"]["must_reopen"]
    assert signal_data["research_signal"]["research_planning_context"]["history_found"] is True
