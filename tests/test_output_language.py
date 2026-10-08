"""Output-language contract: persistence, capability gating, inheritance, prompts.

Generation-supported non-English languages are simulated by marking a
(model, language) pair as validated for the duration of a test, so these
tests exercise the plumbing independently of which languages the local
benchmark actually passed.
"""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from src import model_capabilities
from src.api.app import create_app
from src.artifact_text import artifact_text
from src.config import AtlasConfig, ConfigError, _language_models_env
from src.languages import (
    DEFAULT_OUTPUT_LANGUAGE,
    OUTPUT_LANGUAGE_CODES,
    UnknownLanguageError,
    language_instruction,
    parse_output_language,
    stored_output_language,
)
from src.model_capabilities import LanguageRouter, UnsupportedOutputLanguageError
from src.models.research import CriticDecision
from src.models.runs import ResearchRun, RunStatus
from src.persistence.db import Database
from src.persistence.runs import RunsRepository
from src.prompts.research import FOLLOWUP_SYSTEM, SYNTHESIZER_SYSTEM
from src.services.comparison_synthesis import ComparisonSynthesis
from src.templates import resolve_template
from tests.conftest import FakeLLM, make_critique, make_plan
from tests.conftest_v2 import make_container
from tests.test_comparisons import synthesis as comparison_synthesis
from tests.test_comparisons import two_runs

MODEL = AtlasConfig().model  # the default configured model in tests


@pytest.fixture
def spanish_supported(monkeypatch):
    """Pretend the configured model passed validation for Spanish."""
    monkeypatch.setitem(
        model_capabilities._VALIDATED, (MODEL, "es"), (model_capabilities.SUPPORTED, "test")
    )
    for feature in model_capabilities.FEATURES:
        monkeypatch.delitem(model_capabilities._FEATURE_VERDICTS, (MODEL, "es", feature), raising=False)


def system_prompts(llm: FakeLLM) -> list[str]:
    return [messages[0][1] for messages in llm.invoke_calls]


# --- canonical definition -------------------------------------------------------


def test_canonical_codes_and_default():
    assert OUTPUT_LANGUAGE_CODES == ("en", "ml", "hi", "es", "fr", "de")
    assert DEFAULT_OUTPUT_LANGUAGE == "en"
    assert parse_output_language(None) == "en"
    assert parse_output_language("") == "en"
    assert parse_output_language("ml") == "ml"
    for bad in ("xx", "EN", "en-US", 3, "english"):
        with pytest.raises(UnknownLanguageError):
            parse_output_language(bad)
    assert stored_output_language(None) == "en"
    assert stored_output_language("garbage") == "en"
    assert stored_output_language("fr") == "fr"


def test_language_routing_config_is_validated():
    assert _language_models_env("") == ()
    assert _language_models_env("ml=qwen3:8b, hi=qwen3:8b") == (("ml", "qwen3:8b"), ("hi", "qwen3:8b"))
    for bad in ("ml", "xx=qwen3:8b", "ml="):
        with pytest.raises(ConfigError):
            _language_models_env(bad)


# --- prompt contract ----------------------------------------------------------------


def test_english_prompt_is_byte_identical():
    assert language_instruction("en") == ""


@pytest.mark.parametrize("code, name", [("ml", "Malayalam"), ("hi", "Hindi"), ("es", "Spanish"),
                                        ("fr", "French"), ("de", "German")])
def test_language_instruction_contract(code, name):
    text = language_instruction(code)
    assert f"OUTPUT LANGUAGE: {name} ({code})" in text
    assert "ASCII bracketed digits: [1], [2], [12]" in text
    assert "numbers and percentages, units, chemical formulas" in text
    # No concrete example values: the model would copy them in as content.
    assert "IEC" not in text and "61215" not in text and "e.g." not in text
    assert "Do not add a References, Bibliography or Sources list" in text
    with pytest.raises(UnknownLanguageError):
        language_instruction("xx")


