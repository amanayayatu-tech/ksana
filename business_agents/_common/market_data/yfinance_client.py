"""Free Yahoo Finance market-data adapter."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen


@dataclass
class Quote:
    ticker: str
    price: float | None = None
    currency: str | None = None
    source_url: str | None = None
    evidence_unverified: bool = False


class YFinanceClient:
    """Free market-data adapter with graceful network fallback.

    The first phase intentionally avoids paid data sources. This client uses Yahoo's
    public chart endpoint and returns empty/unverified data instead of synthesizing
    prices when the endpoint is unavailable.
    """

    def get_quote(self, ticker: str) -> Quote:
        history = self.get_history(ticker, period="1mo")
        if history:
            latest = history[-1]
            return Quote(
                ticker=ticker,
                price=_float_or_none(latest.get("close")),
                source_url=f"https://finance.yahoo.com/quote/{ticker}",
                evidence_unverified=bool(latest.get("evidence_unverified")),
            )
        return Quote(
            ticker=ticker,
            price=None,
            source_url=f"https://finance.yahoo.com/quote/{ticker}",
            evidence_unverified=True,
        )

    def get_history(self, ticker: str, period: str = "7d") -> list[dict[str, Any]]:
        chart = self._fetch_chart(ticker, period)
        if not chart:
            return []

        timestamps = chart.get("timestamp") or []
        quote_payload = ((chart.get("indicators") or {}).get("quote") or [{}])[0]
        opens = quote_payload.get("open") or []
        highs = quote_payload.get("high") or []
        lows = quote_payload.get("low") or []
        closes = quote_payload.get("close") or []
        volumes = quote_payload.get("volume") or []
        source_url = f"https://finance.yahoo.com/quote/{ticker}"
        rows: list[dict[str, Any]] = []
        previous_close: float | None = None
        for index, timestamp in enumerate(timestamps):
            close = _float_or_none(_at(closes, index))
            open_price = _float_or_none(_at(opens, index))
            if close is None:
                continue
            change_pct = (
                round((close - previous_close) / previous_close * 100, 4)
                if previous_close
                else None
            )
            gap_pct = (
                round((open_price - previous_close) / previous_close * 100, 4)
                if previous_close and open_price is not None
                else None
            )
            row = {
                "ticker": ticker,
                "date": datetime.fromtimestamp(int(timestamp), UTC).date().isoformat(),
                "open": open_price,
                "high": _float_or_none(_at(highs, index)),
                "low": _float_or_none(_at(lows, index)),
                "close": close,
                "previous_close": previous_close,
                "change_pct": change_pct,
                "gap_pct": gap_pct,
                "volume": int(_at(volumes, index) or 0),
                "source_url": source_url,
                "evidence_unverified": False,
            }
            rows.append(row)
            previous_close = close
        return rows

    def get_financials(self, ticker: str) -> dict[str, Any]:
        return {"ticker": ticker, "source_url": f"https://finance.yahoo.com/quote/{ticker}/financials"}

    def get_options(self, ticker: str) -> dict[str, Any] | None:
        return {"ticker": ticker, "source_url": f"https://finance.yahoo.com/quote/{ticker}/options"}

    def get_volume_20d_average(self, ticker: str) -> float:
        history = self.get_history(ticker, period="1mo")
        volumes = [float(row["volume"]) for row in history[-20:] if row.get("volume")]
        if not volumes:
            return 0.0
        return round(sum(volumes) / len(volumes), 2)

    def _fetch_chart(self, ticker: str, period: str) -> dict[str, Any] | None:
        safe_ticker = quote(ticker, safe="")
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{safe_ticker}?range={period}&interval=1d"
        request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urlopen(request, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception:
            return None
        result = ((payload.get("chart") or {}).get("result") or [None])[0]
        if not isinstance(result, dict):
            return None
        return result


def _at(values: list[Any], index: int) -> Any:
    return values[index] if index < len(values) else None


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None
