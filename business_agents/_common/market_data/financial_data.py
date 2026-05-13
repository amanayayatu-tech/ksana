"""Financial data helpers."""

from __future__ import annotations


def compact_financial_snapshot(ticker: str) -> dict:
    """Return a compact placeholder financial snapshot for prompt rendering."""

    return {
        "ticker": ticker,
        "valuation": {"pe": None, "pb": None, "ps": None},
        "cash_flow": {"free_cash_flow": None},
        "source_url": f"https://finance.yahoo.com/quote/{ticker}",
    }
