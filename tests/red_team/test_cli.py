from __future__ import annotations

import yaml
from click.testing import CliRunner

from chairman.core.brief_assembler import assemble_brief
from chairman.persistence.archive import archive_brief
from red_team.cli import cli
from tests.conftest import make_fengliu, make_liguofei, make_signal, make_wanmu


def write_red_team_inputs(data_dir):
    signal = make_signal()
    recs = [make_fengliu("long"), make_wanmu("watch"), make_liguofei("watch")]
    signal_dir = data_dir / "research_signals"
    rec_root = data_dir / "recommendations" / "20260513"
    signal_dir.mkdir(parents=True)
    for agent in ["fengliu", "wanmu", "liguofei"]:
        (rec_root / agent).mkdir(parents=True)
    (signal_dir / "RS-20260513-001.yaml").write_text(
        yaml.safe_dump({"research_signal": signal.model_dump(mode="json")}, allow_unicode=True),
        encoding="utf-8",
    )
    for agent_dir, rec in zip(["fengliu", "wanmu", "liguofei"], recs, strict=True):
        (rec_root / agent_dir / f"{rec.recommendation_id}.yaml").write_text(
            yaml.safe_dump({"recommendation": rec.model_dump(mode="json")}, allow_unicode=True),
            encoding="utf-8",
        )
    brief = assemble_brief(
        research_signals=[signal],
        recommendations=recs,
        brief_type="morning",
        date="2026-05-13",
        use_llm=False,
    )
    archive_brief(brief, data_dir)


def test_red_team_cli_generates_audit_and_rules_only(tmp_path):
    data_dir = tmp_path / "data"
    write_red_team_inputs(data_dir)
    runner = CliRunner()

    validate_result = runner.invoke(
        cli,
        ["validate", "--date", "2026-05-13", "--type", "morning", "--data-dir", str(data_dir)],
    )
    assert validate_result.exit_code == 0, validate_result.output

    audit_result = runner.invoke(
        cli,
        [
            "audit",
            "--date",
            "2026-05-13",
            "--type",
            "morning",
            "--data-dir",
            str(data_dir),
            "--no-llm",
        ],
    )
    assert audit_result.exit_code == 0, audit_result.output
    assert (data_dir / "red_team_audits" / "20260513" / "AUDIT-20260513-AM.md").exists()
    assert (data_dir / "red_team_audits" / "20260513" / "AUDIT-20260513-AM.json").exists()

    rules_result = runner.invoke(
        cli,
        [
            "audit",
            "--date",
            "2026-05-13",
            "--type",
            "morning",
            "--data-dir",
            str(data_dir),
            "--rules-only",
        ],
    )
    assert rules_result.exit_code == 0, rules_result.output
