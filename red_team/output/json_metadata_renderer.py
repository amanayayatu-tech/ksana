"""JSON renderer for Red Team audit metadata."""

from __future__ import annotations

import json

from red_team.models import RedTeamAudit


def render_json_metadata(audit: RedTeamAudit) -> str:
    return json.dumps(audit.model_dump(mode="json"), ensure_ascii=False, indent=2)
