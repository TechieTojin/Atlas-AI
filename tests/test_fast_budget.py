"""FAST-mode performance budget: configuration, bounded LLM work, timeouts,
fallbacks, LLM-call metrics, and parallel retrieval."""

import time
import uuid

import httpx
import pytest

from src.cancellation import awake_clock
from src.agents.critic import CriticAgent
from src.agents.planner import PlannerAgent, PlanningError
from src.agents.researcher import ResearcherAgent
from src.agents.synthesizer import SynthesizerAgent, extractive_fallback_report
from src.config import AtlasConfig
from src.evaluation import evaluate_report
from src.llm import (
    LLMCallRecorder,
    LLMCallSink,
    create_llm,
    is_llm_timeout,
    make_llm,
    stage_limits,
)
from src.models.research import CriticDecision, Critique, ResearchPlan
from src.models.runs import RunMode
from src.modes import apply_mode
from tests.conftest import FakeLLM, FakeMessage, make_critique, make_evidence, make_plan, make_search_fn
from tests.conftest_v2 import WEB_RESULTS, make_container

BASE = AtlasConfig(tavily_api_key="k")
FAST = apply_mode(BASE, RunMode.FAST)
DEEP = apply_mode(BASE, RunMode.DEEP)


def timeout_error():
    return httpx.ReadTimeout("timed out")


class TestFastProfile:
    def test_thinking_disabled_in_fast_only(self):
        assert FAST.ollama_structured_reasoning is False
        assert DEEP.ollama_structured_reasoning is True  # DEEP not degraded

    def test_bounded_queries_iterations_and_evidence(self):
        assert FAST.max_research_iterations == 1
        assert FAST.max_queries_per_iteration <= 3
        assert FAST.planner_max_tasks == 3
        assert FAST.max_evidence_for_critic <= 6
        assert FAST.max_evidence_for_synthesis <= 6
        assert FAST.page_fetch_per_query == 1

    def test_every_llm_stage_has_output_cap_and_timeout(self):
        for stage in ("planner", "critic", "synthesis", "repair"):
            tokens, timeout = stage_limits(FAST, stage)
            assert tokens is not None and 0 < tokens <= 900
            if stage == "synthesis":
                # Bounded by the run budget (minus finalization) instead of a
                # fixed cap; see test_budget_allocation.py.
                assert timeout is None and FAST.budget_allocation
            else:
                assert 0 < timeout <= 180 or (stage == "critic" and timeout <= 150)

    def test_worst_case_stage_time_fits_run_budget(self):
        # Mandatory path (planner + synthesis) must fit; optional stages are
        # skipped by the run budget instead of overrunning.
        assert (
            FAST.planner_timeout_seconds + FAST.synthesis_timeout_seconds
            <= FAST.run_budget_seconds
        )
        assert FAST.run_budget_seconds <= 600

    def test_context_bounded(self):
        assert FAST.synthesis_context_chars <= 4200
        assert FAST.critic_chars_per_evidence <= 350
        assert FAST.synthesis_chars_per_source <= 700

    def test_deep_keeps_full_budgets(self):
        assert DEEP == BASE
        assert stage_limits(DEEP, "synthesis")[0] is None  # uncapped
        assert DEEP.run_budget_seconds == 0

    def test_fast_never_raises_user_caps(self):
        import dataclasses

        tight = dataclasses.replace(BASE, max_queries_per_iteration=2,
                                    max_evidence_for_synthesis=4)
        fast = apply_mode(tight, RunMode.FAST)
        assert fast.max_queries_per_iteration == 2
        assert fast.max_evidence_for_synthesis == 4


