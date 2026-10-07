"""Regression tests for the live-run bug: Qwen drafting/reasoning text
(including an orphan </think> marker) leaked into the top of report.md."""

from src.agents.synthesizer import SynthesizerAgent, strip_reasoning_artifacts
from tests.conftest import FakeLLM, make_evidence

REPORT = "## Major Technical Barriers\n\nSensors degrade in rain [1]."
LEAKED = (
    "We are rewriting the report with inline citations...\n"
    "Let's go through the original report...\n"
    "Let's write:\n</think>\n\n" + REPORT
)
EVIDENCE = [make_evidence("https://a.com/1", title="A")]


class TestStripReasoningArtifacts:
    def test_full_think_block_removed(self):
        text = "<think>planning the answer</think>\n" + REPORT
        assert strip_reasoning_artifacts(text) == REPORT

    def test_orphan_close_tag_prefix_removed(self):
        assert strip_reasoning_artifacts("</think>\n" + REPORT) == REPORT

    def test_reasoning_prose_before_orphan_close_removed(self):
        assert strip_reasoning_artifacts(LEAKED) == REPORT

    def test_last_close_marker_wins(self):
        text = "draft one </think> more musing </think>\n" + REPORT
        assert strip_reasoning_artifacts(text) == REPORT

    def test_unterminated_open_tag_truncates_reasoning(self):
        text = REPORT + "\n<think>should not leak"
        assert strip_reasoning_artifacts(text) == REPORT

    def test_case_insensitive(self):
        assert strip_reasoning_artifacts("<THINK>x</THINK>" + REPORT) == REPORT

    def test_clean_markdown_untouched(self):
        assert strip_reasoning_artifacts(REPORT) == REPORT

    def test_markdown_mentioning_thinking_in_prose_untouched(self):
        prose = "## Results\n\nResearchers are thinking about safety [1]."
        assert strip_reasoning_artifacts(prose) == prose


class TestCleanupAppliedToBothPaths:
    def test_initial_synthesis_output_cleaned(self):
        agent = SynthesizerAgent(FakeLLM(synthesis=LEAKED))
        report = agent({"question": "q?", "evidence": EVIDENCE})["final_report"]
        assert "rewriting the report" not in report
        assert "</think>" not in report
        assert report.startswith("## Major Technical Barriers")
        assert report.count("## Sources") == 1

    def test_repair_output_cleaned(self):
        # First draft has no citations -> repair runs and leaks reasoning.
        agent = SynthesizerAgent(FakeLLM(synthesis=["Uncited draft.", LEAKED]))
        report = agent({"question": "q?", "evidence": EVIDENCE})["final_report"]
        assert "</think>" not in report
        assert "Let's" not in report
        assert "Sensors degrade in rain [1]." in report
        assert report.count("## Sources") == 1
        assert "https://a.com/1" in report  # source integrity intact

    def test_reasoning_only_output_counts_as_uncited_and_repairs(self):
        # If the whole first response is reasoning, cleanup leaves no
        # citations, so the single repair attempt still fires.
        agent = SynthesizerAgent(
            FakeLLM(synthesis=["pondering... </think>", "Fixed claim [1]."])
        )
        report = agent({"question": "q?", "evidence": EVIDENCE})["final_report"]
        assert "Fixed claim [1]." in report
        assert "pondering" not in report
