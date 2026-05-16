"""Shared implementation for the three trading agents."""

from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import re
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader

from chairman.models import ResearchSignal
from business_agents._common.base_agent import AgentRunResult, BaseBusinessAgent, write_yaml
from business_agents._common.llm_client import LLMClient, LLMError, build_llm_client_from_env
from business_agents._common.knowledge_store import get_recent_knowledge_context
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
        run_date: str | None = None,
    ) -> None:
        super().__init__(data_dir, project_root)
        self.llm_client = llm_client
        self.run_date = normalize_run_date(run_date)
        self.compact_run_date = self.run_date.replace("-", "")
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
                            signal,
                            target.ticker,
                            perplexity_context,
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
                    except LLMError as exc:
                        payload = self.build_abstain_recommendation(
                            signal,
                            target.ticker,
                            index,
                            format_exception(exc),
                            failure_category="llm_runtime_failed",
                        )
                        llm_used = True
                    except Exception as exc:
                        payload = self.build_abstain_recommendation(
                            signal,
                            target.ticker,
                            index,
                            format_exception(exc),
                            failure_category="agent_runtime_failed",
                        )

                payload = self.enforce_trial_run_policy(payload)
                payload = self.finalize_payload_for_target(
                    payload,
                    signal,
                    target.ticker,
                    perplexity_context,
                )
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
                    payload = self.finalize_payload_for_target(
                        payload,
                        signal,
                        target.ticker,
                        perplexity_context,
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
        pattern = f"RS-{self.compact_run_date}*.yaml"
        for path in sorted((self.data_dir / "research_signals").glob(pattern)):
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
            historical_knowledge_yaml=get_recent_knowledge_context(
                self.data_dir,
                ticker,
                as_of_date=self.run_date,
            ),
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
        today = self.compact_run_date
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
                f"{ticker} 由 K deep 信号 {signal.research_signal_id} 触发，已读取 Perplexity 回填，"
                "但第一阶段 long 禁用，只能保守 watch。"
                if used_perplexity
                else f"{ticker} 由 K deep 信号 {signal.research_signal_id} 触发，"
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
            "catalysts": ["K deep research signal"],
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
        signal: ResearchSignal,
        ticker: str,
        perplexity_context: PerplexityContext,
    ) -> dict[str, Any]:
        """Ask the model for JSON and retry with validation errors before fallback."""

        errors: list[str] = []
        prompt = user_prompt
        last_text = ""
        default_payload = self.build_debug_recommendation(signal, ticker, 1, perplexity_context)
        for attempt in range(3):
            text = client.complete(
                system_prompt=system_prompt,
                user_prompt=prompt,
                max_tokens=4000,
                timeout_seconds=trading_llm_timeout_seconds(),
                temperature=0.2,
            )
            last_text = text
            try:
                raw_payload = unwrap_recommendation_payload(parse_json_payload(text))
                assert_llm_payload_has_minimum_fields(raw_payload)
                raw_payload = merge_payload_defaults(default_payload, raw_payload)
                payload = self.finalize_payload_for_target(
                    self.enforce_trial_run_policy(raw_payload),
                    signal,
                    ticker,
                    perplexity_context,
                )
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

    def normalize_payload_data_points(
        self,
        payload: dict[str, Any],
        signal: ResearchSignal,
        ticker: str,
    ) -> dict[str, Any]:
        """Accept common LLM aliases without weakening Red Team source checks."""

        fallback_source_url = first_signal_source_url(signal) or f"https://finance.yahoo.com/quote/{ticker}"
        normalized = []
        for item in payload.get("data_points") or []:
            if not isinstance(item, dict):
                normalized.append(item)
                continue
            point = dict(item)
            source_url = point.get("source_url") or point.get("url")
            if not source_url:
                source_url = fallback_source_url
            point["source_url"] = str(source_url)
            normalized.append(point)
        if normalized:
            payload["data_points"] = normalized
        return payload

    def finalize_payload_for_target(
        self,
        payload: dict[str, Any],
        signal: ResearchSignal,
        ticker: str,
        perplexity_context: PerplexityContext | None = None,
    ) -> dict[str, Any]:
        """Normalize model-controlled identity fields before validation/writing."""

        payload["agent_id"] = self.agent_id
        payload["ticker"] = ticker
        payload["market"] = market_for_ticker(ticker)
        payload["recommendation_id"] = self.recommendation_id_for_ticker(ticker)
        payload = normalize_payload_scalar_fields(payload)
        payload = self.normalize_upstream_research_refs(payload, signal, perplexity_context)
        payload = self.apply_cold_start_guardrail(payload, signal, perplexity_context)
        return self.normalize_payload_data_points(payload, signal, ticker)

    def apply_cold_start_guardrail(
        self,
        payload: dict[str, Any],
        signal: ResearchSignal,
        context: PerplexityContext,
    ) -> dict[str, Any]:
        pending = cold_start_pending_items(signal, context)
        if not pending:
            return payload

        payload["confidence"] = min(parse_confidence(payload.get("confidence")), 50)
        waiting_conditions = list(payload.get("waiting_conditions") or [])
        waiting_conditions.extend(format_cold_start_waiting_conditions(pending))
        payload["waiting_conditions"] = unique_text_items(waiting_conditions, limit=10)

        gaps = list(payload.get("analysis_gaps") or [])
        gaps.append(f"冷启动历史研究未完成：{len(pending)} 条")
        payload["analysis_gaps"] = unique_text_items(gaps, limit=12)

        payload["thesis"] = (
            f"{payload.get('thesis', '')} 当前仍有 {len(pending)} 条新股票冷启动历史研究未完成，"
            "本轮结论只能作为低置信度观察。"
        ).strip()

        refs = payload.get("upstream_research_signals") or []
        if isinstance(refs, list):
            for ref in refs:
                if not isinstance(ref, dict):
                    continue
                ref["evidence_unverified_inherited"] = True
                ref["confidence_ceiling_applied"] = 50
                ref["red_team_priority_flag"] = "high"
                ref["chairman_weight_multiplier"] = min(float(ref.get("chairman_weight_multiplier") or 1.0), 0.5)
                ref["cold_start_pending"] = [
                    {
                        "prompt_id": item.get("prompt_id"),
                        "research_dimension": item.get("research_dimension"),
                        "priority_order": item.get("priority_order"),
                    }
                    for item in pending
                ]
        return payload

    def normalize_upstream_research_refs(
        self,
        payload: dict[str, Any],
        signal: ResearchSignal,
        perplexity_context: PerplexityContext | None = None,
    ) -> dict[str, Any]:
        context = perplexity_context or collect_perplexity_context(self.data_dir, signal)
        pending_cold_start = cold_start_pending_items(signal, context)
        confidence_ceiling = 50 if pending_cold_start else (None if context.has_filled_results else 70)
        current_refs = payload.get("upstream_research_signals") or [{}]
        if isinstance(current_refs, dict):
            current = dict(current_refs)
        elif isinstance(current_refs, list) and current_refs and isinstance(current_refs[0], dict):
            current = dict(current_refs[0])
        else:
            current = {}
        current.update(
            {
                "research_signal_id": signal.research_signal_id,
                "signal_summary": current.get("signal_summary") or signal.signal_summary,
                "pull_request_id": context.all_prompt_ids[0] if context.all_prompt_ids else None,
                "used_perplexity_results": context.has_filled_results,
                "perplexity_prompt_ids_consumed": context.filled_prompt_ids,
                "evidence_unverified_inherited": bool(pending_cold_start) or not context.has_filled_results,
                "confidence_ceiling_applied": confidence_ceiling,
                "red_team_priority_flag": current.get("red_team_priority_flag")
                or ("high" if pending_cold_start else ("low" if context.has_filled_results else "medium")),
                "chairman_weight_multiplier": 0.5 if pending_cold_start else (1.0 if context.has_filled_results else 0.7),
            }
        )
        current.setdefault("my_methodology_verdict", "partial")
        current.setdefault(
            "verdict_reason",
            "已读取 Nepha 回填的 Perplexity 深度研究；试运行期禁用 long，保持 watch 等待人工判断。"
            if context.has_filled_results
            else "只具备公开价量初筛证据，缺少 Perplexity 事件原因回填。",
        )
        current.setdefault("relevance_score", 80)
        payload["upstream_research_signals"] = [current]
        return payload

    def recommendation_id_for_ticker(self, ticker: str) -> str:
        return f"{self.recommendation_prefix}-{self.compact_run_date}-{sanitize_identifier(ticker)}"

    def write_recommendation(self, payload: dict[str, Any]) -> Path:
        today = self.compact_run_date
        output_dir = self.data_dir / "recommendations" / today / self.output_dir_name
        output_path = output_dir / f"{payload['recommendation_id']}.yaml"
        self.remove_obsolete_recommendations(output_dir, output_path, payload)
        return write_yaml(
            output_path,
            {"recommendation": payload},
        )

    def remove_obsolete_recommendations(
        self,
        output_dir: Path,
        output_path: Path,
        payload: dict[str, Any],
    ) -> None:
        if not output_dir.exists():
            return
        ticker = str(payload.get("ticker") or "")
        for path in sorted([*output_dir.glob("*.yaml"), *output_dir.glob("*.yml")]):
            if path == output_path:
                continue
            data = read_yaml_safely(path)
            existing = data.get("recommendation", data) if isinstance(data, dict) else {}
            if isinstance(existing, dict) and str(existing.get("ticker") or "") == ticker:
                path.unlink()


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
            "label": "K deep signal",
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


