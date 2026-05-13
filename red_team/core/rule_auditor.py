"""Hard-rule audit checks AR-001 through AR-011."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from chairman.models import AgentId, Direction, Recommendation, ResearchSignal
from red_team.models import RuleAuditFinding

FUZZY_WORD_RE = re.compile(r"(可能|或许|大概|应该是|感觉|估计是|看起来)")


def audit_rules(
    recommendations: list[Recommendation],
    research_signals: list[ResearchSignal],
    chairman_brief: dict[str, Any] | None = None,
) -> list[RuleAuditFinding]:
    """Run all 11 Red Team hard-rule checks."""

    findings: list[RuleAuditFinding] = []
    for rec in recommendations:
        findings.extend(
            [
                *_ar_001_dual_gate_anomaly(rec),
                *_ar_002_deployment_failure_not_abstain(rec),
                *_ar_003_abstain_reason_or_thesis_missing(rec),
                *_ar_004_evidence_unverified_high_confidence(rec),
                *_ar_007_fuzzy_thesis(rec),
                *_ar_008_data_points_without_source_url(rec),
                *_ar_009_long_without_catalysts(rec),
                *_ar_010_long_without_thesis_kill_criteria(rec),
                *_ar_011_fengliu_logic_kill_not_avoid(rec),
                *_ar_012_trial_long_disabled_violation(rec),
                *_ar_013_schema_validation_failure(rec),
                *_ar_014_methodology_gaps(rec),
            ]
        )
    findings.extend(_ar_005_split_long_vs_avoid(chairman_brief or {}))
    findings.extend(_ar_006_unverified_signal_skipped_twice(research_signals))
    return findings


def _finding(
    rule_id: str,
    severity: str,
    rec: Recommendation | None,
    text: str,
    evidence: dict[str, Any],
    decisions: list[str] | None = None,
) -> RuleAuditFinding:
    return RuleAuditFinding(
        rule_id=rule_id,
        severity=severity,  # type: ignore[arg-type]
        target_recommendation_id=rec.recommendation_id if rec else None,
        target_agent_id=rec.agent_id.value if rec else None,
        finding_text=text,
        evidence=evidence,
        referenced_decisions=decisions or [],
    )


def _ar_001_dual_gate_anomaly(rec: Recommendation) -> list[RuleAuditFinding]:
    if (
        rec.agent_id == AgentId.LIGUOFEI
        and rec.deployment_compliance.dual_gate_consistency == "anomaly_review_required"
    ):
        r7 = getattr(rec.authority_resolution, "r7_dual_gate_status", {}) or {}
        return [
            _finding(
                "AR-001",
                "critical",
                rec,
                f"李国飞 Agent 在 {rec.ticker} 上触发 dual_gate anomaly。",
                {"dual_gate_consistency": rec.deployment_compliance.dual_gate_consistency, "r7": r7},
                ["DEC-011"],
            )
        ]
    return []


def _ar_002_deployment_failure_not_abstain(rec: Recommendation) -> list[RuleAuditFinding]:
    if rec.deployment_compliance.any_failure_must_abstain and rec.direction != Direction.ABSTAIN:
        return [
            _finding(
                "AR-002",
                "critical",
                rec,
                f"{rec.agent_id.value} 在 {rec.ticker} 上声明 deployment_compliance 失败但 direction={rec.direction.value}。按 R4 规则必须 abstain。",
                {
                    "any_failure_must_abstain": True,
                    "direction": rec.direction.value,
                    "hard_rules_passed": rec.deployment_compliance.hard_rules_passed.model_dump(),
                },
                ["R4"],
            )
        ]
    return []


def _ar_003_abstain_reason_or_thesis_missing(rec: Recommendation) -> list[RuleAuditFinding]:
    reason = rec.abstain_reason or rec.deployment_compliance.abstain_reason
    if rec.direction == Direction.ABSTAIN and (not reason or len(rec.thesis or "") < 20):
        return [
            _finding(
                "AR-003",
                "high",
                rec,
                f"{rec.agent_id.value} 在 {rec.ticker} 输出 abstain 但未提供 abstain_reason 或 thesis 过短。",
                {"abstain_reason": reason, "thesis_length": len(rec.thesis or "")},
                ["DEC-003"],
            )
        ]
    return []


def _ar_004_evidence_unverified_high_confidence(rec: Recommendation) -> list[RuleAuditFinding]:
    if rec.confidence > 70 and any(s.evidence_unverified_inherited for s in rec.upstream_research_signals):
        return [
            _finding(
                "AR-004",
                "high",
                rec,
                f"{rec.agent_id.value} 在 {rec.ticker} 引用未验证的 4.1 证据但 confidence={rec.confidence}（超过 DEC-004 上限 70）。",
                {
                    "confidence": rec.confidence,
                    "unverified_signals": [
                        s.research_signal_id
                        for s in rec.upstream_research_signals
                        if s.evidence_unverified_inherited
                    ],
                },
                ["DEC-004"],
            )
        ]
    return []


def _ar_005_split_long_vs_avoid(chairman_brief: dict[str, Any]) -> list[RuleAuditFinding]:
    findings: list[RuleAuditFinding] = []
    for summary in chairman_brief.get("per_recommendation_summary", []):
        consensus = summary.get("direction_consensus", {})
        if consensus.get("consensus_level") == "split_long_vs_avoid":
            findings.append(
                RuleAuditFinding(
                    rule_id="AR-005",
                    severity="medium",
                    finding_text=(
                        f"{summary.get('ticker')} 出现 long vs avoid 完全相反分歧。Chairman 已标注，"
                        "Red Team 重申该分歧来源必须超出方法论 DNA。"
                    ),
                    evidence={"ticker": summary.get("ticker"), "consensus": consensus},
                    referenced_decisions=["DEC-001"],
                )
            )
    return findings


def _ar_006_unverified_signal_skipped_twice(
    research_signals: list[ResearchSignal],
) -> list[RuleAuditFinding]:
    findings: list[RuleAuditFinding] = []
    for signal in research_signals:
        skipped = signal.perplexity_research.get("prompts_skipped_by_nepha", []) or []
        if len(skipped) >= 2:
            findings.append(
                RuleAuditFinding(
                    rule_id="AR-006",
                    severity="medium",
                    finding_text=(
                        f"4.1 信号 {signal.research_signal_id} 的关键 prompt 已连续被 Nepha 跳过 2 次。"
                    ),
                    evidence={"research_signal_id": signal.research_signal_id, "skipped": skipped},
                    referenced_decisions=["DEC-002"],
                )
            )
    return findings


def _ar_007_fuzzy_thesis(rec: Recommendation) -> list[RuleAuditFinding]:
    count = len(FUZZY_WORD_RE.findall(rec.thesis or ""))
    if count >= 3:
        return [
            _finding(
                "AR-007",
                "low",
                rec,
                f"{rec.agent_id.value} 在 {rec.ticker} 的 thesis 中使用了 ≥3 次模糊词。",
                {"fuzzy_word_count": count, "thesis": rec.thesis},
            )
        ]
    return []


def _ar_008_data_points_without_source_url(rec: Recommendation) -> list[RuleAuditFinding]:
    data_points = rec.data_points or []
    if not data_points:
        return []
    missing = [dp for dp in data_points if not dp.get("source_url")]
    if len(missing) / len(data_points) >= 0.5:
        return [
            _finding(
                "AR-008",
                "medium",
                rec,
                f"{rec.agent_id.value} 在 {rec.ticker} 引用 {len(data_points)} 个 data_points，但 {len(missing)} 个缺 source_url。",
                {"total_data_points": len(data_points), "missing_source_url": len(missing)},
            )
        ]
    return []


def _ar_009_long_without_catalysts(rec: Recommendation) -> list[RuleAuditFinding]:
    catalysts = getattr(rec, "catalysts", None)
    if rec.direction == Direction.LONG and not catalysts:
        return [
            _finding(
                "AR-009",
                "high",
                rec,
                f"{rec.agent_id.value} 建议 long {rec.ticker} 但未列出任何 catalyst。",
                {"catalysts": catalysts},
            )
        ]
    return []


def _ar_010_long_without_thesis_kill_criteria(rec: Recommendation) -> list[RuleAuditFinding]:
    criteria = getattr(rec, "thesis_kill_criteria", None)
    if rec.direction == Direction.LONG and not criteria:
        return [
            _finding(
                "AR-010",
                "high",
                rec,
                f"{rec.agent_id.value} 在 {rec.ticker} long 但未定义 thesis_kill_criteria。",
                {"thesis_kill_criteria": criteria},
            )
        ]
    return []


def _ar_011_fengliu_logic_kill_not_avoid(rec: Recommendation) -> list[RuleAuditFinding]:
    if rec.agent_id != AgentId.FENGLIU:
        return []
    confidence = extract_logic_kill_confidence(rec)
    if confidence is not None and confidence >= 0.65 and rec.direction != Direction.AVOID:
        return [
            _finding(
                "AR-011",
                "high",
                rec,
                f"冯柳 Agent 在 {rec.ticker} 识别 logic_kill（confidence={confidence}）但 direction != avoid。",
                {"logic_kill_confidence": confidence, "direction": rec.direction.value},
                ["DEC-014"],
            )
        ]
    return []


def _ar_012_trial_long_disabled_violation(rec: Recommendation) -> list[RuleAuditFinding]:
    policy = getattr(rec, "trial_run_policy", {}) or {}
    original = str(policy.get("original_direction") or "").lower()
    long_disabled = bool(policy.get("long_disabled", True))
    if rec.direction in {Direction.LONG, Direction.SHORT} and long_disabled:
        return [
            _finding(
                "AR-012",
                "critical",
                rec,
                f"{rec.agent_id.value} 在试运行期仍输出 {rec.direction.value}，违反 long/short 禁用策略。",
                {"direction": rec.direction.value, "trial_run_policy": policy},
                ["TRIAL-001"],
            )
        ]
    if original in {"long", "short"} and rec.direction == Direction.WATCH:
        return [
            _finding(
                "AR-012",
                "info",
                rec,
                f"{rec.agent_id.value} 原始方向为 {original}，已由试运行校验层降级为 watch。",
                {"direction": rec.direction.value, "trial_run_policy": policy},
                ["TRIAL-001"],
            )
        ]
    return []


def _ar_013_schema_validation_failure(rec: Recommendation) -> list[RuleAuditFinding]:
    failure = getattr(rec, "validation_failure", None)
    if not isinstance(failure, dict):
        return []
    if failure.get("category") == "schema_validation_failed":
        return [
            _finding(
                "AR-013",
                "high",
                rec,
                f"{rec.agent_id.value} 在 {rec.ticker} 的输出经过 schema 修复仍失败，已按格式失败 abstain。",
                {"validation_failure": failure},
                ["SCHEMA-REPAIR-001"],
            )
        ]
    return []


def _ar_014_methodology_gaps(rec: Recommendation) -> list[RuleAuditFinding]:
    gaps = getattr(rec, "analysis_gaps", None) or getattr(rec, "methodology_gaps", None)
    if not gaps:
        return []
    return [
        _finding(
            "AR-014",
            "medium",
            rec,
            f"{rec.agent_id.value} 在 {rec.ticker} 明确存在证据或方法论缺口，不能升级为交易判断。",
            {"gaps": gaps},
            ["TRIAL-002"],
        )
    ]


def extract_logic_kill_confidence(rec: Recommendation) -> float | None:
    """Extract Fengliu logic_kill confidence as 0-1."""

    heuristic = getattr(rec, "kill_type_heuristic", None) or {}
    if isinstance(heuristic, dict):
        logic_kill = heuristic.get("logic_kill", {}) or {}
        if isinstance(logic_kill, dict) and logic_kill.get("confidence") is not None:
            value = float(logic_kill["confidence"])
            return value / 100 if value > 1 else value
    framework = getattr(rec, "fengliu_specific_framework", {}) or {}
    if framework.get("kill_type_heuristic_verdict") == "logic_kill":
        value = framework.get("kill_type_confidence")
        if value is not None:
            value_float = float(value)
            return value_float / 100 if value_float > 1 else value_float
    return None


def findings_by_recommendation(findings: list[RuleAuditFinding]) -> dict[str, list[RuleAuditFinding]]:
    """Group findings by recommendation id."""

    grouped: dict[str, list[RuleAuditFinding]] = defaultdict(list)
    for finding in findings:
        if finding.target_recommendation_id:
            grouped[finding.target_recommendation_id].append(finding)
    return dict(grouped)
