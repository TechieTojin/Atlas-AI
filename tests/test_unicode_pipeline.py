"""Phase 3: the report pipeline must not depend on text being English/ASCII.

These are structural guarantees only. Multilingual generation is NOT enabled:
no test here asks for, or expects, a non-English report from the planner,
critic or synthesizer prompts. Non-English text is injected directly (or via
the fake LLM) to prove it survives the machinery unharmed.
"""

from __future__ import annotations

import time
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

from src.agents.synthesizer import (
    extract_valid_citations,
    is_empty_draft,
    strip_generated_reference_sections,
    strip_invalid_citations,
    trim_partial_sentence,
)
from src.api.app import create_app
from src.evaluation.checks import evaluate_report
from src.evaluation.claims import extract_claims
from src.export.pdf import pdf_content_disposition, safe_pdf_filename
from src.memory.project_memory import extract_findings
from src.models.memory import FindingSource, ProjectFinding, normalize_finding
from src.models.research import CriticDecision, Source
from src.models.runs import ResearchRun, RunStatus
from src.rag.service import sanitize_filename
from src.services.comparison_title import comparison_title, same_question
from src.services.followup_service import classify_followup
from src.models.workspace import FollowUpKind
from src.services.project_graph import candidate_phrases, extract_concepts
from src.tools.webpage import select_relevant_chunks
from src.unicode_text import (
    comparison_key,
    content_word_count,
    filename_safe,
    has_meaningful_text,
    normalize_citation_markers,
    truncate_clusters,
    words,
)
from tests.conftest import FakeLLM, make_critique, make_plan
from tests.conftest_v2 import make_container

ML = "ലിഥിയം-അയോൺ ബാറ്ററികൾ ഉയർന്ന താപനിലയിൽ അസ്ഥിരമാകുന്നു."
ML_OTHER = "സൗരോർജ്ജ പാനലുകളുടെ കാര്യക്ഷമത കഴിഞ്ഞ ദശകത്തിൽ വർദ്ധിച്ചു."
HI = "लिथियम-आयन बैटरियां उच्च तापमान पर अस्थिर हो जाती हैं।"
HI_OTHER = "पिछले दशक में सौर पैनलों की दक्षता बढ़ी है।"
EN = "Lithium-ion batteries become unstable at high temperatures."


# --- 2. Meaningful-text / empty-draft validation ---------------------------


@pytest.mark.parametrize(
    "text",
    [
        EN,
        ML,
        HI,
        "Solid-state ബാറ്ററികൾ और लिथियम cells.",  # mixed script
        "है",  # a two-code-point Hindi word (consonant + vowel sign)
        "## സംഗ്രഹം\n\nസൗരോർജ്ജം വളരുന്നു [1].",
        "## सारांश\n\nसौर ऊर्जा बढ़ रही है [1]।",
    ],
)
def test_prose_in_any_script_is_not_an_empty_draft(text):
    assert has_meaningful_text(text)
    assert not is_empty_draft(text)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   \n\t  ",
        "?!... ।। ॥ —",
        "[1] [2] [12]",
        "[१] [२]",
        "{}",
        "\x00\x01\x02​‌‍",
        "1234 5678",
        "a",  # a single Latin letter was never prose
        "ക",  # nor is a single consonant
        "## \n\n- \n- [3]",
        "🙂🚀✨",
    ],
)
def test_whitespace_punctuation_citations_and_controls_are_empty(text):
    assert not has_meaningful_text(text)
    assert is_empty_draft(text)


def test_english_empty_draft_rule_is_unchanged():
    # The historical rule was "two consecutive ASCII letters".
    assert not is_empty_draft("ok")
    assert is_empty_draft("a b c [1]")


def test_content_word_count_counts_letter_bearing_runs_in_any_script():
    assert content_word_count(EN) == 8  # "Lithium" "ion" ... (hyphen splits)
    assert content_word_count(ML) == 6  # five words, one of them hyphenated
    assert content_word_count("[1] 2024 —") == 0
    # Words keep their combining marks: Python's \w alone would split "മലയാളം".
    assert words("മലയാളം भाषा") == ["മലയാളം", "भाषा"]


