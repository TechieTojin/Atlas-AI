"""FAST budget allocation: report completion > optional critique > repair,
and evidence cleaning for synthesis and the last-resort fallback."""

import pytest

import src.budget as budget_mod
from src.agents.synthesizer import (
    SynthesizerAgent,
    extractive_fallback_report,
    format_evidence_for_synthesis,
)
from src.budget import FINALIZATION_MARGIN_SECONDS, RunBudget
from src.cancellation import awake_clock
from src.config import AtlasConfig
from src.evaluation import evaluate_report
from src.models.research import CriticDecision, Evidence, Source
from src.models.runs import RunMode, RunStatus
from src.modes import apply_mode
from src.tools.excerpts import clean_excerpt, has_claims, is_reference_fragment
from src.tools.selection import select_synthesis_evidence
from tests.conftest import FakeLLM, make_critique, make_plan, make_search_fn
from tests.conftest_v2 import make_container

FAST = apply_mode(AtlasConfig(tavily_api_key="k"), RunMode.FAST)
DEEP = apply_mode(AtlasConfig(tavily_api_key="k"), RunMode.DEEP)

# Measured planner call of the slow hydrogen run (efa29d36).
SLOW_PLANNER = {"stage": "planner", "tokens_available": True, "prompt_tokens": 191,
                "prompt_eval_ms": 8304, "output_tokens": 303, "eval_ms": 67903}
# Measured planner call of the fast solar run (98b6c520).
FAST_PLANNER = {"stage": "planner", "tokens_available": True, "prompt_tokens": 184,
                "prompt_eval_ms": 4212, "output_tokens": 234, "eval_ms": 46630}


def budget_with(remaining_s, calls):
    deadline = awake_clock() + remaining_s
    return RunBudget(FAST, lambda: calls, lambda: deadline)


class TestReserveFromMeasuredSpeed:
    def test_rates_come_from_this_runs_calls(self):
        prefill, generate = budget_with(400, [SLOW_PLANNER]).rates()
        assert prefill == pytest.approx(191 / 8.304, rel=0.01)
        assert generate == pytest.approx(303 / 67.903, rel=0.01)

    def test_slower_machine_means_bigger_reserve(self):
        slow = budget_with(400, [SLOW_PLANNER]).synthesis_reserve()
        fast = budget_with(400, [FAST_PLANNER]).synthesis_reserve()
        assert slow > fast

    def test_defaults_used_when_nothing_measured(self):
        b = budget_with(400, [])
        assert b.rates() == (budget_mod.DEFAULT_PREFILL_TPS, budget_mod.DEFAULT_GENERATE_TPS)


class TestCriticVersusReserve:
    def test_critic_skipped_when_it_would_invade_the_reserve(self):
        # The failing hydrogen run: ~450 s left after planning and search.
        b = budget_with(450, [SLOW_PLANNER])
        reason = b.critic_skip_reason()
        assert "protect the synthesis time reserve" in reason
        assert b.decisions["critic"] == "skipped"

    def test_critic_runs_when_budget_suffices(self):
        # The solar run: ~483 s left with faster measured speed.
        b = budget_with(483, [FAST_PLANNER])
        assert b.critic_skip_reason() == ""
        assert b.decisions["critic"] == "ran"

    def test_critic_deadline_never_reaches_into_reserve(self):
        b = budget_with(483, [FAST_PLANNER])
        critic_left = b.critic_deadline() - awake_clock()
        assert critic_left == pytest.approx(483 - b.synthesis_reserve(), abs=1)

    def test_no_run_deadline_means_no_skipping(self):
        b = RunBudget(DEEP, lambda: [], lambda: None)
        assert b.critic_skip_reason() == ""
        assert b.critic_deadline() is None and b.synthesis_deadline() is None


class TestSynthesisAndRepair:
    def test_synthesis_gets_remaining_budget_minus_finalization(self):
        b = budget_with(435, [SLOW_PLANNER])
        left = b.synthesis_deadline() - awake_clock()
        assert left == pytest.approx(435 - FINALIZATION_MARGIN_SECONDS, abs=1)
        assert b.decisions["synthesis_budget_s"] == pytest.approx(420, abs=1)

    def test_repair_cannot_consume_the_reserve(self):
        assert budget_with(60, [SLOW_PLANNER]).repair_check() is False
        assert budget_with(10_000, [SLOW_PLANNER]).repair_check() is True

    def test_fast_synthesis_has_no_fixed_cap_but_a_hard_budget(self):
        from src.llm import stage_limits

        assert stage_limits(FAST, "synthesis")[1] is None
        assert FAST.run_budget_seconds == 540 and FAST.budget_allocation


