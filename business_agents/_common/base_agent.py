"""Base classes and logging for business agents."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


@dataclass
class AgentRunResult:
    run_id: str
    output_files: list[Path]
    llm_used: bool
    status: str = "success"


class BaseBusinessAgent:
    """Shared run-log behavior for stage 3.7 agents."""

    agent_name = "business_agent"

    def __init__(self, data_dir: str | Path = "data", project_root: str | Path = ".") -> None:
        self.data_dir = Path(data_dir)
        self.project_root = Path(project_root)
        self.run_id = f"{self.agent_name}-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8]}"

    def log_run(self, payload: dict[str, Any], llm_messages: list[dict[str, Any]] | None = None) -> None:
        today = datetime.now().strftime("%Y%m%d")
        output_dir = self.data_dir / "agent_logs" / today / self.agent_name
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / f"{self.run_id}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (output_dir / f"{self.run_id}.llm.log").write_text(
            yaml.safe_dump(llm_messages or [], allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )


def write_yaml(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path