def test_a_malayalam_report_is_kept_not_replaced_by_the_english_fallback(tmp_path):
    """End to end: the synthesizer must accept a valid non-Latin draft.

    Before Phase 3 this draft counted as empty, was retried, and was replaced
    by the extractive English "Evidence Summary".
    """
    draft = f"## പ്രധാന കണ്ടെത്തലുകൾ\n\n{ML} [1]\n\n{ML_OTHER} [2]"
    llm = FakeLLM(
        plans=[make_plan(n_queries=2)],
        critiques=[make_critique(CriticDecision.SYNTHESIZE, score=9)],
        synthesis=draft,
    )
    container = make_container(tmp_path, llm=llm)
    with TestClient(create_app(container)) as client:
        run_id = client.post("/api/runs", json={"query": "battery safety"}).json()["id"]
        detail = client.get(f"/api/runs/{run_id}").json()
    assert detail["status"] == "COMPLETED"
    report = detail["final_report"]
    assert "Evidence Summary" not in report
    assert "## പ്രധാന കണ്ടെത്തലുകൾ" in report
    assert f"{ML} [1]" in report
    # The internal Sources marker is still the canonical English one.
    assert "\n## Sources\n" in report
    assert detail["evaluation"]["has_citations"] is True


# --- 3. Citation markers -----------------------------------------------------


def test_canonical_ascii_citations_are_untouched():
    text = "Growth [1] and decline [12]."
    assert normalize_citation_markers(text) == text
    assert strip_invalid_citations(text, 12) == text
    assert extract_valid_citations(text, 12) == {1, 12}


def test_native_decimal_digits_normalise_to_canonical_markers():
    assert normalize_citation_markers("ഫലം [१].") == "ഫലം [1]."
    assert normalize_citation_markers("परिणाम [१२]।") == "परिणाम [12]।"
    assert normalize_citation_markers("ഫലം [൩]") == "ഫലം [3]"  # Malayalam digits
    assert normalize_citation_markers("x [١٢]") == "x [12]"  # Arabic-Indic, same rule
    out = strip_invalid_citations("सौर [१] और पवन [२]।", 2)
    assert out == "सौर [1] और पवन [2]।"
    assert extract_valid_citations(out, 2) == {1, 2}


def test_mixed_digit_systems_are_rejected_not_reinterpreted():
    """``[1२]`` would be 12 to Python's int(); it is a malformed marker instead."""
    assert normalize_citation_markers("x [1२]") == "x [1२]"
    assert strip_invalid_citations("x [1२] y", 20) == "x  y"
    assert extract_valid_citations("x [1२] y", 20) == set()


def test_out_of_range_and_malformed_markers_never_become_citations():
    assert strip_invalid_citations("a [९] b [3]", 3) == "a  b [3]"  # ९ = 9 > 3
    assert strip_invalid_citations("a [0] b", 3) == "a  b"
    for text in ("[१", "१]", "[ १ ]", "[१.२]", "[ab]", "[ൿ]", "[①]", "[¹]", "[Ⅻ]"):
        assert extract_valid_citations(normalize_citation_markers(text), 20) == set(), text
    # Non-decimal numerals (circled, superscript, Roman) are not citations.
    assert normalize_citation_markers("[①] [¹] [Ⅻ]") == "[①] [¹] [Ⅻ]"


def test_evaluation_and_claims_read_only_canonical_markers():
    sources = [Source(title="A", url="https://a.test/1", domain="a.test")]
    report = f"{HI} [1]\n\n## Sources\n\n1. [A](https://a.test/1)\n"
    result = evaluate_report(report, sources)
    assert result.has_citations and result.citations_valid and result.single_sources_section
    # A non-canonical marker in a stored report is not counted as a citation.
    assert not evaluate_report("तथ्य [१]\n\n## Sources\n", sources).has_citations


# --- 4. Sentence boundaries / trimming ---------------------------------------


def test_trimming_keeps_complete_sentences_in_every_script():
    assert trim_partial_sentence("Solar grew. It is cheap") == "Solar grew."
    assert trim_partial_sentence("Solar grew [1]. It is cheap [2") == "Solar grew [1]."
    assert trim_partial_sentence(f"{ML} ഇത് വിലകുറഞ്ഞ") == ML
    assert trim_partial_sentence(f"{HI} यह सस्ता") == HI
    assert trim_partial_sentence("सौर ऊर्जा बढ़ी [1]। पवन ऊर्जा") == "सौर ऊर्जा बढ़ी [1]।"
    assert trim_partial_sentence("श्लोक समाप्त॥ अधूरा") == "श्लोक समाप्त॥"
    # Complete text is returned unchanged, including a danda ending.
    assert trim_partial_sentence(HI) == HI
    assert trim_partial_sentence("Mixed end! और फिर।") == "Mixed end! और फिर।"


