"""Regression tests for the live bug: a Pydantic-valid but semantically empty
ResearchPlan ('Plan ready: 0 subquestions, 0 research queries') flowed through
the entire graph and produced an evidence-free report."""

import pytest

from src.agents.planner import (
    MAX_PLANNER_ATTEMPTS,
    PlannerAgent,
    PlanningError,
    normalize_plan,
    plan_problems,
)
from src.agents.researcher import ResearcherAgent
from src.events.models import EventType
from src.models.research import ResearchPlan, ResearchTask
from src.models.runs import RunStatus, SourceScope
from src.services.research_service import PlanValidationError
from tests.conftest import FakeLLM, make_critique, make_plan, make_search_fn
from tests.conftest_v2 import WEB_RESULTS, make_container
from src.models.research import CriticDecision

EMPTY_PLAN = ResearchPlan(objective="o", tasks=[], search_queries=[])
BLANK_PLAN = ResearchPlan(
    objective="o",
    tasks=[ResearchTask(subquestion="   ", evidence_needed="")],
    search_queries=["", "   "],
)
VALID_PLAN = make_plan(n_queries=2)


def event_types(container, run_id):
    return [e.type for e in container.bus.history(run_id)]


class TestNormalizationAndValidation:
    def test_empty_lists_invalid(self):
        assert len(plan_problems(normalize_plan(EMPTY_PLAN, 5))) == 2

    def test_blank_only_entries_invalid(self):
        normalized = normalize_plan(BLANK_PLAN, 5)
        assert normalized.search_queries == []
        assert normalized.tasks == []
        assert plan_problems(normalized)

    def test_whitespace_around_valid_queries_normalized(self):
        plan = ResearchPlan(
            objective="o",
            tasks=[ResearchTask(subquestion="  Q? ", evidence_needed=" e ")],
            search_queries=["  lithium thermal runaway  ", "", "lithium thermal runaway"],
        )
        normalized = normalize_plan(plan, 5)
        assert normalized.search_queries == ["lithium thermal runaway"]  # trimmed+deduped
        assert normalized.tasks[0].subquestion == "Q?"
        assert plan_problems(normalized) == []

    def test_valid_plan_has_no_problems(self):
        assert plan_problems(normalize_plan(VALID_PLAN, 5)) == []


class TestPlannerRepair:
    def test_valid_plan_accepted_without_repair(self):
        llm = FakeLLM(plans=[VALID_PLAN])
        structured = llm.with_structured_output(ResearchPlan)
        result = PlannerAgent(llm)({"question": "q?"})
        assert result["planner_attempts"] == 1
        assert len(structured.calls) == 1
        assert result["pending_queries"]

    def test_invalid_then_valid_repairs_once_and_proceeds(self):
        llm = FakeLLM(plans=[EMPTY_PLAN, VALID_PLAN])
        structured = llm.with_structured_output(ResearchPlan)
        result = PlannerAgent(llm)({"question": "q?"})
        assert result["planner_attempts"] == 2
        assert len(structured.calls) == 2
        assert result["pending_queries"]
        # Repair prompt explains the rejection without any reasoning leakage.
        repair_messages = str(structured.calls[1])
        assert "no usable" in repair_messages
        assert "<think>" not in repair_messages

    def test_invalid_twice_raises_planning_error(self):
        llm = FakeLLM(plans=[EMPTY_PLAN, BLANK_PLAN])
        structured = llm.with_structured_output(ResearchPlan)
        with pytest.raises(PlanningError, match="usable research plan"):
            PlannerAgent(llm)({"question": "q?"})
        assert len(structured.calls) == MAX_PLANNER_ATTEMPTS == 2  # never a third try

    def test_repair_emits_event(self):
        class Recorder:
            def __init__(self):
                self.events = []

            def emit(self, type_, message="", **kwargs):
                self.events.append((type_, message))

        recorder = Recorder()
        llm = FakeLLM(plans=[EMPTY_PLAN, VALID_PLAN])
        PlannerAgent(llm, emitter=recorder)({"question": "q?"})
        assert recorder.events[0][0] is EventType.PLANNING_REPAIR_STARTED
        assert "think" not in recorder.events[0][1].lower()