# --- capability registry --------------------------------------------------------------


def test_router_reflects_the_benchmark_verdicts_and_is_pure_config():
    """qwen3:4b: English and Spanish passed the local benchmark; the rest did not."""
    router = LanguageRouter(AtlasConfig(model="qwen3:4b"))
    supported = {code for code in OUTPUT_LANGUAGE_CODES if router.is_supported(code)}
    assert supported == {"en", "es"}
    for code in ("ml", "hi", "fr", "de"):
        assert router.capability(code).status == model_capabilities.UNSUPPORTED
        assert router.capability(code).reason.startswith("Benchmark failed")
    with pytest.raises(UnsupportedOutputLanguageError, match="Malayalam"):
        router.require("ml")
    assert router.budget_overrides("en", "FAST") == {}
    assert router.budget_overrides("en", "DEEP") == {}
    # Spanish gets its own FAST word ceiling so a report fits the same token cap.
    assert router.budget_overrides("es", "FAST") == {"report_target_words": 330, "synthesis_max_words": 380}
    assert router.budget_overrides("es", "DEEP") == {}


def test_english_is_never_gated_even_for_unknown_models():
    router = LanguageRouter(AtlasConfig(model="some-custom-model"))
    assert router.require("en") == "en"
    assert router.capability("fr").status == model_capabilities.UNVALIDATED


def test_routing_sends_a_language_to_its_configured_model(monkeypatch):
    config = AtlasConfig(language_models=(("ml", "big-multilingual"),))
    router = LanguageRouter(config)
    assert router.model_for("ml") == "big-multilingual"
    assert router.model_for("en") == config.model
    assert not router.is_supported("ml")  # routed but never validated
    monkeypatch.setitem(model_capabilities._VALIDATED, ("big-multilingual", "ml"),
                        (model_capabilities.SUPPORTED, "test"))
    assert router.require("ml") == "ml"


def test_validated_table_marks_known_failures_unsupported():
    """The real verdicts: Malayalam and Hindi on qwen3:4b must stay unsupported."""
    router = LanguageRouter(AtlasConfig(model="qwen3:4b"))
    assert not router.is_supported("ml")
    assert not router.is_supported("hi")


def test_capability_endpoint(tmp_path):
    with TestClient(create_app(make_container(tmp_path))) as client:
        body = client.get("/api/capabilities/languages").json()
    assert body["default_output_language"] == "en"
    assert [row["code"] for row in body["languages"]] == list(OUTPUT_LANGUAGE_CODES)
    english = body["languages"][0]
    assert english["supported"] is True and english["native_name"] == "English"
    assert {row["code"] for row in body["languages"] if row["supported"]} == {"en", "es"}
    malayalam = next(row for row in body["languages"] if row["code"] == "ml")
    assert malayalam["supported"] is False and malayalam["reason"]


# --- runs ---------------------------------------------------------------------------------


def _client(tmp_path, llm=None):
    container = make_container(tmp_path, llm=llm)
    return container, TestClient(create_app(container))


def test_runs_default_to_english_for_old_clients(tmp_path):
    container, client = _client(tmp_path)
    with client:
        detail = client.post("/api/runs", json={"query": "What is X?"}).json()
        assert detail["output_language"] == "en"
        assert client.get(f"/api/runs/{detail['id']}").json()["output_language"] == "en"
        listing = client.get("/api/runs").json()["runs"]
        assert listing[0]["output_language"] == "en"


def test_english_runs_send_the_unchanged_prompt(tmp_path):
    llm = FakeLLM(plans=[make_plan(n_queries=2)], critiques=[make_critique(CriticDecision.SYNTHESIZE, score=9)],
                  synthesis="Findings [1] and [2].")
    container, client = _client(tmp_path, llm)
    with client:
        client.post("/api/runs", json={"query": "What is X?", "output_language": "en"})
    _, structure = resolve_template("STANDARD")
    expected = SYNTHESIZER_SYSTEM.format(target_words=container.config.report_target_words,
                                         structure=structure)
    assert expected in system_prompts(llm)
    assert all("OUTPUT LANGUAGE" not in prompt for prompt in system_prompts(llm))