def test_claim_extraction_splits_hindi_sentences_at_the_danda():
    claims = extract_claims("## मुख्य निष्कर्ष\n\nसौर ऊर्जा बढ़ी [1]। पवन ऊर्जा स्थिर रही [2]।", 2)
    assert [c.citations for c in claims] == [[1], [2]]
    assert all(c.section == "मुख्य निष्कर्ष" for c in claims)
    english = extract_claims("Solar grew [1]. Wind held [2].", 2)
    assert [c.text for c in english] == ["Solar grew [1].", "Wind held [2]."]


# --- 6/7. Question comparison and normalization ------------------------------


def test_same_question_detection_in_every_script():
    assert same_question(["What limits battery life?", "what limits battery life"])
    assert not same_question(["What limits battery life?", "How do solar farms affect birds?"])
    assert same_question([ML, ML])
    assert not same_question([ML, ML_OTHER]), "different Malayalam questions are different"
    assert same_question([HI, HI])
    assert not same_question([HI, HI_OTHER]), "different Hindi questions are different"
    assert not same_question([ML, HI])
    assert same_question(["Solid-state ബാറ്ററി?", "solid-state ബാറ്ററി"])
    # Punctuation, case and spacing still do not matter.
    assert same_question(["सौर   ऊर्जा, क्या है?", "सौर ऊर्जा क्या है"])


def test_comparison_titles_for_non_latin_questions_stay_distinct():
    title = comparison_title([ML, ML_OTHER])
    assert " vs " in title and "ലിഥിയം" in title and "സൗരോർജ്ജ" in title
    assert comparison_title([HI, HI]).startswith("Comparison: ")


def test_comparison_key_normalises_without_erasing_scripts():
    assert comparison_key("What  IS  this?") == "what is this"
    assert comparison_key("ﬁne") == comparison_key("fine")  # NFKC ligature
    assert comparison_key("ＡＢＣ") == "abc"  # full-width forms
    assert comparison_key(ML) != comparison_key(ML_OTHER)
    assert comparison_key("ഭാഷ") != ""


# --- 8/9. Memory dedup keys and extraction -----------------------------------


def test_finding_keys_keep_unicode_and_still_dedupe():
    assert normalize_finding(EN) == normalize_finding("  lithium-ion BATTERIES become unstable at high temperatures!! ")
    assert normalize_finding(ML) == normalize_finding(f"  {ML}  ")
    assert normalize_finding(ML) != normalize_finding(ML_OTHER)
    assert normalize_finding(HI) == normalize_finding(HI.replace("।", "."))
    assert normalize_finding(HI) != normalize_finding(HI_OTHER)
    assert normalize_finding(ML).strip() != ""
    assert normalize_finding(f"{EN} {ML}") != normalize_finding(f"{EN} {ML_OTHER}")


def test_finding_keys_for_ascii_are_byte_identical_to_the_original_rule():
    import re

    def original(text):
        return re.sub(r"[^a-z0-9 ]+", "", " ".join(text.lower().split()))

    for text in (EN, "H₂S gas — toxic!", "Costs fell 40% (2020–2024).", "  a  -  b  ", "Ünïcödé"):
        if text.isascii() or not any(c.isalpha() and not c.isascii() for c in text):
            assert normalize_finding(text) == original(text), text


def test_non_latin_findings_are_skipped_safely_not_collapsed():
    """Extraction stays English-semantic (verb hints, Latin word counts) by design.

    A Malayalam report yields no findings rather than corrupt or colliding ones.
    """
    sources = [Source(title="A", url="https://a.test/1", domain="a.test"),
               Source(title="B", url="https://b.test/2", domain="b.test")]
    run = ResearchRun(query="ബാറ്ററി സുരക്ഷ", project_id="p1", status=RunStatus.COMPLETED)
    run.final_report = f"## പ്രധാന കണ്ടെത്തലുകൾ\n\n{ML} [1] {ML_OTHER} [2]\n\n## Sources\n"
    run.selected_sources = sources
    assert extract_findings(run) == []