def first_signal_source_url(signal: ResearchSignal) -> str | None:
    for item in signal.data_points or []:
        if isinstance(item, dict) and item.get("source_url"):
            return str(item["source_url"])
    for trigger in signal.discontinuity_assessment.get("triggered_rules", []) or []:
        if isinstance(trigger, dict) and trigger.get("source_url"):
            return str(trigger["source_url"])
    return None


def market_for_ticker(ticker: str) -> str:
    if ticker.endswith(".HK"):
        return "HK"
    return "US"


def sanitize_identifier(value: str) -> str:
    token = re.sub(r"[^A-Za-z0-9]+", "-", value.upper()).strip("-")
    return token or "UNKNOWN"


def read_yaml_safely(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}


def unwrap_recommendation_payload(payload: dict[str, Any]) -> dict[str, Any]:
    value = payload.get("recommendation", payload)
    if not isinstance(value, dict):
        raise OutputValidationError("recommendation payload must be an object")
    return value


def merge_payload_defaults(default_payload: dict[str, Any], llm_payload: dict[str, Any]) -> dict[str, Any]:
    """Use deterministic agent fields as a schema backbone, then overlay LLM judgment."""

    merged = dict(default_payload)
    for key, value in llm_payload.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        elif value not in (None, [], {}):
            merged[key] = value
    return merged


