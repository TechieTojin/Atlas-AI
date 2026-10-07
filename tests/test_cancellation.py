"""Cancellation and hard-timeout behaviour.

Mid-run tests use a real thread pool and a model double that blocks like an
in-flight HTTP request until it is ABORTED (the equivalent of Atlas closing
the request's connection), so they prove the request was actually stopped —
not merely that a status flag changed.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.cancellation import (
    CancelScope,
    RunCancelledError,
    StageTimeoutError,
    run_abortable,
)
from src.events.models import EventType
from src.llm import AbortableLLM, abort_chat_model
from src.models.research import CriticDecision, Critique, ResearchPlan
from src.models.runs import ResearchRun, RunMode, RunStatus
from src.services.research_service import InvalidRunStateError
from tests.conftest import FakeLLM, FakeMessage, make_critique, make_plan, make_search_fn
from tests.conftest_v2 import WEB_RESULTS, make_container


class BlockingModel:
    """Blocks in invoke() until aborted (or released); records lifecycle."""

    def __init__(self, release_after: float | None = None):
        self.started = threading.Event()
        self.unblocked = threading.Event()
        self.finished = threading.Event()
        self.aborted = False
        self.release_after = release_after
        self.result = None

    def abort(self):
        self.aborted = True
        self.unblocked.set()

    def with_structured_output(self, schema, **kwargs):
        return self

    def invoke(self, messages, **kwargs):
        self.started.set()
        try:
            self.unblocked.wait(self.release_after if self.release_after else 30)
            if self.aborted:
                raise ConnectionError("connection closed by client")
            return self.result
        finally:
            self.finished.set()


def stage_factory(blocking_stage: str, blocker: BlockingModel, builds: list):
    """LLM factory: the chosen stage blocks, every other stage is a fast fake."""
    fast = FakeLLM(
        plans=[make_plan(n_queries=2)],
        critiques=[make_critique(CriticDecision.SYNTHESIZE, score=9)],
        synthesis="Findings [1] and [2].",
    )

    def factory(cfg, *, reasoning, stage="default", call_sink=None):
        builds.append(stage)
        return blocker if stage == blocking_stage else fast

    return factory


def wait_for(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def threaded_container(tmp_path, **overrides):
    return make_container(
        tmp_path,
        db_path=str(tmp_path / "atlas.db"),
        executor=ThreadPoolExecutor(max_workers=2),
        **overrides,
    )


def event_types(c, run_id):
    return [e.type for e in c.bus.history(run_id)]


def status(c, run_id):
    return c.research_service.get_run(run_id).status


# --------------------------------------------------------------------------
# Unit: hard deadline + abort primitive
# --------------------------------------------------------------------------


class TestRunAbortable:
    def test_returns_result(self):
        assert run_abortable(lambda: 42, lambda: None, timeout=5) == 42

    def test_deadline_is_total_and_aborts(self):
        blocker = BlockingModel()
        start = time.monotonic()
        with pytest.raises(StageTimeoutError):
            run_abortable(lambda: blocker.invoke([]), blocker.abort, timeout=0.5)
        assert time.monotonic() - start < 3
        assert blocker.aborted
        assert blocker.finished.wait(2)  # underlying request no longer running

    def test_cancel_during_call_aborts_promptly(self):
        blocker = BlockingModel()
        scope = CancelScope()
        threading.Timer(0.3, scope.cancel).start()
        start = time.monotonic()
        with pytest.raises(RunCancelledError):
            run_abortable(lambda: blocker.invoke([]), blocker.abort, scope=scope)
        assert time.monotonic() - start < 2
        assert blocker.aborted and blocker.finished.wait(2)

    def test_already_cancelled_never_starts(self):
        scope = CancelScope()
        scope.cancel()
        called = []
        with pytest.raises(RunCancelledError):
            run_abortable(lambda: called.append(1), lambda: None, scope=scope)
        assert called == []

    def test_cancel_racing_a_result_wins(self):
        scope = CancelScope()

        def op():
            scope.cancel()  # cancellation lands as the result is produced
            return "result"

        with pytest.raises(RunCancelledError):
            run_abortable(op, lambda: None, scope=scope)

    def test_cancel_returns_even_if_abort_is_ineffective(self):
        scope = CancelScope()
        never_unblocks = threading.Event()
        threading.Timer(0.2, scope.cancel).start()
        start = time.monotonic()
        with pytest.raises(RunCancelledError):
            run_abortable(lambda: never_unblocks.wait(30), lambda: None,
                          scope=scope, join_seconds=0.2)
        assert time.monotonic() - start < 2

    def test_errors_propagate(self):
        def boom():
            raise ValueError("bad")

        with pytest.raises(ValueError):
            run_abortable(boom, lambda: None, timeout=5)

    def test_timeout_is_a_timeout_error_for_existing_fallbacks(self):
        from src.llm import is_llm_timeout

        assert issubclass(StageTimeoutError, TimeoutError)
        assert is_llm_timeout(StageTimeoutError("x"))
        assert not is_llm_timeout(RunCancelledError("x"))  # never a fallback


class TestAbortChatModel:
    def test_closes_real_ollama_http_connection(self):
        from langchain_ollama import ChatOllama

        model = ChatOllama(model="qwen3:4b")
        http_client = model._client._client
        assert not http_client.is_closed
        abort_chat_model(model)
        assert http_client.is_closed

    def test_fresh_model_per_request(self):
        builds = []

        def build():
            builds.append(1)
            return FakeLLM(synthesis="ok")

        llm = AbortableLLM(build, timeout=5)
        llm.invoke([("user", "a")])
        llm.invoke([("user", "b")])
        assert len(builds) == 2  # an abort can never poison a later request


# --------------------------------------------------------------------------
# Cancellation during every stage (real threads, blocked in-flight requests)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "stage, later_stages",
    [
        ("planner", {"critic", "synthesis"}),
        ("critic", {"synthesis"}),
        ("synthesis", set()),
    ],
)
def test_cancel_during_llm_stage_aborts_request(tmp_path, stage, later_stages):
    blocker = BlockingModel()
    builds: list[str] = []
    search = make_search_fn(default=WEB_RESULTS)
    c = threaded_container(tmp_path, search_fn=search)
    c.research_service._llm_factory = stage_factory(stage, blocker, builds)

    run = c.research_service.create_run("q", mode=RunMode.FAST)
    assert blocker.started.wait(10), f"{stage} never started"
    builds_before_cancel = list(builds)

    t_cancel = time.monotonic()
    ack = c.research_service.cancel(run.id)
    assert ack.status is RunStatus.CANCELLING

    assert wait_for(lambda: status(c, run.id) is RunStatus.CANCELLED, 5)
    assert time.monotonic() - t_cancel < 3
    assert blocker.aborted, "in-flight request was not aborted"
    assert blocker.finished.wait(2), "request still running after cancel"

    final = c.research_service.get_run(run.id)
    assert final.final_report == ""  # no normal report for a cancelled run
    assert final.completed_at is not None and final.metrics.total_ms > 0
    types = event_types(c, run.id)
    assert EventType.CANCEL_REQUESTED in types
    assert types[-1] is EventType.RUN_CANCELLED
    assert types.count(EventType.RUN_CANCELLED) == 1
    assert EventType.RUN_COMPLETED not in types
    # No later pipeline stage was started after cancellation.
    assert not (set(builds) - set(builds_before_cancel)) & later_stages
    if stage == "planner":
        assert search.calls == []
        assert EventType.SEARCH_STARTED not in types


def test_cancel_during_search_stops_pipeline(tmp_path):
    gate = threading.Event()
    in_search = threading.Event()

    def slow_search(query, max_results):
        in_search.set()
        gate.wait(10)  # a search request in flight
        return WEB_RESULTS[:max_results]

    builds: list[str] = []
    c = threaded_container(tmp_path, search_fn=slow_search)
    c.research_service._llm_factory = stage_factory("none", BlockingModel(), builds)
    run = c.research_service.create_run("q", mode=RunMode.FAST)
    assert in_search.wait(10)

    assert c.research_service.cancel(run.id).status is RunStatus.CANCELLING
    gate.set()  # the in-flight search completes; nothing after it may run
    assert wait_for(lambda: status(c, run.id) is RunStatus.CANCELLED, 5)
    assert "critic" not in builds and "synthesis" not in builds
    final = c.research_service.get_run(run.id)
    assert final.final_report == ""
    assert final.plan is not None  # collected plan kept
    assert EventType.CRITIC_STARTED not in event_types(c, run.id)


def test_cancel_twice_is_idempotent(tmp_path):
    blocker = BlockingModel()
    c = threaded_container(tmp_path)
    c.research_service._llm_factory = stage_factory("planner", blocker, [])
    run = c.research_service.create_run("q", mode=RunMode.FAST)
    assert blocker.started.wait(10)
    first = c.research_service.cancel(run.id)
    second = c.research_service.cancel(run.id)
    assert first.status is RunStatus.CANCELLING
    assert second.status in (RunStatus.CANCELLING, RunStatus.CANCELLED)
    assert wait_for(lambda: status(c, run.id) is RunStatus.CANCELLED, 5)
    third = c.research_service.cancel(run.id)  # after completion of cancel
    assert third.status is RunStatus.CANCELLED
    assert event_types(c, run.id).count(EventType.RUN_CANCELLED) == 1
    assert event_types(c, run.id).count(EventType.CANCEL_REQUESTED) == 1


def test_new_run_starts_immediately_after_cancel(tmp_path):
    blocker = BlockingModel()
    c = threaded_container(tmp_path)
    c.research_service._llm_factory = stage_factory("planner", blocker, [])
    first = c.research_service.create_run("q1", mode=RunMode.FAST)
    assert blocker.started.wait(10)
    c.research_service.cancel(first.id)
    assert wait_for(lambda: status(c, first.id) is RunStatus.CANCELLED, 5)
    assert blocker.finished.wait(2)  # worker freed, not stuck behind it

    c.research_service._llm_factory = stage_factory("none", BlockingModel(), [])
    second = c.research_service.create_run("q2", mode=RunMode.FAST)
    assert wait_for(lambda: status(c, second.id) is RunStatus.COMPLETED, 10)
    assert "## Sources" in c.research_service.get_run(second.id).final_report


# --------------------------------------------------------------------------
# Races
# --------------------------------------------------------------------------


class _ManualExecutor:
    def __init__(self):
        self.jobs = []

    def submit(self, fn, *args, **kwargs):
        self.jobs.append((fn, args, kwargs))

    def run_all(self):
        while self.jobs:
            fn, args, kwargs = self.jobs.pop(0)
            fn(*args, **kwargs)


def test_cancel_before_worker_starts_is_not_overwritten(tmp_path):
    executor = _ManualExecutor()
    llm = FakeLLM(plans=[make_plan()])
    c = make_container(tmp_path, llm=llm, executor=executor)
    run = c.research_service.create_run("q")
    assert c.research_service.cancel(run.id).status is RunStatus.CANCELLED
    executor.run_all()  # the queued worker finally starts
    assert status(c, run.id) is RunStatus.CANCELLED  # not overwritten to PLANNING
    assert llm.with_structured_output(ResearchPlan).calls == []  # never planned


def test_cancel_after_completion_reports_finished(tmp_path):
    c = make_container(tmp_path)
    run = c.research_service.create_run("q")
    assert status(c, run.id) is RunStatus.COMPLETED
    with pytest.raises(InvalidRunStateError):
        c.research_service.cancel(run.id)
    assert status(c, run.id) is RunStatus.COMPLETED  # history not corrupted


def test_cancel_landing_as_synthesis_finishes_wins(tmp_path):
    c = make_container(tmp_path)
    run = ResearchRun(query="q", status=RunStatus.SYNTHESIZING)
    c.runs_repo.save(run)
    c.research_service._scope_for(run.id).cancel()
    from src.events import RunEmitter

    c.research_service._finish(
        run.id, RunEmitter(c.bus, run.id),
        {"final_report": "Report [1].", "evidence": [], "executed_queries": []},
    )
    final = c.research_service.get_run(run.id)
    assert final.status is RunStatus.CANCELLED
    assert final.final_report == ""


def test_events_cannot_overwrite_cancelling(tmp_path):
    c = make_container(tmp_path)
    run = ResearchRun(query="q", status=RunStatus.CANCELLING)
    c.runs_repo.save(run)
    from src.events import RunEmitter

    RunEmitter(c.bus, run.id).emit(EventType.SYNTHESIS_STARTED, message="late event")
    assert status(c, run.id) is RunStatus.CANCELLING


class TestInterruptedRunRecovery:
    def test_orphaned_runs_closed_out(self, tmp_path):
        c = make_container(tmp_path)
        planning = ResearchRun(query="stuck", status=RunStatus.PLANNING)
        cancelling = ResearchRun(query="was cancelling", status=RunStatus.CANCELLING)
        awaiting = ResearchRun(query="awaiting", status=RunStatus.AWAITING_APPROVAL)
        for r in (planning, cancelling, awaiting):
            c.runs_repo.save(r)
        assert c.research_service.recover_interrupted_runs() == 2
        assert status(c, planning.id) is RunStatus.FAILED
        assert "Interrupted" in c.research_service.get_run(planning.id).error
        assert status(c, cancelling.id) is RunStatus.CANCELLED
        assert status(c, awaiting.id) is RunStatus.AWAITING_APPROVAL  # resumable

    def test_cancel_of_orphaned_run_completes_immediately(self, tmp_path):
        c = make_container(tmp_path)
        stuck = ResearchRun(query="stuck", status=RunStatus.PLANNING)
        c.runs_repo.save(stuck)  # no live worker (e.g. server restarted)
        assert c.research_service.cancel(stuck.id).status is RunStatus.CANCELLED


# --------------------------------------------------------------------------
# Hard timeouts terminate the request (DEEP config so the limit is testable)
# --------------------------------------------------------------------------


def timeout_container(tmp_path, stage, **limits):
    blocker = BlockingModel()
    builds: list[str] = []
    c = threaded_container(tmp_path, **limits)
    c.research_service._llm_factory = stage_factory(stage, blocker, builds)
    return c, blocker


def test_planner_hard_timeout_terminates_request(tmp_path):
    c, blocker = timeout_container(tmp_path, "planner", planner_timeout_seconds=1)
    start = time.monotonic()
    run = c.research_service.create_run("q", mode=RunMode.DEEP)
    assert wait_for(lambda: status(c, run.id).is_terminal, 10)
    assert time.monotonic() - start < 6
    final = c.research_service.get_run(run.id)
    assert final.status is RunStatus.FAILED
    assert "time budget" in final.error
    assert blocker.aborted and blocker.finished.wait(2)  # not left generating


def test_critic_hard_timeout_terminates_request_and_falls_back(tmp_path):
    c, blocker = timeout_container(tmp_path, "critic", critic_timeout_seconds=1)
    run = c.research_service.create_run("q", mode=RunMode.DEEP)
    assert wait_for(lambda: status(c, run.id).is_terminal, 10)
    final = c.research_service.get_run(run.id)
    assert final.status is RunStatus.COMPLETED
    assert final.metrics.critic_fallback == "critic exceeded its time budget"
    assert blocker.aborted and blocker.finished.wait(2)


def test_synthesis_hard_timeout_terminates_request_and_falls_back(tmp_path):
    c, blocker = timeout_container(tmp_path, "synthesis", synthesis_timeout_seconds=1)
    run = c.research_service.create_run("q", mode=RunMode.DEEP)
    assert wait_for(lambda: status(c, run.id).is_terminal, 10)
    final = c.research_service.get_run(run.id)
    assert final.status is RunStatus.COMPLETED
    assert final.metrics.synthesis_fallback is True
    assert "## Sources" in final.final_report
    assert blocker.aborted and blocker.finished.wait(2)


def test_timeout_does_not_block_next_run(tmp_path):
    c, blocker = timeout_container(tmp_path, "planner", planner_timeout_seconds=1)
    first = c.research_service.create_run("q1", mode=RunMode.DEEP)
    assert wait_for(lambda: status(c, first.id).is_terminal, 10)
    assert blocker.finished.wait(2)
    c.research_service._llm_factory = stage_factory("none", BlockingModel(), [])
    second = c.research_service.create_run("q2", mode=RunMode.DEEP)
    assert wait_for(lambda: status(c, second.id) is RunStatus.COMPLETED, 10)


def test_fast_stage_deadlines_are_real_and_deep_unbounded():
    from src.config import AtlasConfig
    from src.llm import stage_limits
    from src.modes import apply_mode

    fast = apply_mode(AtlasConfig(tavily_api_key="k"), RunMode.FAST)
    deep = apply_mode(AtlasConfig(tavily_api_key="k"), RunMode.DEEP)
    assert stage_limits(fast, "planner")[1] == 150
    assert stage_limits(fast, "critic")[1] == 150
    assert stage_limits(fast, "synthesis")[1] is None  # budget-bounded instead
    assert fast.budget_allocation and fast.run_budget_seconds == 540
    for stage in ("planner", "critic", "synthesis", "repair"):
        assert stage_limits(deep, stage)[1] is None  # DEEP: cancellable, no cap


def test_fast_and_deep_runs_still_complete(tmp_path):
    for mode in (RunMode.FAST, RunMode.DEEP):
        c = make_container(tmp_path)
        run = c.research_service.create_run("q", mode=mode)
        final = c.research_service.get_run(run.id)
        assert final.status is RunStatus.COMPLETED
        assert final.evaluation.passed


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------


def test_cancel_api_idempotent_and_conflict_on_completed(tmp_path):
    from fastapi.testclient import TestClient

    from src.api.app import create_app

    blocker = BlockingModel()
    c = threaded_container(tmp_path)
    c.research_service._llm_factory = stage_factory("planner", blocker, [])
    with TestClient(create_app(c)) as client:
        run_id = client.post("/api/runs", json={"query": "q", "mode": "FAST"}).json()["id"]
        assert blocker.started.wait(10)
        first = client.post(f"/api/runs/{run_id}/cancel")
        assert first.status_code == 200 and first.json()["status"] == "CANCELLING"
        assert client.post(f"/api/runs/{run_id}/cancel").status_code == 200
        assert wait_for(lambda: client.get(f"/api/runs/{run_id}").json()["status"]
                        == "CANCELLED", 5)

        c.research_service._llm_factory = stage_factory("none", BlockingModel(), [])
        done_id = client.post("/api/runs", json={"query": "q2"}).json()["id"]
        assert wait_for(lambda: client.get(f"/api/runs/{done_id}").json()["status"]
                        == "COMPLETED", 10)
        assert client.post(f"/api/runs/{done_id}/cancel").status_code == 409
