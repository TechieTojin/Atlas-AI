"""ResearchService tests: lifecycle, events, HITL, cancellation, modes, metrics."""

import pytest

from src.events.models import EventType
from src.models.research import CriticDecision
from src.models.runs import RunMode, RunStatus, SourceScope
from src.services.research_service import InvalidRunStateError, PlanValidationError
from tests.conftest import FakeLLM, make_critique, make_plan, make_search_fn
from tests.conftest_v2 import WEB_RESULTS, make_container


def event_types(container, run_id):
    return [e.type for e in container.bus.history(run_id)]


class TestFullRun:
    def test_completed_run_persisted_with_report_and_metrics(self, tmp_path):
        c = make_container(tmp_path)
        run = c.research_service.create_run("What is X?", mode=RunMode.DEEP)
        final = c.research_service.get_run(run.id)
        assert final.status is RunStatus.COMPLETED
        assert "Findings [1] and [2]." in final.final_report
        assert "## Sources" in final.final_report
        assert final.iterations == 1
        assert final.metrics.sources_collected == 2
        assert final.metrics.sources_selected == 2
        assert final.metrics.sources_cited == 2
        assert final.metrics.citation_coverage == 1.0
        assert final.metrics.search_ms >= 0
        assert final.metrics.critic_scores == [9]
        assert final.evaluation is not None and final.evaluation.passed

    def test_event_ordering_and_terminal_event(self, tmp_path):
        c = make_container(tmp_path)
        run = c.research_service.create_run("What is X?")
        types = event_types(c, run.id)
        assert types[0] is EventType.RUN_STARTED
        assert types[-1] is EventType.RUN_COMPLETED
        for required in (
            EventType.PLANNING_STARTED,
            EventType.PLAN_CREATED,
            EventType.SEARCH_STARTED,
            EventType.SEARCH_QUERY_STARTED,
            EventType.SEARCH_QUERY_COMPLETED,
            EventType.EVIDENCE_COLLECTED,
            EventType.CRITIC_STARTED,
            EventType.CRITIC_COMPLETED,
            EventType.SYNTHESIS_STARTED,
        ):
            assert required in types
        assert types.index(EventType.PLAN_CREATED) < types.index(EventType.SEARCH_STARTED)
        assert types.index(EventType.CRITIC_COMPLETED) < types.index(
            EventType.SYNTHESIS_STARTED
        )

    def test_events_persisted_durably(self, tmp_path):
        c = make_container(tmp_path)
        run = c.research_service.create_run("What is X?")
        stored = c.events_repo.list(run.id)
        assert stored[-1].type is EventType.RUN_COMPLETED
        assert [e.seq for e in stored] == sorted(e.seq for e in stored)

    def test_no_reasoning_markers_in_events(self, tmp_path):
        c = make_container(tmp_path)
        run = c.research_service.create_run("What is X?")
        for event in c.bus.history(run.id):
            assert "<think>" not in event.message.lower()
            assert "</think>" not in str(event.payload).lower()

    def test_failure_produces_failed_status_and_event(self, tmp_path):
        class ExplodingLLM(FakeLLM):
            def with_structured_output(self, schema):
                raise RuntimeError("model exploded")

        c = make_container(tmp_path, llm=ExplodingLLM())
        run = c.research_service.create_run("What is X?")
        final = c.research_service.get_run(run.id)
        assert final.status is RunStatus.FAILED
        assert "model exploded" in final.error
        assert event_types(c, run.id)[-1] is EventType.RUN_FAILED

    def test_empty_query_rejected(self, tmp_path):
        c = make_container(tmp_path)
        with pytest.raises(PlanValidationError):
            c.research_service.create_run("   ")

    def test_documents_scope_requires_documents(self, tmp_path):
        c = make_container(tmp_path)
        with pytest.raises(PlanValidationError):
            c.research_service.create_run("q", source_scope=SourceScope.DOCUMENTS)


