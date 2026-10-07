"""Regression tests for the live-run bug: 'Critic deemed evidence sufficient
(score 0/10)' — contradictory structured output must be normalized."""

from src.agents.critic import CriticAgent, normalize_critique, route_after_critic
from src.models.research import CriticDecision
from tests.conftest import FakeLLM, make_critique, make_evidence, make_plan

THRESHOLD = 7


def _normalized(decision, score):
    return normalize_critique(make_critique(decision, score=score), THRESHOLD)


class TestNormalizeCritique:
    def test_synthesize_with_score_0_becomes_more_research(self):
        assert _normalized(CriticDecision.SYNTHESIZE, 0).decision is CriticDecision.MORE_RESEARCH

    def test_synthesize_below_threshold_becomes_more_research(self):
        assert _normalized(CriticDecision.SYNTHESIZE, 6).decision is CriticDecision.MORE_RESEARCH

    def test_synthesize_at_threshold_allowed(self):
        assert _normalized(CriticDecision.SYNTHESIZE, 7).decision is CriticDecision.SYNTHESIZE

    def test_more_research_never_upgraded_even_with_high_score(self):
        # Only the iteration cap (in routing) may force synthesis.
        assert _normalized(CriticDecision.MORE_RESEARCH, 10).decision is CriticDecision.MORE_RESEARCH

    def test_score_preserved_through_normalization(self):
        assert _normalized(CriticDecision.SYNTHESIZE, 0).overall_score == 0


class TestCriticNodeAppliesInvariant:
    def test_contradictory_llm_output_normalized_in_node(self):
        llm = FakeLLM(
            critiques=[make_critique(CriticDecision.SYNTHESIZE, score=0,
                                     follow_ups=["gap query"])]
        )
        agent = CriticAgent(llm, sufficiency_threshold=THRESHOLD)
        state = {
            "question": "q?",
            "plan": make_plan(),
            "evidence": [make_evidence("https://a.com/1")],
            "executed_queries": ["q1"],
            "iteration": 1,
            "max_iterations": 3,
        }
        result = agent(state)
        assert result["critique"].decision is CriticDecision.MORE_RESEARCH
        assert result["pending_queries"] == ["gap query"]


class TestIterationCapStillWins:
    def test_low_score_at_max_iterations_routes_to_synthesizer(self):
        state = {
            "critique": make_critique(CriticDecision.MORE_RESEARCH, score=2,
                                      follow_ups=["more"]),
            "pending_queries": ["more"],
            "iteration": 3,
            "max_iterations": 3,
        }
        assert route_after_critic(state) == "synthesizer"
