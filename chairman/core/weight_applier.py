"""Chairman weighting rules."""

from __future__ import annotations

from chairman.models import Recommendation

WEIGHT_MULTIPLIER_FOR_UNVERIFIED = 0.7  # DEC-004


def get_chairman_weight_multiplier(rec: Recommendation) -> float:
    """Return Chairman weight multiplier for a recommendation. DEC-004."""

    if any(signal.evidence_unverified_inherited for signal in rec.upstream_research_signals):
        return WEIGHT_MULTIPLIER_FOR_UNVERIFIED
    return 1.0


def weighted_confidence(rec: Recommendation) -> float:
    """Confidence after Chairman weight application. DEC-004."""

    return rec.confidence * get_chairman_weight_multiplier(rec)