def assert_llm_payload_has_minimum_fields(payload: dict[str, Any]) -> None:
    required = {
        "direction",
        "confidence",
        "thesis",
    }
    missing = sorted(key for key in required if key not in payload)
    if missing:
        raise OutputValidationError("missing required recommendation fields before trial policy: " + ", ".join(missing))


def normalize_payload_scalar_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """Clean common LLM formatting noise before strict schema validation."""

    if "confidence" in payload:
        payload["confidence"] = normalize_int_like(payload["confidence"], field_name="confidence")
    if "position_size_pct" in payload:
        payload["position_size_pct"] = normalize_float_like_or_none(payload["position_size_pct"])
    if "entry_zone" in payload:
        payload["entry_zone"] = normalize_entry_zone(payload["entry_zone"])
    for field_name in ("target_price", "stop_loss"):
        if is_blank_like(payload.get(field_name)):
            payload[field_name] = None
    if "direction" in payload and isinstance(payload["direction"], str):
        payload["direction"] = payload["direction"].strip().lower()
    return payload


def normalize_entry_zone(value: Any) -> list[float] | None:
    if is_blank_like(value):
        return None
    if not isinstance(value, list):
        parsed = normalize_float_like_or_none(value)
        return [parsed] if parsed is not None else None
    normalized = [item for item in (normalize_float_like_or_none(item) for item in value) if item is not None]
    return normalized or None