def service_container(tmp_path, **kw):
    llm = FakeLLM(
        plans=[make_plan()],
        critiques=[make_critique(CriticDecision.SYNTHESIZE, score=9)],
        synthesis='{"report": "Storage is costly [1]. Losses are high [2]."}',
    )
    search = make_search_fn(default=[
        {"url": "https://a.org/1", "title": "Storage costs", "score": 0.9,
         "content": "Hydrogen storage requires high-pressure tanks that add significant cost."},
        {"url": "https://b.org/2", "title": "Efficiency", "score": 0.8,
         "content": "Round-trip conversion of electricity through hydrogen loses most of the energy."},
    ])
    return make_container(tmp_path, llm=llm, search_fn=search, **kw), llm


class TestServiceAllocation:
    def test_fast_completes_normally_and_records_decisions(self, tmp_path):
        c, _ = service_container(tmp_path)
        run = c.research_service.create_run("q", mode=RunMode.FAST)
        final = c.research_service.get_run(run.id)
        assert final.status is RunStatus.COMPLETED
        assert final.metrics.synthesis_fallback is False
        assert final.metrics.budget_decisions["critic"] == "ran"
        assert final.metrics.budget_decisions["synthesis_budget_s"] > 0
        assert evaluate_report(final.final_report, final.selected_sources).passed

    def test_critic_skipped_to_protect_report_which_still_completes(self, tmp_path, monkeypatch):
        monkeypatch.setattr(RunBudget, "synthesis_reserve", lambda self: 10_000)
        c, llm = service_container(tmp_path)
        run = c.research_service.create_run("q", mode=RunMode.FAST)
        final = c.research_service.get_run(run.id)
        assert final.status is RunStatus.COMPLETED
        assert final.metrics.synthesis_fallback is False  # normal report
        assert "protect the synthesis time reserve" in final.metrics.critic_fallback
        assert final.metrics.budget_decisions["critic"] == "skipped"
        assert final.metrics.critic_scores == []
        from src.models.research import Critique

        assert llm.with_structured_output(Critique).calls == []  # no critic request

    def test_deep_unchanged(self, tmp_path):
        c, llm = service_container(tmp_path)
        run = c.research_service.create_run("q", mode=RunMode.DEEP)
        final = c.research_service.get_run(run.id)
        assert final.status is RunStatus.COMPLETED
        assert final.metrics.budget_decisions == {}
        assert not DEEP.synthesis_clean_evidence and not DEEP.budget_allocation


# --- evidence cleaning --------------------------------------------------------

BIBLIOGRAPHY = ("29. Srinivasan, S.; Robinson, C.; Blakey, S.; Mauduit-LeClercq, C.; "
                "Bernu, J.; Pantazopoulou, A. S & P Global Hydrogen: New Ambitions and "
                "Challenges. Available online: (accessed on 28 June 2026). 30. Linde.")
ECHO = ("Ecosense ecosense # Cost to Produce Hydrogen & The Factors Affecting The cost to "
        "produce hydrogen ranges from approximately $1.50-2.50 per kg for grey hydrogen.")
KEYWORDS = ("Hydrogen (Pink Hydrogen) LCOH Analysis Applying Average Nuclear Power "
            "Settlement Price Clean Hydrogen Overseas Introduction Cost")
CLAIM = ("Hydrogen storage and transportation pose significant risks because high pressure "
         "lets hydrogen atoms penetrate and embrittle steel pipelines.")


def ev(url, content, title="T", query="hydrogen storage risks"):
    return Evidence(source=Source(title=title, url=url, domain=url.split("/")[2]),
                    content=content, query=query, relevance_score=0.5)


class TestExcerptCleaning:
    def test_bibliography_rejected(self):
        assert is_reference_fragment(BIBLIOGRAPHY.split(" 30.")[0])
        assert not has_claims(BIBLIOGRAPHY)

    def test_keyword_list_rejected(self):
        assert not has_claims(KEYWORDS)

    def test_site_and_title_echo_removed(self):
        out = clean_excerpt(ECHO, "Cost to Produce Hydrogen & The Factors Affecting")
        assert out.startswith("The cost to produce hydrogen ranges")
        assert "ecosense" not in out.lower()

    def test_never_cut_mid_sentence_and_deduplicated(self):
        text = f"{CLAIM} {CLAIM} Second complete sentence about hydrogen leaks is here and matters."
        out = clean_excerpt(text, max_chars=len(CLAIM) + 10)
        assert out == CLAIM  # second sentence didn't fit; no partial sentence

    def test_claim_less_items_excluded_before_numbering(self):
        items = [ev("https://ref.org/a", BIBLIOGRAPHY), ev("https://a.org/1", CLAIM),
                 ev("https://b.org/2", CLAIM.replace("steel", "iron")),
                 ev("https://c.org/3", CLAIM.replace("pipelines", "tanks"))]
        chosen = select_synthesis_evidence(items, 6, require_claims=True)
        assert "https://ref.org/a" not in {e.source.url for e in chosen}
        # Without the flag (DEEP) nothing is filtered.
        assert len(select_synthesis_evidence(items, 6)) == 4

    def test_synthesis_prompt_uses_cleaned_text(self):
        items = [ev("https://a.org/1", ECHO, title="Cost to Produce Hydrogen & The Factors Affecting")]
        from src.agents.synthesizer import build_numbered_sources

        text = format_evidence_for_synthesis(items, build_numbered_sources(items), 700, clean=True)
        assert "Ecosense ecosense" not in text and "The cost to produce hydrogen" in text


