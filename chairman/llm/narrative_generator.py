"""LLM-assisted disagreement narrative generation.

This is the only Chairman module allowed to call a language model. Core modules
stay deterministic and auditable.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from chairman.models import DisagreementAnalysis, DisagreementType, Recommendation

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """Language-model call failed."""


class LLMTimeout(LLMError):
    """Language-model call timed out."""


class LLMClient(ABC):
    """Minimal narrative-generation client interface."""

    @abstractmethod
    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        timeout_seconds: int,
        temperature: float,
    ) -> str:
        """Return a text completion."""


class OpenAIClient(LLMClient):
    """OpenAI implementation using environment-provided credentials."""

    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        load_dotenv()
        self.model = model or os.getenv("LLM_MODEL", "gpt-5.5")
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise LLMError("OPENAI_API_KEY is not set")

    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        timeout_seconds: int,
        temperature: float,
    ) -> str:
        """Call OpenAI through the official Python client."""

        try:
            from openai import OpenAI
        except Exception as exc:  # pragma: no cover - depends on local install
            raise LLMError(f"openai package unavailable: {exc}") from exc

        try:
            client = OpenAI(api_key=self.api_key, timeout=timeout_seconds)
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return response.choices[0].message.content or ""
        except TimeoutError as exc:  # pragma: no cover - network path
            raise LLMTimeout(str(exc)) from exc
        except Exception as exc:  # pragma: no cover - network path
            raise LLMError(str(exc)) from exc


class CodexCliClient(LLMClient):
    """Codex CLI implementation using the local Codex login state."""

    def __init__(
        self,
        model: str | None = None,
        project_root: str | Path | None = None,
        codex_binary: str = "codex",
    ) -> None:
        load_dotenv()
        self.model = model if model is not None else os.getenv("LLM_MODEL", "")
        self.project_root = resolve_codex_project_root(project_root)
        self.codex_binary = codex_binary

    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        timeout_seconds: int,
        temperature: float,
    ) -> str:
        """Call Codex CLI as a provider and return only the final message."""

        if not shutil.which(self.codex_binary):
            raise LLMError("codex CLI is not installed or not on PATH")

        prompt = build_codex_provider_prompt(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        with tempfile.NamedTemporaryFile("w+", encoding="utf-8", suffix=".txt") as output_file:
            # codex 0.130 exposes approval as a global option, before `exec`.
            command = [
                self.codex_binary,
                "--ask-for-approval",
                "never",
                "exec",
                "-c",
                f'model_reasoning_effort="{codex_provider_reasoning_effort()}"',
                "--cd",
                str(self.project_root),
                "--sandbox",
                codex_provider_sandbox(),
                "--output-last-message",
                output_file.name,
            ]
            if codex_provider_clean_enabled():
                command.insert(command.index("-c"), "--ignore-user-config")
            if self.model:
                command.extend(["--model", self.model])
            command.append(prompt)

            try:
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds,
                    check=False,
                    cwd=self.project_root,
                )
            except FileNotFoundError as exc:
                raise LLMError("codex CLI is not installed or not on PATH") from exc
            except subprocess.TimeoutExpired as exc:
                raise LLMTimeout(str(exc)) from exc

            stdout = completed.stdout or ""
            stderr = completed.stderr or ""
            if completed.returncode != 0:
                detail = (stderr or stdout).strip()
                if looks_like_codex_login_error(detail):
                    raise LLMError("codex CLI is not logged in")
                raise LLMError(f"codex CLI failed with exit code {completed.returncode}: {detail}")

            output_file.seek(0)
            final_message = output_file.read().strip()
            return final_message or stdout.strip()


class AnthropicClient(LLMClient):
    """Anthropic placeholder behind the same interface."""

    def complete(self, **_: Any) -> str:
        raise LLMError("AnthropicClient is not configured in Chairman v0.1")


class LocalClient(LLMClient):
    """Local model placeholder behind the same interface."""

    def complete(self, **_: Any) -> str:
        raise LLMError("LocalClient is not configured in Chairman v0.1")


def build_llm_client_from_env() -> LLMClient:
    """Build an LLM client from .env settings."""

    load_dotenv()
    provider = os.getenv("LLM_PROVIDER", "openai").lower()
    model = os.getenv("LLM_MODEL", "")
    if provider == "openai":
        return OpenAIClient(model=model or "gpt-5.5")
    if provider == "codex_cli":
        return CodexCliClient(model=model)
    if provider == "anthropic":
        return AnthropicClient()
    if provider == "local":
        return LocalClient()
    raise LLMError(f"unsupported LLM_PROVIDER={provider!r}")


def codex_provider_reasoning_effort() -> str:
    """Keep provider-style Codex calls responsive unless explicitly overridden."""

    return os.getenv("CODEX_PROVIDER_REASONING_EFFORT", "low").strip() or "low"


def codex_provider_sandbox() -> str:
    """Return the Codex provider sandbox without changing the legacy default."""

    sandbox = os.getenv("CODEX_PROVIDER_SANDBOX", "workspace-write").strip() or "workspace-write"
    allowed = {"read-only", "workspace-write"}
    if sandbox not in allowed:
        raise LLMError(
            "CODEX_PROVIDER_SANDBOX must be one of: " + ", ".join(sorted(allowed))
        )
    return sandbox


def codex_provider_clean_enabled() -> bool:
    """Return whether Codex provider calls should ignore user config."""

    return os.getenv("CODEX_PROVIDER_CLEAN", "").strip().lower() in {"1", "true", "yes", "on"}


def build_codex_provider_prompt(
    *,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
    temperature: float,
) -> str:
    """Compose a strict provider prompt for non-interactive Codex CLI."""

    return f"""You are the Codex CLI acting as an LLM provider for ksana.