def normalize_int_like(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool):
        raise OutputValidationError(f"{field_name} must be integer-like before validation: {value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if text.endswith("%"):
            text = text[:-1].strip()
        if text.isdigit():
            return int(text)
    raise OutputValidationError(f"{field_name} must be integer-like before validation: {value!r}")


def normalize_float_like_or_none(value: Any) -> float | None:
    if is_blank_like(value) or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if text.endswith("%"):
            text = text[:-1].strip()
        if not text:
            return None
        try:
            return float(text.replace(",", ""))
        except ValueError:
            return None
    return None


def is_blank_like(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"", "n/a", "na", "none", "null", "-", "未填", "不适用"}
    return False


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
    pending_cold_start = cold_start_pending_items(signal, context)
    if pending_cold_start:
        gaps.append(f"缺冷启动历史研究回填：{len(pending_cold_start)} 条")
    if not signal.data_points:
        gaps.append("缺公开价量 data_points")
    if signal.discontinuity_assessment.get("evidence_unverified"):
        gaps.append("K deep 证据仍标记为 evidence_unverified")
    return gaps


def cold_start_pending_items(signal: ResearchSignal, context: PerplexityContext) -> list[dict[str, Any]]:
    pending_ids = set(context.pending_prompt_ids)
    closed_ids = set(context.filled_prompt_ids) | set(context.skipped_prompt_ids)
    planning_context = getattr(signal, "research_planning_context", {}) or {}
    items: list[dict[str, Any]] = []
    if isinstance(planning_context, dict):
        for item in planning_context.get("cold_start_pending") or []:
            if not isinstance(item, dict):
                continue
            prompt_id = str(item.get("prompt_id") or "")
            if prompt_id and prompt_id not in closed_ids:
                items.append(dict(item))
    known_ids = {str(item.get("prompt_id") or "") for item in items}
    for prompt_id in sorted(prompt_id for prompt_id in pending_ids if "COLDSTART" in prompt_id):
        if prompt_id in known_ids:
            continue
        items.append({"prompt_id": prompt_id, "status": "pending_cold_start"})
    return items


def format_cold_start_waiting_conditions(items: list[dict[str, Any]]) -> list[str]:
    conditions: list[str] = []
    for item in sorted(items, key=lambda value: safe_priority_order(value.get("priority_order"))):
        label = item.get("research_dimension_label") or item.get("research_dimension") or "冷启动历史研究"
        prompt_id = item.get("prompt_id") or "unknown"
        conditions.append(f"需要先完成冷启动研究 {prompt_id}（{label}）再提高判断置信度")
    return conditions


def safe_priority_order(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 99


def unique_text_items(items: list[Any], *, limit: int) -> list[str]:
    seen: set[str] = set()
    values: list[str] = []
    for item in items:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        values.append(text)
        if len(values) >= limit:
            break
    return values


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
        return normalize_int_like(value, field_name="confidence")
    except OutputValidationError as exc:
        raise OutputValidationError(f"confidence must be integer-like before trial downgrade: {value!r}") from exc


def format_exception(exc: Exception) -> str:
    message = str(exc)
    return f"{type(exc).__name__}: {message}" if message else type(exc).__name__


def trading_llm_timeout_seconds() -> int:
    raw = os.getenv("TRADING_LLM_TIMEOUT_SECONDS", "180")
    try:
        return max(30, int(raw))
    except ValueError:
        return 180


def normalize_run_date(value: str | None) -> str:
    if not value:
        return datetime.now().strftime("%Y-%m-%d")
    text = value.strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text
