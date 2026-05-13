from __future__ import annotations

import asyncio
import json

import yaml

from orchestrator.core.perplexity_wait import wait_for_perplexity_fill


def test_perplexity_wait_all_filled(tmp_path):
    data_dir = tmp_path / "data"
    (data_dir / "pull_requests").mkdir(parents=True)
    (data_dir / "perplexity_results").mkdir(parents=True)
    (data_dir / "pull_requests" / "P0-1.yaml").write_text(
        yaml.safe_dump({"prompt_id": "P0-1", "priority": "P0"}),
        encoding="utf-8",
    )
    (data_dir / "perplexity_results" / "P0-1_filled.yaml").write_text("ok: true", encoding="utf-8")

    result = asyncio.run(wait_for_perplexity_fill(data_dir=data_dir, run_id="RUN-X", timeout_seconds=0))

    assert result.all_p0_filled is True
    assert result.filled_count == 1


def test_perplexity_wait_timeout(tmp_path):
    data_dir = tmp_path / "data"
    (data_dir / "pull_requests").mkdir(parents=True)
    (data_dir / "pull_requests" / "P0-2.yaml").write_text(
        yaml.safe_dump({"prompt_id": "P0-2", "priority": "P0"}),
        encoding="utf-8",
    )

    result = asyncio.run(wait_for_perplexity_fill(data_dir=data_dir, run_id="RUN-Y", timeout_seconds=0))
    outcome = json.loads((data_dir / "orchestrator" / "perplexity_wait_outcome_RUN-Y.json").read_text())

    assert result.status == "partial"
    assert outcome["evidence_unverified_prompt_ids"] == ["P0-2"]


def test_perplexity_wait_skip_when_no_p0(tmp_path):
    result = asyncio.run(wait_for_perplexity_fill(data_dir=tmp_path / "data", run_id="RUN-Z", timeout_seconds=0))

    assert result.status == "skipped_no_p0"
