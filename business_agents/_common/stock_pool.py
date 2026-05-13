"""Read-only Nepha stock-pool management."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class StockPoolError(Exception):
    """Stock-pool validation error."""


@dataclass(frozen=True)
class StockPoolEntry:
    ticker: str
    name: str = ""
    market: str = "US"
    tags: list[str] = field(default_factory=list)
    notes: str | None = None
    bucket: str = "main"


class StockPool:
    """Read-only stock-pool view. Agents never write this file."""

    def __init__(self, entries: list[StockPoolEntry], watchlist: list[StockPoolEntry]) -> None:
        self.entries = entries
        self.watchlist = watchlist

    @classmethod
    def load(cls, data_dir: str | Path) -> "StockPool":
        path = Path(data_dir) / "stock_pool" / "master_pool.yaml"
        if not path.exists():
            raise StockPoolError(f"stock pool not found: {path}")
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        pool = data.get("stock_pool", data)
        entries: list[StockPoolEntry] = []
        watchlist: list[StockPoolEntry] = []
        for item in pool.get("hk_stocks", []) or []:
            entries.append(_entry(item, "HK", "main"))
        for item in pool.get("us_stocks", []) or []:
            entries.append(_entry(item, "US", "main"))
        for item in pool.get("a_stocks_reference_only", []) or []:
            entries.append(_entry(item, "A", "a_reference"))
        for item in pool.get("watchlist", []) or []:
            watchlist.append(_entry(item, _infer_market(item.get("ticker", "")), "watchlist"))
        if not entries and not watchlist:
            raise StockPoolError("stock pool is empty")
        return cls(entries, watchlist)

    def all_allowed_research_tickers(self) -> set[str]:
        return {entry.ticker for entry in self.entries if entry.bucket in {"main", "a_reference"}}

    def trading_tickers(self) -> set[str]:
        return {entry.ticker for entry in self.entries if entry.bucket == "main" and entry.market in {"HK", "US"}}

    def watchlist_tickers(self) -> set[str]:
        return {entry.ticker for entry in self.watchlist}

    def a_share_tickers(self) -> set[str]:
        return {entry.ticker for entry in self.entries if entry.market == "A" or entry.bucket == "a_reference"}

    def first_tradable(self) -> StockPoolEntry:
        for entry in self.entries:
            if entry.ticker in self.trading_tickers():
                return entry
        raise StockPoolError("no tradable HK/US tickers in stock pool")

    def to_prompt_dict(self) -> dict[str, Any]:
        return {
            "main": [entry.__dict__ for entry in self.entries if entry.bucket == "main"],
            "a_reference_only": [entry.__dict__ for entry in self.entries if entry.bucket == "a_reference"],
            "watchlist": [entry.__dict__ for entry in self.watchlist],
        }


def _entry(item: dict[str, Any], market: str, bucket: str) -> StockPoolEntry:
    return StockPoolEntry(
        ticker=str(item.get("ticker", "")).strip(),
        name=str(item.get("name", "") or ""),
        market=market,
        tags=list(item.get("tags", []) or []),
        notes=item.get("notes") or item.get("reason_to_watch"),
        bucket=bucket,
    )


def _infer_market(ticker: str) -> str:
    if ticker.endswith(".HK"):
        return "HK"
    if ticker.endswith((".SH", ".SZ")):
        return "A"
    return "US"
