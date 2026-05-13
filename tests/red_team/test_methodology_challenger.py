from __future__ import annotations

from chairman.llm.narrative_generator import LLMClient, LLMError
from red_team.llm.methodology_challenger import generate_challenges
from tests.conftest import make_fengliu


class FailingClient(LLMClient):
    def complete(self, **kwargs):
        raise LLMError("mock failure")


def test_methodology_challenges_template_fallback():
    challenge_set = generate_challenges(make_fengliu("long"), llm_client=FailingClient(), use_llm=True)

    assert len(challenge_set.challenges) == 3
    assert all(q.text.endswith("？") or q.text.endswith("?") for q in challenge_set.challenges)
    assert challenge_set.agent_response_required is True
