"""Hard deadlines: stage limits, run budget, sleep-safe clock, and honest
metrics for aborted calls. Short durations stand in for 300 s / 9 min."""

import threading
import time
import uuid

import pytest

import src.cancellation as cancellation
from src.cancellation import StageTimeoutError, awake_clock, run_abortable
from src.evaluation import evaluate_report
from src.llm import AbortableLLM, LLMCallRecorder, LLMCallSink
from src.models.research import CriticDecision
from src.models.runs import RunMode, RunStatus
from tests.conftest import FakeLLM, make_critique, make_plan, make_search_fn
from tests.conftest_v2 import make_container


class SlowModel:
    """A 'generation' that takes ``seconds`` unless aborted."""

    def __init__(self, seconds: float):
        self.seconds = seconds
        self.released = threading.Event()
        self.finished = threading.Event()
        self.aborted = False

    def abort(self):
        self.aborted = True
        self.released.set()

    def with_structured_output(self, schema, **kwargs):
        return self

    def invoke(self, messages, **kwargs):
        try:
            if self.released.wait(self.seconds) and self.aborted:
                raise ConnectionError("aborted")
            return "done"
        finally:
            self.finished.set()


class TestStageDeadline:
    def test_pipeline_regains_control_at_the_deadline(self):
        # Equivalent of a 300 s limit vs a 10x longer generation.
        model = SlowModel(10)
        start = time.monotonic()
        with pytest.raises(StageTimeoutError):
            AbortableLLM(lambda: model, timeout=1.0, label="synthesis").invoke([])
        elapsed = time.monotonic() - start
        assert elapsed < 1.0 + 0.6  # deadline + small bounded grace
        assert model.aborted and model.finished.wait(1)  # generation stopped

    def test_unresponsive_helper_never_blocks_the_pipeline(self):
        never = threading.Event()
        start = time.monotonic()
        with pytest.raises(StageTimeoutError):
            run_abortable(lambda: never.wait(60), lambda: None, timeout=0.5,
                          join_seconds=2.0)
        assert time.monotonic() - start < 0.5 + 2.0 + 0.5  # bounded grace only

    def test_next_request_not_blocked_by_aborted_one(self):
        slow = SlowModel(10)
        with pytest.raises(StageTimeoutError):
            AbortableLLM(lambda: slow, timeout=0.5).invoke([])
        start = time.monotonic()
        AbortableLLM(lambda: FakeLLM(synthesis="ok"), timeout=5).invoke([("user", "x")])
        assert time.monotonic() - start < 0.5


class TestRunBudget:
    def test_run_budget_overrides_longer_stage_limit(self):
        model = SlowModel(10)
        deadline = awake_clock() + 0.5  # 0.5 s left in the run
        start = time.monotonic()
        with pytest.raises(StageTimeoutError):
            AbortableLLM(lambda: model, timeout=5.0,
                         run_deadline=lambda: deadline).invoke([])
        assert time.monotonic() - start < 0.5 + 0.6
        assert model.aborted

    def test_exhausted_budget_makes_no_request(self):
        builds = []
        sink = LLMCallSink()
        llm = AbortableLLM(lambda: builds.append(1), timeout=300, label="synthesis",
                           run_deadline=lambda: awake_clock() - 1, sink=sink)
        with pytest.raises(StageTimeoutError, match="budget is exhausted"):
            llm.invoke([])
        assert builds == []
        [call] = sink.snapshot()
        assert call["outcome"] == "skipped" and call["tokens_available"] is False

    def test_fast_run_falls_back_within_budget(self, tmp_path):
        """Budget spent before synthesis: cited Evidence Summary, no overrun."""

        class SlowPlanner(FakeLLM):
            def with_structured_output(self, schema):
                inner = super().with_structured_output(schema)

                class Slow:
                    def invoke(self, messages, **kw):
                        time.sleep(0.6)  # planner fits; critic gets cut by the budget
                        return inner.invoke(messages)
                return Slow()

        llm = SlowPlanner(
            plans=[make_plan()],
            critiques=[make_critique(CriticDecision.SYNTHESIZE, score=9)],
            synthesis="should never be called",
        )
        realistic = make_search_fn(default=[
            {"url": "https://a.org/h2", "title": "Hydrogen storage", "score": 0.9,
             "content": "Hydrogen storage requires high-pressure tanks that add significant cost to every system."},
            {"url": "https://b.org/h2", "title": "Round-trip losses", "score": 0.8,
             "content": "Converting electricity to hydrogen and back loses roughly sixty percent of the energy."},
        ])
        c = make_container(tmp_path, llm=llm, search_fn=realistic, run_budget_seconds=1)
        start = time.monotonic()
        run = c.research_service.create_run("q", mode=RunMode.DEEP)
        final = c.research_service.get_run(run.id)
        assert time.monotonic() - start < 4
        assert final.status is RunStatus.COMPLETED
        assert final.metrics.synthesis_fallback is True
        assert llm.invoke_calls == []  # no synthesis request after budget ran out
        evaluation = evaluate_report(final.final_report, final.selected_sources)
        assert evaluation.has_citations and evaluation.citations_valid
        outcomes = {c["stage"]: c.get("outcome") for c in final.metrics.llm_call_log}
        assert outcomes.get("synthesis") == "skipped"
        assert outcomes.get("critic") == "timed_out"  # bounded by remaining budget
        assert final.metrics.critic_fallback == "critic exceeded its time budget"

    def test_mandatory_planner_bounded_by_run_budget(self, tmp_path):
        slow = SlowModel(10)
        c = make_container(tmp_path, run_budget_seconds=1)
        c.research_service._llm_factory = lambda cfg, reasoning: slow
        start = time.monotonic()
        run = c.research_service.create_run("q", mode=RunMode.DEEP)
        final = c.research_service.get_run(run.id)
        assert time.monotonic() - start < 3
        assert final.status is RunStatus.FAILED and "time budget" in final.error
        assert slow.aborted

    def test_deep_has_no_run_deadline(self, tmp_path):
        c = make_container(tmp_path)
        run = c.research_service.create_run("q", mode=RunMode.DEEP)
        assert c.research_service.get_run(run.id).status is RunStatus.COMPLETED
        assert run.id not in c.research_service._run_deadlines


