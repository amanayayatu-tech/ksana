"""Direction consensus calculation for Chairman."""

from __future__ import annotations

from chairman.core.weight_applier import get_chairman_weight_multiplier
from chairman.models import ConsensusLevel, Direction, DirectionConsensus, Recommendation, ResearchSignal

VOTING_DIRECTIONS = (
    Direction.LONG,
    Direction.SHORT,
    Direction.WATCH,
    Direction.AVOID,
)  # DEC-003: abstain is valuable but not a vote against.


def calculate_direction_consensus(
    recommendations: list[Recommendation],
    research_signal: ResearchSignal | None = None,
) -> DirectionConsensus:
    """Calculate direction consensus without cross-methodology mapping.

    Implements DEC-001, DEC-003, DEC-004, DEC-005, and DEC-008.
    R5/R6/R7 and method-specific interpretation fields are intentionally ignored here.
    """

    del research_signal  # DEC-008: upstream/method-specific audit fields do not affect voting.
    valid_recs = [
        rec
        for rec in recommendations
        if not rec.deployment_compliance.any_failure_must_abstain or rec.direction == Direction.ABSTAIN
    ]

    vote_distribution = {
        "long": [rec.agent_id.value for rec in valid_recs if rec.direction == Direction.LONG],
        "short": [rec.agent_id.value for rec in valid_recs if rec.direction == Direction.SHORT],
        "watch": [rec.agent_id.value for rec in valid_recs if rec.direction == Direction.WATCH],
        "avoid": [rec.agent_id.value for rec in valid_recs if rec.direction == Direction.AVOID],
        "abstain": [rec.agent_id.value for rec in valid_recs if rec.direction == Direction.ABSTAIN],
    }

    long_count = len(vote_distribution["long"])
    short_count = len(vote_distribution["short"])
    avoid_count = len(vote_distribution["avoid"])
    watch_count = len(vote_distribution["watch"])
    abstain_count = len(vote_distribution["abstain"])
    voted_count = long_count + short_count + avoid_count + watch_count
    consensus_level = _classify_consensus(
        long_count=long_count,
        short_count=short_count,
        avoid_count=avoid_count,
        watch_count=watch_count,
        abstain_count=abstain_count,
        voted_count=voted_count,
    )

    weighted_long_strength = sum(
        rec.confidence * get_chairman_weight_multiplier(rec)
        for rec in valid_recs
        if rec.direction == Direction.LONG
    )

    first = valid_recs[0] if valid_recs else None
    return DirectionConsensus(
        ticker=first.ticker if first else None,
        market=first.market if first else None,
        vote_distribution=vote_distribution,
        consensus_level=consensus_level,
        weighted_long_strength=weighted_long_strength,
        agents_voted=voted_count,
        long_count=long_count,
        short_count=short_count,
        avoid_count=avoid_count,
        watch_count=watch_count,
        abstain_count=abstain_count,
    )


def _classify_consensus(
    *,
    long_count: int,
    short_count: int,
    avoid_count: int,
    watch_count: int,
    abstain_count: int,
    voted_count: int,
) -> ConsensusLevel:
    """Classify the nine consensus patterns required by the spec."""

    if voted_count == 0:
        return ConsensusLevel.ALL_ABSTAIN
    if long_count == 3:
        return ConsensusLevel.FULL_CONSENSUS_LONG
    if avoid_count == 3:
        return ConsensusLevel.FULL_CONSENSUS_AVOID
    if long_count >= 1 and avoid_count == 0 and short_count == 0 and watch_count == 0:
        return ConsensusLevel.MAJORITY_LONG
    if long_count >= 2 and avoid_count == 0 and short_count == 0:
        return ConsensusLevel.MAJORITY_LONG
    if avoid_count >= 2 and long_count == 0 and short_count == 0:
        return ConsensusLevel.MAJORITY_AVOID
    if long_count >= 1 and avoid_count >= 1:
        return ConsensusLevel.SPLIT_LONG_VS_AVOID
    if long_count >= 1 and watch_count >= 1 and avoid_count == 0 and short_count == 0:
        return ConsensusLevel.MIXED_LONG_WATCH
    if abstain_count >= 2:
        return ConsensusLevel.MOSTLY_ABSTAIN
    return ConsensusLevel.OTHER
