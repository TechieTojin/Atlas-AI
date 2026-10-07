"""A comparison must always reach a terminal state.

The bug these cover: the comparison made a bare `llm.invoke` with no output cap
and no deadline. httpx's timeout is per-read, and a streaming generation resets it
with every token, so nothing could stop the call. One ran for 20+ minutes, holding
Ollama so no other request could start, with no way to cancel it.
"""

from __future__ import annotations

import dataclasses
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.cancellation import RunCancelledError
from src.models.research import CriticDecision
from src.models.workspace import ComparisonStatus
from src.services.comparison_synthesis import (
    ComparisonPoint,
    ComparisonSynthesis,
    Conclusion,
    UniqueEvidencePoint,
)
from src.services.comparison_title import comparison_title, topic_phrase
from tests.conftest import FakeLLM, make_critique, make_plan, make_search_fn
from tests.conftest_v2 import make_container

RUN1_RESULTS = [
    {"url": "https://shared.com/x", "title": "Shared", "content": "Shared evidence.", "score": 0.9},
    {"url": "https://only1.com/a", "title": "Only1", "content": "Unique to run one.", "score": 0.8},
]
RUN2_RESULTS = [
    {"url": "https://shared.com/x/", "title": "Shared", "content": "Shared again.", "score": 0.9},
    {"url": "https://only2.com/b", "title": "Only2", "content": "Contradicting data.", "score": 0.8},
]

BATTERY_Q = (
    "Which of the technical barriers previously identified for solid-state "
    "batteries is currently the biggest obstacle to mass production, and why?"
)


def valid_synthesis():
    """Structured output that satisfies every V2.1 semantic rule."""
    return ComparisonSynthesis(
        overview="The runs converge on one barrier and differ on supporting detail.",
        agreements=[ComparisonPoint(
            id="A1", text="Both runs drew on the shared source.",
            runs=[1, 2], citations=[1],
        )],
        contradictions=[],
        unique_evidence=[UniqueEvidencePoint(
            id="U1", run=1, text="Run 1 alone reached its own source.",
            citations=[2],
        )],
        conclusion=Conclusion(
            text="The runs broadly agree.", based_on=["A1", "U1"]
        ),
    )


def two_runs(tmp_path, llm=None):
    base = llm or FakeLLM(
        plans=[make_plan(n_queries=1), make_plan(n_queries=1)],
        critiques=[
            make_critique(CriticDecision.SYNTHESIZE, score=9),
            make_critique(CriticDecision.SYNTHESIZE, score=9),
        ],
        synthesis=["R1 report [1][2].", "R2 report [1][2].", "Comparison [1] vs [2]."],
    )
    c = make_container(
        tmp_path, llm=base, search_fn=make_search_fn(default=RUN1_RESULTS),
        memory_ttl_hours=0,
    )
    run1 = c.research_service.create_run(BATTERY_Q)
    c.research_service._search_factory = lambda cfg: make_search_fn(default=RUN2_RESULTS)
    run2 = c.research_service.create_run(BATTERY_Q)
    base.queue_structured(ComparisonSynthesis, [valid_synthesis()])
    return c, c.research_service.get_run(run1.id), c.research_service.get_run(run2.id)


