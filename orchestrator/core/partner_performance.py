"""Partner recommendation log used by Chairman, not by trading agents."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
import json
from pathlib import Path
from typing import Any

from chairman.models import ChairmanBrief

PERFORMANCE_DIRNAME = "partner_performance"
SNAPSHOT_FILENAME = "recommendation_log.json"
REVIEW_DIRNAME = "reviews"


def append_partner_snapshots_from_brief(brief: ChairmanBrief, data_dir: str | Path) -> Path:
    root = Path(data_dir)
    output_dir = root / PERFORMANCE_DIRNAME
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / SNAPSHOT_FILENAME
    existing = load_snapshots(output_path)
    by_id = {snapshot["snapshot_id"]: snapshot for snapshot in existing}
    for summary in brief.per_recommendation_summary:
        for view in summary.get("individual_views", []):
            snapshot = build_snapshot(brief.brief_id, summary, view)
            by_id[snapshot["snapshot_id"]] = merge_partner_snapshot(
                by_id.get(snapshot["snapshot_id"]),
                snapshot,
            )
    output_path.write_text(
        json.dumps(list(by_id.values()), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output_path


def load_partner_performance_context(data_dir: str | Path | None) -> dict[str, Any]:
    if data_dir is None:
        return {"visibility": "chairman_only", "profiles": {}, "verified_outcomes_available": False}
    path = Path(data_dir) / PERFORMANCE_DIRNAME / SNAPSHOT_FILENAME
    snapshots = load_snapshots(path)
    profiles: dict[str, dict[str, Any]] = {}
    by_agent: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for snapshot in snapshots:
        by_agent[str(snapshot.get("agent_id"))].append(snapshot)
    for agent_id, items in by_agent.items():
        direction_counts = Counter(str(item.get("direction")) for item in items)
        status_counts = Counter(str(item.get("verification_status")) for item in items)
        multiplier = calculate_performance_weight_multiplier(status_counts)
        profiles[agent_id] = {
            "total_recommendations_logged": len(items),
            "direction_counts": dict(direction_counts),
            "verification_status_counts": dict(status_counts),
            "verified_outcomes_available": any(status != "pending" for status in status_counts),
            "validated_rate": safe_rate(status_counts["validated"], len(items)),
            "invalidated_rate": safe_rate(status_counts["invalidated"], len(items)),
            "performance_weight_multiplier": multiplier,
            "visibility": "chairman_only",
        }
    latest_review = latest_partner_review_path(Path(data_dir))
    return {
        "visibility": "chairman_only",
        "profiles": profiles,
        "verified_outcomes_available": any(
            profile["verified_outcomes_available"] for profile in profiles.values()
        ),
        "latest_review_path": str(latest_review) if latest_review else "",
    }


def load_snapshots(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8") or "[]")
    return data if isinstance(data, list) else []


def build_snapshot(brief_id: str, summary: dict[str, Any], view: dict[str, Any]) -> dict[str, Any]:
    recommendation_id = str(view.get("recommendation_id") or "")
    return {
        "snapshot_id": f"PP-{brief_id}-{recommendation_id}",
        "source_brief_id": brief_id,
        "recommendation_id": recommendation_id,
        "agent_id": view.get("agent_id"),
        "ticker": summary.get("ticker"),
        "direction": view.get("direction"),
        "confidence": view.get("confidence"),
        "verification_status": "pending",
        "evidence_url": "",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def merge_partner_snapshot(existing: dict[str, Any] | None, generated: dict[str, Any]) -> dict[str, Any]:
    """Preserve manual outcome annotations when regenerating a brief."""

    if not existing:
        return generated
    merged = {**existing, **generated}
    if existing.get("verification_status") and existing.get("verification_status") != "pending":
        for key in (
            "verification_status",
            "evidence_url",
            "verification_notes",
            "verified_at",
            "verified_by",
        ):
            if key in existing:
                merged[key] = existing[key]
    elif existing.get("evidence_url"):
        merged["evidence_url"] = existing["evidence_url"]
    merged["created_at"] = existing.get("created_at") or generated.get("created_at")
    return merged


def calculate_performance_weight_multiplier(status_counts: Counter[str]) -> float:
    validated = status_counts["validated"]
    partial = status_counts["partially_validated"]
    invalidated = status_counts["invalidated"]
    inconclusive = status_counts["inconclusive"]
    total_resolved = validated + partial + invalidated + inconclusive
    if total_resolved == 0:
        return 1.0
    score = (validated * 1.0 + partial * 0.45 + inconclusive * 0.0 - invalidated * 0.75) / total_resolved
    return round(max(0.75, min(1.25, 1.0 + score * 0.2)), 4)


def safe_rate(count: int, total: int) -> float:
    return round(count / total, 4) if total else 0.0


def generate_partner_review_report(
    data_dir: str | Path,
    *,
    as_of_date: str | None = None,
) -> dict[str, Any]:
    """Generate a compact investment-committee review from logged partner snapshots."""

    root = Path(data_dir)
    snapshots = load_snapshots(root / PERFORMANCE_DIRNAME / SNAPSHOT_FILENAME)
    verification_cases = load_verification_cases(root)
    red_team_objections = load_red_team_objections(root)
    case_by_ticker = {case.get("ticker"): case for case in verification_cases}
    by_agent: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for snapshot in snapshots:
        by_agent[str(snapshot.get("agent_id"))].append(snapshot)

    profiles = {}
    for agent_id, items in by_agent.items():
        direction_counts = Counter(str(item.get("direction")) for item in items)
        status_counts = Counter(str(item.get("verification_status")) for item in items)
        ticker_counts = Counter(str(item.get("ticker")) for item in items)
        profiles[agent_id] = {
            "total_recommendations": len(items),
            "direction_counts": dict(direction_counts),
            "verification_status_counts": dict(status_counts),
            "performance_weight_multiplier": calculate_performance_weight_multiplier(status_counts),
            "most_common_tickers": ticker_counts.most_common(5),
            "known_open_verification_cases": [
                case_by_ticker[item.get("ticker")]
                for item in items[:10]
                if item.get("ticker") in case_by_ticker
            ],
            "diagnosis": diagnose_agent_profile(direction_counts, status_counts),
        }

    return {
        "report_id": f"PARTNER-REVIEW-{(as_of_date or datetime.now().date().isoformat()).replace('-', '')}",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "as_of_date": as_of_date or datetime.now().date().isoformat(),
        "visibility": "chairman_and_nepha_only",
        "profiles": profiles,
        "red_team_effectiveness": summarize_red_team_effectiveness(red_team_objections, case_by_ticker),
        "system_observations": build_system_observations(profiles),
        "methodology_upgrade_policy": "不允许 Agent 自动改写方法论；低表现只触发 Nepha 人工复盘。",
    }


def write_partner_review_report(data_dir: str | Path, *, as_of_date: str | None = None) -> tuple[Path, Path]:
    root = Path(data_dir)
    report = generate_partner_review_report(root, as_of_date=as_of_date)
    output_dir = root / PERFORMANCE_DIRNAME / REVIEW_DIRNAME
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{report['report_id']}.json"
    md_path = output_dir / f"{report['report_id']}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_partner_review_markdown(report), encoding="utf-8")
    return md_path, json_path


def load_verification_cases(root: Path) -> list[dict[str, Any]]:
    path = root / "decision_verification" / "pending_cases.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8") or "[]")
    return data if isinstance(data, list) else []


def load_red_team_objections(root: Path) -> list[dict[str, Any]]:
    objections: list[dict[str, Any]] = []
    for path in sorted((root / "red_team_audits").glob("**/AUDIT-*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8") or "{}")
        except json.JSONDecodeError:
            continue
        for item in data.get("substantive_objections", []) or []:
            objections.append({**item, "source_audit_path": str(path)})
    return objections


def summarize_red_team_effectiveness(
    objections: list[dict[str, Any]],
    case_by_ticker: dict[Any, dict[str, Any]],
) -> dict[str, Any]:
    verdict_counts = Counter(str(item.get("red_team_verdict")) for item in objections)
    validated: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    for item in objections:
        case = case_by_ticker.get(item.get("ticker"))
        row = {
            "ticker": item.get("ticker"),
            "red_team_verdict": item.get("red_team_verdict"),
            "strongest_objection": item.get("strongest_objection"),
            "verification_status": (case or {}).get("status", "no_case"),
            "source_audit_path": item.get("source_audit_path"),
        }
        if row["verification_status"] in {"validated", "partially_validated", "invalidated"}:
            validated.append(row)
        else:
            pending.append(row)
    return {
        "total_objections_logged": len(objections),
        "verdict_counts": dict(verdict_counts),
        "validated_or_invalidated_samples": validated[:10],
        "pending_samples": pending[:10],
        "note": "Red Team 有效性以 decision_verification 状态为准；没有 evidence_url 的样本不计入最终表现。",
    }


def diagnose_agent_profile(direction_counts: Counter[str], status_counts: Counter[str]) -> list[str]:
    notes: list[str] = []
    total = sum(direction_counts.values())
    if total and direction_counts["abstain"] / total > 0.5:
        notes.append("abstain 比例偏高，可能过度保守或证据输入不足。")
    if total and direction_counts["avoid"] / total > 0.45:
        notes.append("avoid 比例偏高，需复盘是否过度风险规避。")
    if status_counts["invalidated"] > status_counts["validated"]:
        notes.append("已验证样本中 invalidated 多于 validated，Chairman 应下调其类似场景权重。")
    if not notes:
        notes.append("样本不足或表现暂未显示结构性偏差。")
    return notes


def build_system_observations(profiles: dict[str, Any]) -> list[str]:
    if not profiles:
        return ["尚无 Partner Performance 样本；先积累，不调整方法论。"]
    observations = []
    for agent_id, profile in profiles.items():
        observations.append(
            f"{agent_id}: {profile['total_recommendations']} 条记录，历史表现权重 ×{profile['performance_weight_multiplier']}。"
        )
    return observations


def render_partner_review_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# {report['report_id']}",
        "",
        f"- generated_at: {report['generated_at']}",
        f"- visibility: {report['visibility']}",
        "",
        "## System Observations",
    ]
    lines.extend(f"- {item}" for item in report.get("system_observations") or [])
    lines.append("")
    lines.append("## Partner Profiles")
    for agent_id, profile in (report.get("profiles") or {}).items():
        lines.extend(
            [
                "",
                f"### {agent_id}",
                f"- total_recommendations: {profile.get('total_recommendations')}",
                f"- performance_weight_multiplier: {profile.get('performance_weight_multiplier')}",
                f"- direction_counts: {profile.get('direction_counts')}",
                f"- verification_status_counts: {profile.get('verification_status_counts')}",
                "- diagnosis:",
            ]
        )
        lines.extend(f"  - {item}" for item in profile.get("diagnosis") or [])
    lines.append("")
    lines.append("## Red Team Effectiveness")
    red_team = report.get("red_team_effectiveness") or {}
    lines.append(f"- total_objections_logged: {red_team.get('total_objections_logged', 0)}")
    lines.append(f"- verdict_counts: {red_team.get('verdict_counts', {})}")
    lines.append(f"- note: {red_team.get('note', '')}")
    lines.extend(["", f"> {report['methodology_upgrade_policy']}", ""])
    return "\n".join(lines)


def latest_partner_review_path(root: Path) -> Path | None:
    review_dir = root / PERFORMANCE_DIRNAME / REVIEW_DIRNAME
    if not review_dir.exists():
        return None
    reports = sorted(review_dir.glob("PARTNER-REVIEW-*.json"))
    return reports[-1] if reports else None
