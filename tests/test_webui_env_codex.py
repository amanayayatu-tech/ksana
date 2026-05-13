from __future__ import annotations

from fastapi.testclient import TestClient

import webui


def test_env_reports_codex_status(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    example_path = tmp_path / ".env.example"
    example_path.write_text(
        "LLM_PROVIDER=local\nLLM_MODEL=\nOPENAI_API_KEY=\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(webui, "ENV_PATH", env_path)
    monkeypatch.setattr(webui, "ENV_EXAMPLE_PATH", example_path)
    monkeypatch.setattr(
        webui,
        "get_codex_status",
        lambda: {
            "available": True,
            "status": "logged_in",
            "label": "ChatGPT 登录",
            "detail": "Logged in using ChatGPT",
        },
    )

    response = TestClient(webui.app).get("/api/env")

    assert response.status_code == 200
    env = response.json()["env"]
    assert env["codex"]["status"] == "logged_in"
    assert env["codex"]["label"] == "ChatGPT 登录"


def test_save_env_accepts_codex_cli_provider(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    example_path = tmp_path / ".env.example"
    example_path.write_text(
        "LLM_PROVIDER=local\nLLM_MODEL=\nOPENAI_API_KEY=\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(webui, "ENV_PATH", env_path)
    monkeypatch.setattr(webui, "ENV_EXAMPLE_PATH", example_path)
    monkeypatch.setattr(
        webui,
        "get_codex_status",
        lambda: {"available": True, "status": "logged_in", "label": "已登录", "detail": ""},
    )

    response = TestClient(webui.app).post(
        "/api/env",
        json={
            "llm_provider": "codex_cli",
            "llm_model": "",
            "openai_api_key": "",
            "clear_api_key": False,
        },
    )

    assert response.status_code == 200
    assert "LLM_PROVIDER=codex_cli" in env_path.read_text(encoding="utf-8")
    assert response.json()["env"]["llm_provider"] == "codex_cli"


def test_codex_login_stream_handles_missing_codex(monkeypatch):
    monkeypatch.setattr(webui.shutil, "which", lambda _: None)
    client = TestClient(webui.app)

    with client.stream("GET", "/api/codex/login-stream") as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "找不到 codex CLI" in body
    assert '"return_code": 127' in body