class TestOllamaParameters:
    def test_fast_stage_llm_options(self):
        llm = create_llm(FAST, reasoning=False, stage="synthesis")
        assert llm.reasoning is False
        assert llm.num_predict == FAST.synthesis_max_tokens
        assert llm.num_ctx == FAST.llm_num_ctx
        assert llm.keep_alive == FAST.llm_keep_alive

    def test_single_context_size_across_stages(self):
        # num_ctx changes force Ollama model reloads.
        sizes = {create_llm(FAST, stage=s).num_ctx for s in
                 ("planner", "critic", "synthesis", "repair")}
        assert len(sizes) == 1

    def test_make_llm_supports_legacy_factories(self):
        calls = []

        def legacy(cfg, reasoning):
            calls.append(reasoning)
            return "llm"

        assert make_llm(legacy, DEEP, reasoning=False, stage="critic") == "llm"
        assert calls == [False]

    def test_make_llm_passes_stage_when_supported(self):
        seen = {}

        def modern(cfg, *, reasoning, stage="default", call_sink=None):
            seen.update(stage=stage, sink=call_sink)
            return "llm"

        sink = LLMCallSink()
        make_llm(modern, FAST, reasoning=False, stage="critic", call_sink=sink)
        assert seen == {"stage": "critic", "sink": sink}


class TestCallRecorder:
    def test_records_ollama_statistics(self):
        from langchain_core.messages import AIMessage, HumanMessage
        from langchain_core.outputs import ChatGeneration, LLMResult

        sink = LLMCallSink()
        recorder = LLMCallRecorder("critic", sink)
        run_id = uuid.uuid4()
        recorder.on_chat_model_start({}, [[HumanMessage(content="x" * 500)]], run_id=run_id)
        message = AIMessage(
            content="answer",
            response_metadata={
                "prompt_eval_count": 1340, "eval_count": 339,
                "prompt_eval_duration": 62_700_000_000,
                "eval_duration": 101_700_000_000, "load_duration": 0,
                "done_reason": "stop",
            },
        )
        recorder.on_llm_end(
            LLMResult(generations=[[ChatGeneration(message=message)]]), run_id=run_id
        )
        [call] = sink.snapshot()
        assert call["stage"] == "critic"
        assert call["input_chars"] == 500
        assert call["prompt_tokens"] == 1340
        assert call["output_tokens"] == 339
        assert call["prompt_eval_ms"] == 62_700
        assert call["eval_ms"] == 101_700
        assert "answer" not in str(call)  # sizes only, never text

    def test_records_errors_and_summarizes(self):
        sink = LLMCallSink()
        recorder = LLMCallRecorder("synthesis", sink)
        run_id = uuid.uuid4()
        recorder.on_llm_start({}, ["prompt"], run_id=run_id)
        recorder.on_llm_error(timeout_error(), run_id=run_id)
        sink.add({"stage": "planner", "duration_ms": 10, "input_chars": 5,
                  "prompt_tokens": 100, "output_tokens": 50})
        summary = sink.summary()
        assert summary["llm_calls"] == 2
        assert summary["llm_prompt_tokens"] == 100
        assert summary["llm_stage_stats"]["synthesis"]["errors"] == 1

    def test_recorder_fires_through_a_real_chat_model(self):
        from langchain_core.language_models import GenericFakeChatModel

        sink = LLMCallSink()
        model = GenericFakeChatModel(
            messages=iter(["hello"]), callbacks=[LLMCallRecorder("planner", sink)]
        )
        model.invoke("question?")
        assert sink.snapshot()[0]["stage"] == "planner"

    def test_timeout_classification(self):
        assert is_llm_timeout(timeout_error())
        assert is_llm_timeout(TimeoutError())
        wrapped = RuntimeError("outer")
        wrapped.__cause__ = timeout_error()
        assert is_llm_timeout(wrapped)
        assert not is_llm_timeout(ValueError("x"))


class _Raising:
    def __init__(self, exc):
        self.exc = exc
        self.calls = 0

    def invoke(self, *args, **kwargs):
        self.calls += 1
        raise self.exc


