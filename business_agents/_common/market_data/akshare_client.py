"""Optional AKShare adapter for A-share reference-only research."""

from __future__ import annotations


class AKShareClient:
    """A-share reference data adapter. Not used for trading recommendations."""

    def get_history(self, ticker: str) -> list[dict]:
        return [{"ticker": ticker, "reference_only": True}]

    def get_financials(self, ticker: str) -> dict:
        return {"ticker": ticker, "reference_only": True}