@pytest.mark.parametrize("language", ["xx", "EN", "english"])
def test_unknown_language_is_a_clean_validation_error(tmp_path, language):
    container, client = _client(tmp_path)
    with client:
        response = client.post("/api/runs", json={"query": "q", "output_language": language})
    assert response.status_code == 422
    assert "Unknown output language" in response.json()["detail"]
    assert container.runs_repo.list()[1] == 0


@pytest.mark.parametrize("language", ["ml", "hi", "fr", "de"])
def test_unsupported_language_is_rejected_not_downgraded(tmp_path, language):
    container, client = _client(tmp_path)
    with client:
        response = client.post("/api/runs", json={"query": "q", "output_language": language})
    assert response.status_code == 422
    assert "not supported with the configured model" in response.json()["detail"]
    # No artifact is created, let alone an English one labelled as another language.
    assert container.runs_repo.list()[1] == 0


def test_supported_language_is_persisted_and_instructed(tmp_path, spanish_supported):
    llm = FakeLLM(plans=[make_plan(n_queries=2)], critiques=[make_critique(CriticDecision.SYNTHESIZE, score=9)],
                  synthesis="Hallazgos [1] y [2].")
    container, client = _client(tmp_path, llm)
    with client:
        detail = client.post("/api/runs", json={"query": "¿Qué es X?", "output_language": "es"}).json()
        stored = client.get(f"/api/runs/{detail['id']}").json()
    assert stored["output_language"] == "es"
    assert stored["status"] == "COMPLETED"
    synthesis_prompts = [p for p in system_prompts(llm) if "synthesis agent" in p]
    assert synthesis_prompts and all("OUTPUT LANGUAGE: Spanish (es)" in p for p in synthesis_prompts)
    # Planning and critique are not language-instructed: search is language-independent.
    assert all("OUTPUT LANGUAGE" not in p for p in system_prompts(llm) if "synthesis agent" not in p)
    # The internal Sources protocol marker stays English.
    assert "\n## Sources\n" in stored["final_report"]


def test_supported_language_routes_the_writing_model(tmp_path, monkeypatch):
    monkeypatch.setitem(model_capabilities._VALIDATED, ("multi", "es"),
                        (model_capabilities.SUPPORTED, "test"))
    seen: list[tuple[str, str]] = []
    llm = FakeLLM(plans=[make_plan(n_queries=2)], critiques=[make_critique(CriticDecision.SYNTHESIZE, score=9)],
                  synthesis="Hallazgos [1] y [2].")

    def factory(cfg, reasoning, stage="default", call_sink=None):
        seen.append((stage, cfg.model))
        return llm

    container = make_container(tmp_path, llm=llm, language_models=(("es", "multi"),))
    container.research_service._llm_factory = factory
    run = container.research_service.create_run("q", output_language="es")
    assert container.research_service.get_run(run.id).output_language == "es"
    models = dict(seen)
    assert models.get("synthesis") == "multi"
    assert models.get("planner") == container.config.model


def test_persistence_round_trip_and_summary(tmp_path):
    repo = RunsRepository(Database(str(tmp_path / "a.db")))
    run = ResearchRun(query="q", output_language="fr", status=RunStatus.COMPLETED)
    repo.save(run)
    assert repo.get(run.id).output_language == "fr"
    assert repo.list()[0][0].output_language == "fr"