class _StructuredRaising(FakeLLM):
    def __init__(self, exc):
        super().__init__()
        self.raiser = _Raising(exc)

    def with_structured_output(self, schema):
        return self.raiser


class TestPlannerBudget:
    def test_compact_plan_hint_and_task_cap(self):
        many = ResearchPlan(
            objective="o",
            tasks=[make_plan().tasks[0]] * 6,
            search_queries=[f"q{i}" for i in range(6)],
        )
        llm = FakeLLM(plans=[many])
        result = PlannerAgent(llm, max_queries=3, max_tasks=3)({"question": "q?"})
        assert len(result["plan"].tasks) == 3
        assert len(result["pending_queries"]) == 3
        prompt = str(llm.with_structured_output(ResearchPlan).calls[0])
        assert "at most 3 subquestions" in prompt

    def test_timeout_fails_cleanly_without_repair(self):
        llm = _StructuredRaising(timeout_error())
        with pytest.raises(PlanningError, match="time budget"):
            PlannerAgent(llm)({"question": "q?"})
        assert llm.raiser.calls == 1  # no repair after a timeout

    def test_truncated_output_triggers_single_repair(self):
        from langchain_core.exceptions import OutputParserException

        llm = _StructuredRaising(OutputParserException("cut off"))
        with pytest.raises(PlanningError, match="usable research plan"):
            PlannerAgent(llm)({"question": "q?"})
        assert llm.raiser.calls == 2  # initial + exactly one repair


def critic_state(iteration=1, max_iterations=1):
    return {
        "question": "q?",
        "plan": make_plan(),
        "evidence": [make_evidence("https://a.com/1", content="x" * 2000)],
        "executed_queries": ["q1"],
        "iteration": iteration,
        "max_iterations": max_iterations,
    }


class TestCriticBudget:
    def test_evidence_excerpts_bounded(self):
        llm = FakeLLM(critiques=[make_critique(CriticDecision.SYNTHESIZE, score=9)])
        CriticAgent(llm, chars_per_evidence=350)(critic_state())
        prompt = str(llm.with_structured_output(Critique).calls[0])
        assert "x" * 350 in prompt and "x" * 351 not in prompt

    def test_final_pass_note_only_on_final_iteration(self):
        llm = FakeLLM(critiques=[make_critique(CriticDecision.SYNTHESIZE, score=9)])
        CriticAgent(llm)(critic_state(iteration=1, max_iterations=1))
        assert "FINAL research pass" in str(llm.with_structured_output(Critique).calls[0])
        llm2 = FakeLLM(critiques=[make_critique(CriticDecision.SYNTHESIZE, score=9)])
        CriticAgent(llm2)(critic_state(iteration=1, max_iterations=3))
        assert "FINAL research pass" not in str(llm2.with_structured_output(Critique).calls[0])

    def test_timeout_falls_back_flagged(self):
        result = CriticAgent(_StructuredRaising(timeout_error()))(critic_state())
        assert result["critic_fallback"] == "critic exceeded its time budget"
        assert result["critique"].decision is CriticDecision.SYNTHESIZE
        assert result["pending_queries"] == []

    def test_budget_exhausted_skips_llm_call(self):
        llm = _StructuredRaising(AssertionError("must not be called"))
        agent = CriticAgent(llm, deadline=awake_clock() + 10, min_seconds_required=500)
        result = agent(critic_state())
        assert result["critic_fallback"] == "run time budget exhausted"
        assert llm.raiser.calls == 0

    def test_schema_puts_assessment_before_score(self):
        # Grammar-constrained decoding emits fields in schema order; without
        # thinking, score-first produced 0/10 on strong evidence live.
        order = list(Critique.model_json_schema()["properties"])
        assert order.index("coverage_assessment") < order.index("overall_score")
        assert order.index("missing_information") < order.index("overall_score")

    def test_programming_errors_still_raise(self):
        with pytest.raises(KeyError):
            CriticAgent(_StructuredRaising(KeyError("bug")))(critic_state())


