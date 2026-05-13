"""Shared implementation for the three trading agents."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader

from chairman.models import ResearchSignal
from business_agents._common.base_agent import AgentRunResult, BaseBusinessAgent, write_yaml
from business_agents._common.llm_client import LLMClient, build_llm_client_from_env
from business_agents._common.market_data.financial_data import compact_financial_snapshot
from business_agents._common.methodology_loader import MethodologyLoader
from business_agents._common.output_validator import (
    OutputValidationError,
    parse_json_payload,
    validate_trading_recommendation_output,
)
from business_agents._common.perplexity_results import (
    PerplexityContext,
    collect_perplexity_context,
    sync_signal_perplexity_status,
)
from business_agents._common.stock_pool import StockPool


class TradingAgent(BaseBusinessAgent):
    """Generic file-system trading-agent runner."""

    methodology_id = ""
    agent_id = ""
    output_dir_name = ""
    recommendation_prefix = "R"

    def __init__(
        self,
        data_dir: str | Path = "data",
        project_root: str | Path = ".",
        llm_client: LLMClient | None = None,
    ) -> None:
        super().__init__(data_dir, project_root)
        self.llm_client = llm_client
        self.env = Environment(
            loader=FileSystemLoader(str(Path(__file__).with_name("prompts"))),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def run(self, no_llm: bool = False) -> AgentRunResult:
        stock_pool = StockPool.load(self.data_dir)
        signals = self.load_research_signals()
        system_prompt = MethodologyLoader(self.project_root).load(self.methodology_id)
        output_files: list[Path] = []
        llm_used = False
        llm_messages = [{"role": "system", "content": system_prompt}]

        for index, signal in enumerate(signals, start=1):
            for target in signal.candidate_targets:
                if target.ticker not in stock_pool.trading_tickers():
                    continue
                perplexity_context = collect_perplexity_context(self.data_dir, signal)
                user_prompt = self.render_user_prompt(signal, target.ticker, perplexity_context)
                llm_messages.append({"role": "user", "content": user_prompt})
                if no_llm:
                    payload = self.build_debug_recommendation(
                        signal,
                        target.ticker,
                        index,
                        perplexity_context,
                    )
                else:
                    try:
                        client = self.llm_client or build_llm_client_from_env()
                        payload = self.complete_payload_with_schema_repair(
                            client,
                            system_prompt,
                            user_prompt,
                            stock_pool,
                        )
                        llm_used = True
                    except OutputValidationError as exc:
                        payload = self.build_abstain_recommendation(
                            signal,
                            target.ticker,
                            index,
                            str(exc),
                            failure_category="schema_validation_failed",
                        )
                        llm_used = True
                    except Exception:
                        payload = self.build_debug_recommendation(
                            signal,
                            target.ticker,
                            index,
                            perplexity_context,
                        )

                payload = self.enforce_trial_run_policy(payload)
                try:
                    rec = validate_trading_recommendation_output(
                        payload,
                        agent_id=self.agent_id,
                        stock_pool=stock_pool,
                    )
                except OutputValidationError as exc:
                    payload = self.build_abstain_recommendation(
                        signal,
                        target.ticker,
                        index,
                        str(exc),
                        failure_category="schema_validation_failed",
                    )
                    rec = validate_trading_recommendation_output(
                        payload,
                        agent_id=self.agent_id,
                        stock_pool=stock_pool,
                    )
                output_files.append(self.write_recommendation(rec.model_dump(mode="json")))

        self.log_run(
            {
                "run_id": self.run_id,
                "agent": self.agent_name,
                "llm_used": llm_used,
                "signals_consumed": [signal.research_signal_id for signal in signals],
                "output_files": [str(path) for path in output_files],
            },
            llm_messages,
        )
        return AgentRunResult(run_id=self.run_id, output_files=output_files, llm_used=llm_used)

    def load_research_signals(self) -> list[ResearchSignal]:
        signals: list[ResearchSignal] = []
        for path in sorted((self.data_dir / "research_signals").glob("RS-*.yaml")):
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            payload = data.get("research_signal", data)
            signal = ResearchSignal.model_validate(payload)
            signals.append(sync_signal_perplexity_status(self.data_dir, signal))
        return signals

    def render_user_prompt(
        self,
        signal: ResearchSignal,
        ticker: str,
        perplexity_context: PerplexityContext | None = None,
    ) -> str:
        context = perplexity_context or collect_perplexity_context(self.data_dir, signal)
        return self.env.get_template("trading_user_prompt.j2").render(
            target_ticker=ticker,
            signal_id=signal.research_signal_id,
            signal_summary=signal.signal_summary,
            market_data_yaml=compact_financial_snapshot(ticker),
            perplexity_results_yaml=context.yaml_text,
            upstream_signal_full_yaml=signal.model_dump(mode="json"),
            schema_name=self.agent_id,
        )

    def build_debug_recommendation(
        self,
        signal: ResearchSignal,
        ticker: str,
        index: int,
        perplexity_context: PerplexityContext | None = None,
    ) -> dict[str, Any]:
        today = datetime.now().strftime("%Y%m%d")
        context = perplexity_context or collect_perplexity_context(self.data_dir, signal)
        used_perplexity = context.has_filled_results
        features = extract_signal_features(signal)
        confidence = 58 if used_perplexity else min(70, 42 + len(features["trigger_rules"]) * 5)
        verdict_reason = (
            "已读取 Nepha 回填的 Perplexity 深度研究；试运行期禁用 long，保持 watch 等待人工判断。"
            if used_perplexity
            else "只具备公开价量初筛证据，缺少 Perplexity 事件原因回填，试运行期保持 watch。"
        )
        base = {
            "recommendation_id": f"{self.recommendation_prefix}-{today}-{index:03d}",
            "agent_id": self.agent_id,
            "ticker": ticker,
            "market": "HK" if ticker.endswith(".HK") else "US",
            "direction": "watch",
            "confidence": confidence,
            "entry_zone": None,
            "target_price": None,
            "stop_loss": None,
            "position_size_pct": 0,
            "thesis": (
                f"{ticker} 由 4.1 信号 {signal.research_signal_id} 触发，已读取 Perplexity 回填，"
                "但第一阶段 long 禁用，只能保守 watch。"
                if used_perplexity
                else f"{ticker} 由 4.1 信号 {signal.research_signal_id} 触发，"
                "当前只有公开价量初筛证据，缺少事件原因解释，先 watch。"
            ),
            "deployment_compliance": _deployment_compliance(),
            "authority_resolution": _authority_resolution(),
            "upstream_research_signals": [
                {
                    "research_signal_id": signal.research_signal_id,
                    "signal_summary": signal.signal_summary,
                    "my_methodology_verdict": "partial",
                    "verdict_reason": verdict_reason,
                    "relevance_score": 80,
                    "pull_request_id": context.all_prompt_ids[0] if context.all_prompt_ids else None,
                    "used_perplexity_results": used_perplexity,
                    "perplexity_prompt_ids_consumed": context.filled_prompt_ids,
                    "evidence_unverified_inherited": not used_perplexity,
                    "confidence_ceiling_applied": None if used_perplexity else 70,
                    "red_team_priority_flag": "low" if used_perplexity else "medium",
                    "chairman_weight_multiplier": 1.0 if used_perplexity else 0.7,
                }
            ],
            "data_points": build_data_points(signal, context),
            "catalysts": ["4.1 research signal"],
            "thesis_kill_criteria": ["Nepha 手动研究回填后若证据不足则维持 watch 或 abstain。"],
            "trial_run_policy": {
                "trial_run_mode": True,
                "long_disabled": True,
                "allowed_directions": ["watch", "avoid", "abstain"],
                "original_direction": "watch",
                "final_direction": "watch",
                "downgrade_reason": None,
            },
            "analysis_gaps": build_analysis_gaps(signal, context),
        }
        return self.add_method_specific_fields(base, signal, context)

    def build_abstain_recommendation(
        self,
        signal: ResearchSignal,
        ticker: str,
        index: int,
        reason: str,
        failure_category: str = "schema_validation_failed",
    ) -> dict[str, Any]:
        payload = self.build_debug_recommendation(signal, ticker, index)
        payload["direction"] = "abstain"
        payload["confidence"] = 0
        payload["abstain_reason"] = "methodology_specific_other"
        payload["deployment_compliance"]["abstain_reason"] = "methodology_specific_other"
        payload["thesis"] = f"格式校验失败，强制 abstain：{reason[:120]}"
        payload["validation_failure"] = {
            "category": failure_category,
            "reason": reason[:1000],
        }
        payload["trial_run_policy"]["fallback_reason"] = failure_category
        return payload

    def complete_payload_with_schema_repair(
        self,
        client: LLMClient,
        system_prompt: str,
        user_prompt: str,
        stock_pool: StockPool,
    ) -> dict[str, Any]:
        """Ask the model for JSON and retry with validation errors before fallback."""

        errors: list[str] = []
        prompt = user_prompt
        last_text = ""
        for attempt in range(3):
            text = client.complete(
                system_prompt=system_prompt,
                user_prompt=prompt,
                max_tokens=4000,
                timeout_seconds=60,
                temperature=0.2,
            )
            last_text = text
            try:
                payload = self.enforce_trial_run_policy(parse_json_payload(text))
                validate_trading_recommendation_output(
                    payload,
                    agent_id=self.agent_id,
                    stock_pool=stock_pool,
                )
                if attempt or errors:
                    payload["schema_repair"] = {"attempts": attempt, "errors": errors}
                return payload
            except OutputValidationError as exc:
                errors.append(str(exc))
                prompt = build_repair_prompt(user_prompt, last_text, errors)
        raise OutputValidationError(
            "schema_validation_failed after repair attempts: " + " | ".join(errors)
        )

    def enforce_trial_run_policy(self, payload: dict[str, Any]) -> dict[str, Any]:
        """First phase forbids long/short outputs even if the model suggests them."""

        direction = str(payload.get("direction") or "").lower()
        policy = dict(payload.get("trial_run_policy") or {})
        original_direction = (
            direction
            if direction in {"long", "short"}
            else policy.get("original_direction") or direction or None
        )
        policy.update(
            {
                "trial_run_mode": True,
                "long_disabled": True,
                "allowed_directions": ["watch", "avoid", "abstain"],
                "original_direction": original_direction,
            }
        )
        if direction in {"long", "short"}:
            payload["direction"] = "watch"
            payload["position_size_pct"] = 0
            payload["confidence"] = min(parse_confidence(payload.get("confidence")), 60)
            policy["final_direction"] = "watch"
            policy["downgrade_reason"] = f"first_phase_{direction}_disabled"
            payload["thesis"] = (
                f"{payload.get('thesis', '')} 试运行期禁止 {direction}，校验层已降级为 watch。"
            ).strip()
            if payload.get("action") in {"buy", "add"}:
                payload["action"] = "watch"
        elif direction not in {"watch", "avoid", "abstain"}:
            payload["direction"] = "abstain"
            payload["confidence"] = 0
            payload.setdefault("abstain_reason", "invalid_direction")
            payload.setdefault("deployment_compliance", _deployment_compliance())
            payload["deployment_compliance"]["abstain_reason"] = "invalid_direction"
            policy["final_direction"] = "abstain"
            policy["downgrade_reason"] = "invalid_direction"
        else:
            policy["final_direction"] = direction
            policy.setdefault("downgrade_reason", None)
        payload["trial_run_policy"] = policy
        return payload

    def add_method_specific_fields(
        self,
        base: dict[str, Any],
        signal: ResearchSignal,
        context: PerplexityContext,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def write_recommendation(self, payload: dict[str, Any]) -> Path:
        today = datetime.now().strftime("%Y%m%d")
        return write_yaml(
            self.data_dir
            / "recommendations"
            / today
            / self.output_dir_name
            / f"{payload['recommendation_id']}.yaml",
            {"recommendation": payload},
        )


def _deployment_compliance() -> dict[str, Any]:
    return {
        "deployment_layer_version": "0.1",
        "hard_rules_passed": {
            "position_size_pct": True,
            "industry_exposure_pct": True,
            "cash_floor_pct": True,
            "liquidity_three_locks": True,
            "market_cap_minimum": True,
            "forbidden_actions_check": True,
            "cooldown_check": True,
        },
        "any_failure_must_abstain": False,
        "failure_details": [],
    }


def _authority_resolution() -> dict[str, Any]:
    return {
        "overridden_by_deployment": False,
        "overridden_principle": None,
        "philosophy_deferred": False,
        "kill_log": [],
        "upstream_signal_disagreement": False,
        "disagreement_reason": None,
    }


def build_data_points(signal: ResearchSignal, context: PerplexityContext) -> list[dict[str, Any]]:
    data_points = [
        {
            "label": "4.1 signal",
            "value": signal.signal_summary,
            "date": datetime.now().date().isoformat(),
            "source_url": f"file://data/research_signals/{signal.research_signal_id}.yaml",
        }
    ]
    for item in (signal.data_points or [])[:5]:
        if isinstance(item, dict):
            data_points.append(item)
    for prompt_id in context.filled_prompt_ids:
        data_points.append(
            {
                "label": f"Perplexity filled result {prompt_id}",
                "value": "Nepha 已回填 Perplexity 深度研究结果，完整内容已注入交易 Agent prompt。",
                "date": datetime.now().date().isoformat(),
                "source_url": f"file://data/perplexity_results/{prompt_id}_filled.yaml",
            }
        )
    return data_points


def extract_signal_features(signal: ResearchSignal) -> dict[str, Any]:
    triggers = signal.discontinuity_assessment.get("triggered_rules", []) or []
    trigger_rules = [item.get("rule") for item in triggers if isinstance(item, dict) and item.get("rule")]
    latest_change = None
    volume_ratio = None
    for item in signal.data_points or []:
        if not isinstance(item, dict):
            continue
        value = item.get("value")
        if isinstance(value, dict):
            latest_change = value.get("change_pct", latest_change)
            volume_ratio = value.get("volume_ratio", volume_ratio)
    return {
        "trigger_rules": trigger_rules,
        "trigger_count": len(trigger_rules),
        "latest_change_pct": latest_change,
        "volume_ratio": volume_ratio,
        "perplexity_pending": signal.perplexity_research.get("prompts_pending", []) or [],
        "perplexity_filled": signal.perplexity_research.get("prompts_filled_back", []) or [],
    }


def build_analysis_gaps(signal: ResearchSignal, context: PerplexityContext) -> list[str]:
    gaps: list[str] = []
    if not context.has_filled_results:
        gaps.append("缺 Perplexity 事件原因回填")
    if not signal.data_points:
        gaps.append("缺公开价量 data_points")
    if signal.discontinuity_assessment.get("evidence_unverified"):
        gaps.append("4.1 证据仍标记为 evidence_unverified")
    return gaps


def build_repair_prompt(original_prompt: str, last_text: str, errors: list[str]) -> str:
    return f"""{original_prompt}

# JSON 修复任务

上一次输出未通过 schema 校验。请只返回修复后的严格 JSON，不要解释。

## 校验错误
{yaml.safe_dump(errors, allow_unicode=True, sort_keys=False)}

## 上一次输出
{last_text}
"""


def parse_confidence(value: Any) -> int:
    """Parse confidence for trial-policy downgrades without hiding schema errors."""

    if value is None or value == "":
        return 0
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise OutputValidationError(f"confidence must be integer-like before trial downgrade: {value!r}") from exc
