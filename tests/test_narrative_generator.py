from __future__ import annotations

import subprocess

import pytest

import chairman.llm.narrative_generator as narrative_generator
from chairman.llm.narrative_generator import LLMClient, LLMError, generate_disagreement_narrative
from chairman.models import DisagreementAnalysis, DisagreementType
from tests.conftest import make_fengliu, make_wanmu


class FailingClient(LLMClient):
    def complete(self, **kwargs):
        raise LLMError("mock failure")


def test_fallback_when_llm_fails():
    recs = [make_fengliu("long"), make_wanmu("avoid")]
    disagreement = DisagreementAnalysis(
        primary_type=DisagreementType.METHODOLOGY_DNA,
        narrative="llm would rewrite this",
    )

    narrative = generate_disagreement_narrative(recs, disagreement, FailingClient(), use_llm=True)

    assert "方法论 DNA" in narrative
    assert "mock failure" not in narrative


def test_build_codex_cli_client_from_env(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "codex_cli")
    monkeypatch.setenv("LLM_MODEL", "gpt-5.5")

    client = narrative_generator.build_llm_client_from_env()

    assert isinstance(client, narrative_generator.CodexCliClient)
    assert client.model == "gpt-5.5"


def test_codex_cli_client_defaults_to_cwd_repo_root(monkeypatch, tmp_path):
    nested = tmp_path / "nested"
    nested.mkdir()
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")
    monkeypatch.chdir(nested)
    monkeypatch.delenv("CODEX_PROJECT_ROOT", raising=False)

    client = narrative_generator.CodexCliClient(model="")

    assert client.project_root == tmp_path


def test_codex_cli_client_respects_project_root_env(monkeypatch, tmp_path):
    monkeypatch.setenv("CODEX_PROJECT_ROOT", str(tmp_path))

    client = narrative_generator.CodexCliClient(model="")

    assert client.project_root == tmp_path


def test_codex_cli_client_invokes_codex_exec(monkeypatch, tmp_path):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        output_path = command[command.index("--output-last-message") + 1]
        with open(output_path, "w", encoding="utf-8") as handle:
            handle.write('{"ok": true}')
        return subprocess.CompletedProcess(command, 0, stdout="ignored", stderr="")

    monkeypatch.setattr(narrative_generator.shutil, "which", lambda _: "/usr/local/bin/codex")
    monkeypatch.setattr(narrative_generator.subprocess, "run", fake_run)
    client = narrative_generator.CodexCliClient(model="gpt-5.5", project_root=tmp_path)

    output = client.complete(
        system_prompt="Return JSON.",
        user_prompt="Say ok.",
        max_tokens=100,
        timeout_seconds=12,
        temperature=0.2,
    )

    command, kwargs = calls[0]
    assert output == '{"ok": true}'
    assert command[:4] == ["codex", "--ask-for-approval", "never", "exec"]
    assert command[command.index("--cd") + 1] == str(tmp_path)
    assert command[command.index("--sandbox") + 1] == "workspace-write"
    assert command[command.index("--model") + 1] == "gpt-5.5"
    assert kwargs["timeout"] == 12
    assert kwargs["cwd"] == tmp_path


def test_codex_cli_client_reports_missing_binary(monkeypatch, tmp_path):
    monkeypatch.setattr(narrative_generator.shutil, "which", lambda _: None)
    client = narrative_generator.CodexCliClient(project_root=tmp_path)

    with pytest.raises(LLMError, match="not installed"):
        client.complete(
            system_prompt="",
            user_prompt="",
            max_tokens=10,
            timeout_seconds=1,
            temperature=0,
        )


def test_codex_cli_client_reports_login_error(monkeypatch, tmp_path):
    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, stdout="Please login first", stderr="")

    monkeypatch.setattr(narrative_generator.shutil, "which", lambda _: "/usr/local/bin/codex")
    monkeypatch.setattr(narrative_generator.subprocess, "run", fake_run)
    client = narrative_generator.CodexCliClient(project_root=tmp_path)

    with pytest.raises(LLMError, match="not logged in"):
        client.complete(
            system_prompt="",
            user_prompt="",
            max_tokens=10,
            timeout_seconds=1,
            temperature=0,
        )


def test_codex_cli_client_timeout(monkeypatch, tmp_path):
    def fake_run(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(narrative_generator.shutil, "which", lambda _: "/usr/local/bin/codex")
    monkeypatch.setattr(narrative_generator.subprocess, "run", fake_run)
    client = narrative_generator.CodexCliClient(project_root=tmp_path)

    with pytest.raises(narrative_generator.LLMTimeout):
        client.complete(
            system_prompt="",
            user_prompt="",
            max_tokens=10,
            timeout_seconds=1,
            temperature=0,
        )