class _TimeoutChat:
    def __init__(self):
        self.calls = 0

    def invoke(self, messages):
        self.calls += 1
        raise timeout_error()


EVIDENCE = [
    make_evidence("https://a.com/1", title="A", content="Solid-state cells use a ceramic electrolyte. " * 40),
    make_evidence("https://b.com/2", title="B", content="Energy density can exceed 400 Wh/kg in lab cells. " * 40),
]


class TestSynthesisBudget:
    def test_total_context_bounded(self):
        llm = FakeLLM(synthesis="Claim [1][2].")
        SynthesizerAgent(llm, chars_per_source=700, context_chars=600)(
            {"question": "q?", "evidence": EVIDENCE}
        )
        user_prompt = llm.invoke_calls[0][1][1]
        evidence_part = user_prompt.split("Numbered sources")[1]
        assert len(evidence_part) < 600 + 400  # caps + labels/instructions

    def test_timeout_produces_cited_extractive_fallback(self):
        result = SynthesizerAgent(_TimeoutChat())({"question": "q?", "evidence": EVIDENCE})
        report = result["final_report"]
        assert result["synthesis_fallback"] is True
        assert "could not finish writing a narrative report" in report
        assert report.count("## Sources") == 1
        evaluation = evaluate_report(report, [e.source for e in EVIDENCE])
        assert evaluation.has_citations and evaluation.citations_valid
        assert evaluation.no_reasoning_markers

    def test_repair_skipped_when_budget_cannot_afford_it(self):
        llm = FakeLLM(synthesis="Uncited draft.")
        agent = SynthesizerAgent(llm, deadline=awake_clock() + 5, repair_min_seconds=180)
        result = agent({"question": "q?", "evidence": EVIDENCE})
        assert result["repair_skipped"] is True
        assert len(llm.invoke_calls) == 1  # no repair call
        assert "Uncited draft." in result["final_report"]

    def test_repair_timeout_keeps_draft(self):
        class DraftThenTimeout:
            def __init__(self):
                self.calls = 0

            def invoke(self, messages):
                self.calls += 1
                return FakeMessage("Uncited draft.")

        agent = SynthesizerAgent(DraftThenTimeout(), repair_llm=_TimeoutChat())
        result = agent({"question": "q?", "evidence": EVIDENCE})
        assert "Uncited draft." in result["final_report"]
        assert result["sources_cited"] == 0  # nothing fabricated

    def test_fallback_flattens_untrusted_markup(self):
        hostile = [make_evidence("https://a.com/1", content="# Heading\n<script>x</script> fact.")]
        text = extractive_fallback_report(hostile, [hostile[0].source])
        assert "\n# Heading" not in text
        assert all(not line.startswith("#") or line.startswith("## Evidence")
                   for line in text.splitlines())


class _Concurrency:
    """Tracks simultaneous calls; only used for UPPER-bound assertions."""

    def __init__(self):
        import threading

        self.lock = threading.Lock()
        self.active = 0
        self.peak = 0

    def __enter__(self):
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        time.sleep(0.05)

    def __exit__(self, *exc):
        with self.lock:
            self.active -= 1


