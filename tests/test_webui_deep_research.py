from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

import webui


def test_deep_research_fill_and_skip_round_trip(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    pull_dir = data_dir / "pull_requests"
    pull_dir.mkdir(parents=True)
    (pull_dir / "PR-20260513-001.yaml").write_text(
        yaml.safe_dump(
            {
                "prompt_id": "PR-20260513-001",
                "related_signal_id": "RS-20260513-001",
                "priority": "P1",
                "prompt_text": "请研究 0700.HK 最近 7 天是否有非连续变化证据。",
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(webui, "DATA_DIR", data_dir)
    client = TestClient(webui.app)

    list_response = client.get("/api/deep-research/prompts?date=2026-05-13")
    assert list_response.status_code == 200
    prompts = list_response.json()["prompts"]
    assert prompts[0]["status"] == "pending"
    assert "Perplexity 深度研究 Prompt" in prompts[0]["prompt_markdown"]

    fill_response = client.post(
        "/api/deep-research/fill",
        json={
            "prompt_id": "PR-20260513-001",
            "answer_text": "Perplexity 回填：存在结构性证据，但仍需复核。",
        },
    )
    assert fill_response.status_code == 200
    filled_path = data_dir / "perplexity_results" / "PR-20260513-001_filled.yaml"
    assert filled_path.exists()
    assert "Perplexity 回填" in filled_path.read_text(encoding="utf-8")

    filled_response = client.get("/api/deep-research/prompts?status=filled")
    assert filled_response.json()["prompts"][0]["answer_text"].startswith("Perplexity 回填")

    skip_response = client.post(
        "/api/deep-research/skip",
        json={"prompt_id": "PR-20260513-001", "reason": "这条研究暂不需要。"},
    )
    assert skip_response.status_code == 200
    assert not filled_path.exists()
    assert (data_dir / "perplexity_results" / "PR-20260513-001_skipped.yaml").exists()


def test_history_marks_schema_repair_from_recommendation_yaml(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    rec_dir = data_dir / "recommendations" / "20260513" / "fengliu"
    rec_dir.mkdir(parents=True)
    (rec_dir / "R-FL-20260513-001.yaml").write_text(
        yaml.safe_dump(
            {
                "recommendation": {
                    "recommendation_id": "R-FL-20260513-001",
                    "schema_repair": {"attempts": 1, "errors": ["bad JSON"]},
                }
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(webui, "DATA_DIR", data_dir)

    row = webui.shape_history_row(
        {
            "run_id": "RUN-1",
            "status": "completed",
            "metadata_json": json.dumps({"date": "2026-05-13", "brief_type": "morning"}),
            "started_at": "2026-05-13T08:00:00+08:00",
            "ended_at": "2026-05-13T08:01:00+08:00",
        }
    )

    assert row["schema_repair_or_fallback"] is True


def test_history_marks_fallback_from_agent_log(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    log_dir = data_dir / "agent_logs" / "20260513" / "trading_fengliu"
    log_dir.mkdir(parents=True)
    (log_dir / "R-FL-20260513-001.json").write_text(
        json.dumps({"event": {"fallback_reason": "schema_validation_failed"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(webui, "DATA_DIR", data_dir)

    row = webui.shape_history_row(
        {
            "run_id": "RUN-1",
            "status": "completed",
            "metadata_json": json.dumps({"date": "2026-05-13", "brief_type": "evening"}),
            "started_at": "2026-05-13T18:00:00+08:00",
            "ended_at": "2026-05-13T18:01:00+08:00",
        }
    )

    assert row["schema_repair_or_fallback"] is True


def test_history_reconciles_stale_running_rerun(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setattr(webui, "DATA_DIR", data_dir)
    monkeypatch.setattr(webui, "has_active_rerun_process", lambda: False)
    run_log = webui.RunLog(data_dir / "orchestrator" / "runs.db")
    run_id = run_log.create_run(
        pipeline_type="deep_research_rerun",
        trigger_source="manual",
        metadata={
            "date": "2026-05-14",
            "brief_type": "morning",
            "source": "deep_research_rerun",
            "no_llm": False,
        },
    )
    with sqlite3.connect(data_dir / "orchestrator" / "runs.db") as conn:
        conn.execute(
            "UPDATE pipeline_runs SET started_at = ? WHERE run_id = ?",
            ("2000-01-01T00:00:00+08:00", run_id),
        )

    updated = webui.reconcile_stale_running_runs()

    assert updated == [run_id]
    with sqlite3.connect(data_dir / "orchestrator" / "runs.db") as conn:
        row = conn.execute("SELECT status, metadata_json FROM pipeline_runs").fetchone()
    assert row[0] == "cancelled"
    assert '"cancelled": true' in row[1]
    assert '"cancelled_reason": "stale_running_without_backend_process"' in row[1]


def test_history_does_not_reconcile_while_rerun_process_exists(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setattr(webui, "DATA_DIR", data_dir)
    monkeypatch.setattr(webui, "has_active_rerun_process", lambda: True)
    run_log = webui.RunLog(data_dir / "orchestrator" / "runs.db")
    run_id = run_log.create_run(
        pipeline_type="deep_research_rerun",
        trigger_source="manual",
        metadata={
            "date": "2026-05-14",
            "brief_type": "morning",
            "source": "deep_research_rerun",
            "no_llm": False,
        },
    )
    with sqlite3.connect(data_dir / "orchestrator" / "runs.db") as conn:
        conn.execute(
            "UPDATE pipeline_runs SET started_at = ? WHERE run_id = ?",
            ("2000-01-01T00:00:00+08:00", run_id),
        )

    updated = webui.reconcile_stale_running_runs()

    assert updated == []
    with sqlite3.connect(data_dir / "orchestrator" / "runs.db") as conn:
        row = conn.execute("SELECT status FROM pipeline_runs").fetchone()
    assert row[0] == "running"


def test_active_rerun_process_detects_dated_trading_command(monkeypatch):
    class ProcessList:
        returncode = 0
        stdout = "uv run trading-fengliu run --date 2026-05-14 --data-dir data\n"

    monkeypatch.setattr(webui.subprocess, "run", lambda *args, **kwargs: ProcessList())

    assert webui.has_active_rerun_process() is True


def test_history_does_not_reconcile_while_background_task_exists(tmp_path, monkeypatch):
    class PendingTask:
        def done(self) -> bool:
            return False

    data_dir = tmp_path / "data"
    monkeypatch.setattr(webui, "DATA_DIR", data_dir)
    monkeypatch.setattr(webui, "background_tasks", {PendingTask()})
    monkeypatch.setattr(webui, "has_active_rerun_process", lambda: False)
    run_log = webui.RunLog(data_dir / "orchestrator" / "runs.db")
    run_id = run_log.create_run(
        pipeline_type="deep_research_rerun",
        trigger_source="manual",
        metadata={
            "date": "2026-05-14",
            "brief_type": "morning",
            "source": "deep_research_rerun",
            "no_llm": False,
        },
    )
    with sqlite3.connect(data_dir / "orchestrator" / "runs.db") as conn:
        conn.execute(
            "UPDATE pipeline_runs SET started_at = ? WHERE run_id = ?",
            ("2000-01-01T00:00:00+08:00", run_id),
        )

    updated = webui.reconcile_stale_running_runs()

    assert updated == []
    with sqlite3.connect(data_dir / "orchestrator" / "runs.db") as conn:
        row = conn.execute("SELECT status FROM pipeline_runs").fetchone()
    assert row[0] == "running"


def test_history_reconciles_stale_running_rerun_even_if_lock_is_stuck(tmp_path, monkeypatch):
    class LockedRunLock:
        def locked(self):
            return True

    data_dir = tmp_path / "data"
    monkeypatch.setattr(webui, "DATA_DIR", data_dir)
    monkeypatch.setattr(webui, "run_lock", LockedRunLock())
    monkeypatch.setattr(webui, "has_active_rerun_process", lambda: False)
    run_log = webui.RunLog(data_dir / "orchestrator" / "runs.db")
    run_id = run_log.create_run(
        pipeline_type="deep_research_rerun",
        trigger_source="manual",
        metadata={
            "date": "2026-05-14",
            "brief_type": "morning",
            "source": "deep_research_rerun",
            "no_llm": False,
        },
    )
    with sqlite3.connect(data_dir / "orchestrator" / "runs.db") as conn:
        conn.execute(
            "UPDATE pipeline_runs SET started_at = ? WHERE run_id = ?",
            ("2000-01-01T00:00:00+08:00", run_id),
        )

    updated = webui.reconcile_stale_running_runs()

    assert updated == [run_id]
    with sqlite3.connect(data_dir / "orchestrator" / "runs.db") as conn:
        row = conn.execute("SELECT status FROM pipeline_runs").fetchone()
    assert row[0] == "cancelled"


def test_artifact_endpoint_reads_project_markdown(tmp_path, monkeypatch):
    project_root = tmp_path / "app"
    data_dir = project_root / "data"
    brief_dir = data_dir / "briefs" / "20260513"
    brief_dir.mkdir(parents=True)
    (brief_dir / "BRIEF-20260513-PM.md").write_text("# 晚间报告\n\nok", encoding="utf-8")
    monkeypatch.setattr(webui, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(webui, "DATA_DIR", data_dir)

    response = TestClient(webui.app).get(
        "/api/artifact",
        params={"path": "data/briefs/20260513/BRIEF-20260513-PM.md"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["exists"] is True
    assert "晚间报告" in payload["content"]


def test_artifact_endpoint_rejects_path_traversal(tmp_path, monkeypatch):
    project_root = tmp_path / "app"
    data_dir = project_root / "data"
    data_dir.mkdir(parents=True)
    monkeypatch.setattr(webui, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(webui, "DATA_DIR", data_dir)

    response = TestClient(webui.app).get("/api/artifact", params={"path": "../secret.md"})

    assert response.status_code == 400


def test_trial_status_counts_pending_and_filled(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    pull_dir = data_dir / "pull_requests"
    result_dir = data_dir / "perplexity_results"
    pull_dir.mkdir(parents=True)
    result_dir.mkdir(parents=True)
    for prompt_id in ("PR-20260513-001", "PR-20260513-002"):
        (pull_dir / f"{prompt_id}.yaml").write_text(
            yaml.safe_dump({"prompt_id": prompt_id, "prompt_text": "研究"}, allow_unicode=True),
            encoding="utf-8",
        )
    (result_dir / "PR-20260513-001_filled.yaml").write_text(
        yaml.safe_dump({"prompt_id": "PR-20260513-001", "status": "filled", "answer_text": "done"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(webui, "DATA_DIR", data_dir)

    status = webui.get_trial_status()

    assert status["pending_perplexity"] == 1
    assert status["filled_perplexity"] == 1
    assert status["total_perplexity"] == 2


def test_deep_research_rerun_stream_writes_history(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setattr(webui, "DATA_DIR", data_dir)

    async def collect_events() -> list[str]:
        return [
            chunk
            async for chunk in webui.stream_command_sequence(
                [("Smoke Step", [sys.executable, "-c", "print('ok')"])],
                {},
                history={
                    "pipeline_type": "deep_research_rerun",
                    "trigger_source": "manual",
                    "date": "2026-05-13",
                    "brief_type": "evening",
                    "no_llm": False,
                },
            )
        ]

    events = asyncio.run(collect_events())

    assert any("已写入运行历史" in event for event in events)
    with sqlite3.connect(data_dir / "orchestrator" / "runs.db") as conn:
        row = conn.execute("SELECT pipeline_type, status, metadata_json FROM pipeline_runs").fetchone()
    assert row[0] == "deep_research_rerun"
    assert row[1] == "completed"
    assert '"date": "2026-05-13"' in row[2]


def test_deep_research_background_rerun_survives_stream_close(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setattr(webui, "DATA_DIR", data_dir)
    monkeypatch.setattr(webui, "run_lock", asyncio.Lock())
    monkeypatch.setattr(webui, "background_tasks", set())

    async def start_and_close() -> None:
        stream = webui.stream_background_command_sequence_start(
            [
                (
                    "Smoke Step",
                    [sys.executable, "-c", "import time; print('background-ok'); time.sleep(0.2)"],
                )
            ],
            {},
            history={
                "pipeline_type": "deep_research_rerun",
                "trigger_source": "manual",
                "date": "2026-05-13",
                "brief_type": "evening",
                "no_llm": False,
            },
        )
        first_event = await stream.__anext__()
        await stream.aclose()
        assert "已创建后台任务" in first_event
        tasks = list(webui.background_tasks)
        assert len(tasks) == 1
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=5)

    asyncio.run(start_and_close())

    with sqlite3.connect(data_dir / "orchestrator" / "runs.db") as conn:
        run_row = conn.execute("SELECT status, metadata_json FROM pipeline_runs").fetchone()
        step_row = conn.execute("SELECT status, stdout_path FROM step_executions").fetchone()
    assert run_row[0] == "completed"
    assert '"background": true' in run_row[1]
    assert step_row[0] == "success"
    assert "background-ok" in Path(step_row[1]).read_text(encoding="utf-8")
    assert not webui.run_lock.locked()


def test_background_command_start_returns_history_run_id(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setattr(webui, "DATA_DIR", data_dir)
    monkeypatch.setattr(webui, "run_lock", asyncio.Lock())
    monkeypatch.setattr(webui, "background_tasks", set())
    script = (
        "import sys, time;"
        "from orchestrator.persistence.run_log import RunLog;"
        "run_log=RunLog(sys.argv[1]);"
        "run_id=run_log.create_run("
        "pipeline_type='full', trigger_source='manual', "
        "metadata={'date':'2026-05-14','brief_type':'morning'}"
        ");"
        "time.sleep(0.2);"
        "run_log.finish_run(run_id,'completed',{'date':'2026-05-14','brief_type':'morning'})"
    )

    async def start_background() -> list[str]:
        events = [
            chunk
            async for chunk in webui.stream_background_command_start(
                [sys.executable, "-c", script, str(data_dir / "orchestrator" / "runs.db")],
                {},
                expected_history={
                    "pipeline_type": "full",
                    "date": "2026-05-14",
                    "brief_type": "morning",
                },
            )
        ]
        await asyncio.wait_for(asyncio.gather(*list(webui.background_tasks)), timeout=5)
        return events

    events = asyncio.run(start_background())

    assert any('"status": "running"' in event for event in events)
    assert any('"run_id": "RUN-20260514-' in event for event in events)
    with sqlite3.connect(data_dir / "orchestrator" / "runs.db") as conn:
        row = conn.execute("SELECT status, metadata_json FROM pipeline_runs").fetchone()
    assert row[0] == "completed"
    assert '"brief_type": "morning"' in row[1]
    assert not webui.run_lock.locked()


def test_deep_research_background_rerun_cleans_stale_downstream_outputs(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    rec_dir = data_dir / "recommendations" / "20260514" / "fengliu"
    brief_dir = data_dir / "briefs" / "20260514"
    audit_dir = data_dir / "red_team_audits" / "20260514"
    rec_dir.mkdir(parents=True)
    brief_dir.mkdir(parents=True)
    audit_dir.mkdir(parents=True)
    (rec_dir / "OLD.yaml").write_text("recommendation: {ticker: AMD}", encoding="utf-8")
    (brief_dir / "BRIEF-20260514-AM.md").write_text("old brief", encoding="utf-8")
    (audit_dir / "AUDIT-20260514-AM.md").write_text("old audit", encoding="utf-8")
    monkeypatch.setattr(webui, "DATA_DIR", data_dir)
    monkeypatch.setattr(webui, "run_lock", asyncio.Lock())
    monkeypatch.setattr(webui, "background_tasks", set())

    async def start_background() -> None:
        events = [
            chunk
            async for chunk in webui.stream_background_command_sequence_start(
                [("Smoke Step", [sys.executable, "-c", "print('ok')"])],
                {},
                history={
                    "pipeline_type": "deep_research_rerun",
                    "trigger_source": "manual",
                    "date": "2026-05-14",
                    "brief_type": "morning",
                    "no_llm": False,
                },
            )
        ]
        assert any("已创建后台任务" in event for event in events)
        await asyncio.wait_for(asyncio.gather(*list(webui.background_tasks)), timeout=5)

    asyncio.run(start_background())

    assert not rec_dir.exists()
    assert not (brief_dir / "BRIEF-20260514-AM.md").exists()
    assert not (audit_dir / "AUDIT-20260514-AM.md").exists()
    with sqlite3.connect(data_dir / "orchestrator" / "runs.db") as conn:
        row = conn.execute("SELECT status, metadata_json FROM pipeline_runs").fetchone()
    assert row[0] == "completed"
    assert '"cleanup_removed_count": 3' in row[1]


def test_deep_research_rerun_commands_include_selected_date():
    commands = webui.build_deep_research_rerun_commands("morning", "2026-05-14", no_llm=False)
    trading_commands = [command for label, command in commands if label.endswith("Agent")]

    assert trading_commands
    assert all("--date" in command and "2026-05-14" in command for command in trading_commands)


def test_running_history_row_does_not_show_stale_date_artifacts(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    brief_dir = data_dir / "briefs" / "20260514"
    audit_dir = data_dir / "red_team_audits" / "20260514"
    brief_dir.mkdir(parents=True)
    audit_dir.mkdir(parents=True)
    (brief_dir / "BRIEF-20260514-AM.md").write_text("old brief", encoding="utf-8")
    (audit_dir / "AUDIT-20260514-AM.md").write_text("old audit", encoding="utf-8")
    monkeypatch.setattr(webui, "DATA_DIR", data_dir)

    row = webui.shape_history_row(
        {
            "run_id": "RUN-20260514-ABC",
            "status": "running",
            "metadata_json": json.dumps({"date": "2026-05-14", "brief_type": "morning"}),
            "started_at": "2026-05-14T13:00:00+08:00",
            "ended_at": None,
        }
    )

    assert row["artifacts"] == {}


def test_deep_research_rerun_stream_marks_cancelled_history(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setattr(webui, "DATA_DIR", data_dir)

    async def cancel_events() -> None:
        started = asyncio.Event()

        async def consume() -> None:
            async for chunk in webui.stream_command_sequence(
                [
                    (
                        "Long Step",
                        [
                            sys.executable,
                            "-c",
                            "import time; print('started', flush=True); time.sleep(30)",
                        ],
                    )
                ],
                {},
                history={
                    "pipeline_type": "deep_research_rerun",
                    "trigger_source": "manual",
                    "date": "2026-05-13",
                    "brief_type": "evening",
                    "no_llm": False,
                },
            ):
                if "started" in chunk:
                    started.set()

        task = asyncio.create_task(consume())
        await asyncio.wait_for(started.wait(), timeout=5)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(cancel_events())

    with sqlite3.connect(data_dir / "orchestrator" / "runs.db") as conn:
        run_row = conn.execute("SELECT status, metadata_json FROM pipeline_runs").fetchone()
        step_row = conn.execute("SELECT status FROM step_executions").fetchone()
    assert run_row[0] == "cancelled"
    assert '"cancelled": true' in run_row[1]
    assert '"failed_step": "long_step"' in run_row[1]
    assert step_row[0] == "cancelled"


def test_deep_research_rerun_stream_keeps_failed_status_after_disconnect(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setattr(webui, "DATA_DIR", data_dir)

    async def close_after_failure() -> None:
        stream = webui.stream_command_sequence(
            [("Fail Step", [sys.executable, "-c", "import sys; sys.exit(2)"])],
            {},
            history={
                "pipeline_type": "deep_research_rerun",
                "trigger_source": "manual",
                "date": "2026-05-13",
                "brief_type": "evening",
                "no_llm": False,
            },
        )
        async for chunk in stream:
            if '"return_code": 2' in chunk:
                await stream.aclose()
                break

    asyncio.run(close_after_failure())

    with sqlite3.connect(data_dir / "orchestrator" / "runs.db") as conn:
        row = conn.execute("SELECT status, metadata_json FROM pipeline_runs").fetchone()
    assert row[0] == "failed"
    assert '"failed_step": "fail_step"' in row[1]
