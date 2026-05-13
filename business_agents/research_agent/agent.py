"""Research Agent implementation."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from business_agents._common.base_agent import AgentRunResult, BaseBusinessAgent, write_yaml
from business_agents._common.llm_client import LLMClient, build_llm_client_from_env
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
    ) -> None:
        super().__init__(data_dir, project_root)
        self.llm_client = llm_client
        self.env = Environment(
            loader=FileSystemLoader(str(Path(__file__).with_name("prompts"))),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def run(self, trigger_type: str = "scheduled", no_llm: bool = False) -> AgentRunResult:
        """Run scan and write research_signal + pull_request YAML files."""

        stock_pool = StockPool.load(self.data_dir)
        system_prompt = MethodologyLoader(self.project_root).load(self.methodology_id)
        user_prompt = self.render_user_prompt(stock_pool, trigger_type)
        llm_used = False
        llm_messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]

        payload: dict[str, Any]
        if not no_llm:
            try:
                client = self.llm_client or build_llm_client_from_env()
                text = client.complete(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    max_tokens=4000,
                    timeout_seconds=60,
                    temperature=0.2,
                )
                payload = json.loads(text)
                llm_used = True
            except Exception:
                payload = self.build_debug_payload(stock_pool)
        else:
            payload = self.build_debug_payload(stock_pool)

        try:
            result = validate_research_agent_output(payload, stock_pool)
        except OutputValidationError as exc:
            if not llm_used:
                self._write_error(str(exc), payload)
                raise
            payload = self.build_debug_payload(stock_pool)
            result = validate_research_agent_output(payload, stock_pool)
            self._write_error(f"LLM output rejected; conservative fallback used: {exc}", payload)

        output_files = self.write_outputs(result.model_dump(mode="json"))
        self.log_run(
            {
                "run_id": self.run_id,
                "agent": self.agent_name,
                "llm_used": llm_used,
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
        entry = stock_pool.first_tradable()
        today = datetime.now().strftime("%Y%m%d")
        signal_id = f"RS-{today}-001"
        return {
            "research_signals": [
                {
                    "research_signal_id": signal_id,
                    "emitted_at": datetime.now().astimezone().isoformat(),
                    "emitter": "4.1_research_system",
                    "signal_status": "active",
                    "signal_type": "event",
                    "research_stage": "daily_scan",
                    "signal_summary": f"{entry.ticker} 进入股池扫描，占位信号用于阶段 3.7 端到端验证。",
                    "candidate_targets": [
                        {
                            "ticker": entry.ticker,
                            "market": entry.market,
                            "company_name": entry.name,
                            "relevance_score": 80,
                            "role": "primary",
                        }
                    ],
                    "research_object": {
                        "primary": "company",
                        "secondary": [],
                        "why_this_object": "来自 Nepha 主股池。",
                    },
                    "event_input": {
                        "event_name": "stock_pool_scan",
                        "event_date": datetime.now().date().isoformat(),
                        "event_level": "company",
                        "event_size": "small",
                        "expected_bayesian_impact": "needs_manual_research",
                        "is_market_aware": False,
                    },
                    "discontinuity_assessment": {
                        "type": "other",
                        "why_now": "阶段 3.7 首次可执行扫描。",
                        "evidence": [],
                        "counter_evidence": [],
                        "confidence": 50,
                        "evidence_unverified": True,
                    },
                    "bayesian_update": {
                        "market_prior_probability": None,
                        "my_prior_probability": None,
                        "assumed_true_base_rate": None,
                        "event_input_summary": "debug scan",
                        "posterior_probability": None,
                        "posterior_minus_market_prior": None,
                        "confidence": 50,
                        "evidence": [],
                        "evidence_unverified": True,
                    },
                    "beta_attribution": {
                        "expected_return_decomposition": {},
                        "beta_linked": False,
                        "alpha_clarity": "mixed",
                    },
                    "routing_recommendation": {
                        "suggested_for": ["fengliu_reverse_odds", "wanmu_single_sided", "liguofei_zen_value"],
                        "routing_reason": "debug signal for executable system smoke test",
                        "not_suitable_for": [],
                        "not_suitable_reason": None,
                        "expected_disagreement": [],
                    },
                    "upstream_to_trading_agents": {
                        "chairman_route_id": f"ROUTE-{today}-001",
                        "downstream_agents_notified": [
                            "fengliu_reverse_odds",
                            "wanmu_single_sided",
                            "liguofei_zen_value",
                        ],
                        "notification_status": "pending",
                        "delivery_notes": "file-system handoff",
                    },
                    "perplexity_research": {
                        "prompts_requested": [f"PR-{today}-001"],
                        "prompts_filled_back": [],
                        "prompts_skipped_by_nepha": [],
                        "prompts_pending": [f"PR-{today}-001"],
                        "results_summary": None,
                        "confidence_after_research": None,
                        "coverage_ratio": 0,
                    },
                    "red_team_questions": [],
                    "falsification_points": [],
                    "signal_kill_criteria": [],
                    "data_points": [],
                    "downstream_responses": [],
                }
            ],
            "perplexity_prompt_brief": {
                "brief_id": f"PRBRIEF-{today}-001",
                "prompts": [
                    {
                        "prompt_id": f"PR-{today}-001",
                        "related_signal_id": signal_id,
                        "priority": "P1",
                        "prompt_text": f"请手动研究 {entry.ticker} 最近 7 天是否有非连续变化证据。",
                    }
                ],
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
        client = YFinanceClient()
        movers = []
        for entry in list(stock_pool.entries)[:20]:
            if entry.market in {"HK", "US"}:
                quote = client.get_quote(entry.ticker)
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
