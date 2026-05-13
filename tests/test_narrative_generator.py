from __future__ import annotations

from chairman.llm.narrative_generator import LLMClient, LLMError, generate_disagreement_narrative
from chairman.models import DisagreementAnalysis, DisagreementType
from tests.conftest import make_fengliu, make_wanmu


class FailingClient(LLMClient):
    def complete(self, **kwargs):
        raise LLMError("mock failure")


def test_fallback_when_llm_fails():
    recs = [make_fengliu("long"), make_wanmu("avoid")]
    disagreement = DisagreementAnalysis(
        primary_type=DisagreementType.METHODOLOGY_DNA,
        narrative="llm would rewrite this",
    )

    narrative = generate_disagreement_narrative(recs, disagreement, FailingClient(), use_llm=True)

    assert "方法论 DNA" in narrative
    assert "mock failure" not in narrative
