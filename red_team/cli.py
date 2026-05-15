"""CLI for Red Team Agent."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import click

from chairman.core.input_validator import InputValidationError
from chairman.llm.narrative_generator import LLMError, build_llm_client_from_env
from red_team.core.audit_assembler import assemble_audit
from red_team.core.input_validator import load_red_team_inputs
from red_team.fallback.rules_only import rules_only_fallback
from red_team.persistence.archive import archive_audit

AUDIT_TYPES = ["morning", "evening", "ad_hoc", "escalation_response"]


@click.group()
def cli() -> None:
    """Red Team Agent v0.1."""


@cli.command("validate")
@click.option("--date", "run_date", default=None)
@click.option("--type", "audit_type", default="morning", type=click.Choice(AUDIT_TYPES))
@click.option("--target-brief", default=None)
@click.option("--data-dir", default="data", type=click.Path(path_type=Path))
def validate_command(run_date: str | None, audit_type: str, target_brief: str | None, data_dir: Path) -> None:
    date = normalize_date(run_date)
    try:
        chairman_brief, recommendations, signals, _ = load_red_team_inputs(
            data_dir, date, audit_type, target_brief
        )
    except InputValidationError as exc:
        click.echo("\n".join(exc.errors), err=True)
        raise click.exceptions.Exit(2) from exc
    click.echo(
        f"valid: chairman_brief={chairman_brief['brief_id']} recommendations={len(recommendations)} research_signals={len(signals)}"
    )


@cli.command("audit")
@click.option("--date", "run_date", default=None)
@click.option("--type", "audit_type", default="morning", type=click.Choice(AUDIT_TYPES))
@click.option("--target-brief", default=None)
@click.option("--no-llm", is_flag=True)
@click.option("--rules-only", is_flag=True)
@click.option("--data-dir", default="data", type=click.Path(path_type=Path))
def audit_command(
    run_date: str | None,
    audit_type: str,
    target_brief: str | None,
    no_llm: bool,
    rules_only: bool,
    data_dir: Path,
) -> None:
    date = normalize_date(run_date)
    use_llm = not no_llm and not rules_only
    llm_client = None
    if use_llm:
        try:
            llm_client = build_llm_client_from_env()
        except LLMError:
            use_llm = False

    try:
        chairman_brief, recommendations, signals, _ = load_red_team_inputs(
            data_dir, date, audit_type, target_brief
        )
        audit = assemble_audit(
            chairman_brief=chairman_brief,
            recommendations=recommendations,
            research_signals=signals,
            audit_type=audit_type,
            date=date,
            llm_client=llm_client,
            use_llm=use_llm,
            rules_only=rules_only,
            data_dir=data_dir,
        )
        md_path, json_path = archive_audit(audit, data_dir)
    except Exception as exc:
        try:
            chairman_brief, recommendations, signals, _ = load_red_team_inputs(
                data_dir, date, audit_type, target_brief
            )
            md_path, json_path = rules_only_fallback(
                data_dir=data_dir,
                date=date,
                audit_type=audit_type,
                chairman_brief=chairman_brief,
                recommendations=recommendations,
                research_signals=signals,
                failure_reason=str(exc),
            )
            click.echo(f"rules-only fallback: {md_path}", err=True)
            click.echo(f"metadata: {json_path}", err=True)
            raise click.exceptions.Exit(4) from exc
        except click.exceptions.Exit:
            raise
        except Exception as fallback_exc:
            click.echo(f"red-team failed: {fallback_exc}", err=True)
            raise click.exceptions.Exit(99) from fallback_exc

    click.echo(f"generated: {md_path}")
    click.echo(f"metadata: {json_path}")


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