def test_migration_marks_existing_runs_english_and_keeps_their_data(tmp_path):
    """A v3 database upgrades to v4: every old run reads as English, data unchanged."""
    path = str(tmp_path / "old.db")
    db = Database(path)
    old = ResearchRun(query="old", status=RunStatus.COMPLETED, final_report="Old report [1].")
    RunsRepository(db).save(old)
    conn = sqlite3.connect(path)
    before = conn.execute("SELECT data FROM runs WHERE id = ?", (old.id,)).fetchone()[0]
    # Roll the schema back to v3 by removing the column, as an older Atlas had it.
    conn.executescript(
        "ALTER TABLE runs DROP COLUMN output_language; DELETE FROM schema_version WHERE version = 4;"
    )
    conn.commit()
    conn.close()

    reopened = Database(path)  # applies v4
    run = RunsRepository(reopened).get(old.id)
    assert run.output_language == "en"
    assert run.final_report == "Old report [1]."
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT data FROM runs WHERE id = ?", (old.id,)).fetchone()[0] == before
    assert conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == 4
    conn.close()
    Database(path)  # idempotent: a second open applies nothing and does not fail


# --- regeneration -------------------------------------------------------------------------


def test_regeneration_inherits_the_original_language(tmp_path, spanish_supported):
    llm = FakeLLM(plans=[make_plan(n_queries=2)], critiques=[make_critique(CriticDecision.SYNTHESIZE, score=9)],
                  synthesis="Hallazgos [1] y [2].")
    container = make_container(tmp_path, llm=llm)
    original = container.research_service.create_run("q", output_language="es")
    regenerated = container.research_service.regenerate_report(original.id, "ACADEMIC")
    assert regenerated.output_language == "es"
    assert container.research_service.get_run(regenerated.id).output_language == "es"
    assert "OUTPUT LANGUAGE: Spanish (es)" in system_prompts(llm)[-1]


def test_regeneration_refuses_a_language_that_is_no_longer_supported(tmp_path):
    container = make_container(tmp_path)
    run = ResearchRun(query="q", status=RunStatus.COMPLETED, output_language="ml",
                      evidence=[], final_report="x")
    container.runs_repo.save(run)
    from tests.conftest import make_evidence

    run.evidence = [make_evidence("https://a.com/1")]
    container.runs_repo.save(run)
    with pytest.raises(UnsupportedOutputLanguageError):
        container.research_service.regenerate_report(run.id, "STANDARD")


# --- follow-ups -------------------------------------------------------------------------------


def test_follow_ups_inherit_the_run_language_and_keep_the_question(tmp_path, spanish_supported):
    llm = FakeLLM(plans=[make_plan(n_queries=2)], critiques=[make_critique(CriticDecision.SYNTHESIZE, score=9)],
                  synthesis="Respuesta [1].")
    container = make_container(tmp_path, llm=llm)
    run = container.research_service.create_run("q", output_language="es")
    question = "What evidence is strongest?"  # typed in English while the run is Spanish
    followup = container.followup_service.create(run.id, question)
    stored = container.followup_service.get(followup.id)
    assert stored.output_language == "es"
    assert stored.question == question
    prompt = system_prompts(llm)[-1]
    assert prompt.startswith(FOLLOWUP_SYSTEM) and "OUTPUT LANGUAGE: Spanish (es)" in prompt


def test_english_follow_ups_are_unchanged(tmp_path):
    llm = FakeLLM(plans=[make_plan(n_queries=2)], critiques=[make_critique(CriticDecision.SYNTHESIZE, score=9)])
    container = make_container(tmp_path, llm=llm)
    run = container.research_service.create_run("q")
    followup = container.followup_service.create(run.id, "Why?")
    assert container.followup_service.get(followup.id).output_language == "en"
    assert system_prompts(llm)[-1] == FOLLOWUP_SYSTEM


def test_follow_ups_refuse_an_unsupported_run_language(tmp_path):
    container = make_container(tmp_path)
    run = ResearchRun(query="q", status=RunStatus.COMPLETED, output_language="ml", final_report="x")
    container.runs_repo.save(run)
    with pytest.raises(UnsupportedOutputLanguageError):
        container.followup_service.create(run.id, "Why?")


