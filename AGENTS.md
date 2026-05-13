# AGENTS.md

## Project Context

This repository is `worldpay77`, a local multi-agent investment decision system.
It has a deterministic Python pipeline around `research-agent`, three trading
agents, `chairman`, `red-team`, and `orchestrator`.

## Codex CLI Provider Rules

- When invoked by the backend as an LLM provider, return only the requested final
  content. If the caller asks for JSON, return strict JSON with no Markdown
  fences or commentary.
- Do not bypass the Python validators or output schemas. Business outputs must
  still pass the existing Pydantic/schema validation in the repository.
- Do not directly write business artifacts into `data/`, including historical
  briefs, recommendations, run logs, or Perplexity result files. The Python
  pipeline is responsible for writing those files after validation.
- Do not call Perplexity, web search, data APIs, or broker/trading APIs. The
  Perplexity workflow is human-in-the-loop: output prompts, wait for Nepha's
  manual result, and consume local `data/perplexity_results/` files only.
- Do not make trading decisions for Nepha. Summarize, validate, flag risk, and
  preserve the final decision boundary.
- If evidence is missing or unverified, keep the conservative watch/abstain
  posture required by the methodology and deployment layer.

## Local Commands

- Use `uv run ...` for repository commands when shell execution is needed.
- Prefer `--no-llm` smoke tests for deterministic local verification.
- Keep generated caches and transient logs separate from source changes.
