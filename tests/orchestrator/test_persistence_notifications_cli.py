from __future__ import annotations

import json

from click.testing import CliRunner

from orchestrator.cli import cli
from orchestrator.core.pipeline import run_step_by_name
from orchestrator.notifications.local_notifier import LocalNotifier
from orchestrator.notifications.notifier import NotificationMessage
from orchestrator.persistence.run_log import RunLog


def test_run_log_creation(tmp_path):
    run_log = RunLog(tmp_path / "data" / "orchestrator" / "runs.db")
    run_id = run_log.create_run(pipeline_type="full", trigger_source="manual")
    run_log.finish_run(run_id, "completed")

    rows = run_log.list_runs(tail=1)
    assert rows[0]["run_id"] == run_id
    assert rows[0]["status"] == "completed"


def test_rerun_from_step(tmp_path):
    result = run_step_by_name(
        step_name="research_scan",
        brief_type="morning",
        date="2026-05-13",
        data_dir=tmp_path / "data",
    )

    assert result.status == "success"


def test_local_notifier(tmp_path):
    sent = LocalNotifier(tmp_path / "data").send(
        NotificationMessage(title="test", body="body", priority="normal")
    )

    assert sent is True
    assert list((tmp_path / "data" / "notifications").rglob("notification.log"))


def test_critical_finding_high_priority_notification(tmp_path):
    LocalNotifier(tmp_path / "data").send(
        NotificationMessage(title="Red Team critical", body="finding", priority="critical")
    )
    log = next((tmp_path / "data" / "notifications").rglob("notification.log")).read_text()
    assert "[critical]" in log


def test_orchestrator_cli_history_and_notify(tmp_path):
    data_dir = tmp_path / "data"
    run_log = RunLog(data_dir / "orchestrator" / "runs.db")
    run_id = run_log.create_run(pipeline_type="full", trigger_source="manual")
    run_log.finish_run(run_id, "completed")
    runner = CliRunner()

    history = runner.invoke(cli, ["history", "--data-dir", str(data_dir), "--tail", "1"])
    assert history.exit_code == 0
    assert json.loads(history.output)[0]["run_id"] == run_id

    notify = runner.invoke(cli, ["notify-test", "--data-dir", str(data_dir)])
    assert notify.exit_code == 0
    assert "sent" in notify.output


def test_orchestrator_cli_wait_for_perplexity(tmp_path):
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "wait-for-perplexity-fill",
            "--run-id",
            "RUN-CLI",
            "--timeout",
            "0",
            "--data-dir",
            str(tmp_path / "data"),
        ],
    )
    assert result.exit_code == 0
    assert "skipped_no_p0" in result.output