class TestSleepSafeClock:
    def test_awake_clock_is_monotonic(self):
        a = awake_clock()
        time.sleep(0.05)
        assert awake_clock() > a

    def test_system_sleep_does_not_consume_the_deadline(self, monkeypatch):
        # Simulate standby: real time passes, awake time does not.
        frozen = awake_clock()
        monkeypatch.setattr(cancellation, "awake_clock", lambda: frozen)
        start = time.monotonic()
        result = run_abortable(lambda: (time.sleep(1.0), "finished")[1],
                               lambda: None, timeout=0.5)
        assert result == "finished"  # 1 s "asleep" did not trip the 0.5 s limit
        assert time.monotonic() - start >= 1.0


class TestAbortedCallMetrics:
    def _recorder(self):
        sink = LLMCallSink()
        return sink, LLMCallRecorder("synthesis", sink)

    def test_abort_before_first_token(self):
        sink, rec = self._recorder()
        rid = uuid.uuid4()
        rec.on_llm_start({}, ["prompt"], run_id=rid)
        rec.on_llm_error(ConnectionError("closed"), run_id=rid)
        [call] = sink.snapshot()
        assert call["phase"] == "waiting_for_first_token"
        assert call["prompt_tokens"] is None and call["tokens_available"] is False

    def test_abort_while_generating(self):
        sink, rec = self._recorder()
        rid = uuid.uuid4()
        rec.on_llm_start({}, ["prompt"], run_id=rid)
        rec.on_llm_new_token("a", run_id=rid)
        rec.on_llm_new_token("b", run_id=rid)
        rec.on_llm_error(ConnectionError("closed"), run_id=rid)
        [call] = sink.snapshot()
        assert call["phase"] == "generating"
        assert call["streamed_chunks"] == 2
        assert call["first_token_ms"] is not None

    def test_timeout_outcome_and_unavailable_tokens_in_summary(self):
        sink = LLMCallSink()
        sink.add({"stage": "planner", "duration_ms": 100, "input_chars": 10,
                  "prompt_tokens": 50, "output_tokens": 20, "tokens_available": True})

        class Recorded(SlowModel):
            def invoke(self, messages, **kwargs):
                rid = uuid.uuid4()
                rec = LLMCallRecorder("synthesis", sink)
                rec.on_llm_start({}, ["p"], run_id=rid)
                try:
                    return super().invoke(messages)
                except Exception as exc:
                    rec.on_llm_error(exc, run_id=rid)
                    raise

        with pytest.raises(StageTimeoutError):
            AbortableLLM(lambda: Recorded(10), timeout=0.5, label="synthesis",
                         sink=sink).invoke([])
        summary = sink.summary()
        synth = summary["llm_stage_stats"]["synthesis"]
        assert synth["outcomes"] == ["timed_out"]
        assert synth["tokens_available"] is False
        assert summary["llm_tokens_complete"] is False
        assert summary["llm_prompt_tokens"] == 50  # only genuine counts summed

    def test_suspended_time_is_measured(self, monkeypatch):
        sink, rec = self._recorder()
        clock = {"t": 1000.0}
        monkeypatch.setattr(cancellation, "awake_clock", lambda: clock["t"])
        rid = uuid.uuid4()
        rec.on_llm_start({}, ["p"], run_id=rid)
        time.sleep(0.3)  # wall time passes; awake clock frozen => "asleep"
        rec.on_llm_error(ConnectionError("x"), run_id=rid)
        assert sink.snapshot()[0]["suspended_ms"] >= 250