class TestRunLevelBehavior:
    def test_web_run_fails_cleanly_when_plan_unrepairable(self, tmp_path):
        llm = FakeLLM(plans=[EMPTY_PLAN, EMPTY_PLAN])
        search = make_search_fn(default=WEB_RESULTS)
        c = make_container(tmp_path, llm=llm, search_fn=search)
        run = c.research_service.create_run("Why thermal runaway?")
        final = c.research_service.get_run(run.id)
        assert final.status is RunStatus.FAILED
        assert "usable research plan" in final.error
        assert final.final_report == ""  # no fake empty report
        assert search.calls == []  # researcher never executed
        types = event_types(c, run.id)
        assert types[-1] is EventType.RUN_FAILED
        assert EventType.PLANNING_REPAIR_STARTED in types
        assert EventType.SEARCH_STARTED not in types
        assert EventType.CRITIC_STARTED not in types
        assert EventType.SYNTHESIS_STARTED not in types

    def test_failed_status_survives_repository_reload(self, tmp_path):
        llm = FakeLLM(plans=[EMPTY_PLAN, EMPTY_PLAN])
        c = make_container(tmp_path, llm=llm)
        run = c.research_service.create_run("q")
        reloaded = c.runs_repo.get(run.id)
        assert reloaded.status is RunStatus.FAILED
        assert "usable research plan" in reloaded.error

    def test_web_run_repaired_plan_completes(self, tmp_path):
        llm = FakeLLM(
            plans=[EMPTY_PLAN, VALID_PLAN],
            critiques=[make_critique(CriticDecision.SYNTHESIZE, score=9)],
        )
        c = make_container(tmp_path, llm=llm)
        run = c.research_service.create_run("q")
        final = c.research_service.get_run(run.id)
        assert final.status is RunStatus.COMPLETED
        assert final.metrics.planner_attempts == 2
        assert "## Sources" in final.final_report

    def test_web_and_documents_scope_same_protection(self, tmp_path):
        llm = FakeLLM(plans=[EMPTY_PLAN, EMPTY_PLAN])
        c = make_container(tmp_path, llm=llm)
        doc = c.document_service.ingest("ctx.txt", b"domain knowledge " * 30)
        run = c.research_service.create_run(
            "q",
            source_scope=SourceScope.WEB_AND_DOCUMENTS,
            document_ids=[doc.id],
        )
        assert c.research_service.get_run(run.id).status is RunStatus.FAILED

    def test_documents_only_run_with_valid_plan_completes(self, tmp_path):
        # Document retrieval is query-driven, so document-only runs need the
        # same usable queries — and with them they work normally.
        llm = FakeLLM(
            plans=[make_plan(n_queries=2)],
            critiques=[make_critique(CriticDecision.SYNTHESIZE, score=9)],
        )
        c = make_container(tmp_path, llm=llm)
        doc = c.document_service.ingest("ctx.txt", b"domain knowledge text " * 30)
        run = c.research_service.create_run(
            "q", source_scope=SourceScope.DOCUMENTS, document_ids=[doc.id]
        )
        final = c.research_service.get_run(run.id)
        assert final.status is RunStatus.COMPLETED
        assert final.metrics.document_chunks_retrieved > 0

    def test_planner_attempts_metric_default_one(self, tmp_path):
        c = make_container(tmp_path)
        run = c.research_service.create_run("q")
        assert c.research_service.get_run(run.id).metrics.planner_attempts == 1


class TestHitlBoundary:
    def test_invalid_unrepairable_plan_never_reaches_approval(self, tmp_path):
        llm = FakeLLM(plans=[EMPTY_PLAN, BLANK_PLAN])
        c = make_container(tmp_path, llm=llm)
        run = c.research_service.create_run("q", approval_required=True)
        final = c.research_service.get_run(run.id)
        assert final.status is RunStatus.FAILED
        types = event_types(c, run.id)
        assert EventType.WAITING_FOR_PLAN_APPROVAL not in types
        assert types[-1] is EventType.RUN_FAILED

    def test_repaired_plan_reaches_approval_normally(self, tmp_path):
        llm = FakeLLM(
            plans=[EMPTY_PLAN, VALID_PLAN],
            critiques=[make_critique(CriticDecision.SYNTHESIZE, score=9)],
        )
        c = make_container(tmp_path, llm=llm)
        run = c.research_service.create_run("q", approval_required=True)
        paused = c.research_service.get_run(run.id)
        assert paused.status is RunStatus.AWAITING_APPROVAL
        assert paused.plan.search_queries
        assert paused.metrics.planner_attempts == 2
        c.research_service.approve_plan(run.id)
        assert c.research_service.get_run(run.id).status is RunStatus.COMPLETED

    def test_user_cannot_edit_plan_to_blank_queries(self, tmp_path):
        c = make_container(tmp_path)
        run = c.research_service.create_run("q", approval_required=True)
        with pytest.raises(PlanValidationError):
            c.research_service.edit_plan(run.id, search_queries=[])
        with pytest.raises(PlanValidationError):
            c.research_service.edit_plan(run.id, search_queries=["", "   "])
        # Run state is not corrupted: still approvable with the original plan.
        paused = c.research_service.get_run(run.id)
        assert paused.status is RunStatus.AWAITING_APPROVAL
        assert paused.plan.search_queries


class TestResearcherDefenseInDepth:
    def _state(self, queries):
        return {
            "pending_queries": queries,
            "iteration": 0,
            "max_iterations": 1,
            "evidence": [],
        }

    def test_zero_queries_rejected(self):
        agent = ResearcherAgent(make_search_fn(default=WEB_RESULTS))
        with pytest.raises(RuntimeError, match="no usable research queries"):
            agent(self._state([]))

    def test_blank_queries_rejected(self):
        agent = ResearcherAgent(make_search_fn(default=WEB_RESULTS))
        with pytest.raises(RuntimeError, match="no usable research queries"):
            agent(self._state(["", "   "]))

    def test_valid_queries_still_run(self):
        agent = ResearcherAgent(make_search_fn(default=WEB_RESULTS))
        result = agent(self._state(["real query"]))
        assert len(result["evidence"]) == 2
