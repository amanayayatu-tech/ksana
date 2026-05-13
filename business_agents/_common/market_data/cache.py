"""SQLite-backed market data cache."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any


class MarketDataCache:
    """Tiny TTL cache for market-data snapshots."""

    def __init__(self, path: str | Path = "data/market_cache/cache.db") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS cache(key TEXT PRIMARY KEY, expires_at REAL, payload TEXT)"
            )

    def get(self, key: str) -> dict[str, Any] | None:
        with sqlite3.connect(self.path) as conn:
            row = conn.execute("SELECT expires_at, payload FROM cache WHERE key = ?", (key,)).fetchone()
        if not row:
            return None
        expires_at, payload = row
        if expires_at < time.time():
            return None
        return json.loads(payload)

    def set(self, key: str, payload: dict[str, Any], ttl_seconds: int) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO cache(key, expires_at, payload) VALUES (?, ?, ?)",
                (key, time.time() + ttl_seconds, json.dumps(payload, ensure_ascii=False)),
            )
