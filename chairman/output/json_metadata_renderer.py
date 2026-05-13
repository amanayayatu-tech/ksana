"""JSON metadata rendering for Chairman briefs."""

from __future__ import annotations

import json

from chairman.models import ChairmanBrief


def render_json_metadata(brief: ChairmanBrief) -> str:
    """Render ChairmanBrief as formatted JSON."""

    return json.dumps(brief.model_dump(mode="json"), ensure_ascii=False, indent=2)
