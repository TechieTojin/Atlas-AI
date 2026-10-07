"""Regression tests for the live-run citation-integrity bug:
'Report complete: 21 sources, 0 cited' plus an LLM-written References list."""

from src.agents.synthesizer import (
    SynthesizerAgent,
    extract_valid_citations,
    format_evidence_for_synthesis,
    build_numbered_sources,
    strip_generated_reference_sections,
    strip_invalid_citations,
)
from src.config import AtlasConfig, DEFAULT_MODEL, load_config
from tests.conftest import FakeLLM, make_evidence

EVIDENCE = [
    make_evidence("https://a.com/1", title="A", content="Alpha fact."),
    make_evidence("https://b.com/2", title="B", content="Beta fact."),
]


def _run(llm: FakeLLM) -> tuple[str, FakeLLM]:
    agent = SynthesizerAgent(llm)
    return agent({"question": "q?", "evidence": EVIDENCE})["final_report"], llm


class TestCitationValidation:
    def test_valid_citation_kept(self):
        assert strip_invalid_citations("Claim [1].", 2) == "Claim [1]."
        assert extract_valid_citations("Claim [1].", 2) == {1}

    def test_out_of_range_citation_removed(self):
        assert strip_invalid_citations("Claim [999].", 2) == "Claim ."
        assert extract_valid_citations("Claim [999].", 2) == set()

    def test_mixed_valid_and_invalid(self):
        cleaned = strip_invalid_citations("A [1] B [999] C [2][3].", 2)
        assert cleaned == "A [1] B  C [2]."
        assert extract_valid_citations(cleaned, 2) == {1, 2}


class TestReferenceSectionStripping:
    def _strip(self, title: str) -> str:
        md = f"Body [1].\n\n## {title}\n\n1. Fake Source\n2. Another\n\n## Next\n\nMore."
        return strip_generated_reference_sections(md)

    def test_references_removed(self):
        out = self._strip("References")
        assert "Fake Source" not in out
        assert "## Next" in out and "More." in out

    def test_bibliography_removed(self):
        assert "Fake Source" not in self._strip("Bibliography")

    def test_llm_sources_section_removed(self):
        assert "Fake Source" not in self._strip("Sources")

    def test_works_cited_at_end_removed(self):
        md = "Body [1].\n\n### Works Cited\n- fake\n- fake2"
        out = strip_generated_reference_sections(md)
        assert "fake" not in out
        assert out.strip() == "Body [1]."

    def test_normal_headings_untouched(self):
        md = "## Technical Barriers\n\nText [1].\n\n## Conclusion\n\nDone [2]."
        assert strip_generated_reference_sections(md) == md


class TestSynthesizerIntegration:
    def test_exactly_one_sources_section(self):
        report, _ = _run(
            FakeLLM(synthesis="Claim [1].\n\n## References\n\n1. Fake [link](https://fake.example)")
        )
        assert report.count("## Sources") == 1
        assert "fake.example" not in report
        assert "https://a.com/1" in report

    def test_urls_only_from_collected_sources(self):
        report, _ = _run(FakeLLM(synthesis="Claim [1][2]."))
        import re

        urls = set(re.findall(r"\((https?://[^)]+)\)", report))
        assert urls == {"https://a.com/1", "https://b.com/2"}

    def test_zero_citations_triggers_single_repair_that_succeeds(self):
        report, llm = _run(
            FakeLLM(synthesis=["Uncited draft.", "Repaired claim [1]."])
        )
        assert len(llm.invoke_calls) == 2
        assert "Repaired claim [1]." in report
        assert "Uncited draft." not in report

    def test_failed_repair_keeps_report_without_fabricating(self):
        report, llm = _run(
            FakeLLM(synthesis=["Uncited draft.", "Still uncited. Bad [999]."])
        )
        assert len(llm.invoke_calls) == 2  # exactly one repair, no retry loop
        # Failed repair is discarded; the original draft is kept honestly.
        assert "Uncited draft." in report
        assert "[999]" not in report
        assert report.count("## Sources") == 1
        assert "https://a.com/1" in report  # real sources still listed

    def test_cited_draft_needs_no_repair(self):
        _, llm = _run(FakeLLM(synthesis="Good claim [2]."))
        assert len(llm.invoke_calls) == 1


class TestEvidenceNumberingFormat:
    def test_source_blocks_numbered_and_merged(self):
        evidence = EVIDENCE + [make_evidence("https://a.com/1", title="A", content="More alpha.")]
        sources = build_numbered_sources(evidence)
        text = format_evidence_for_synthesis(evidence, sources)
        assert "SOURCE [1]\nTitle: A" in text
        assert "SOURCE [2]\nTitle: B" in text
        assert text.count("SOURCE [") == 2  # merged, not duplicated
        assert "More alpha." in text
        assert "https://" not in text  # LLM never sees URLs


class TestModelDefaults:
    def test_default_model_is_qwen3_4b(self, monkeypatch):
        monkeypatch.delenv("ATLAS_MODEL", raising=False)
        assert DEFAULT_MODEL == "qwen3:4b"
        assert load_config(dotenv_path="nonexistent.env").model == "qwen3:4b"

    def test_qwen3_8b_still_selectable(self, monkeypatch):
        monkeypatch.setenv("ATLAS_MODEL", "qwen3:8b")
        assert load_config(dotenv_path="nonexistent.env").model == "qwen3:8b"
