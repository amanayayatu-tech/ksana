"""Research Agent implementation."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from business_agents._common.base_agent import AgentRunResult, BaseBusinessAgent, write_yaml
from business_agents._common.llm_client import LLMClient
from business_agents._common.knowledge_store import build_research_planning_context
from business_agents._common.market_data.yfinance_client import YFinanceClient
from business_agents._common.methodology_loader import MethodologyLoader
from business_agents._common.output_validator import (
    OutputValidationError,
    validate_research_agent_output,
)
from business_agents._common.stock_pool import StockPool
from business_agents.research_agent.methodology_profile import (
    RESEARCH_SYSTEM_FRAMEWORK_ID,
    RESEARCH_SYSTEM_HARD_RULES,
    RESEARCH_SYSTEM_METHODOLOGY_ID,
    RESEARCH_SYSTEM_SOURCE_FILE,
    RESEARCH_SYSTEM_VERSION,
    SELF_CRITIQUE_HOOKS,
    build_gate_question_groups,
    build_methodology_profile_snapshot,
)


class ResearchAgent(BaseBusinessAgent):
    """K deep research upstream agent."""

    agent_name = "research_agent"
    methodology_id = "k_deep"

    def __init__(
        self,
        data_dir: str | Path = "data",
        project_root: str | Path = ".",
        llm_client: LLMClient | None = None,
        market_client: YFinanceClient | None = None,
        run_date: str | None = None,
    ) -> None:
        super().__init__(data_dir, project_root)
        self.llm_client = llm_client
        self.market_client = market_client or YFinanceClient()
        self.run_date = normalize_run_date(run_date)
        self.compact_run_date = self.run_date.replace("-", "")
        self.env = Environment(
            loader=FileSystemLoader(str(Path(__file__).with_name("prompts"))),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def run(self, trigger_type: str = "scheduled", no_llm: bool = False) -> AgentRunResult:
        """Run deterministic public price/volume scan and write local artifacts."""

        stock_pool = StockPool.load(self.data_dir)
        system_prompt = MethodologyLoader(self.project_root).load(self.methodology_id)
        user_prompt = self.render_user_prompt(stock_pool, trigger_type)
        llm_messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]
        llm_used = False
        _ = no_llm

        payload = self.build_scan_payload(stock_pool)
        try:
            result = validate_research_agent_output(payload, stock_pool)
        except OutputValidationError as exc:
            self._write_error(str(exc), payload)
            raise

        output_files = self.write_outputs(result.model_dump(mode="json"))
        if payload.get("run_summary"):
            output_files.append(
                write_yaml(
                    self.data_dir / "research_runs" / f"RESEARCH-{self.run_id}.yaml",
                    {"research_run": payload["run_summary"]},
                )
            )
        self.log_run(
            {
                "run_id": self.run_id,
                "agent": self.agent_name,
                "llm_used": llm_used,
                "scan_mode": "public_price_volume",
                "signals_generated": len(result.research_signals),
                "prompts_generated": len(result.perplexity_prompt_brief.prompts),
                "output_files": [str(path) for path in output_files],
            },
            llm_messages,
        )
        return AgentRunResult(run_id=self.run_id, output_files=output_files, llm_used=llm_used)

    def render_user_prompt(self, stock_pool: StockPool, trigger_type: str) -> str:
        recent_market_data = self._recent_market_data(stock_pool)
        return self.env.get_template("scan_user_prompt.j2").render(
            now_hkt=datetime.now().astimezone().isoformat(),
            trigger_type=trigger_type,
            stock_pool_yaml=stock_pool.to_prompt_dict(),
            recent_market_data_yaml=recent_market_data,
            recent_signal_ids=self._recent_signal_ids(),
        )

    def build_debug_payload(self, stock_pool: StockPool) -> dict[str, Any]:
        """Backward-compatible alias for the deterministic trial scan."""

        return self.build_scan_payload(stock_pool)

    def build_scan_payload(self, stock_pool: StockPool) -> dict[str, Any]:
        """Scan every HK/US main-pool ticker and emit only rule-triggered signals."""

        today = self.compact_run_date
        emitted_at = datetime.now().astimezone().isoformat()
        signals: list[dict[str, Any]] = []
        prompts: list[dict[str, Any]] = []
        no_signal_tickers: list[str] = []
        data_failures: list[dict[str, Any]] = []
        scanned_tickers: list[str] = []

        entries = [
            entry
            for entry in stock_pool.entries
            if entry.bucket == "main" and entry.market in {"HK", "US"}
        ]

        for entry in entries:
            scanned_tickers.append(entry.ticker)
            history = self.market_client.get_history(entry.ticker, period="1mo")
            features = build_price_volume_features(entry.ticker, history)
            if not features["data_sufficient"]:
                data_failures.append(
                    {
                        "ticker": entry.ticker,
                        "market": entry.market,
                        "reason": "public_price_volume_history_insufficient",
                        "rows_returned": len(history),
                        "source_url": f"https://finance.yahoo.com/quote/{entry.ticker}",
                    }
                )
                no_signal_tickers.append(entry.ticker)
                continue

            triggers = evaluate_triggers(features)
            if not triggers:
                no_signal_tickers.append(entry.ticker)
                continue

            target_key = sanitize_identifier(entry.ticker)
            signal_id = f"RS-{today}-{target_key}"
            prompt_id = f"PR-{today}-{target_key}" if len(prompts) < 30 else None
            data_points = build_signal_data_points(features, triggers)
            signal_fingerprint = build_signal_fingerprint(entry.ticker, entry.market, triggers, features)
            research_planning_context = build_research_planning_context(
                self.data_dir,
                entry.ticker,
                as_of_date=self.run_date,
                signal_fingerprint=signal_fingerprint,
            )
            research_task_plan = build_research_task_plan(
                entry.ticker,
                entry.name,
                triggers,
                features,
                signal_fingerprint,
                research_planning_context,
            )
            k_deep_question_set = build_k_deep_research_question_set(
                entry.ticker,
                entry.name,
                triggers,
                features,
                research_planning_context=research_planning_context,
                research_task_plan=research_task_plan,
            )
            methodology_profile = k_deep_question_set["methodology_profile"]
            signal = {
                "research_signal_id": signal_id,
                "emitted_at": emitted_at,
                "emitter": "K deep_research_system",
                "signal_status": "active",
                "signal_type": infer_signal_type(triggers),
                "research_stage": "daily_scan",
                "signal_summary": build_signal_summary(entry.ticker, entry.name, triggers, features),
                "candidate_targets": [
                    {
                        "ticker": entry.ticker,
                        "market": entry.market,
                        "company_name": entry.name,
                        "relevance_score": min(95, 55 + len(triggers) * 8),
                        "role": "primary",
                    }
                ],
                "research_object": {
                    "primary": "company",
                    "secondary": [
                        "public_price_volume",
                        "k_deep_question_framework",
                    ],
                    "why_this_object": "来自 Nepha HK/US 主股池，触发公开价量规则；K deep 负责把异动升级为商业、产业、竞争和资本市场问题。",
                },
                "k_deep_research_questions": k_deep_question_set,
                "research_methodology_profile": methodology_profile,
                "signal_fingerprint": signal_fingerprint,
                "research_planning_context": research_planning_context,
                "research_task_plan": research_task_plan,
                "event_input": {
                    "event_name": "public_price_volume_anomaly",
                    "event_date": features["latest_date"],
                    "event_level": "company",
                    "event_size": infer_event_size(triggers),
                    "expected_bayesian_impact": "needs_manual_causal_research",
                    "is_market_aware": True,
                },
                "discontinuity_assessment": {
                    "type": "price_volume_discontinuity",
                    "why_now": "近 7-10 个交易日出现规则化价量异动。",
                    "triggered_rules": triggers,
                    "evidence": data_points,
                    "counter_evidence": [],
                    "confidence": confidence_from_triggers(triggers),
                    "evidence_unverified": True,
                },
                "bayesian_update": {
                    "market_prior_probability": None,
                    "my_prior_probability": None,
                    "assumed_true_base_rate": None,
                    "event_input_summary": build_event_input_summary(features),
                    "posterior_probability": None,
                    "posterior_minus_market_prior": None,
                    "confidence": confidence_from_triggers(triggers),
                    "evidence": data_points,
                    "evidence_unverified": True,
                },
                "beta_attribution": {
                    "expected_return_decomposition": {
                        "single_stock_component": features["ten_day_change_pct"],
                        "volume_anomaly_ratio": features["max_volume_ratio"],
                    },
                    "beta_linked": False,
                    "alpha_clarity": "needs_manual_research",
                },
                "routing_recommendation": {
                    "suggested_for": [
                        "f_partner",
                        "w_partner",
                        "g_partner",
                    ],
                    "routing_reason": "公开价量异动只做初筛，需三位交易 Agent 保守评估。",
                    "not_suitable_for": [],
                    "not_suitable_reason": None,
                    "expected_disagreement": ["证据未验证", "方法论阈值可能不通过"],
                },
                "upstream_to_trading_agents": {
                    "chairman_route_id": f"ROUTE-{today}-{target_key}",
                    "downstream_agents_notified": [
                        "f_partner",
                        "w_partner",
                        "g_partner",
                    ],
                    "notification_status": "pending",
                    "delivery_notes": "file-system handoff",
                },
                "perplexity_research": {
                    "prompts_requested": [prompt_id] if prompt_id else [],
                    "prompts_filled_back": [],
                    "prompts_skipped_by_nepha": [],
                    "prompts_pending": [prompt_id] if prompt_id else [],
                    "results_summary": None,
                    "confidence_after_research": None,
                    "coverage_ratio": 0,
                },
                "red_team_questions": [
                    "价量异动是否集中依赖单一公开数据源？",
                    "是否缺少真实事件原因解释？",
                    "Perplexity 是否验证了商业模式、竞争格局或预期差的真实变化，而不只是复述当天新闻？",
                    "是否存在历史研究中尚未关闭的问题与本次乐观/悲观解释冲突？",
                ],
                "falsification_points": [
                    "如果 Perplexity 回填显示异动仅来自指数或技术性成交，则不进入交易判断。",
                    "如果数据源错误或复权异常，则该信号 invalidated。",
                    "如果核心催化剂无法改变收入、利润率、竞争地位、监管路径或市场预期，则仅保留 watch。",
                ],
                "signal_kill_criteria": [
                    "公开价量数据无法复核。",
                    "没有任何事件原因或基本面变化证据。",
                ],
                "data_points": data_points,
                "downstream_responses": [],
            }
            signals.append(signal)
            if prompt_id:
                prompts.append(
                    {
                        "prompt_id": prompt_id,
                        "related_signal_id": signal_id,
                        "priority": "P1",
                        "research_question_set": k_deep_question_set,
                        "research_task_plan": research_task_plan,
                        "research_planning_context": research_planning_context,
                        "prompt_text": build_perplexity_prompt(
                            entry.ticker,
                            entry.name,
                            triggers,
                            features,
                            k_deep_question_set,
                            research_planning_context,
                            research_task_plan,
                        ),
                    }
                )

        return {
            "research_signals": signals,
            "perplexity_prompt_brief": {
                "brief_id": f"PRBRIEF-{today}-001",
                "prompts": prompts,
            },
            "run_summary": {
                "run_id": self.run_id,
                "agent": self.agent_name,
                "scan_mode": "trial_public_price_volume",
                "trial_policy": {
                    "long_disabled": True,
                    "allowed_directions": ["watch", "avoid", "abstain"],
                    "data_sources": ["Yahoo Finance public chart endpoint"],
                    "perplexity": "manual_fill_only",
                },
                "emitted_at": emitted_at,
                "tickers_scanned": scanned_tickers,
                "reference_only_tickers_skipped": sorted(stock_pool.a_share_tickers()),
                "signals_generated": len(signals),
                "no_signal_tickers": no_signal_tickers,
                "data_failures": data_failures,
                "perplexity_prompts_generated": len(prompts),
            },
        }

    def write_outputs(self, payload: dict[str, Any]) -> list[Path]:
        output_files: list[Path] = []
        for signal in payload["research_signals"]:
            output_files.append(
                write_yaml(
                    self.data_dir / "research_signals" / f"{signal['research_signal_id']}.yaml",
                    {"research_signal": signal},
                )
            )
        for prompt in payload["perplexity_prompt_brief"]["prompts"]:
            output_files.append(
                write_yaml(self.data_dir / "pull_requests" / f"{prompt['prompt_id']}.yaml", prompt)
            )
        return output_files

    def _recent_market_data(self, stock_pool: StockPool) -> list[dict[str, Any]]:
        movers = []
        for entry in list(stock_pool.entries)[:20]:
            if entry.market in {"HK", "US"}:
                quote = self.market_client.get_quote(entry.ticker)
                movers.append(
                    {
                        "ticker": entry.ticker,
                        "price": quote.price,
                        "source_url": quote.source_url,
                        "evidence_unverified": quote.evidence_unverified,
                    }
                )
        return movers

    def _recent_signal_ids(self) -> list[str]:
        return [path.stem for path in sorted((self.data_dir / "research_signals").glob("RS-*.yaml"))[-10:]]

    def _write_error(self, message: str, payload: dict[str, Any]) -> None:
        path = self.data_dir / "errors" / f"{self.run_id}.json"
        write_yaml(path, {"error": message, "payload": payload})


def build_price_volume_features(ticker: str, history: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [row for row in history if row.get("close") is not None]
    recent = rows[-10:]
    volumes_20d = [float(row.get("volume") or 0) for row in rows[-20:] if row.get("volume")]
    volume_20d_average = round(sum(volumes_20d) / len(volumes_20d), 2) if volumes_20d else 0.0
    for row in recent:
        volume = float(row.get("volume") or 0)
        row["volume_20d_average"] = volume_20d_average
        row["volume_ratio"] = round(volume / volume_20d_average, 4) if volume_20d_average else None

    latest = recent[-1] if recent else {}
    first = recent[0] if recent else {}
    ten_day_change_pct = (
        round((float(latest["close"]) - float(first["close"])) / float(first["close"]) * 100, 4)
        if latest.get("close") is not None and first.get("close")
        else None
    )
    return {
        "ticker": ticker,
        "data_sufficient": len(recent) >= 6,
        "recent_rows": recent,
        "latest_date": latest.get("date"),
        "latest_close": latest.get("close"),
        "volume_20d_average": volume_20d_average,
        "max_volume_ratio": max(
            [float(row["volume_ratio"]) for row in recent if row.get("volume_ratio") is not None],
            default=None,
        ),
        "max_abs_change_row": max(
            [row for row in recent if row.get("change_pct") is not None],
            key=lambda row: abs(float(row["change_pct"])),
            default={},
        ),
        "max_abs_gap_row": max(
            [row for row in recent if row.get("gap_pct") is not None],
            key=lambda row: abs(float(row["gap_pct"])),
            default={},
        ),
        "trailing_up": trailing_streak(recent, positive=True),
        "trailing_down": trailing_streak(recent, positive=False),
        "five_day_change_pct": period_change(recent[-6:]) if len(recent) >= 6 else None,
        "ten_day_change_pct": ten_day_change_pct,
    }


def evaluate_triggers(features: dict[str, Any]) -> list[dict[str, Any]]:
    triggers: list[dict[str, Any]] = []
    move_row = features.get("max_abs_change_row") or {}
    move = move_row.get("change_pct")
    if move is not None and abs(float(move)) >= 7:
        triggers.append(
            {
                "rule": "single_day_move_ge_7pct",
                "value": round(float(move), 4),
                "date": move_row.get("date"),
                "source_url": move_row.get("source_url"),
            }
        )

    gap_row = features.get("max_abs_gap_row") or {}
    gap = gap_row.get("gap_pct")
    if gap is not None and abs(float(gap)) >= 4:
        triggers.append(
            {
                "rule": "opening_gap_ge_4pct",
                "value": round(float(gap), 4),
                "date": gap_row.get("date"),
                "source_url": gap_row.get("source_url"),
            }
        )

    max_volume_ratio = features.get("max_volume_ratio")
    if max_volume_ratio is not None and float(max_volume_ratio) >= 2:
        volume_row = max(
            [row for row in features["recent_rows"] if row.get("volume_ratio") is not None],
            key=lambda row: float(row["volume_ratio"]),
            default={},
        )
        if abs(float(volume_row.get("change_pct") or 0)) >= 3:
            triggers.append(
                {
                    "rule": "volume_ratio_ge_2x_with_price_move",
                    "value": round(float(max_volume_ratio), 4),
                    "date": volume_row.get("date"),
                    "source_url": volume_row.get("source_url"),
                }
            )

    if features["trailing_up"]["days"] >= 3 and features["trailing_up"]["cumulative_change_pct"] >= 8:
        triggers.append({"rule": "three_day_consecutive_up", **features["trailing_up"]})
    if features["trailing_down"]["days"] >= 3 and features["trailing_down"]["cumulative_change_pct"] <= -8:
        triggers.append({"rule": "three_day_consecutive_down", **features["trailing_down"]})

    five_day_change = features.get("five_day_change_pct")
    if five_day_change is not None and abs(float(five_day_change)) >= 10:
        triggers.append(
            {
                "rule": "five_day_move_ge_10pct",
                "value": round(float(five_day_change), 4),
                "date": features.get("latest_date"),
                "source_url": f"https://finance.yahoo.com/quote/{features['ticker']}",
            }
        )
    return triggers


def build_signal_data_points(features: dict[str, Any], triggers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    data_points = []
    latest = features["recent_rows"][-1]
    data_points.append(
        {
            "label": "latest_public_price_volume",
            "value": {
                "close": latest.get("close"),
                "change_pct": latest.get("change_pct"),
                "volume": latest.get("volume"),
                "volume_ratio": latest.get("volume_ratio"),
            },
            "date": latest.get("date"),
            "source_url": latest.get("source_url"),
            "evidence_unverified": False,
        }
    )
    for trigger in triggers:
        data_points.append(
            {
                "label": f"trigger:{trigger['rule']}",
                "value": trigger.get("value") or trigger,
                "date": trigger.get("date") or latest.get("date"),
                "source_url": trigger.get("source_url") or latest.get("source_url"),
                "evidence_unverified": False,
            }
        )
    return data_points


def trailing_streak(rows: list[dict[str, Any]], *, positive: bool) -> dict[str, Any]:
    selected: list[dict[str, Any]] = []
    for row in reversed(rows):
        change = row.get("change_pct")
        if change is None:
            break
        value = float(change)
        if (positive and value > 0) or (not positive and value < 0):
            selected.append(row)
        else:
            break
    ordered = list(reversed(selected))
    return {
        "days": len(ordered),
        "cumulative_change_pct": period_change(ordered),
        "date": ordered[-1].get("date") if ordered else None,
        "source_url": ordered[-1].get("source_url") if ordered else None,
    }


def period_change(rows: list[dict[str, Any]]) -> float | None:
    if len(rows) < 2:
        return 0.0 if rows else None
    start = rows[0].get("close")
    end = rows[-1].get("close")
    if not start or end is None:
        return None
    return round((float(end) - float(start)) / float(start) * 100, 4)


def infer_signal_type(triggers: list[dict[str, Any]]) -> str:
    rules = {trigger["rule"] for trigger in triggers}
    if "opening_gap_ge_4pct" in rules or "volume_ratio_ge_2x_with_price_move" in rules:
        return "discontinuity"
    if "five_day_move_ge_10pct" in rules:
        return "bayesian_shift"
    return "event"


def infer_event_size(triggers: list[dict[str, Any]]) -> str:
    if len(triggers) >= 3:
        return "large"
    if len(triggers) == 2:
        return "medium"
    return "small"


def confidence_from_triggers(triggers: list[dict[str, Any]]) -> int:
    score = 45 + len(triggers) * 6
    if any(trigger["rule"] == "volume_ratio_ge_2x_with_price_move" for trigger in triggers):
        score += 8
    return min(score, 70)


def build_signal_summary(
    ticker: str,
    name: str,
    triggers: list[dict[str, Any]],
    features: dict[str, Any],
) -> str:
    trigger_text = "、".join(trigger["rule"] for trigger in triggers)
    display_name = f"{ticker}（{name}）" if name else ticker
    return (
        f"{display_name} 在近 7-10 个交易日触发公开价量初筛规则：{trigger_text}；"
        f"最新收盘 {features.get('latest_close')}，10 日变化 {features.get('ten_day_change_pct')}%。"
    )


def build_event_input_summary(features: dict[str, Any]) -> str:
    return (
        f"latest_close={features.get('latest_close')}, "
        f"five_day_change_pct={features.get('five_day_change_pct')}, "
        f"ten_day_change_pct={features.get('ten_day_change_pct')}, "
        f"max_volume_ratio={features.get('max_volume_ratio')}"
    )


def build_perplexity_prompt(
    ticker: str,
    name: str,
    triggers: list[dict[str, Any]],
    features: dict[str, Any],
    k_deep_question_set: dict[str, Any] | None = None,
    research_planning_context: dict[str, Any] | None = None,
    research_task_plan: dict[str, Any] | None = None,
) -> str:
    trigger_lines = "\n".join(
        f"- {trigger['rule']}: {trigger.get('value')} ({trigger.get('date')})"
        for trigger in triggers
    )
    display_name = f"{ticker} {name}".strip()
    planning_context = research_planning_context or {}
    task_plan = research_task_plan or {}
    question_set = k_deep_question_set or build_k_deep_research_question_set(
        ticker,
        name,
        triggers,
        features,
        research_planning_context=planning_context,
        research_task_plan=task_plan,
    )
    if not task_plan:
        task_plan = question_set.get("research_task_plan") or {}
    if not planning_context:
        planning_context = question_set.get("research_planning_context") or {}
    question_lines = render_k_deep_questions_for_prompt(question_set)
    reuse_lines = render_research_planning_context_for_prompt(planning_context)
    task_lines = render_research_task_plan_for_prompt(task_plan)
    return (
        f"请作为 Worldpay77 的首席研究员，研究 {display_name} 最近 7-10 个交易日公开价量异动背后的真实原因。\n\n"
        "研究边界：只判断是否存在新闻、财报、监管、行业、竞争、资金面、指数或预期差层面的可验证原因；不要给交易建议，不要输出买卖操作。\n\n"
        f"触发规则：\n{trigger_lines}\n\n"
        f"最新收盘：{features.get('latest_close')}；"
        f"5 日变化：{features.get('five_day_change_pct')}%；"
        f"10 日变化：{features.get('ten_day_change_pct')}%。\n\n"
        "请不要只解释“为什么涨跌”。价量只是触发器，你的核心任务是基于 K deep 框架做研究任务编排：先复用历史知识，再判断这次异动是否触及商业模式、产业结构、竞争格局、管理层动作、监管环境或资本市场预期差的真实变化。\n\n"
        "## 历史知识复用要求\n\n"
        f"{reuse_lines}\n\n"
        "## 本次研究任务编排\n\n"
        f"{task_lines}\n\n"
        "## K deep 研究问题组\n\n"
        f"{question_lines}\n\n"
        "## 输出结构要求\n\n"
        "1. 结论摘要：本次异动最可能由哪些可验证因素驱动，并给出总体可信度。\n"
        "2. 证据链：按“财报/公司事件、行业、竞争、监管、资金面、指数、宏观”分类列证据，每条必须带来源链接。\n"
        "3. K deep 关键判断：回答商业模式、竞争格局、渗透率/成本曲线、管理层/资本配置、市场预期差是否发生变化。\n"
        "4. 反证：列出最能推翻主结论的公开证据或不一致数据。\n"
        "5. 仍未验证：列出后续需要继续跟踪的 5-10 个问题，尤其是机构资金、期权、监管落地、财报后分析师调整和竞争对手动作。\n"
        "6. 可沉淀记忆：最后单独给出“可进入知识库的结构化要点”，包括事件摘要、主要催化剂、反证、未关闭问题和可信度。\n"
    )


def build_research_task_plan(
    ticker: str,
    name: str,
    triggers: list[dict[str, Any]],
    features: dict[str, Any],
    signal_fingerprint: dict[str, Any],
    planning_context: dict[str, Any],
) -> dict[str, Any]:
    """Plan K deep-style research work before asking Perplexity new questions."""

    display_name = f"{ticker} {name}".strip()
    open_questions = planning_context.get("open_questions", []) or []
    do_not_repeat = planning_context.get("do_not_repeat", []) or []
    similar_cases = planning_context.get("similar_cases", []) or []
    focus_tracks = [
        "reuse_existing_knowledge",
        "refresh_unresolved_questions" if open_questions else "establish_first_stock_memory",
        "new_event_causality",
        "beta_vs_alpha_attribution",
        "falsification_and_counter_evidence",
    ]
    if similar_cases:
        focus_tracks.append("historical_analogy_check")
    if planning_context.get("historical_conflicts"):
        focus_tracks.append("historical_conflict_resolution")
    priority_questions = list(planning_context.get("questions_to_refresh") or [])
    priority_questions.extend(
        [
            f"{display_name} 本次价量触发是否改变历史结论，还是只是旧 thesis 的短期噪音？",
            "这次异动的主因是公司 alpha、行业 beta、宏观 beta、资金面，还是指数/期权结构？",
            "哪些公开证据最能推翻主因判断，未来 7/30/90 天如何跟踪？",
        ]
    )
    return {
        "plan_version": "research_task_plan_v1",
        "ticker": ticker,
        "trigger_layer": {
            "source": "public_price_volume",
            "trigger_rules": [trigger["rule"] for trigger in triggers],
            "latest_close": features.get("latest_close"),
            "five_day_change_pct": features.get("five_day_change_pct"),
            "ten_day_change_pct": features.get("ten_day_change_pct"),
            "fingerprint": signal_fingerprint,
        },
        "k_deep_director_mode": True,
        "focus_tracks": unique_preserve_order(focus_tracks),
        "memory_reuse_policy": {
            "history_found": bool(planning_context.get("history_found")),
            "do_not_repeat": do_not_repeat[:8],
            "must_reopen": open_questions[:8],
            "historical_conflicts": (planning_context.get("historical_conflicts") or [])[:6],
            "similar_case_prompt_ids": [
                case.get("prompt_id") for case in similar_cases[:5] if case.get("prompt_id")
            ],
        },
        "priority_questions": unique_preserve_order(priority_questions)[:10],
    }


def render_research_planning_context_for_prompt(context: dict[str, Any]) -> str:
    if not context or not context.get("history_found"):
        return (
            "- 知识库没有找到同标的可复用研究；本次报告必须建立第一份可沉淀股票档案。\n"
            "- 输出时请明确哪些事实已验证、哪些问题仍未关闭、哪些结论需要设置有效期。"
        )
    lines = ["- 已找到历史知识；请先复用，再提出新问题。"]
    lines.extend(render_prompt_list("已回答/已沉淀事实", context.get("answered_facts") or [], 5))
    lines.extend(render_prompt_list("不要重复研究", context.get("do_not_repeat") or [], 5))
    lines.extend(render_prompt_list("必须继续追问的未关闭问题", context.get("open_questions") or [], 6))
    lines.extend(render_prompt_list("历史冲突或反例", context.get("historical_conflicts") or [], 4))
    similar_cases = context.get("similar_cases") or []
    if similar_cases:
        lines.append("相似历史案例：")
        for case in similar_cases[:3]:
            lines.append(
                f"- {case.get('prompt_id')} / {case.get('stock_code')}: "
                f"{(case.get('event_summary') or case.get('company_conclusions') or ['未抽取摘要'])[0]}"
            )
    lines.extend(render_prompt_list("本次优先刷新", context.get("questions_to_refresh") or [], 6))
    return "\n".join(lines).strip()


def render_research_task_plan_for_prompt(plan: dict[str, Any]) -> str:
    if not plan:
        return "- 未生成 task plan；按 K deep Gate 1-7 完成研究。"
    lines = [
        f"- plan_version: {plan.get('plan_version')}",
        f"- k_deep_director_mode: {plan.get('k_deep_director_mode')}",
        f"- focus_tracks: {', '.join(plan.get('focus_tracks') or [])}",
    ]
    policy = plan.get("memory_reuse_policy") or {}
    if policy.get("similar_case_prompt_ids"):
        lines.append(f"- similar_case_prompt_ids: {', '.join(map(str, policy['similar_case_prompt_ids']))}")
    lines.extend(render_prompt_list("优先研究问题", plan.get("priority_questions") or [], 8))
    return "\n".join(lines).strip()


def render_prompt_list(title: str, items: list[Any], limit: int) -> list[str]:
    if not items:
        return []
    lines = [f"{title}："]
    lines.extend(f"- {item}" for item in items[:limit])
    return lines


def build_k_deep_research_question_set(
    ticker: str,
    name: str,
    triggers: list[dict[str, Any]],
    features: dict[str, Any],
    research_planning_context: dict[str, Any] | None = None,
    research_task_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build deterministic K deep questions from the frozen methodology profile."""

    display_name = f"{ticker} {name}".strip()
    trigger_names = [trigger["rule"] for trigger in triggers]
    trigger_rule_text = "、".join(trigger_names)
    event_date = features.get("latest_date") or next(
        (trigger.get("date") for trigger in triggers if trigger.get("date")),
        None,
    )
    profile_snapshot = build_methodology_profile_snapshot()
    question_context = {
        "ticker": ticker,
        "name": name,
        "display_name": display_name,
        "trigger_rule_text": trigger_rule_text,
        "event_date": event_date,
        "latest_close": features.get("latest_close"),
        "five_day_change_pct": features.get("five_day_change_pct"),
        "ten_day_change_pct": features.get("ten_day_change_pct"),
        "max_volume_ratio": features.get("max_volume_ratio"),
    }
    return {
        "framework": RESEARCH_SYSTEM_FRAMEWORK_ID,
        "methodology_id": RESEARCH_SYSTEM_METHODOLOGY_ID,
        "methodology_source": RESEARCH_SYSTEM_SOURCE_FILE,
        "methodology_version": RESEARCH_SYSTEM_VERSION,
        "ticker": ticker,
        "company_name": name,
        "event_date": event_date,
        "triggered_rules": trigger_names,
        "methodology_profile": profile_snapshot,
        "research_planning_context": research_planning_context or {},
        "research_task_plan": research_task_plan or {},
        "question_groups": build_gate_question_groups(question_context),
        "self_critique_hooks": list(SELF_CRITIQUE_HOOKS),
    }


