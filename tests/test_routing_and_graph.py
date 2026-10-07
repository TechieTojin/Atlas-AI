from src.agents.critic import route_after_critic
from src.graph.workflow import build_workflow, run_atlas
from src.models.research import CriticDecision
from tests.conftest import FakeLLM, make_critique, make_evidence, make_plan, make_search_fn


def _state(decision, pending, iteration, max_iterations=3):
    return {
        "critique": make_critique(decision, follow_ups=pending),
        "pending_queries": pending,
        "iteration": iteration,
        "max_iterations": max_iterations,
    }


class TestRouting:
    def test_insufficient_routes_to_researcher(self):
        state = _state(CriticDecision.MORE_RESEARCH, ["new query"], iteration=1)
        assert route_after_critic(state) == "researcher"

    def test_sufficient_routes_to_synthesizer(self):
        state = _state(CriticDecision.SYNTHESIZE, [], iteration=1)
        assert route_after_critic(state) == "synthesizer"

    def test_iteration_cap_forces_synthesis(self):
        state = _state(CriticDecision.MORE_RESEARCH, ["new query"], iteration=3, max_iterations=3)
        assert route_after_critic(state) == "synthesizer"

    def test_no_follow_up_queries_forces_synthesis(self):
        state = _state(CriticDecision.MORE_RESEARCH, [], iteration=1)
        assert route_after_critic(state) == "synthesizer"


RESULTS = [
    {"url": "https://a.com/1", "title": "A1", "content": "Alpha evidence."},
    {"url": "https://b.com/2", "title": "B2", "content": "Beta evidence."},
]
MORE_RESULTS = [
    {"url": "https://c.com/3", "title": "C3", "content": "Gamma evidence."},
    {"url": "https://a.com/1", "title": "A1 dup", "content": "Duplicate."},
]


class TestGraph:
    def test_graph_constructs(self, config):
        llm = FakeLLM(plans=[make_plan()], critiques=[make_critique(CriticDecision.SYNTHESIZE)])
        app = build_workflow(llm, make_search_fn(default=RESULTS), config)
        nodes = set(app.get_graph().nodes)
        assert {"planner", "researcher", "critic", "synthesizer"} <= nodes

    def test_single_pass_sufficient(self, config):
        llm = FakeLLM(
            plans=[make_plan()],
            critiques=[make_critique(CriticDecision.SYNTHESIZE, score=9)],
            synthesis="Findings [1] and [2].",
        )
        state = run_atlas("q?", config, llm=llm, search_fn=make_search_fn(default=RESULTS))
        assert state["iteration"] == 1
        assert len(state["evidence"]) == 2
        assert "Findings [1] and [2]." in state["final_report"]
        assert "https://a.com/1" in state["final_report"]
        assert "## Sources" in state["final_report"]

    def test_research_loop_runs_second_iteration(self, config):
        llm = FakeLLM(
            plans=[make_plan(n_queries=1)],
            critiques=[
                make_critique(CriticDecision.MORE_RESEARCH, follow_ups=["follow up"]),
                make_critique(CriticDecision.SYNTHESIZE, score=8),
            ],
        )
        search = make_search_fn(
            results_by_query={"av barriers query 0": RESULTS, "follow up": MORE_RESULTS}
        )
        state = run_atlas("q?", config, llm=llm, search_fn=search)
        assert state["iteration"] == 2
        assert "follow up" in search.calls
        # Duplicate URL from second search was deduplicated across iterations.
        assert len(state["evidence"]) == 3

    def test_max_iterations_terminate_loop(self, config):
        always_more = [
            make_critique(CriticDecision.MORE_RESEARCH, follow_ups=[f"fu {i}"])
            for i in range(10)
        ]
        llm = FakeLLM(plans=[make_plan(n_queries=1)], critiques=always_more)
        state = run_atlas("q?", config, llm=llm, search_fn=make_search_fn(default=RESULTS))
        assert state["iteration"] == config.max_research_iterations
        assert state["final_report"]

    def test_empty_search_results_still_produce_report(self, config):
        llm = FakeLLM(plans=[make_plan()], critiques=[])
        state = run_atlas("q?", config, llm=llm, search_fn=make_search_fn(default=[]))
        assert state["final_report"]
        assert "unable to collect any evidence" in state["final_report"]
