"""Financial data helpers."""

from __future__ import annotations

from business_agents._common.market_data.yfinance_client import YFinanceClient


def compact_financial_snapshot(ticker: str) -> dict:
    """Return a compact public-data snapshot for prompt rendering."""

    client = YFinanceClient()
    history = client.get_history(ticker, period="1mo")
    recent = history[-10:]
    change_values = [
        abs(float(row["change_pct"]))
        for row in recent
        if row.get("change_pct") is not None
    ]
    latest = recent[-1] if recent else {}

    return {
        "ticker": ticker,
        "recent_price": latest.get("close"),
        "recent_price_date": latest.get("date"),
        "recent_10d": recent,
        "max_abs_change_pct_10d": max(change_values) if change_values else None,
        "volume_20d_average": client.get_volume_20d_average(ticker),
        "valuation": {"pe": None, "pb": None, "ps": None},
        "cash_flow": {"free_cash_flow": None},
        "source_url": f"https://finance.yahoo.com/quote/{ticker}",
        "evidence_unverified": not bool(recent),
    }