class TestJsonModeSynthesis:
    """qwen3:4b (2507) is thinking-only: with think:false it deliberates in
    prose before free text. A JSON grammar is the mechanism that measurably
    stopped it, so FAST requests the report as {"report": "..."}."""

    def test_fast_enables_json_mode_deep_does_not(self):
        assert FAST.synthesis_json_mode is True
        assert DEEP.synthesis_json_mode is False

    def test_json_report_decoded_and_grammar_requested(self):
        import json

        from src.agents.synthesizer import REPORT_JSON_SCHEMA

        llm = FakeLLM(synthesis=json.dumps({"report": "## Findings\n\nClaim [1]."}))
        result = SynthesizerAgent(llm, json_mode=True)({"question": "q?", "evidence": EVIDENCE})
        assert llm.invoke_kwargs[0]["format"] == REPORT_JSON_SCHEMA
        assert result["final_report"].startswith("## Findings\n\nClaim [1].")
        assert '"report"' not in result["final_report"]
        assert result["sources_cited"] == 1

    def test_truncated_json_salvaged_and_trimmed(self):
        # Raw JSON text as the model emits it (escaped newlines), cut off by
        # the output cap mid-sentence and before the closing quote/brace.
        llm = FakeLLM(synthesis=r'{"report": "## Findings\n\nDensity is higher [1]. Safety impro')
        result = SynthesizerAgent(llm, json_mode=True, max_words=600)(
            {"question": "q?", "evidence": EVIDENCE}
        )
        report = result["final_report"]
        assert report.startswith("## Findings\n\nDensity is higher [1].")
        assert "impro" not in report  # unfinished sentence trimmed
        assert report.count("## Sources") == 1

    def test_plain_text_still_accepted(self):
        from src.agents.synthesizer import extract_report_text

        assert extract_report_text("Plain markdown [1].") == "Plain markdown [1]."
        assert extract_report_text('{"other": 1}') == '{"other": 1}'

    def test_repair_also_uses_json_mode(self):
        import json

        llm = FakeLLM(synthesis=[json.dumps({"report": "Uncited."}),
                                 json.dumps({"report": "Repaired [2]."})])
        result = SynthesizerAgent(llm, json_mode=True)({"question": "q?", "evidence": EVIDENCE})
        assert len(llm.invoke_kwargs) == 2
        assert all("format" in kw for kw in llm.invoke_kwargs)
        assert "Repaired [2]." in result["final_report"]

    def test_fast_service_run_uses_json_mode(self, tmp_path):
        llm = FakeLLM(
            plans=[make_plan()],
            critiques=[make_critique(CriticDecision.SYNTHESIZE, score=9)],
            synthesis='{"report": "Findings [1] and [2]."}',
        )
        c = make_container(tmp_path, llm=llm)
        run = c.research_service.create_run("q", mode=RunMode.FAST)
        final = c.research_service.get_run(run.id)
        assert "format" in llm.invoke_kwargs[0]
        assert final.final_report.startswith("Findings [1] and [2].")
        assert final.evaluation.passed


class TestLengthCeiling:
    def test_partial_trailing_sentence_trimmed(self):
        from src.agents.synthesizer import trim_partial_sentence

        body = "## Findings\n\nDensity is higher [1]. Safety improves because the"
        assert trim_partial_sentence(body) == "## Findings\n\nDensity is higher [1]."

    def test_complete_text_unchanged(self):
        from src.agents.synthesizer import trim_partial_sentence

        for body in ("Done [2].", "Ends with citation [3]", "Question?"):
            assert trim_partial_sentence(body) == body

    def test_dangling_heading_dropped(self):
        from src.agents.synthesizer import trim_partial_sentence

        assert trim_partial_sentence("Para one [1].\n\n## Conclu") == "Para one [1]."

    def test_word_ceiling_stated_in_prompt(self):
        llm = FakeLLM(synthesis="Claim [1].")
        SynthesizerAgent(llm, max_words=600)({"question": "q?", "evidence": EVIDENCE})
        assert "at most 600 words" in llm.invoke_calls[0][1][1]