def render_k_deep_questions_for_prompt(question_set: dict[str, Any]) -> str:
    profile = question_set.get("methodology_profile") or {}
    hard_rules = profile.get("hard_rules") or {}
    lines: list[str] = [
        "### 方法论来源",
        f"- methodology_id: {question_set.get('methodology_id')}",
        f"- methodology_source: {question_set.get('methodology_source')}",
        f"- methodology_version: {question_set.get('methodology_version')}",
        f"- perplexity_integration_mode: {hard_rules.get('perplexity_integration_mode')}",
        "- 边界：K deep 只做研究信号与问题生成，不给交易建议；Perplexity 由 Nepha 手动跑并回填。",
        "",
        "### K deep Gate 问题",
    ]
    for group in question_set.get("question_groups", []):
        gate_id = group.get("gate_id")
        title = f"{gate_id}: {group.get('label')}" if gate_id else str(group.get("label"))
        lines.append(f"#### {title}")
        check_items = group.get("check_items") or []
        if check_items:
            lines.append("检查项：")
            for item in check_items:
                lines.append(f"- {item}")
            lines.append("研究问题：")
        for question in group.get("questions", []):
            lines.append(f"- {question}")
        lines.append("")
    self_critique_hooks = question_set.get("self_critique_hooks") or []
    if self_critique_hooks:
        lines.append("### 自我质疑")
        for hook in self_critique_hooks:
            lines.append(f"- {hook}")
    return "\n".join(lines).strip()