# --- comparisons ------------------------------------------------------------------------------


def test_comparisons_default_to_english_and_render_unchanged(tmp_path):
    c, r1, r2 = two_runs(tmp_path)
    comparison = c.comparison_service.create([r1.id, r2.id])
    done = c.comparison_service.get(comparison.id)
    assert done.output_language == "en"
    assert "## Agreements" in done.report and "## Source Differences" in done.report
    assert done.title.startswith("Comparison: ")


def test_comparison_language_is_persisted_rendered_and_inherited_by_repair(tmp_path, spanish_supported):
    bad = comparison_synthesis(agreements=[{"id": "A1", "text": "x", "runs": [1, 2], "citations": [99]}])
    c, r1, r2 = two_runs(tmp_path, comparison=bad)
    llm = c.research_service._llm_factory(c.config, reasoning=False)
    llm.queue_structured(ComparisonSynthesis, [bad, comparison_synthesis()])
    comparison = c.comparison_service.create([r1.id, r2.id], output_language="es")
    done = c.comparison_service.get(comparison.id)
    assert done.output_language == "es"
    assert done.status.value == "COMPLETED"
    assert done.title.startswith("Comparación: ")
    for key in ("comparison.overview", "comparison.agreements", "comparison.conclusion",
                "comparison.source_differences"):
        assert f"## {artifact_text('es', key)}" in done.report
    assert "Investigación 1" in done.report
    assert "\n## Sources\n" in done.report  # protocol marker stays English
    # Both the first attempt and the repair carried the language instruction.
    calls = llm.with_structured_output(ComparisonSynthesis).calls
    assert len(calls) == 2
    assert all("OUTPUT LANGUAGE: Spanish (es)" in call[0][1] for call in calls)


def test_comparison_capability_rejection(tmp_path):
    c, r1, r2 = two_runs(tmp_path)
    with TestClient(create_app(c)) as client:
        response = client.post("/api/comparisons", json={"run_ids": [r1.id, r2.id], "output_language": "ml"})
        assert response.status_code == 422
        bad = client.post("/api/comparisons", json={"run_ids": [r1.id, r2.id], "output_language": "zz"})
        assert bad.status_code == 422
    assert c.comparison_service.list() == []


# --- startup recovery -------------------------------------------------------------------------


def test_interrupted_runs_keep_their_language_through_recovery(tmp_path):
    container = make_container(tmp_path)
    run = ResearchRun(query="q", status=RunStatus.SYNTHESIZING, output_language="fr")
    container.runs_repo.save(run)
    assert container.research_service.recover_interrupted_runs() == 1
    recovered = container.runs_repo.get(run.id)
    assert recovered.status is RunStatus.FAILED
    assert recovered.output_language == "fr"


def test_artifact_text_english_is_unchanged():
    assert artifact_text("en", "comparison.agreements") == "Agreements"
    assert artifact_text("en", "fallback.heading") == "Evidence Summary"
    assert artifact_text("en", "comparison.unique_to", label="Run 1", count=2) == "Unique to Run 1: 2"
    for code in OUTPUT_LANGUAGE_CODES:
        assert artifact_text(code, "comparison.combined", count=3).endswith("3")


# --- project memory and graph ---------------------------------------------------------------

MEMORY_REPORT = (
    "## Findings\n\nGrid-scale storage is the binding constraint on renewable deployment "
    "because transmission upgrades lag behind new generation capacity [1].\n\n## Sources\n"
)


def _project_run(language: str, report: str = MEMORY_REPORT) -> ResearchRun:
    from src.models.research import Source

    run = ResearchRun(query="q", project_id="p1", status=RunStatus.COMPLETED, output_language=language)
    run.final_report = report
    run.selected_sources = [Source(title="A", url="https://a.test/1", domain="a.test")]
    return run