# --- 10. Project knowledge graph -----------------------------------------------


def _finding(text, index):
    return ProjectFinding(id=f"f{index}", project_id="p", run_id=f"r{index % 2}", text=text,
                          sources=[FindingSource(url="https://x.test", title="X")])


def test_graph_ignores_non_latin_concepts_without_crashing_or_colliding():
    assert candidate_phrases(ML) == set()
    assert candidate_phrases(HI) == set()
    findings = [_finding(ML, 0), _finding(HI, 1), _finding(ML_OTHER, 2)]
    assert extract_concepts(findings, project_id="p") == []


def test_graph_english_concepts_are_unaffected_by_unicode_findings():
    english = [
        _finding("Interface stability limits solid-state cells because dendrites form.", 0),
        _finding("Interface stability remains the main barrier for solid-state cells.", 1),
    ]
    baseline = {c.key for c in extract_concepts(english, project_id="p")}
    mixed = english + [_finding(ML, 2), _finding(HI, 3)]
    assert {c.key for c in extract_concepts(mixed, project_id="p")} == baseline
    assert all(all(part for part in key) for key in baseline)


# --- 11. Page / chunk scoring -------------------------------------------------


def test_chunk_scoring_uses_non_latin_query_terms():
    filler = "സാധാരണ വാചകം ഇവിടെ ആവർത്തിക്കുന്നു. " * 60
    target = "ബാറ്ററി താപനില സുരക്ഷ പ്രധാനമാണ്. " * 5
    text = filler + target + filler
    chunks = select_relevant_chunks(text, "ബാറ്ററി താപനില", max_chunks=1, chunk_size=600, overlap=0)
    assert chunks and "ബാറ്ററി" in chunks[0]


def test_chunk_scoring_english_is_unchanged():
    filler = "Unrelated words fill this page about gardening and weather. " * 40
    target = "Battery thermal runaway is the key safety risk. " * 5
    chunks = select_relevant_chunks(filler + target + filler, "battery thermal runaway",
                                    max_chunks=1, chunk_size=600, overlap=0)
    assert "Battery thermal runaway" in chunks[0]


# --- 12. Follow-up classification ----------------------------------------------


@pytest.mark.parametrize("question", [ML, HI, "ഇത് ലളിതമായി വിശദീകരിക്കുക", "और खोजें"])
def test_non_latin_follow_ups_fall_back_to_the_default_kind(question):
    assert classify_followup(question) is FollowUpKind.ANALYTICAL
    # The user's explicit choice still wins.
    assert classify_followup(question, "research") is FollowUpKind.RESEARCH


# --- 13/14. Sources marker and headings -------------------------------------------


def test_unicode_headings_survive_report_processing():
    body = "## പ്രധാന കണ്ടെത്തലുകൾ\n\nസൗരോർജ്ജം [1].\n\n## मुख्य निष्कर्ष\n\nसौर [1]।"
    assert strip_generated_reference_sections(body) == body
    claims = extract_claims(body, 1)
    assert [c.section for c in claims] == ["പ്രധാന കണ്ടെത്തലുകൾ", "मुख्य निष्कर्ष"]


def test_the_internal_sources_marker_stays_canonical_english():
    """``## Sources`` is a protocol marker rendered by code, not a translated heading."""
    sources = [Source(title="A", url="https://a.test/1", domain="a.test")]
    good = f"{HI} [1]\n\n## Sources\n\n1. [A](https://a.test/1)\n"
    assert evaluate_report(good, sources).single_sources_section
    translated = f"{HI} [1]\n\n## स्रोत\n\n1. [A](https://a.test/1)\n"
    assert not evaluate_report(translated, sources).single_sources_section


# --- 15. Filenames / slugs -----------------------------------------------------------


def _run(query):
    return ResearchRun(query=query, status=RunStatus.COMPLETED, id="abcdef1234567890")


def test_pdf_filenames_for_english_are_unchanged():
    assert safe_pdf_filename(_run("What is X? (2024)")) == "atlas-What-is-X-2024.pdf"
    assert pdf_content_disposition(_run("Solar growth")) == 'attachment; filename="atlas-Solar-growth.pdf"'


