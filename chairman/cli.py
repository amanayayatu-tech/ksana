"""CLI entry point for Chairman Agent."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

import click

from chairman.core.brief_assembler import assemble_brief
from chairman.core.input_validator import InputValidationError, load_inputs
from chairman.fallback.raw_passthrough import fallback_passthrough
from chairman.llm.narrative_generator import LLMError, build_llm_client_from_env
from chairman.models import BriefType
from chairman.persistence.archive import archive_brief

logger = logging.getLogger(__name__)


class JsonFormatter(logging.Formatter):
    """Tiny JSON logging formatter for local auditability."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        return json.dumps(payload, ensure_ascii=False)


def setup_logging() -> None:
    """Configure structured logs once."""

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    if not root.handlers:
        root.addHandler(handler)
    root.setLevel(logging.INFO)


@click.group()
def cli() -> None:
    """Chairman Agent v0.1."""

    setup_logging()


@cli.command("validate")
@click.option("--date", "run_date", default=None, help="YYYY-MM-DD or YYYYMMDD")
@click.option("--data-dir", default="data", type=click.Path(path_type=Path))
def validate_command(run_date: str | None, data_dir: Path) -> None:
    """Validate input files only."""

    date = normalize_date(run_date)
    try:
        signals, recommendations, _ = load_inputs(data_dir, date)
    except InputValidationError as exc:
        click.echo("\n".join(exc.errors), err=True)
        raise click.exceptions.Exit(2) from exc
    click.echo(
        f"valid: research_signals={len(signals)} recommendations={len(recommendations)} date={date}"
    )


@cli.command("generate-brief")
@click.option(
    "--type",
    "brief_type",
    required=True,
    type=click.Choice([item.value for item in BriefType]),
)
@click.option("--date", "run_date", default=None, help="YYYY-MM-DD or YYYYMMDD")
@click.option("--trigger-signal", default=None, help="Only include one signal for ad_hoc runs")
@click.option("--no-llm", is_flag=True, help="Use deterministic template narrative")
@click.option("--data-dir", default="data", type=click.Path(path_type=Path))
def generate_brief_command(
    brief_type: str,
    run_date: str | None,
    trigger_signal: str | None,
    no_llm: bool,
    data_dir: Path,
) -> None:
    """Generate Markdown and JSON Chairman brief files."""

    date = normalize_date(run_date)
    llm_client = None
    llm_fallback = False
    use_llm = not no_llm
    if use_llm:
        try:
            llm_client = build_llm_client_from_env()
        except LLMError as exc:
            logger.warning("LLM unavailable; using template narrative: %s", exc)
            use_llm = False
            llm_fallback = True

    try:
        signals, recommendations, consumed = load_inputs(data_dir, date)
        if trigger_signal:
            signals = [signal for signal in signals if signal.research_signal_id == trigger_signal]
        brief = assemble_brief(
            research_signals=signals,
            recommendations=recommendations,
            brief_type=brief_type,
            date=date,
            llm_client=llm_client,
            use_llm=use_llm,
            input_files_consumed=consumed,
            data_dir=data_dir,
        )
        markdown_path, json_path = archive_brief(brief, data_dir)
    except Exception as exc:
        output_path = fallback_passthrough(
            data_dir=data_dir,
            date=date,
            brief_type=brief_type,
            failure_reason=str(exc),
        )
        click.echo(f"fallback generated: {output_path}", err=True)
        raise click.exceptions.Exit(4) from exc

    click.echo(f"generated: {markdown_path}")
    click.echo(f"metadata: {json_path}")
    if llm_fallback:
        raise click.exceptions.Exit(3)


@cli.command("fallback")
@click.option("--date", "run_date", default=None, help="YYYY-MM-DD or YYYYMMDD")
@click.option(
    "--type",
    "brief_type",
    required=True,
    type=click.Choice([item.value for item in BriefType]),
)
@click.option("--failure-reason", default="manual fallback requested")
@click.option("--data-dir", default="data", type=click.Path(path_type=Path))
def fallback_command(
    run_date: str | None,
    brief_type: str,
    failure_reason: str,
    data_dir: Path,
) -> None:
    """Manually generate raw passthrough fallback."""

    date = normalize_date(run_date)
    output_path = fallback_passthrough(
        data_dir=data_dir,
        date=date,
        brief_type=brief_type,
        failure_reason=failure_reason,
    )
    click.echo(f"fallback generated: {output_path}")


def normalize_date(value: str | None) -> str:
    """Normalize dates to YYYY-MM-DD."""

    if not value:
        return datetime.now().strftime("%Y-%m-%d")
    text = value.strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text


def main() -> None:
    """Console script entry."""

    cli()


if __name__ == "__main__":
    main()
