"""Tests for deterministic evidence selection (LLM context budgeting)."""

from src.agents.synthesizer import (
    SynthesizerAgent,
    build_numbered_sources,
    format_evidence_for_synthesis,
)
from src.config import load_config
from src.models.research import Evidence, Source
from src.tools.selection import select_evidence
from tests.conftest import FakeLLM


def ev(url, query, score=None, domain=None):
    return Evidence(
        source=Source(title=url, url=url, domain=domain or url.split("/")[2]),
        content=f"content from {url}",
        query=query,
        relevance_score=score,
    )


class TestSelectEvidence:
    def test_under_budget_returns_everything_in_order(self):
        items = [ev(f"https://a.com/{i}", "q1") for i in range(3)]
        assert select_evidence(items, 12) == items

    def test_budget_enforced(self):
        items = [ev(f"https://a.com/{i}", "q1") for i in range(20)]
        assert len(select_evidence(items, 12)) == 12

    def test_round_robin_covers_all_queries(self):
        items = (
            [ev(f"https://a{i}.com/x", "q1") for i in range(6)]
            + [ev(f"https://b{i}.com/x", "q2") for i in range(6)]
            + [ev(f"https://c{i}.com/x", "q3") for i in range(6)]
        )
        picked = select_evidence(items, 6)
        queries = {e.query for e in picked}
        assert queries == {"q1", "q2", "q3"}  # not exhausted by one query
        assert sum(1 for e in picked if e.query == "q1") == 2

    def test_higher_relevance_preferred_within_query(self):
        items = [
            ev("https://low.com/x", "q1", score=0.1),
            ev("https://high.com/x", "q1", score=0.9),
            ev("https://mid.com/x", "q1", score=0.5),
        ]
        picked = select_evidence(items, 1)
        assert picked[0].source.url == "https://high.com/x"

    def test_domain_diversity_preferred(self):
        items = [
            ev("https://same.com/1", "q1", score=0.9, domain="same.com"),
            ev("https://same.com/2", "q1", score=0.8, domain="same.com"),
            ev("https://other.com/1", "q1", score=0.1, domain="other.com"),
        ]
        picked = select_evidence(items, 2)
        assert {e.source.domain for e in picked} == {"same.com", "other.com"}

    def test_deterministic(self):
        items = [ev(f"https://d{i % 4}.com/{i}", f"q{i % 3}", score=(i % 5) / 5) for i in range(20)]
        assert select_evidence(items, 8) == select_evidence(list(items), 8)


class TestNumberingAfterSelection:
    def _many(self, n=20):
        return [ev(f"https://s{i}.com/x", f"q{i % 4}", score=1 - i / 100) for i in range(n)]

    def test_synthesis_numbering_contiguous_and_consistent(self):
        evidence = self._many()
        agent = SynthesizerAgent(FakeLLM(synthesis="Claim [1]. Also [5]."), max_evidence=6)
        report = agent({"question": "q?", "evidence": evidence})["final_report"]

        selected = select_evidence(evidence, 6)
        sources = build_numbered_sources(selected)
        assert len(sources) == 6
        # Sources section numbering is exactly 1..6 over the selected subset.
        for i, s in enumerate(sources, 1):
            assert f"{i}. [{s.title}]({s.url})" in report
        # No unselected source leaks into the report.
        selected_urls = {s.url for s in sources}
        for item in evidence:
            if item.source.url not in selected_urls:
                assert item.source.url not in report

    def test_citation_beyond_subset_is_invalid(self):
        # 20 collected but only 6 synthesized: [7] must not survive.
        agent = SynthesizerAgent(FakeLLM(synthesis="Claim [1]. Out of range [7]."), max_evidence=6)
        report = agent({"question": "q?", "evidence": self._many()})["final_report"]
        assert "[7]" not in report
        assert "[1]" in report

    def test_prompt_contains_only_selected_sources(self):
        evidence = self._many()
        selected = select_evidence(evidence, 6)
        sources = build_numbered_sources(selected)
        text = format_evidence_for_synthesis(selected, sources)
        assert text.count("SOURCE [") == 6


class TestBudgetConfig:
    def test_defaults(self, monkeypatch):
        for var in ("ATLAS_MAX_EVIDENCE_FOR_CRITIC", "ATLAS_MAX_EVIDENCE_FOR_SYNTHESIS",
                    "ATLAS_SUFFICIENCY_THRESHOLD", "ATLAS_REPORT_TARGET_WORDS"):
            monkeypatch.delenv(var, raising=False)
        cfg = load_config(dotenv_path="nonexistent.env")
        assert cfg.max_evidence_for_critic == 12
        assert cfg.max_evidence_for_synthesis == 12
        assert cfg.sufficiency_threshold == 7
        assert cfg.report_target_words == 1000

    def test_env_overrides(self, monkeypatch):
        monkeypatch.setenv("ATLAS_MAX_EVIDENCE_FOR_SYNTHESIS", "8")
        monkeypatch.setenv("ATLAS_SUFFICIENCY_THRESHOLD", "5")
        cfg = load_config(dotenv_path="nonexistent.env")
        assert cfg.max_evidence_for_synthesis == 8
        assert cfg.sufficiency_threshold == 5