class TestModes:
    def test_fast_mode_budgets_applied(self, tmp_path):
        from src.modes import apply_mode
        from src.config import AtlasConfig

        base = AtlasConfig(tavily_api_key="k")
        fast = apply_mode(base, RunMode.FAST)
        assert fast.max_research_iterations == 1
        assert fast.max_queries_per_iteration == 3
        assert fast.max_evidence_for_synthesis == 6
        assert fast.report_target_words == 500
        deep = apply_mode(base, RunMode.DEEP)
        assert deep == base

    def test_fast_never_raises_above_user_config(self, tmp_path):
        import dataclasses
        from src.modes import apply_mode
        from src.config import AtlasConfig

        tight = dataclasses.replace(
            AtlasConfig(tavily_api_key="k"), max_queries_per_iteration=2
        )
        fast = apply_mode(tight, RunMode.FAST)
        assert fast.max_queries_per_iteration == 2

    def test_mode_persisted_with_run(self, tmp_path):
        c = make_container(tmp_path)
        run = c.research_service.create_run("q", mode=RunMode.FAST)
        assert c.research_service.get_run(run.id).mode is RunMode.FAST


class TestHumanInTheLoop:
    def _awaiting(self, tmp_path, llm=None):
        c = make_container(tmp_path, llm=llm)
        run = c.research_service.create_run("What is X?", approval_required=True)
        return c, c.research_service.get_run(run.id)

    def test_pauses_at_awaiting_approval(self, tmp_path):
        c, run = self._awaiting(tmp_path)
        assert run.status is RunStatus.AWAITING_APPROVAL
        assert run.plan is not None
        types = event_types(c, run.id)
        assert EventType.WAITING_FOR_PLAN_APPROVAL in types
        # Research has NOT started.
        assert EventType.SEARCH_STARTED not in types
        assert run.final_report == ""

    def test_approve_resumes_and_completes(self, tmp_path):
        c, run = self._awaiting(tmp_path)
        c.research_service.approve_plan(run.id)
        final = c.research_service.get_run(run.id)
        assert final.status is RunStatus.COMPLETED
        assert "## Sources" in final.final_report
        types = event_types(c, run.id)
        assert EventType.PLAN_APPROVED in types
        assert types[-1] is EventType.RUN_COMPLETED
        # Planner ran exactly once (phase 1); resumed graph skips it.
        assert final.metrics.planner_ms >= 0

    def test_edit_plan_then_approve_uses_edited_queries(self, tmp_path):
        search = make_search_fn(default=WEB_RESULTS)
        llm = FakeLLM(
            plans=[make_plan(n_queries=2)],
            critiques=[make_critique(CriticDecision.SYNTHESIZE, score=9)],
        )
        c = make_container(tmp_path, llm=llm, search_fn=search)
        run = c.research_service.create_run("q", approval_required=True)
        c.research_service.edit_plan(
            run.id, search_queries=["edited query one"], subquestions=["Edited subq?"]
        )
        c.research_service.approve_plan(run.id)
        final = c.research_service.get_run(run.id)
        assert final.status is RunStatus.COMPLETED
        assert search.calls == ["edited query one"]
        assert final.plan.tasks[0].subquestion == "Edited subq?"
        assert EventType.PLAN_EDITED in event_types(c, run.id)

    def test_invalid_edit_rejected(self, tmp_path):
        c, run = self._awaiting(tmp_path)
        with pytest.raises(PlanValidationError):
            c.research_service.edit_plan(run.id, search_queries=["  ", ""])
        with pytest.raises(PlanValidationError):
            c.research_service.edit_plan(run.id, subquestions=[])
        # Still approvable afterwards.
        assert c.research_service.get_run(run.id).status is RunStatus.AWAITING_APPROVAL

    def test_cancel_while_awaiting(self, tmp_path):
        c, run = self._awaiting(tmp_path)
        c.research_service.cancel(run.id)
        final = c.research_service.get_run(run.id)
        assert final.status is RunStatus.CANCELLED
        assert event_types(c, run.id)[-1] is EventType.RUN_CANCELLED

    def test_approve_wrong_state_rejected(self, tmp_path):
        c = make_container(tmp_path)
        run = c.research_service.create_run("q")  # completes immediately
        with pytest.raises(InvalidRunStateError):
            c.research_service.approve_plan(run.id)


class TestExport:
    def test_markdown_export_contains_report_and_header(self, tmp_path):
        c = make_container(tmp_path)
        run = c.research_service.create_run("What is X?")
        exported = c.research_service.export_markdown(run.id)
        assert exported.startswith("# Atlas Research Report")
        assert "**Query:** What is X?" in exported
        assert "Findings [1] and [2]." in exported
        assert "## Sources" in exported

    def test_export_requires_completion(self, tmp_path):
        c = make_container(tmp_path)
        run = c.research_service.create_run("q", approval_required=True)
        with pytest.raises(InvalidRunStateError):
            c.research_service.export_markdown(run.id)
