# Agent Trading System

Local scaffold for the Chairman Agent v0.1.

## Quick Start

```bash
uv sync --extra dev
uv run chairman validate --date 2026-05-13
uv run chairman generate-brief --type morning --date 2026-05-13 --no-llm
uv run chairman generate-brief --type evening --date 2026-05-13 --no-llm
uv run chairman generate-brief --type ad_hoc --date 2026-05-13 --trigger-signal RS-20260513-001 --no-llm
uv run red-team audit --type morning --date 2026-05-13 --no-llm
uv run orchestrator run --type full --brief-type morning --date 2026-05-13
```

## Data Layout

Runtime files live under `data/` and are intentionally gitignored:

```text
data/
  research_signals/
  recommendations/YYYYMMDD/{fengliu,wanmu,liguofei}/
  pull_requests/
  briefs/
  errors/
  red_team_audits/
  orchestrator/
  notifications/
```

## Verification

```bash
uv run python -m pytest --cov=chairman --cov-report=term-missing --cov-fail-under=85 -q
uv run ruff check chairman tests
```

## Stage Notes

`research-agent` and the three trading-agent Python CLIs are stage 3.7. Until they exist, Orchestrator uses configurable no-op placeholders for those steps and runs the delivered Chairman and Red Team CLIs against files already present under `data/`.
