from __future__ import annotations

from fastapi.testclient import TestClient

import webui


class HealthyLLM:
    def complete(self, **_):
        return "OK"


class NotOkLLM:
    def complete(self, **_):
        return "NOT OK"


def test_env_page_is_available_from_sidebar_meta():
    response = TestClient(webui.app).get("/env")

    assert response.status_code == 200
    assert "LLM API 设置" in response.text
    assert 'href="/env"' in response.text
    assert "Codex 登录" in response.text
    assert "OPENAI_API_KEY" in response.text
    assert "检测 LLM 调用" in response.text


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


def test_llm_health_endpoint_reports_callable(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text("LLM_PROVIDER=codex_cli\nLLM_MODEL=gpt-5.5\nOPENAI_API_KEY=\n", encoding="utf-8")
    monkeypatch.setattr(webui, "ENV_PATH", env_path)
    monkeypatch.setattr(webui, "build_llm_client_from_env", lambda: HealthyLLM())

    response = TestClient(webui.app).get("/api/llm/health")

    assert response.status_code == 200
    health = response.json()["health"]
    assert health["ok"] is True
    assert health["provider"] == "codex_cli"


def test_llm_health_endpoint_rejects_not_ok_suffix(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text("LLM_PROVIDER=codex_cli\nLLM_MODEL=gpt-5.5\nOPENAI_API_KEY=\n", encoding="utf-8")
    monkeypatch.setattr(webui, "ENV_PATH", env_path)
    monkeypatch.setattr(webui, "build_llm_client_from_env", lambda: NotOkLLM())

    response = TestClient(webui.app).get("/api/llm/health")

    assert response.status_code == 200
    health = response.json()["health"]
    assert health["ok"] is False
    assert health["status"] == "unexpected_output"
