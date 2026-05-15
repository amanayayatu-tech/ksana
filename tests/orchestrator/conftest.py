from __future__ import annotations

import sys

import yaml

from tests.conftest import make_f_partner, make_g_partner, make_signal, make_w_partner, write_stock_pool


def write_pipeline_inputs(data_dir):
    write_stock_pool(data_dir)
    signal = make_signal()
    recs = [make_f_partner("long"), make_w_partner("watch"), make_g_partner("watch")]
    signal_dir = data_dir / "research_signals"
    rec_root = data_dir / "recommendations" / "20260513"
    signal_dir.mkdir(parents=True)
    for agent in ["f_partner", "w_partner", "g_partner"]:
        (rec_root / agent).mkdir(parents=True)
    (signal_dir / "RS-20260513-001.yaml").write_text(
        yaml.safe_dump({"research_signal": signal.model_dump(mode="json")}, allow_unicode=True),
        encoding="utf-8",
    )
    for agent_dir, rec in zip(["f_partner", "w_partner", "g_partner"], recs, strict=True):
        (rec_root / agent_dir / f"{rec.recommendation_id}.yaml").write_text(
            yaml.safe_dump({"recommendation": rec.model_dump(mode="json")}, allow_unicode=True),
            encoding="utf-8",
        )


def py_step(code: str):
    return [sys.executable, "-c", code]