class SlowLLM(FakeLLM):
    """A model whose generation blocks until released or aborted.

    This is how the real failure behaves: Ollama streams, so the per-read timeout
    never fires and only an abort (closing the socket) ends the call.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.released = threading.Event()
        self.aborted = threading.Event()
        self.started = threading.Event()

    def invoke(self, messages, **kwargs):
        self._block()
        return super().invoke(messages, **kwargs)

    def _block(self):
        self.started.set()
        while not self.released.wait(0.02):
            if self.aborted.is_set():
                raise RuntimeError("connection closed")

    def with_structured_output(self, schema, **kwargs):
        """Comparison synthesis goes through structured output, so that is
        where the generation has to block for these tests to mean anything."""
        inner = super().with_structured_output(schema)
        outer = self

        class Blocking:
            def invoke(self, messages, **kw):
                outer._block()
                return inner.invoke(messages)

        return Blocking()

    def abort(self) -> None:
        self.aborted.set()


class ExplodingLLM(FakeLLM):
    def invoke(self, messages, **kwargs):
        raise RuntimeError("ollama is unreachable")

    def with_structured_output(self, schema, **kwargs):
        class Exploding:
            def invoke(self, messages, **kw):
                raise RuntimeError("ollama is unreachable")

        return Exploding()


def comparison_with(tmp_path, llm, *, threaded=False, **config):
    """Two finished runs plus a comparison service wired to `llm`.

    The shared test executor is synchronous, which keeps research runs
    deterministic but means `create()` would not return until the comparison
    finished. Tests that must interact with a *running* comparison ask for a
    real thread instead.
    """
    c, r1, r2 = two_runs(tmp_path)
    c.comparison_service._llm_factory = lambda cfg, **kw: llm
    if config:
        # AtlasConfig is frozen, so overrides mean a replacement instance.
        c.comparison_service._config = dataclasses.replace(c.config, **config)
    if threaded:
        pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="test-cmp")
        c.comparison_service._executor = pool
        _POOLS.append(pool)
    return c, r1, r2


_POOLS: list[ThreadPoolExecutor] = []


@pytest.fixture(autouse=True)
def _shutdown_pools():
    yield
    while _POOLS:
        _POOLS.pop().shutdown(wait=False)


def wait_for(predicate, timeout=15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def settled(service, comparison_id, timeout=15.0) -> bool:
    return wait_for(lambda: service.get(comparison_id).status.is_terminal, timeout)


class TestTerminalStates:
    def test_successful_comparison_completes(self, tmp_path):
        c, r1, r2 = two_runs(tmp_path)
        comparison = c.comparison_service.create([r1.id, r2.id])

        assert settled(c.comparison_service, comparison.id)
        done = c.comparison_service.get(comparison.id)
        assert done.status is ComparisonStatus.COMPLETED
        assert done.report
        assert done.started_at is not None
        assert done.completed_at is not None
        assert done.metrics["outcome"] == "completed"

    def test_model_exception_marks_failed_not_running(self, tmp_path):
        c, r1, r2 = comparison_with(tmp_path, ExplodingLLM())
        comparison = c.comparison_service.create([r1.id, r2.id])

        assert settled(c.comparison_service, comparison.id)
        failed = c.comparison_service.get(comparison.id)
        assert failed.status is ComparisonStatus.FAILED
        assert "ollama is unreachable" in failed.error
        assert failed.metrics["outcome"] == "failed"

    @pytest.mark.parametrize("body", ["", "   ", "no citations at all"])
    def test_empty_or_malformed_output_still_settles(self, tmp_path, body):
        c, r1, r2 = comparison_with(tmp_path, FakeLLM(synthesis=body))
        # No structured output queued: the model returns nothing usable.
        comparison = c.comparison_service.create([r1.id, r2.id])

        assert settled(c.comparison_service, comparison.id)
        done = c.comparison_service.get(comparison.id)
        assert done.status.is_terminal
        if done.status is ComparisonStatus.COMPLETED:
            # The deterministic half of the report is produced regardless.
            assert "Source Differences" in done.report


class TestDeadline:
    def test_deadline_times_out_instead_of_running_forever(self, tmp_path):
        c, r1, r2 = comparison_with(tmp_path, SlowLLM(), comparison_timeout_seconds=1)
        comparison = c.comparison_service.create([r1.id, r2.id])

        assert settled(c.comparison_service, comparison.id, 25)
        timed_out = c.comparison_service.get(comparison.id)
        assert timed_out.status is ComparisonStatus.TIMED_OUT
        assert "time limit" in timed_out.error
        assert timed_out.metrics["outcome"] == "timed_out"

    def test_timeout_aborts_the_underlying_request(self, tmp_path):
        llm = SlowLLM()
        c, r1, r2 = comparison_with(tmp_path, llm, comparison_timeout_seconds=1)
        c.comparison_service.create([r1.id, r2.id])

        # The abort is what stops Ollama generating and frees it for the next call.
        assert wait_for(lambda: llm.aborted.is_set(), 25)

    def test_a_later_comparison_is_not_blocked_by_a_timed_out_one(self, tmp_path):
        c, r1, r2 = comparison_with(tmp_path, SlowLLM(), comparison_timeout_seconds=1)
        first = c.comparison_service.create([r1.id, r2.id])
        assert settled(c.comparison_service, first.id, 25)

        replacement = FakeLLM(synthesis="unused")
        replacement.queue_structured(ComparisonSynthesis, [valid_synthesis()])
        c.comparison_service._llm_factory = lambda cfg, **kw: replacement
        second = c.comparison_service.create([r1.id, r2.id])

        assert settled(c.comparison_service, second.id, 25)
        assert c.comparison_service.get(second.id).status is ComparisonStatus.COMPLETED


class TestCancellation:
    def test_user_cancellation_reaches_cancelled(self, tmp_path):
        llm = SlowLLM()
        c, r1, r2 = comparison_with(tmp_path, llm, threaded=True)
        comparison = c.comparison_service.create([r1.id, r2.id])
        assert wait_for(lambda: llm.started.is_set())

        c.comparison_service.cancel(comparison.id)

        assert settled(c.comparison_service, comparison.id, 25)
        assert c.comparison_service.get(comparison.id).status is ComparisonStatus.CANCELLED

    def test_cancellation_during_generation_aborts_the_request(self, tmp_path):
        llm = SlowLLM()
        c, r1, r2 = comparison_with(tmp_path, llm, threaded=True)
        comparison = c.comparison_service.create([r1.id, r2.id])
        assert wait_for(lambda: llm.started.is_set())

        c.comparison_service.cancel(comparison.id)

        # Cancel must stop the model, not merely rewrite a database row.
        assert wait_for(lambda: llm.aborted.is_set(), 25)

    def test_cancelling_a_finished_comparison_changes_nothing(self, tmp_path):
        c, r1, r2 = two_runs(tmp_path)
        comparison = c.comparison_service.create([r1.id, r2.id])
        assert settled(c.comparison_service, comparison.id)

        after = c.comparison_service.cancel(comparison.id)

        assert after.status is ComparisonStatus.COMPLETED

    def test_deleting_a_running_comparison_stops_the_model(self, tmp_path):
        llm = SlowLLM()
        c, r1, r2 = comparison_with(tmp_path, llm, threaded=True)
        comparison = c.comparison_service.create([r1.id, r2.id])
        assert wait_for(lambda: llm.started.is_set())

        assert c.comparison_service.delete(comparison.id) is True

        assert wait_for(lambda: llm.aborted.is_set(), 25)

    def test_a_late_result_does_not_resurrect_a_deleted_comparison(self, tmp_path):
        llm = SlowLLM()
        c, r1, r2 = comparison_with(tmp_path, llm, threaded=True)
        comparison = c.comparison_service.create([r1.id, r2.id])
        assert wait_for(lambda: llm.started.is_set())

        c.comparison_service._repo.delete(comparison.id)
        llm.released.set()  # the model answers after the row is gone

        time.sleep(0.6)
        assert c.comparison_service._repo.get(comparison.id) is None


class TestRestartRecovery:
    def _orphan(self, c, comparison_id, status=ComparisonStatus.RUNNING):
        stuck = c.comparison_service.get(comparison_id)
        stuck.status = status
        stuck.completed_at = None
        c.comparison_service._repo.save(stuck)

    def test_restart_closes_orphaned_running_comparisons(self, tmp_path):
        c, r1, r2 = two_runs(tmp_path)
        comparison = c.comparison_service.create([r1.id, r2.id])
        assert settled(c.comparison_service, comparison.id)
        self._orphan(c, comparison.id)

        assert c.comparison_service.recover_interrupted_comparisons() == 1

        recovered = c.comparison_service.get(comparison.id)
        assert recovered.status is ComparisonStatus.FAILED
        assert "server stopped" in recovered.error

    def test_an_orphaned_cancelling_comparison_becomes_cancelled(self, tmp_path):
        c, r1, r2 = two_runs(tmp_path)
        comparison = c.comparison_service.create([r1.id, r2.id])
        assert settled(c.comparison_service, comparison.id)
        self._orphan(c, comparison.id, ComparisonStatus.CANCELLING)

        c.comparison_service.recover_interrupted_comparisons()

        assert c.comparison_service.get(comparison.id).status is ComparisonStatus.CANCELLED

    def test_recovery_leaves_completed_comparisons_alone(self, tmp_path):
        c, r1, r2 = two_runs(tmp_path)
        comparison = c.comparison_service.create([r1.id, r2.id])
        assert settled(c.comparison_service, comparison.id)
        before = c.comparison_service.get(comparison.id)

        assert c.comparison_service.recover_interrupted_comparisons() == 0

        after = c.comparison_service.get(comparison.id)
        assert after.status is ComparisonStatus.COMPLETED
        assert after.report == before.report


class TestObservability:
    def test_aborted_token_counts_are_unavailable_not_zero(self, tmp_path):
        c, r1, r2 = comparison_with(tmp_path, SlowLLM(), comparison_timeout_seconds=1)
        comparison = c.comparison_service.create([r1.id, r2.id])
        assert settled(c.comparison_service, comparison.id, 25)

        metrics = c.comparison_service.get(comparison.id).metrics

        # Reporting 0 would claim the model produced nothing, which is unknown.
        assert metrics["prompt_tokens"] is None
        assert metrics["output_tokens"] is None
        assert metrics["model"]
        assert metrics["phase"] == "synthesising"


class TestDeterministicTitle:
    def test_two_phrasings_of_one_question_get_one_subject(self):
        title = comparison_title([BATTERY_Q, BATTERY_Q])

        assert title.startswith("Comparison: ")
        # The old title repeated the same truncated prefix twice.
        assert " vs " not in title
        assert "solid-state" in title.lower()
        assert len(title) <= 120

    def test_unrelated_questions_are_labelled_side_by_side(self):
        title = comparison_title(
            [BATTERY_Q, "What are the main advantages of solar energy?"]
        )

        assert " vs " in title
        assert "solar" in title.lower()

    def test_titles_are_stable(self):
        assert comparison_title([BATTERY_Q, BATTERY_Q]) == comparison_title(
            [BATTERY_Q, BATTERY_Q]
        )

    def test_question_scaffolding_is_dropped(self):
        phrase = topic_phrase("Why are lithium-ion batteries vulnerable to thermal runaway?")

        assert "why" not in phrase.lower()
        assert "vulnerable" not in phrase.lower()
        assert "lithium-ion batteries" in phrase.lower()

    def test_a_question_of_pure_filler_still_yields_something(self):
        assert comparison_title(["What is it about?"])
        assert comparison_title([])


class TestBackwardCompatibility:
    def test_existing_completed_comparisons_remain_readable(self, tmp_path):
        """Rows written before started_at/metrics existed must still load."""
        c, r1, r2 = two_runs(tmp_path)
        comparison = c.comparison_service.create([r1.id, r2.id])
        assert settled(c.comparison_service, comparison.id)

        # Strip the new fields exactly as an older row would lack them.
        raw = c.comparison_service._repo.get(comparison.id).model_dump(mode="json")
        raw.pop("started_at", None)
        raw.pop("metrics", None)
        from src.models.workspace import Comparison

        restored = Comparison.model_validate(raw)

        assert restored.status is ComparisonStatus.COMPLETED
        assert restored.started_at is None
        assert restored.metrics == {}
        assert restored.report


BLOCK = object()


class SequencedLLM(FakeLLM):
    """Returns a queued sequence of structured results or exceptions.

    Lets a test drive the first attempt and the repair attempt independently.
    """

    def __init__(self, outcomes):
        super().__init__(synthesis="unused")
        self.outcomes = list(outcomes)
        self.calls = 0
        self.aborted = threading.Event()

    def abort(self) -> None:
        self.aborted.set()

    def with_structured_output(self, schema, **kwargs):
        outer = self

        class Sequenced:
            def invoke(self, messages, **kw):
                outer.calls += 1
                outcome = outer.outcomes[min(outer.calls - 1, len(outer.outcomes) - 1)]
                if outcome is BLOCK:
                    # Behaves like a real generation: only an abort ends it.
                    while not outer.aborted.wait(0.02):
                        pass
                    raise RuntimeError("connection closed")
                if isinstance(outcome, Exception):
                    raise outcome
                return outcome

        return Sequenced()


def bad_citation():
    """Structurally valid, but cites a source that does not exist."""
    return ComparisonSynthesis(
        overview="The runs converge on one barrier.",
        agreements=[ComparisonPoint(
            id="A1", text="Claim.", runs=[1, 2], citations=[99]
        )],
        contradictions=[],
        unique_evidence=[],
        conclusion=Conclusion(text="Conclusion.", based_on=["A1"]),
    )


def single_run_agreement():
    """The exact real-world defect: an "agreement" only one run supports."""
    return ComparisonSynthesis(
        overview="The runs converge on one barrier.",
        agreements=[ComparisonPoint(
            id="A1", text="Solid-state electrolytes limit charge movement.",
            runs=[1], citations=[2],
        )],
        contradictions=[],
        unique_evidence=[],
        conclusion=Conclusion(text="Conclusion.", based_on=["A1"]),
    )


class TestStructuredSynthesis:
    def test_valid_structured_output_renders_a_full_report(self, tmp_path):
        c, r1, r2 = two_runs(tmp_path)
        comparison = c.comparison_service.create([r1.id, r2.id])
        assert settled(c.comparison_service, comparison.id)

        done = c.comparison_service.get(comparison.id)
        assert done.status is ComparisonStatus.COMPLETED
        for heading in ("## Overview", "## Agreements", "## Contradictions",
                        "## New or Unique Evidence", "## Conclusion",
                        "## Source Differences", "## Sources"):
            assert heading in done.report
        assert done.report.startswith("# Comparison:")
        assert done.metrics["repair_calls"] == 0

    def test_no_model_narration_reaches_the_report(self, tmp_path):
        c, r1, r2 = two_runs(tmp_path)
        comparison = c.comparison_service.create([r1.id, r2.id])
        assert settled(c.comparison_service, comparison.id)

        report = c.comparison_service.get(comparison.id).report
        for narration in ("We are comparing", "Let me", "We need to",
                          "Now, we write", "Let's go through", "The task is"):
            assert narration not in report

    def test_an_invalid_citation_triggers_one_repair_and_then_succeeds(self, tmp_path):
        llm = SequencedLLM([bad_citation(), valid_synthesis()])
        c, r1, r2 = comparison_with(tmp_path, llm)
        comparison = c.comparison_service.create([r1.id, r2.id])
        assert settled(c.comparison_service, comparison.id)

        done = c.comparison_service.get(comparison.id)
        assert done.status is ComparisonStatus.COMPLETED
        assert llm.calls == 2
        assert done.metrics["repair_calls"] == 1

    def test_a_comparison_that_cannot_be_validated_fails_rather_than_persisting(self, tmp_path):
        llm = SequencedLLM([bad_citation(), bad_citation()])
        c, r1, r2 = comparison_with(tmp_path, llm)
        comparison = c.comparison_service.create([r1.id, r2.id])
        assert settled(c.comparison_service, comparison.id)

        done = c.comparison_service.get(comparison.id)
        assert done.status is ComparisonStatus.FAILED
        assert "could not be validated" in done.error
        # Nothing unverified is kept.
        assert done.report == ""
        assert llm.calls == 2

    def test_unparseable_output_is_repaired_once(self, tmp_path):
        llm = SequencedLLM([ValueError("not valid JSON"), valid_synthesis()])
        c, r1, r2 = comparison_with(tmp_path, llm)
        comparison = c.comparison_service.create([r1.id, r2.id])
        assert settled(c.comparison_service, comparison.id)

        assert c.comparison_service.get(comparison.id).status is ComparisonStatus.COMPLETED
        assert llm.calls == 2

    def test_repeatedly_unparseable_output_fails_safely(self, tmp_path):
        llm = SequencedLLM([ValueError("truncated JSON")])
        c, r1, r2 = comparison_with(tmp_path, llm)
        comparison = c.comparison_service.create([r1.id, r2.id])
        assert settled(c.comparison_service, comparison.id)

        done = c.comparison_service.get(comparison.id)
        assert done.status is ComparisonStatus.FAILED
        assert "structured output" in done.error
        assert llm.calls == 2  # one attempt, one repair, then it stops

    def test_the_repair_attempt_is_bounded_by_the_deadline(self, tmp_path):
        """A repair must run under the same deadline, not open a new unbounded
        generation. Here the first attempt fails validation and the repair hangs:
        the comparison must still reach a terminal state."""
        llm = SequencedLLM([bad_citation(), BLOCK])
        c, r1, r2 = comparison_with(tmp_path, llm, comparison_timeout_seconds=1)
        comparison = c.comparison_service.create([r1.id, r2.id])

        assert settled(c.comparison_service, comparison.id, 30)
        done = c.comparison_service.get(comparison.id)
        assert done.status is ComparisonStatus.TIMED_OUT
        assert llm.calls == 2
        assert llm.aborted.is_set()  # the hung repair was actually stopped

    def test_cancellation_during_synthesis_is_not_swallowed_by_repair(self, tmp_path):
        """A cancelled request must abort, never trigger a retry."""
        llm = SequencedLLM([RunCancelledError("cancelled"), valid_synthesis()])
        c, r1, r2 = comparison_with(tmp_path, llm)
        comparison = c.comparison_service.create([r1.id, r2.id])
        assert settled(c.comparison_service, comparison.id)

        assert c.comparison_service.get(comparison.id).status is ComparisonStatus.CANCELLED
        assert llm.calls == 1

    def test_contradictions_absent_renders_the_explicit_message(self, tmp_path):
        c, r1, r2 = two_runs(tmp_path)
        comparison = c.comparison_service.create([r1.id, r2.id])
        assert settled(c.comparison_service, comparison.id)

        report = c.comparison_service.get(comparison.id).report
        assert "No direct contradiction was identified" in report

    def test_metrics_record_the_new_execution_detail(self, tmp_path):
        c, r1, r2 = two_runs(tmp_path)
        comparison = c.comparison_service.create([r1.id, r2.id])
        assert settled(c.comparison_service, comparison.id)

        metrics = c.comparison_service.get(comparison.id).metrics
        for key in ("prefill_ms", "generation_ms", "validation_ms",
                    "output_cap_reached", "deadline_reached", "repair_calls"):
            assert key in metrics
        assert metrics["deadline_reached"] is False
        assert isinstance(metrics["validation_ms"], int)

    def test_overlap_stats_persisted_match_the_rendered_report(self, tmp_path):
        c, r1, r2 = two_runs(tmp_path)
        comparison = c.comparison_service.create([r1.id, r2.id])
        assert settled(c.comparison_service, comparison.id)

        done = c.comparison_service.get(comparison.id)
        stats = done.overlap_stats
        assert f"- Combined unique sources: {stats['total_sources']}" in done.report
        assert f"- Shared across runs: {stats['shared_sources']}" in done.report
        assert len(done.sources) == stats["total_sources"]


class TestSemanticGrounding:
    """The defects visual inspection found in the real V2 comparison."""

    def test_a_single_run_agreement_is_repaired_not_published(self, tmp_path):
        llm = SequencedLLM([single_run_agreement(), valid_synthesis()])
        c, r1, r2 = comparison_with(tmp_path, llm)
        comparison = c.comparison_service.create([r1.id, r2.id])
        assert settled(c.comparison_service, comparison.id)

        done = c.comparison_service.get(comparison.id)
        assert done.status is ComparisonStatus.COMPLETED
        assert done.metrics["repair_calls"] == 1
        # The one-run claim never reaches the reader.
        assert "Solid-state electrolytes limit charge movement" not in done.report

    def test_a_persistently_single_run_agreement_fails_rather_than_publishing(self, tmp_path):
        llm = SequencedLLM([single_run_agreement()])
        c, r1, r2 = comparison_with(tmp_path, llm)
        comparison = c.comparison_service.create([r1.id, r2.id])
        assert settled(c.comparison_service, comparison.id)

        done = c.comparison_service.get(comparison.id)
        assert done.status is ComparisonStatus.FAILED
        assert "agreement needs at least two runs" in done.error
        assert done.report == ""

    def test_the_repair_prompt_names_the_actual_failure(self, tmp_path):
        """A repair that is not told what was wrong is just a second guess."""
        llm = SequencedLLM([single_run_agreement(), valid_synthesis()])
        c, r1, r2 = comparison_with(tmp_path, llm)
        c.comparison_service.create([r1.id, r2.id])

        from src.prompts.research import COMPARISON_REPAIR

        assert "{problem}" in COMPARISON_REPAIR
        assert "two or more runs" in COMPARISON_REPAIR

    def test_every_rendered_agreement_names_at_least_two_runs(self, tmp_path):
        c, r1, r2 = two_runs(tmp_path)
        comparison = c.comparison_service.create([r1.id, r2.id])
        assert settled(c.comparison_service, comparison.id)

        report = c.comparison_service.get(comparison.id).report
        section = report.split("## Agreements")[1].split("##")[0]
        for line in section.splitlines():
            if line.startswith("- "):
                assert " and " in line.split(":")[0], f"single-run agreement: {line}"

    def test_a_conclusion_source_is_never_shown_as_uncited(self, tmp_path):
        c, r1, r2 = two_runs(tmp_path)
        comparison = c.comparison_service.create([r1.id, r2.id])
        assert settled(c.comparison_service, comparison.id)

        report = c.comparison_service.get(comparison.id).report
        import re

        conclusion = report.split("## Conclusion")[1].split("## Source Differences")[0]
        sources = report.split("## Sources")[1]
        for number in {int(n) for n in re.findall(r"\[(\d+)\]", conclusion)}:
            line = next(l for l in sources.splitlines() if l.startswith(f"{number}. "))
            assert "collected, not cited" not in line


class TestRepairAccounting:
    def test_a_repair_is_counted_even_when_the_comparison_fails(self, tmp_path):
        """Metrics that hide a repair make a failure look cheaper than it was."""
        llm = SequencedLLM([single_run_agreement()])
        c, r1, r2 = comparison_with(tmp_path, llm)
        comparison = c.comparison_service.create([r1.id, r2.id])
        assert settled(c.comparison_service, comparison.id)

        done = c.comparison_service.get(comparison.id)
        assert done.status is ComparisonStatus.FAILED
        assert done.metrics["repair_calls"] == 1
        assert done.metrics["llm_calls"] == 2
