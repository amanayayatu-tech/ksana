"""Optional yfinance market-data adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Quote:
    ticker: str
    price: float | None = None
    currency: str | None = None
    source_url: str | None = None
    evidence_unverified: bool = False


class YFinanceClient:
    """Free market-data adapter with graceful fallback if yfinance is unavailable."""

    def get_quote(self, ticker: str) -> Quote:
        try:
            import yfinance as yf  # type: ignore

            info = yf.Ticker(ticker).fast_info
            return Quote(
                ticker=ticker,
                price=float(info.get("last_price")) if info.get("last_price") is not None else None,
                currency=info.get("currency"),
                source_url=f"https://finance.yahoo.com/quote/{ticker}",
            )
        except Exception:
            return Quote(
                ticker=ticker,
                price=None,
                source_url=f"https://finance.yahoo.com/quote/{ticker}",
                evidence_unverified=True,
            )

    def get_history(self, ticker: str, period: str = "7d") -> list[dict[str, Any]]:
        del period
        return [{"ticker": ticker, "change_pct": 0, "source_url": f"https://finance.yahoo.com/quote/{ticker}"}]

    def get_financials(self, ticker: str) -> dict[str, Any]:
        return {"ticker": ticker, "source_url": f"https://finance.yahoo.com/quote/{ticker}/financials"}

    def get_options(self, ticker: str) -> dict[str, Any] | None:
        return {"ticker": ticker, "source_url": f"https://finance.yahoo.com/quote/{ticker}/options"}

    def get_volume_20d_average(self, ticker: str) -> float:
        del ticker
        return 0.0
