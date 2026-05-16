"""CLI for Orchestrator."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

import click
import yaml

from orchestrator.core.event_listener import AdHocThrottle
from orchestrator.core.learning import (
    rebuild_stock_timelines,
    rebuild_learning_from_archived_briefs,
    refresh_outcome_snapshots,
    write_monthly_review,
)
from orchestrator.core.perplexity_wait import wait_for_perplexity_fill
from orchestrator.core.pipeline import run_full_pipeline, run_step_by_name
from orchestrator.core.scheduler import load_scheduler_config
from orchestrator.daemon import daemon_status
from orchestrator.notifications.local_notifier import LocalNotifier
from orchestrator.notifications.notifier import NotificationMessage
from orchestrator.persistence.run_log import RunLog


@click.group()
def cli() -> None:
    """Orchestrator v0.1."""


@cli.group("daemon")
def daemon_group() -> None:
    """Daemon controls."""


@daemon_group.command("start")
def daemon_start() -> None:
    click.echo("daemon configured; use system scheduler or foreground runner to keep it alive")


@daemon_group.command("stop")
def daemon_stop() -> None:
    click.echo("daemon stop requested")


@daemon_group.command("status")
def daemon_status_command() -> None:
    click.echo(daemon_status())


@cli.command("run")
@click.option("--type", "pipeline_type", default="full", type=click.Choice(["full", "ad_hoc"]))
@click.option("--brief-type", default="morning", type=click.Choice(["morning", "evening", "ad_hoc"]))
@click.option("--date", "run_date", default=None)
@click.option("--trigger-signal", default=None)
@click.option("--data-dir", default="data", type=click.Path(path_type=Path))
def run_command(
    pipeline_type: str,
    brief_type: str,
    run_date: str | None,
    trigger_signal: str | None,
    data_dir: Path,
) -> None:
    date = normalize_date(run_date)
    if pipeline_type == "ad_hoc":
        throttle = AdHocThrottle(data_dir)
        if not throttle.allow():
            click.echo("ad_hoc throttled", err=True)
            raise click.exceptions.Exit(1)
        throttle.record()
        brief_type = "ad_hoc"
    result = run_full_pipeline(brief_type=brief_type, date=date, data_dir=data_dir)
    click.echo(f"run_id={result.run_id} status={result.status} trigger_signal={trigger_signal or ''}")
    if result.status not in {"completed", "partial_success"}:
        raise click.exceptions.Exit(4)


@cli.command("run-step")
@click.argument("step_name")
@click.option("--brief-type", default="morning", type=click.Choice(["morning", "evening", "ad_hoc"]))
@click.option("--date", "run_date", default=None)
@click.option("--data-dir", default="data", type=click.Path(path_type=Path))
def run_step_command(step_name: str, brief_type: str, run_date: str | None, data_dir: Path) -> None:
    result = run_step_by_name(
        step_name=step_name,
        brief_type=brief_type,
        date=normalize_date(run_date),
        data_dir=data_dir,
    )
    click.echo(f"{result.step_name}: {result.status} exit_code={result.exit_code}")
    if result.status != "success":
        raise click.exceptions.Exit(4)


@cli.command("wait-for-perplexity-fill")
@click.option("--run-id", required=True)
@click.option("--timeout", "timeout_seconds", default=1800, type=int)
@click.option("--poll-interval", default=30, type=int)
@click.option("--data-dir", default="data", type=click.Path(path_type=Path))
def wait_for_perplexity_command(
    run_id: str,
    timeout_seconds: int,
    poll_interval: int,
    data_dir: Path,
) -> None:
    result = asyncio.run(
        wait_for_perplexity_fill(
            data_dir=data_dir,
            run_id=run_id,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval,
        )
    )
    click.echo(json.dumps(result.__dict__, ensure_ascii=False))


@cli.command("history")
@click.option("--date", "run_date", default=None)
@click.option("--status", default=None)
@click.option("--tail", default=10, type=int)
@click.option("--data-dir", default="data", type=click.Path(path_type=Path))
def history_command(run_date: str | None, status: str | None, tail: int, data_dir: Path) -> None:
    rows = RunLog(data_dir / "orchestrator" / "runs.db").list_runs(
        date=normalize_date(run_date) if run_date else None,
        status=status,
        tail=tail,
    )
    click.echo(json.dumps(rows, ensure_ascii=False, indent=2))


@cli.command("rerun")
@click.option("--run-id", required=True)
@click.option("--from-step", default="chairman")
@click.option("--brief-type", default="morning")
@click.option("--date", "run_date", default=None)
@click.option("--data-dir", default="data", type=click.Path(path_type=Path))
def rerun_command(run_id: str, from_step: str, brief_type: str, run_date: str | None, data_dir: Path) -> None:
    del run_id
    result = run_step_by_name(
        step_name=from_step,
        brief_type=brief_type,
        date=normalize_date(run_date),
        data_dir=data_dir,
    )
    click.echo(f"rerun {from_step}: {result.status}")


@cli.command("notify-test")
@click.option("--channel", default="local")
@click.option("--data-dir", default="data", type=click.Path(path_type=Path))
def notify_test_command(channel: str, data_dir: Path) -> None:
    if channel != "local":
        click.echo("only local notifier is configured in v0.1", err=True)
        raise click.exceptions.Exit(1)
    sent = LocalNotifier(data_dir, echo=False).send(
        NotificationMessage(title="Orchestrator notify test", body="ok", priority="normal")
    )
    click.echo("sent" if sent else "failed")


@cli.group("config")
def config_group() -> None:
    """Config commands."""


@config_group.command("show")
@click.option("--config-path", default=None, type=click.Path(path_type=Path))
def config_show_command(config_path: Path | None) -> None:
    click.echo(yaml.safe_dump(load_scheduler_config(config_path), allow_unicode=True, sort_keys=False))


@cli.group("learning")
def learning_group() -> None:
    """Decision learning, outcome snapshots, and timeline reports."""


@learning_group.command("refresh-outcomes")
@click.option("--as-of-date", default=None)
@click.option("--data-dir", default="data", type=click.Path(path_type=Path))
def learning_refresh_outcomes_command(as_of_date: str | None, data_dir: Path) -> None:
    path = refresh_outcome_snapshots(data_dir, as_of_date=normalize_date(as_of_date) if as_of_date else None)
    click.echo(f"outcome_snapshots={path}")


@learning_group.command("rebuild-cases")
@click.option("--data-dir", default="data", type=click.Path(path_type=Path))
def learning_rebuild_cases_command(data_dir: Path) -> None:
    path = rebuild_learning_from_archived_briefs(data_dir)
    click.echo(f"decision_cases={path}")


@learning_group.command("build-timelines")
@click.option("--ticker", default=None)
@click.option("--data-dir", default="data", type=click.Path(path_type=Path))
def learning_build_timelines_command(ticker: str | None, data_dir: Path) -> None:
    paths = rebuild_stock_timelines(data_dir, ticker=ticker)
    click.echo(json.dumps([str(path) for path in paths], ensure_ascii=False, indent=2))


@learning_group.command("monthly-review")
@click.option("--month", default=None, help="YYYY-MM")
@click.option("--data-dir", default="data", type=click.Path(path_type=Path))
def learning_monthly_review_command(month: str | None, data_dir: Path) -> None:
    paths = write_monthly_review(data_dir, month=month)
    if not paths:
        click.echo("no learning cases found")
        return
    click.echo(f"monthly_review_md={paths[0]}")
    click.echo(f"monthly_review_json={paths[1]}")


def normalize_date(value: str | None) -> str:
    if not value:
        return datetime.now().strftime("%Y-%m-%d")
    text = value.strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
