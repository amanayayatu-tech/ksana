"""CLI for GPartner trading agent."""

from __future__ import annotations

from pathlib import Path

import click

from business_agents._common.output_validator import OutputValidationError
from business_agents._common.stock_pool import StockPoolError
from business_agents.trading_g_partner.agent import GPartnerTradingAgent


@click.group()
def cli() -> None:
    """GPartner trading agent."""


@cli.command("run")
@click.option("--no-llm", is_flag=True)
@click.option("--date", "run_date", default=None)
@click.option("--data-dir", default="data", type=click.Path(path_type=Path))
def run_command(no_llm: bool, run_date: str | None, data_dir: Path) -> None:
    try:
        result = GPartnerTradingAgent(data_dir=data_dir, run_date=run_date).run(no_llm=no_llm)
    except StockPoolError as exc:
        click.echo(str(exc), err=True)
        raise click.exceptions.Exit(1) from exc
    except OutputValidationError as exc:
        click.echo(str(exc), err=True)
        raise click.exceptions.Exit(2) from exc
    except Exception as exc:
        click.echo(f"trading-g_partner failed: {exc}", err=True)
        raise click.exceptions.Exit(99) from exc
    for path in result.output_files:
        click.echo(f"generated: {path}")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
