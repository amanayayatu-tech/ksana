# Agent Trading System

Local scaffold for the Chairman Agent v0.1.

## Quick Start

```bash
uv sync --extra dev
uv run research-agent run --type scan --no-llm
uv run trading-fengliu run --no-llm
uv run trading-wanmu run --no-llm
uv run trading-liguofei run --no-llm
uv run chairman validate --date 2026-05-13
uv run chairman generate-brief --type morning --date 2026-05-13 --no-llm
uv run chairman generate-brief --type evening --date 2026-05-13 --no-llm
uv run chairman generate-brief --type ad_hoc --date 2026-05-13 --trigger-signal RS-20260513-001 --no-llm
uv run red-team audit --type morning --date 2026-05-13 --no-llm
uv run orchestrator run --type full --brief-type morning --date 2026-05-13
```

## Data Layout

Runtime files live under `data/` and are intentionally gitignored. The stock pool is the only tracked runtime input:

```text
data/
  stock_pool/master_pool.yaml
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
uv run ruff check chairman red_team orchestrator business_agents tests
uv run python -m pytest --cov=chairman --cov=red_team --cov=orchestrator --cov=business_agents --cov-report=term-missing --cov-fail-under=80 -q
```

## Stage Notes

`research-agent` and the three trading-agent Python CLIs are stage 3.7. They read only `data/stock_pool/master_pool.yaml`, write file-system outputs, and fall back to conservative debug outputs when LLM credentials are unavailable.
