from __future__ import annotations

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
