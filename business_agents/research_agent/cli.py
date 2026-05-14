"""CLI for 4.1 research agent."""

from __future__ import annotations

from pathlib import Path

import click

from business_agents._common.output_validator import OutputValidationError, validate_research_agent_output
from business_agents._common.stock_pool import StockPool, StockPoolError
from business_agents.research_agent.agent import ResearchAgent


@click.group()
def cli() -> None:
    """4.1 research upstream agent."""


@cli.command("run")
@click.option("--type", "run_type", default="scan", type=click.Choice(["scan", "event"]))
@click.option("--signal", default=None)
@click.option("--no-llm", is_flag=True)
@click.option("--date", "run_date", default=None)
@click.option("--data-dir", default="data", type=click.Path(path_type=Path))
def run_command(run_type: str, signal: str | None, no_llm: bool, run_date: str | None, data_dir: Path) -> None:
    del signal
    try:
        result = ResearchAgent(data_dir=data_dir, run_date=run_date).run(trigger_type=run_type, no_llm=no_llm)
    except StockPoolError as exc:
        click.echo(str(exc), err=True)
        raise click.exceptions.Exit(1) from exc
    except OutputValidationError as exc:
        click.echo(str(exc), err=True)
        raise click.exceptions.Exit(2) from exc
    except Exception as exc:
        click.echo(f"research-agent failed: {exc}", err=True)
        raise click.exceptions.Exit(99) from exc
    for path in result.output_files:
        click.echo(f"generated: {path}")


@cli.command("validate-output")
@click.option("--signal-id", required=True)
@click.option("--data-dir", default="data", type=click.Path(path_type=Path))
def validate_output_command(signal_id: str, data_dir: Path) -> None:
    import yaml

    stock_pool = StockPool.load(data_dir)
    path = data_dir / "research_signals" / f"{signal_id}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    validate_research_agent_output(
        {"research_signals": [data.get("research_signal", data)], "perplexity_prompt_brief": {"brief_id": "VALIDATE", "prompts": []}},
        stock_pool,
    )
    click.echo(f"valid: {signal_id}")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