@pytest.mark.parametrize(
    "query, expected",
    [
        ("സൗരോർജ്ജ വളർച്ച", "atlas-സൗരോർജ്ജ-വളർച്ച.pdf"),
        ("सौर ऊर्जा की वृद्धि", "atlas-सौर-ऊर्जा-की-वृद्धि.pdf"),
        ("Solar സൗരോർജ്ജം", "atlas-Solar-സൗരോർജ്ജം.pdf"),
        ("🙂🚀", "atlas-abcdef12.pdf"),
        ("?!...", "atlas-abcdef12.pdf"),
        ('a<b>c:d"e/f\\g|h?i*j', "atlas-abcdefghij.pdf"),
    ],
)
def test_pdf_filenames_keep_unicode_and_drop_unsafe_characters(query, expected):
    assert safe_pdf_filename(_run(query)) == expected


def test_long_unicode_filenames_are_never_cut_inside_a_syllable():
    name = safe_pdf_filename(_run("ലിഥിയം " * 20))
    stem = name[len("atlas-"):-len(".pdf")]
    assert len(stem) <= 40
    assert stem and not unicodedata_is_mark(stem[0])
    assert truncate_clusters("കാ", 1) == ""  # never leaves a bare consonant's sign behind
    assert truncate_clusters("abc", 2) == "ab"


def unicodedata_is_mark(char):
    import unicodedata

    return unicodedata.category(char).startswith("M")


def test_unicode_filenames_use_an_rfc5987_header():
    header = pdf_content_disposition(_run("സൗരോർജ്ജ വളർച്ച"))
    assert header.startswith('attachment; filename="atlas-abcdef12.pdf"; filename*=UTF-8\'\'')
    header.encode("latin-1")  # must be a valid HTTP header value
    assert unquote(header.split("UTF-8''", 1)[1]) == "atlas-സൗരോർജ്ജ-വളർച്ച.pdf"


@pytest.mark.parametrize(
    "name, expected",
    [
        ("report.pdf", "report.pdf"),
        ("my notes (v2).md", "my notes _v2_.md"),
        ("../../etc/passwd", "passwd"),
        ("റിപ്പോർട്ട്.pdf", "റിപ്പോർട്ട്.pdf"),
        ("रिपोर्ट नोट्स.txt", "रिपोर्ट नोट्स.txt"),
        ("notes:v2*final?.pdf", "notes_v2_final_.pdf"),  # Windows-invalid characters
        ("🙂.md", "_.md"),
    ],
)
def test_upload_names_keep_unicode_but_stay_safe(name, expected):
    assert sanitize_filename(name) == expected


def test_filename_safe_never_emits_windows_invalid_or_control_characters():
    out = filename_safe('x<>:"/\\|?*\x00\x07​y', replacement="_")
    assert not set(out) & set('<>:"/\\|?*\x00\x07​')


# --- 16. Markdown export stays UTF-8 ---------------------------------------------------


def test_markdown_export_preserves_malayalam_and_hindi_bytes(tmp_path):
    container = make_container(tmp_path)
    run = ResearchRun(query="സൗരോർജ്ജ വളർച്ച", status=RunStatus.COMPLETED)
    run.final_report = f"## പ്രധാന കണ്ടെത്തലുകൾ\n\n{ML} [1]\n\n{HI} [1]\n\n## Sources\n"
    container.runs_repo.save(run)
    with TestClient(create_app(container)) as client:
        response = client.get(f"/api/runs/{run.id}/export")
        pdf = client.get(f"/api/runs/{run.id}/export?format=pdf")
    assert response.status_code == 200
    assert "charset=utf-8" in response.headers["content-type"]
    text = response.content.decode("utf-8")
    assert ML in text and HI in text and "സൗരോർജ്ജ വളർച്ച" in text
    assert "?" * 3 not in text
    # The PDF download no longer crashes on a Unicode file name. (Indic glyph
    # shaping inside the PDF is the export phase's problem, not this one's.)
    assert pdf.status_code == 200
    assert "filename*=UTF-8''" in pdf.headers["content-disposition"]


# --- 20. Performance -------------------------------------------------------------------


def test_unicode_helpers_are_cheap_on_page_sized_text():
    page = (EN + " " + ML + " " + HI + " ") * 400  # ~70 KB of mixed text
    start = time.perf_counter()
    for _ in range(5):
        has_meaningful_text(page)
        words(page)
        normalize_citation_markers(page)
    assert (time.perf_counter() - start) / 5 < 0.25
