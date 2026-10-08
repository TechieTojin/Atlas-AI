"""Scientific notation in generated prose (gemma4:e4b Hindi/French regression).

The live failure: the model wrote ``$\\text{MAPbI}_3$`` inside a JSON string
with one backslash; ``json.loads`` decoded ``\\t`` as TAB and Atlas stored
``$<TAB>ext{MAPbI}_3$``.
"""

import json

import pytest

from src.agents.synthesizer import SynthesizerAgent, extract_report_text
from src.languages import language_instruction
from src.scientific_text import (
    plain_notation,
    repair_json_latex_escapes,
    scientific_text_issues,
)

# Raw model bytes as produced by gemma4:e4b (Hindi FAST, tier-2 benchmark).
RAW_HINDI = (
    '{"report": "## निष्कर्ष\\n\\n$\\text{MAPbI}_3$ फिल्में 85% आर्द्रता पर '
    '$\\text{PbI}_2$ में विघटित होती हैं [1]। तापमान $85^\\circ\\text{C}$ से '
    '$150^{\\circ}\\text{C}$ तक बढ़ा [2]।"}'
)


def test_fixture_reproduces_the_original_corruption():
    # Exactly what Atlas used to persist: a TAB where "\t" of "\text" was.
    assert json.loads('{"report": "$\\text{MAPbI}_3$"}')["report"] == "$\text{MAPbI}_3$"
    # An invalid escape (\circ) made the whole object undecodable as well.
    with pytest.raises(json.JSONDecodeError):
        json.loads(RAW_HINDI)


def test_structured_boundary_recovers_the_intended_text():
    report = extract_report_text(RAW_HINDI)
    assert "\t" not in report
    assert "$\\text{MAPbI}_3$" in report
    assert report.startswith("## निष्कर्ष\n\n")  # real \n escapes still decode


def test_plain_notation_rewrites_simple_formulas_and_units():
    report = plain_notation(extract_report_text(RAW_HINDI))
    assert "MAPbI3 फिल्में 85%" in report
    assert "PbI2 में" in report
    assert "85 °C से 150 °C" in report
    assert scientific_text_issues(report) == []


@pytest.mark.parametrize(
    ("latex", "plain"),
    [
        ("$\\text{FA}_{0.85}\\text{Cs}_{0.15}\\text{PbI}_3$", "FA0.85Cs0.15PbI3"),
        ("$\\mathrm{PbI}_2$", "PbI2"),
        ("$0.3\\,\\text{eV}$", "0.3 eV"),
        ("$85^{\\circ}$C", "85 °C"),
    ],
)
def test_plain_notation_examples(latex, plain):
    assert plain_notation(latex) == plain


def test_ambiguous_math_is_left_for_validation_not_guessed():
    # "$85^\text{C}$" (the Hindi output) could mean several things.
    text = plain_notation("ताप $85^\\text{C}$ है।")
    assert "$85^" in text
    assert scientific_text_issues(text)


def test_legitimate_text_is_untouched():
    for text in (
        "Costs fell from $5 to $10 per unit [1].",
        "Line one\n\tindented code",
        "IEC 61215 at 85% RH for 1000 hours, 0.3 eV, 150 °C, MAPbI3 [2].",
    ):
        assert plain_notation(text) == text
        assert scientific_text_issues(text) == []
    # Valid JSON tab/newline escapes that are not LaTeX still decode normally.
    assert extract_report_text('{"report": "a\\tb\\nc"}') == "a\tb\nc"
    assert extract_report_text('{"report": "path \\\\text"}') == "path \\text"


def test_repair_is_raw_json_only_and_idempotent_on_valid_escapes():
    assert repair_json_latex_escapes('"\\\\frac \\u00b0 \\n"') == '"\\\\frac \\u00b0 \\n"'
    assert json.loads(repair_json_latex_escapes('"\\frac{1}{2} \\beta \\circ"')) == "\\frac{1}{2} \\beta \\circ"


def test_control_characters_are_flagged():
    assert scientific_text_issues("$\text{MAPbI}_3$")
    assert scientific_text_issues("a \x0crac{1}{2}")
    assert scientific_text_issues("\x08eta decay")


class _Scripted:
    def __init__(self, outputs):
        self.outputs, self.calls = list(outputs), []

    def invoke(self, messages, **kwargs):
        self.calls.append(messages)
        return type("R", (), {"content": self.outputs.pop(0)})()


def _state():
    from tests.conftest import make_evidence

    claim = "MAPbI3 films at 85% RH decompose to PbI2 within 100 hours."
    return {
        "question": "Why do perovskite cells degrade?",
        "evidence": [make_evidence("https://example.org/a", title="Moisture study", content=claim)],
    }


def test_synthesizer_never_persists_corrupted_notation():
    bad = '{"report": "## A\\n\\nTemp $85^\\text{C}$ rose [1]."}'
    good = '{"report": "## A\\n\\nMAPbI3 decomposes to PbI2 at 85% RH [1]."}'
    llm = _Scripted([bad, good])
    result = SynthesizerAgent(llm, json_mode=True)(_state())
    assert len(llm.calls) == 2
    assert "plain text" in llm.calls[1][-1][1]
    assert "MAPbI3 decomposes to PbI2" in result["final_report"]
    assert not scientific_text_issues(result["final_report"].split("## Sources")[0])


def test_synthesizer_falls_back_rather_than_storing_bad_notation():
    bad = '{"report": "## A\\n\\nTemp $85^\\text{C}$ rose [1]."}'
    result = SynthesizerAgent(_Scripted([bad, bad]), json_mode=True)(_state())
    assert result["synthesis_fallback"] is True
    assert "$85^" not in result["final_report"]


def test_synthesizer_cleans_simple_latex_without_a_retry():
    llm = _Scripted([RAW_HINDI])
    result = SynthesizerAgent(llm, json_mode=True)(_state())
    assert len(llm.calls) == 1
    assert "MAPbI3 फिल्में" in result["final_report"]
    assert "\t" not in result["final_report"]


def test_non_english_instruction_forbids_latex_without_concrete_examples():
    text = language_instruction("hi")
    assert "Never use LaTeX" in text
    assert "MAPbI3" not in text and "61215" not in text  # never seed facts
    assert language_instruction("en") == ""


def test_transcript_timestamp_next_to_a_citation_is_removed():
    from src.agents.synthesizer import strip_invalid_citations

    # Live Spanish run: "[4][17:05]" copied from a YouTube transcript source.
    assert strip_invalid_citations("mitigados [4][17:05].", 6) == "mitigados [4]."
    # A time written in prose is not a pseudo-citation and is kept.
    assert strip_invalid_citations("at [17:05] the talk ends [2].", 6) == "at [17:05] the talk ends [2]."
