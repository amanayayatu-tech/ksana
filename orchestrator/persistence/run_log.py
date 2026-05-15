"""SQLite run history for Orchestrator."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from orchestrator.core.models import StepResult


class RunLog:
    """Small SQLite wrapper for pipeline and step history."""

    def __init__(self, db_path: str | Path = "data/orchestrator/runs.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def create_run(
        self,
        *,
        pipeline_type: str,
        trigger_source: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        metadata = metadata or {}
        run_id = build_run_id(metadata.get("date"))
        now = datetime.now().astimezone().isoformat()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO pipeline_runs(run_id, pipeline_type, trigger_source, started_at, status, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (run_id, pipeline_type, trigger_source, now, "running", json.dumps(metadata)),
            )
        return run_id

    def finish_run(self, run_id: str, status: str, metadata: dict[str, Any] | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE pipeline_runs
                SET ended_at = ?, status = ?, metadata_json = ?
                WHERE run_id = ?
                """,
                (
                    datetime.now().astimezone().isoformat(),
                    status,
                    json.dumps(metadata or {}, ensure_ascii=False),
                    run_id,
                ),
            )

    def record_step(self, run_id: str, result: StepResult) -> None:
        now = datetime.now().astimezone().isoformat()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO step_executions(
                    step_id, run_id, step_name, started_at, ended_at, status, attempt,
                    exit_code, stdout_path, stderr_path, output_files_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"{run_id}:{result.step_name}",
                    run_id,
                    result.step_name,
                    now,
                    now,
                    result.status,
                    result.attempts,
                    result.exit_code,
                    str(result.stdout_path) if result.stdout_path else None,
                    str(result.stderr_path) if result.stderr_path else None,
                    json.dumps([str(p) for p in result.output_files], ensure_ascii=False),
                ),
            )

    def record_notification(self, run_id: str, channel: str, status: str) -> str:
        notification_id = f"NOTIFY-{uuid.uuid4().hex[:12]}"
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO notifications_sent(notification_id, run_id, channel, sent_at, status)
                VALUES (?, ?, ?, ?, ?)
                """,
                (notification_id, run_id, channel, datetime.now().astimezone().isoformat(), status),
            )
        return notification_id

    def list_runs(self, *, date: str | None = None, status: str | None = None, tail: int = 10) -> list[dict]:
        sql = "SELECT * FROM pipeline_runs"
        clauses = []
        params: list[Any] = []
        if date:
            clauses.append("started_at LIKE ?")
            params.append(f"{date}%")
        if status:
            clauses.append("status = ?")
            params.append(status)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY started_at DESC LIMIT ?"
        params.append(tail)
        with self.connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def get_run(self, run_id: str) -> dict | None:
        with self.connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM pipeline_runs WHERE run_id = ?", (run_id,)).fetchone()
        return dict(row) if row else None

    def has_history_for_date(self, date: str) -> bool:
        compact = "".join(ch for ch in date if ch.isdigit())[:8]
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM pipeline_runs
                WHERE run_id LIKE ?
                   OR metadata_json LIKE ?
                   OR metadata_json LIKE ?
                LIMIT 1
                """,
                (f"RUN-{compact}-%", f'%"date": "{date}"%', f'%"date":"{date}"%'),
            ).fetchone()
        return row is not None

    def connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_schema(self) -> None:
        schema_path = Path(__file__).with_name("schema.sql")
        with self.connect() as conn:
            conn.executescript(schema_path.read_text(encoding="utf-8"))


def build_run_id(run_date: str | None = None) -> str:
    compact_date = normalize_run_id_date(run_date)
    return f"RUN-{compact_date}-{uuid.uuid4().hex[:8]}"


def normalize_run_id_date(run_date: str | None = None) -> str:
    if run_date:
        digits = "".join(ch for ch in run_date if ch.isdigit())
        if len(digits) >= 8:
            return digits[:8]
    return datetime.now().strftime("%Y%m%d")
