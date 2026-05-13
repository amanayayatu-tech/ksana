from __future__ import annotations

from pathlib import Path


def test_no_perplexity_api_call():
    """DEC-002: Chairman may mention prompt briefs, but must not call Perplexity."""

    root = Path(__file__).resolve().parents[1] / "chairman"
    forbidden_fragments = [
        "perplexity api",
        "perplexity_client",
        "requests.get(",
        "requests.post(",
        "httpx.get(",
        "httpx.post(",
    ]
    hits = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        for fragment in forbidden_fragments:
            if fragment in text:
                hits.append(f"{path}: {fragment}")

    assert hits == []
