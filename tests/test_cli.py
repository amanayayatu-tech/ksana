from __future__ import annotations

import yaml
from click.testing import CliRunner

from chairman.cli import cli
from tests.conftest import make_fengliu, make_liguofei, make_signal, make_wanmu


def write_mock_inputs(data_dir):
    signal_dir = data_dir / "research_signals"
    rec_root = data_dir / "recommendations" / "20260513"
    signal_dir.mkdir(parents=True)
    (rec_root / "fengliu").mkdir(parents=True)
    (rec_root / "wanmu").mkdir(parents=True)
    (rec_root / "liguofei").mkdir(parents=True)

    (signal_dir / "RS-20260513-001.yaml").write_text(
        yaml.safe_dump({"research_signal": make_signal().model_dump(mode="json")}, allow_unicode=True),
        encoding="utf-8",
    )
    fixtures = [
        ("fengliu", make_fengliu("long")),
        ("wanmu", make_wanmu("watch")),
        ("liguofei", make_liguofei("watch")),
    ]
    for agent_dir, rec in fixtures:
        (rec_root / agent_dir / f"{rec.recommendation_id}.yaml").write_text(
            yaml.safe_dump({"recommendation": rec.model_dump(mode="json")}, allow_unicode=True),
            encoding="utf-8",
        )


def test_cli_validate_and_generate_three_brief_types(tmp_path):
    data_dir = tmp_path / "data"
    write_mock_inputs(data_dir)
    runner = CliRunner()

    validate_result = runner.invoke(
        cli,
        ["validate", "--date", "2026-05-13", "--data-dir", str(data_dir)],
    )
    assert validate_result.exit_code == 0, validate_result.output

    for brief_type, suffix in [
        ("morning", "AM"),
        ("evening", "PM"),
        ("ad_hoc", "ADHOC"),
    ]:
        result = runner.invoke(
            cli,
            [
                "generate-brief",
                "--type",
                brief_type,
                "--date",
                "2026-05-13",
                "--data-dir",
                str(data_dir),
                "--no-llm",
            ],
        )
        assert result.exit_code == 0, result.output
        assert (data_dir / "briefs" / "20260513" / f"BRIEF-20260513-{suffix}.md").exists()
        assert (data_dir / "briefs" / "20260513" / f"BRIEF-20260513-{suffix}.json").exists()