class TestParallelRetrieval:
    """A Barrier(n) only releases if n calls are in flight at once, so these
    assertions prove concurrency deterministically (no wall-clock races)."""

    def test_queries_run_concurrently_with_deterministic_order(self):
        import threading

        barrier = threading.Barrier(3, timeout=10)

        def search(query, max_results):
            barrier.wait()  # sequential execution would time out here
            return [{"url": f"https://{query}.com/a", "title": query,
                     "content": f"evidence for {query}", "score": 0.5}]

        agent = ResearcherAgent(search, results_per_query=1, workers=4)
        result = agent({"pending_queries": ["q1", "q2", "q3"], "iteration": 0,
                        "max_iterations": 1, "evidence": []})
        # A broken barrier would be isolated as a failed search (no evidence).
        assert [e.query for e in result["evidence"]] == ["q1", "q2", "q3"]

    def test_worker_cap_respected(self):
        tracker = _Concurrency()

        def slow_search(query, max_results):
            with tracker:
                return []

        ResearcherAgent(slow_search, results_per_query=1, workers=2)(
            {"pending_queries": ["a", "b", "c", "d"], "iteration": 0,
             "max_iterations": 1, "evidence": []}
        )
        assert 1 <= tracker.peak <= 2

    def test_page_fetches_concurrent_and_ordered(self):
        import threading

        from src.tools.webpage import FetchedPage

        barrier = threading.Barrier(3, timeout=10)

        class ConcurrentFetcher:
            def fetch(self, url):
                barrier.wait()
                return FetchedPage(url=url, text=("relevant words about " + url + ". ") * 20)

        results = [{"url": f"https://p{i}.com/a", "title": f"P{i}",
                    "content": f"snippet {i}", "score": 1 - i / 10} for i in range(3)]
        agent = ResearcherAgent(make_search_fn(default=results), results_per_query=3,
                                page_fetcher=ConcurrentFetcher(), page_fetch_per_query=3,
                                workers=4)
        out = agent({"pending_queries": ["words"], "iteration": 0,
                     "max_iterations": 1, "evidence": []})
        assert out["pages_fetched"] == 3  # all three passed the barrier together
        assert [e.source.url for e in out["evidence"]] == [r["url"] for r in results]


class TestServiceIntegration:
    def test_fast_run_records_budget_and_flags(self, tmp_path):
        c = make_container(tmp_path)
        run = c.research_service.create_run("q", mode=RunMode.FAST)
        final = c.research_service.get_run(run.id)
        assert final.status.value == "COMPLETED"
        assert final.metrics.budget_seconds == FAST.run_budget_seconds
        assert final.metrics.critic_fallback == ""
        assert final.metrics.critic_scores == [9]

    def test_stage_llms_requested_per_stage(self, tmp_path):
        stages = []
        llm = FakeLLM(
            plans=[make_plan()],
            critiques=[make_critique(CriticDecision.SYNTHESIZE, score=9)],
            synthesis="Findings [1] and [2].",
        )

        def factory(cfg, *, reasoning, stage="default", call_sink=None):
            stages.append((stage, reasoning, call_sink is not None))
            return llm

        c = make_container(tmp_path)
        c.research_service._llm_factory = factory
        c.research_service.create_run("q", mode=RunMode.FAST)
        # Models are built per request (so an abort closes only that request's
        # connection); no citation repair was needed, so none was built.
        assert {s for s, _, _ in stages} == {"planner", "critic", "synthesis"}
        assert all(not reasoning for _, reasoning, _ in stages)  # FAST: no thinking
        assert all(has_sink for _, _, has_sink in stages)

    def test_critic_fallback_not_recorded_as_score(self, tmp_path):
        llm = FakeLLM(plans=[make_plan()], synthesis="Findings [1] and [2].")
        c = make_container(tmp_path, llm=llm)

        def factory(cfg, *, reasoning, stage="default", call_sink=None):
            if stage == "critic":
                return _StructuredRaising(timeout_error())
            return llm

        c.research_service._llm_factory = factory
        run = c.research_service.create_run("q", mode=RunMode.FAST)
        final = c.research_service.get_run(run.id)
        assert final.status.value == "COMPLETED"
        assert final.metrics.critic_fallback == "critic exceeded its time budget"
        assert final.metrics.critic_scores == []  # placeholder never recorded
        events = [e for e in c.bus.history(run.id) if e.type.value == "CRITIC_COMPLETED"]
        assert "score" not in events[0].payload
