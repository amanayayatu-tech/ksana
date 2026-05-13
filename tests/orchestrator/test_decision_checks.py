from __future__ import annotations

from pathlib import Path


def test_no_perplexity_api_call_orchestrator():
    root = Path(__file__).resolve().parents[2] / "orchestrator"
    forbidden = ["perplexity api", "perplexity_client", "requests.get(", "requests.post(", "httpx.get(", "httpx.post("]
    hits = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        for fragment in forbidden:
            if fragment in text:
                hits.append(f"{path}: {fragment}")
    assert hits == []
