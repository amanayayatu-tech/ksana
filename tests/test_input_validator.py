from __future__ import annotations

import pytest

from chairman.core.input_validator import InputValidationError, validate_recommendation


def test_direction_enum_validation():
    payload = {
        "recommendation_id": "R-FP-20260513-001",
        "agent_id": "f_partner",
        "ticker": "MOCK",
        "market": "US",
        "direction": "maybe",
        "confidence": 50,
    }

    with pytest.raises(InputValidationError) as exc_info:
        validate_recommendation(payload)

    assert "direction" in "; ".join(exc_info.value.errors)