def test_english_memory_extraction_is_unchanged():
    from src.memory.project_memory import extract_findings

    findings = extract_findings(_project_run("en"))
    assert [f.text for f in findings] == [
        "Grid-scale storage is the binding constraint on renewable deployment because "
        "transmission upgrades lag behind new generation capacity [1]."
    ]


@pytest.mark.parametrize("language", ["ml", "hi", "es", "fr", "de"])
def test_non_english_runs_never_add_project_memory(language):
    """Same-script embeddings leak (0.84-0.91 for unrelated Malayalam/Hindi text),
    and claim detection is English-only, so non-English findings are not stored."""
    from src.memory.project_memory import extract_findings

    spanish_like = (
        "## Hallazgos\n\nLas baterías de estado sólido presentan problemas de interfaz que "
        "limitan su producción masiva en las fábricas actuales [1].\n\n## Sources\n"
    )
    assert extract_findings(_project_run(language, spanish_like)) == []
    assert extract_findings(_project_run(language)) == []  # even English-looking text


# --- exports ---------------------------------------------------------------------------------

SAMPLES = {
    "en": "Cells lose 85% efficiency at 150°C; MAPbI3 fails IEC 61215 after 1000 hours [1][2].",
    "es": "Las celdas pierden un 85% a 150°C; MAPbI3 falla IEC 61215 tras 1000 horas [1][2].",
    "fr": "Les cellules perdent 85% à 150°C ; MAPbI3 échoue à IEC 61215 après 1000 heures [1][2].",
    "de": "Zellen verlieren 85% bei 150°C; MAPbI3 besteht IEC 61215 nach 1000 Stunden nicht [1][2].",
    "hi": "150°C पर सेल 85% दक्षता खोते हैं; MAPbI3 1000 घंटे बाद IEC 61215 में विफल रहता है [1][2]।",
    "ml": "150°C-ൽ സെല്ലുകൾക്ക് 85% കാര്യക്ഷമത നഷ്ടപ്പെടുന്നു; 1000 മണിക്കൂറിന് ശേഷം MAPbI3 IEC 61215-ൽ പരാജയപ്പെടുന്നു [1][2].",
}


def _export_run(language: str) -> ResearchRun:
    run = ResearchRun(query=f"q-{language}", status=RunStatus.COMPLETED, output_language=language)
    run.final_report = f"## Heading\n\n{SAMPLES[language]}\n\n## Sources\n\n1. [A](https://a.test)\n"
    return run


@pytest.mark.parametrize("language", list(SAMPLES))
def test_markdown_export_round_trips_every_language(tmp_path, language):
    container = make_container(tmp_path)
    run = _export_run(language)
    container.runs_repo.save(run)
    with TestClient(create_app(container)) as client:
        response = client.get(f"/api/runs/{run.id}/export")
    assert response.status_code == 200
    assert SAMPLES[language] in response.content.decode("utf-8")


@pytest.mark.parametrize("language", list(SAMPLES))
def test_pdf_export_embeds_the_right_script_fonts(language):
    import io

    from pypdf import PdfReader

    from src.export.pdf import render_run_pdf

    data = render_run_pdf(_export_run(language))
    reader = PdfReader(io.BytesIO(data))
    fonts = set()
    for page in reader.pages:
        for font in page["/Resources"]["/Font"].values():
            fonts.add(str(font.get_object()["/BaseFont"]))
    expected = {"ml": "NotoSansMalayalam", "hi": "NotoSansDevanagari"}.get(language)
    if expected:
        assert any(expected in name for name in fonts), fonts
        other = {"ml": "NotoSansDevanagari", "hi": "NotoSansMalayalam"}[language]
        assert not any(other in name for name in fonts), "shared marks must use the report's own script font"
    else:
        assert not any("NotoSans" in name for name in fonts), "Latin PDFs keep the existing font path"
    text = "".join(page.extract_text() for page in reader.pages)
    for token in ("85%", "150°C", "MAPbI3", "IEC 61215", "1000", "[1]", "[2]"):
        assert token in text, (language, token)
    assert "?" * 2 not in text


