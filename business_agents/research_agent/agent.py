"""Research Agent implementation."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from business_agents._common.base_agent import AgentRunResult, BaseBusinessAgent, write_yaml
from business_agents._common.llm_client import LLMClient
from business_agents._common.market_data.yfinance_client import YFinanceClient
from business_agents._common.methodology_loader import MethodologyLoader
from business_agents._common.output_validator import (
    OutputValidationError,
    validate_research_agent_output,
)
from business_agents._common.stock_pool import StockPool


class ResearchAgent(BaseBusinessAgent):
    """4.1 research upstream agent."""

    agent_name = "research_agent"
    methodology_id = "research_system_event_bayesian"

    def __init__(
        self,
        data_dir: str | Path = "data",
        project_root: str | Path = ".",
        llm_client: LLMClient | None = None,
        market_client: YFinanceClient | None = None,
    ) -> None:
        super().__init__(data_dir, project_root)
        self.llm_client = llm_client
        self.market_client = market_client or YFinanceClient()
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

        today = datetime.now().strftime("%Y%m%d")
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

            signal_index = len(signals) + 1
            signal_id = f"RS-{today}-{signal_index:03d}"
            prompt_id = f"PR-{today}-{len(prompts) + 1:03d}" if len(prompts) < 30 else None
            data_points = build_signal_data_points(features, triggers)
            signal = {
                "research_signal_id": signal_id,
                "emitted_at": emitted_at,
                "emitter": "4.1_research_system",
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
                    "secondary": ["public_price_volume"],
                    "why_this_object": "来自 Nepha HK/US 主股池，触发公开价量规则。",
                },
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
                        "fengliu_reverse_odds",
                        "wanmu_single_sided",
                        "liguofei_zen_value",
                    ],
                    "routing_reason": "公开价量异动只做初筛，需三位交易 Agent 保守评估。",
                    "not_suitable_for": [],
                    "not_suitable_reason": None,
                    "expected_disagreement": ["证据未验证", "方法论阈值可能不通过"],
                },
                "upstream_to_trading_agents": {
                    "chairman_route_id": f"ROUTE-{today}-{signal_index:03d}",
                    "downstream_agents_notified": [
                        "fengliu_reverse_odds",
                        "wanmu_single_sided",
                        "liguofei_zen_value",
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
                ],
                "falsification_points": [
                    "如果 Perplexity 回填显示异动仅来自指数或技术性成交，则不进入交易判断。",
                    "如果数据源错误或复权异常，则该信号 invalidated。",
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
                        "prompt_text": build_perplexity_prompt(entry.ticker, entry.name, triggers, features),
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
) -> str:
    trigger_lines = "\n".join(
        f"- {trigger['rule']}: {trigger.get('value')} ({trigger.get('date')})"
        for trigger in triggers
    )
    display_name = f"{ticker} {name}".strip()
    return (
        f"请研究 {display_name} 最近 7-10 个交易日公开价量异动背后的真实原因。\n"
        "只需要判断是否存在新闻、财报、监管、行业、资金面或指数层面的可验证原因，不要给交易建议。\n"
        f"触发规则：\n{trigger_lines}\n"
        f"最新收盘：{features.get('latest_close')}；"
        f"5 日变化：{features.get('five_day_change_pct')}%；"
        f"10 日变化：{features.get('ten_day_change_pct')}%。\n"
        "输出请包含来源链接、结论可信度、反证和仍未验证的地方。"
    )
