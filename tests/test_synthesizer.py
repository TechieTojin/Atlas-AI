from src.agents.synthesizer import (
    SynthesizerAgent,
    build_numbered_sources,
    render_sources_section,
    strip_invalid_citations,
)
from tests.conftest import FakeLLM, make_evidence


class TestSourceIntegrity:
    def test_numbered_sources_unique_and_ordered(self):
        evidence = [
            make_evidence("https://a.com/1", title="A"),
            make_evidence("https://b.com/2", title="B"),
            make_evidence("https://a.com/1/", title="A again"),
        ]
        sources = build_numbered_sources(evidence)
        assert [s.title for s in sources] == ["A", "B"]

    def test_invalid_citations_stripped(self):
        assert strip_invalid_citations("ok [1] bad [9] [2]", valid_max=2) == "ok [1] bad  [2]"

    def test_sources_section_uses_real_urls_only(self):
        sources = build_numbered_sources([make_evidence("https://a.com/1", title="A")])
        section = render_sources_section(sources, cited={1})
        assert "https://a.com/1" in section
        assert section.startswith("## Sources")

    def test_synthesizer_report_contains_only_collected_urls(self):
        evidence = [make_evidence("https://a.com/1", title="A")]
        agent = SynthesizerAgent(
            FakeLLM(synthesis="Claim [1]. Fabricated [4]. See https://fake.example [2].")
        )
        report = agent({"question": "q?", "evidence": evidence})["final_report"]
        # Invalid citation numbers are removed; sources section lists the one real URL.
        assert "[4]" not in report
        assert "1. [A](https://a.com/1)" in report

    def test_no_evidence_reports_honestly(self):
        agent = SynthesizerAgent(FakeLLM())
        report = agent({"question": "q?", "evidence": []})["final_report"]
        assert "unable to collect any evidence" in report
        assert "## Sources" not in report