def test_pdf_shaping_is_used_only_for_complex_scripts(monkeypatch):
    from src.export import pdf as pdf_module

    calls: list[str] = []
    monkeypatch.setattr(pdf_module, "_enable_script_fonts",
                        lambda pdf, language="en": calls.append(language) or True)
    pdf_module.render_run_pdf(_export_run("en"))
    pdf_module.render_run_pdf(_export_run("de"))
    assert calls == []
    pdf_module.render_run_pdf(_export_run("ml"))
    assert calls == ["ml"]


def test_pdf_fonts_are_not_served_by_the_app(tmp_path):
    with TestClient(create_app(make_container(tmp_path))) as client:
        for path in ("/fonts/NotoSansMalayalam-Regular.ttf", "/api/fonts/NotoSansMalayalam-Regular.ttf",
                     "/src/export/fonts/OFL.txt"):
            assert client.get(path).status_code == 404


def test_interrupted_comparisons_keep_their_language_through_recovery(tmp_path):
    from src.models.workspace import Comparison, ComparisonStatus

    container = make_container(tmp_path)
    comparison = Comparison(run_ids=["a", "b"], output_language="de", status=ComparisonStatus.RUNNING)
    container.comparisons_repo.save(comparison)
    assert container.comparison_service.recover_interrupted_comparisons() == 1
    recovered = container.comparison_service.get(comparison.id)
    assert recovered.status is not ComparisonStatus.RUNNING
    assert recovered.output_language == "de"


def test_follow_up_language_survives_a_restart(tmp_path):
    from src.models.workspace import FollowUp

    path = str(tmp_path / "persist.db")
    first = make_container(tmp_path, db_path=path)
    followup = FollowUp(run_id="r", question="¿Por qué?", output_language="es")
    first.followups_repo.save(followup)
    second = make_container(tmp_path, db_path=path)  # a fresh process on the same database
    stored = second.followup_service.get(followup.id)
    assert stored.output_language == "es" and stored.question == "¿Por qué?"


def test_comparison_titles_never_mine_non_english_questions_with_english_filler():
    from src.services.comparison_title import comparison_title

    spanish = "¿Qué limita actualmente la estabilidad a largo plazo de las celdas solares?"
    title = comparison_title(["What limits battery life?", spanish], "es")
    assert title.startswith("Comparación: ") and "Limita Actualmente" not in title
    assert "Qué limita actualmente" in title
    # English questions keep the deterministic topic phrases exactly as before.
    assert comparison_title(["What limits battery life?", "How do solar farms affect birds?"]) == (
        "Comparison: Limits Battery Life vs Solar Farms Affect Birds"
    )


def test_feature_verdicts_spanish_reports_and_follow_ups_but_not_comparisons():
    router = LanguageRouter(AtlasConfig(model="qwen3:4b"))
    assert router.require("es", "report") == "es"
    assert router.require("es", "followup") == "es"
    with pytest.raises(UnsupportedOutputLanguageError, match="comparison output"):
        router.require("es", "comparison")
    assert router.require("en", "comparison") == "en"  # English is never gated
    spanish = next(row for row in router.describe()["languages"] if row["code"] == "es")
    assert spanish["supported"] is True
    assert spanish["features"]["comparison"]["supported"] is False
    with pytest.raises(ValueError):
        router.capability("es", "slides")


def test_english_comparison_prompt_is_byte_identical(tmp_path):
    from src.prompts.research import COMPARISON_SYSTEM

    c, r1, r2 = two_runs(tmp_path)
    llm = c.research_service._llm_factory(c.config, reasoning=False)
    c.comparison_service.create([r1.id, r2.id])
    calls = llm.with_structured_output(ComparisonSynthesis).calls
    assert calls and calls[0][0] == ("system", COMPARISON_SYSTEM)