Hard constraints:
- Do not modify files, run migrations, edit data, or call external services.
- Do not call Perplexity or any web/data API.
- Return only the requested final answer. If JSON is requested, return strict JSON only.
- Do not wrap JSON in Markdown fences.
- Keep the response within roughly {max_tokens} tokens.
- Use temperature guidance {temperature}, but preserve the requested schema exactly.

<system_prompt>
{system_prompt}
</system_prompt>

<user_prompt>
{user_prompt}
</user_prompt>
"""


def resolve_codex_project_root(project_root: str | Path | None = None) -> Path:
    """Resolve the repository root Codex should use as its workspace."""

    explicit = project_root or os.getenv("CODEX_PROJECT_ROOT", "")
    if explicit:
        return Path(explicit).expanduser().resolve()

    cwd_root = find_repo_root(Path.cwd())
    if cwd_root:
        return cwd_root

    module_root = find_repo_root(Path(__file__).resolve())
    if module_root:
        return module_root

    return Path.cwd().resolve()


def find_repo_root(start: Path) -> Path | None:
    """Walk upward until a project marker is found."""

    current = start if start.is_dir() else start.parent
    for path in (current, *current.parents):
        if (path / ".git").exists() or (path / "pyproject.toml").exists():
            return path.resolve()
    return None


def looks_like_codex_login_error(detail: str) -> bool:
    """Best-effort classification for Codex auth failures."""

    lowered = detail.lower()
    return any(
        marker in lowered
        for marker in (
            "not logged in",
            "login",
            "log in",
            "authenticate",
            "authentication",
            "auth",
        )
    )


def generate_disagreement_narrative(
    recommendations: list[Recommendation],
    disagreement: DisagreementAnalysis,
    llm_client: LLMClient | None = None,
    *,
    use_llm: bool = True,
) -> str:
    """Generate a concise Chinese narrative, with template fallback on any LLM failure."""

    if not use_llm or llm_client is None:
        return template_narrative(disagreement, recommendations)

    try:
        narrative = llm_client.complete(
            system_prompt=build_system_prompt(),
            user_prompt=build_user_prompt(disagreement, recommendations),
            max_tokens=300,
            timeout_seconds=30,
            temperature=0.3,
        )
        return sanitize_narrative(narrative)
    except (LLMTimeout, LLMError) as exc:
        logger.warning("LLM narrative failed; using template narrative: %s", exc)
        return template_narrative(disagreement, recommendations)


def build_system_prompt() -> str:
    """Prompt that confines the LLM to Chief-of-Staff narrative duties."""

    return """
你是投资委员会的 Chief of Staff。任务：用 1-2 段中文（≤200字）描述
3 个分析师 Agent 在某标的上的分歧。

严格规则：
1. 只描述事实，不评价对错
2. 不替任何 Agent 表态
3. 不替 PM（Nepha）做决策
4. 不引用具体数字，除非数字出现在输入中
5. 必须区分“方法论 DNA 差异”和“可能的错误”
6. 输出语言：简体中文，专业但简洁

禁止：
- 不要说“我建议”、“应该”、“最好”
- 不要预测未来
- 不要使用感叹号
- 不要超过 200 字
"""


def build_user_prompt(disagreement: DisagreementAnalysis, recommendations: list[Recommendation]) -> str:
    """Build a compact structured prompt from already-classified data."""

    views = [
        {
            "agent_id": rec.agent_id.value,
            "direction": rec.direction.value,
            "confidence": rec.confidence,
            "thesis": rec.one_liner_thesis or rec.thesis,
        }
        for rec in recommendations
    ]
    return (
        f"disagreement_type={disagreement.primary_type}\n"
        f"red_team_escalation_required={disagreement.red_team_escalation_required}\n"
        f"views={views}"
    )


def template_narrative(
    disagreement: DisagreementAnalysis,
    recommendations: list[Recommendation],
) -> str:
    """Deterministic narrative used by --no-llm and LLM failure fallback."""

    if disagreement.primary_type is None:
        return disagreement.narrative

    agent_labels = ", ".join(f"{rec.agent_id.value}:{rec.direction.value}" for rec in recommendations)
    if disagreement.primary_type == DisagreementType.METHODOLOGY_DNA:
        return f"3 个 Agent 的分歧来源是方法论 DNA 差异：{agent_labels}。这是设计内分歧，不是错误。"
    if disagreement.primary_type == DisagreementType.EVIDENCE_UNVERIFIED_PROPAGATION:
        return "部分 Agent 继承了未验证上游证据，相关权重已按 DEC-004 自动降为 0.7。"
    if disagreement.primary_type == DisagreementType.UPSTREAM_SIGNAL_CONSUMPTION:
        return "Agent 对同一 K deep 研究信号的采纳结论不同，差异已保留给 Nepha 对照。"
    if disagreement.primary_type == DisagreementType.DATA_INPUT_DIFFERENCE:
        return "Agent 使用的数据时效存在明显差异，已标记给 Red Team 核实。"
    if disagreement.primary_type == DisagreementType.POTENTIAL_AGENT_ERROR:
        return "有 Agent 触发异常状态，已强制升级给 Red Team 复核。"
    return disagreement.narrative


def sanitize_narrative(text: str) -> str:
    """Defensively clean LLM output to keep the Chief-of-Staff tone."""

    cleaned = " ".join(text.strip().split())
    for banned in ("我建议", "应该", "最好", "！", "!"):
        cleaned = cleaned.replace(banned, "")
    return cleaned[:200]
