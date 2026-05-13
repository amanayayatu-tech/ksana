from __future__ import annotations

import asyncio
import json
import sqlite3
import sys

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