class TestReadableFallback:
    def test_fallback_excludes_garbage_and_cites_useful_evidence(self):
        items = [ev("https://ref.org/a", BIBLIOGRAPHY), ev("https://a.org/1", CLAIM),
                 ev("https://k.org/k", KEYWORDS, query="hydrogen costs"),
                 ev("https://b.org/2", ECHO, title="Cost to Produce Hydrogen & The Factors Affecting",
                    query="hydrogen costs")]
        from src.agents.synthesizer import build_numbered_sources

        sources = build_numbered_sources(items)
        report = extractive_fallback_report(items, sources)
        assert "Srinivasan" not in report and "LCOH Analysis" not in report
        assert "Ecosense ecosense" not in report
        assert f"{CLAIM} [2]" in report  # verbatim, cited to its real source
        assert "The cost to produce hydrogen ranges" in report and "[4]" in report
        assert "### Hydrogen storage risks" in report and "### Hydrogen costs" in report
        evaluation = evaluate_report(report + "\n\n## Sources\n\n1. x", sources)
        assert evaluation.has_citations and evaluation.citations_valid

    def test_fallback_without_any_claims_says_so(self):
        items = [ev("https://ref.org/a", BIBLIOGRAPHY)]
        from src.agents.synthesizer import build_numbered_sources

        report = extractive_fallback_report(items, build_numbered_sources(items))
        assert "No claim-bearing excerpts" in report and "Srinivasan" not in report


class TestEmptyDraft:
    """Live failure (run 5c9ecec4): JSON mode returned {"report": ""}, and an
    empty body was saved as a 'completed' report with zero citations."""

    EVIDENCE = [ev("https://a.org/1", CLAIM),
                ev("https://b.org/2", CLAIM.replace("steel", "iron"))]

    def test_empty_draft_retried_once_then_succeeds(self):
        llm = FakeLLM(synthesis=['{"report": ""}', '{"report": "Pipelines embrittle [1][2]."}'])
        result = SynthesizerAgent(llm, json_mode=True)({"question": "q?", "evidence": self.EVIDENCE})
        assert len(llm.invoke_calls) == 2
        assert "previous answer was empty" in llm.invoke_calls[1][1][1]
        assert result["final_report"].startswith("Pipelines embrittle [1][2].")
        assert not result.get("synthesis_fallback")

    def test_still_empty_falls_back_to_cited_summary(self):
        llm = FakeLLM(synthesis='{"report": ""}')
        result = SynthesizerAgent(llm, json_mode=True)({"question": "q?", "evidence": self.EVIDENCE})
        assert len(llm.invoke_calls) == 2  # exactly one retry
        assert result["synthesis_fallback"] is True
        assert result["synthesis_fallback_reason"] == "model returned an empty report"
        assert result["sources_cited"] >= 1

    def test_no_retry_when_budget_cannot_afford_it(self):
        llm = FakeLLM(synthesis='{"report": ""}')
        result = SynthesizerAgent(llm, json_mode=True, retry_check=lambda: False)(
            {"question": "q?", "evidence": self.EVIDENCE})
        assert len(llm.invoke_calls) == 1
        assert result["synthesis_fallback"] is True

    def test_retry_check_uses_synthesis_estimate(self):
        assert budget_with(30, [SLOW_PLANNER]).synthesis_retry_check() is False
        assert budget_with(1000, [SLOW_PLANNER]).synthesis_retry_check() is True

    def test_empty_detection(self):
        from src.agents.synthesizer import is_empty_draft

        for empty in ("", "   ", "{}", "[1] [2].", "-- ."):
            assert is_empty_draft(empty)
        assert not is_empty_draft("Uncited draft.")


def test_calls_spanning_sleep_are_excluded_from_speed_measurement():
    # Live run f796b09f: the planner call spanned an overnight sleep.
    slept = {**SLOW_PLANNER, "eval_ms": 18_000_000, "duration_ms": 18_049_500,
             "suspended_ms": 17_980_000}
    b = budget_with(450, [slept])
    assert b.rates() == (budget_mod.DEFAULT_PREFILL_TPS, budget_mod.DEFAULT_GENERATE_TPS)
    assert b.critic_estimate() < 300  # sane, not ~20,000 s
    awake = budget_with(450, [slept, FAST_PLANNER])
    assert awake.rates()[1] == pytest.approx(234 / 46.63, rel=0.01)