def build_signal_fingerprint(
    ticker: str,
    market: str,
    triggers: list[dict[str, Any]],
    features: dict[str, Any],
) -> dict[str, Any]:
    """Build comparable tags for future historical-similarity retrieval."""

    trigger_rules = sorted({trigger["rule"] for trigger in triggers})
    ten_day_change = float(features.get("ten_day_change_pct") or 0)
    max_volume_ratio = float(features.get("max_volume_ratio") or 0)
    return {
        "fingerprint_version": "signal_fingerprint_v1",
        "methodology": {
            "methodology_id": RESEARCH_SYSTEM_METHODOLOGY_ID,
            "methodology_source": RESEARCH_SYSTEM_SOURCE_FILE,
            "methodology_version": RESEARCH_SYSTEM_VERSION,
            "perplexity_integration_mode": RESEARCH_SYSTEM_HARD_RULES["perplexity_integration_mode"],
        },
        "ticker": ticker,
        "market": market,
        "signal_type": infer_signal_type(triggers),
        "event_size": infer_event_size(triggers),
        "trigger_rules": trigger_rules,
        "price_direction": "up" if ten_day_change > 0 else "down" if ten_day_change < 0 else "flat",
        "price_move_bucket": bucket_abs_value(abs(ten_day_change), [(5, "small"), (10, "medium"), (20, "large")]),
        "volume_bucket": bucket_abs_value(max_volume_ratio, [(1.5, "normal"), (2, "elevated"), (4, "extreme")]),
        "tags": unique_preserve_order(
            [
                market.lower(),
                "k_deep",
                RESEARCH_SYSTEM_HARD_RULES["perplexity_integration_mode"],
                infer_signal_type(triggers),
                infer_event_size(triggers),
                *trigger_rules,
            ]
        ),
    }


def bucket_abs_value(value: float, thresholds: list[tuple[float, str]]) -> str:
    label = "none"
    for threshold, current_label in thresholds:
        if value >= threshold:
            label = current_label
    return label


def unique_preserve_order(items: list[str]) -> list[str]:
    seen = set()
    values = []
    for item in items:
        if item and item not in seen:
            values.append(item)
            seen.add(item)
    return values


def normalize_run_date(value: str | None) -> str:
    if not value:
        return datetime.now().strftime("%Y-%m-%d")
    text = value.strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text


def sanitize_identifier(value: str) -> str:
    token = re.sub(r"[^A-Za-z0-9]+", "-", value.upper()).strip("-")
    return token or "UNKNOWN"
