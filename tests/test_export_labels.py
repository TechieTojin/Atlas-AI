"""Exports carry Atlas's own labels in the report's language (Phase 7).

The stored report is never rewritten: only the export localizes the internal
``## Sources`` marker and the not-cited marker. English output is unchanged.
"""

import pytest

from src.export.labels import EXPORT_LABELS, localize_report_markers
from src.export.pdf import render_run_pdf
from tests.test_pdf_export import completed_run, pdf_text_contains

REPORT = (
    "## Resumen\n\nLa humedad degrada MAPbI3 [1].\n\n## Sources\n\n"
    "1. [Moisture study](https://example.org/a)\n"
    "2. [Sources of error](https://example.org/b) *(collected, not cited)*\n"
)


def test_english_report_markers_are_untouched():
    assert localize_report_markers(REPORT, "en") is REPORT


@pytest.mark.parametrize("language", ["es", "fr", "de", "hi", "ml"])
def test_markers_localized_but_titles_kept(language):
    labels = EXPORT_LABELS[language]
    out = localize_report_markers(REPORT, language)
    assert f"## {labels['sources']}\n" in out
    assert labels["not_cited"] in out
    # A source title that happens to contain "Sources" is source text, kept verbatim.
    assert "[Sources of error](https://example.org/b)" in out
    assert "MAPbI3 [1]" in out


@pytest.mark.parametrize("language", ["es", "de", "hi"])
def test_pdf_body_and_metrics_are_localized(language):
    run = completed_run(REPORT)
    run.output_language = language
    pdf = render_run_pdf(run)
    labels = EXPORT_LABELS[language]
    if language != "hi":  # shaped Devanagari does not round-trip through text extraction
        assert pdf_text_contains(pdf, labels["sources"])
    assert not pdf_text_contains(pdf, "Total runtime")
    assert not pdf_text_contains(pdf, "collected, not cited")


def test_english_pdf_metrics_unchanged():
    pdf = render_run_pdf(completed_run(REPORT.replace("Resumen", "Summary")))
    assert pdf_text_contains(pdf, "Total runtime: 12s")
    assert pdf_text_contains(pdf, "Citation coverage: 100%")


def test_markdown_export_header(tmp_path):
    from src.models.runs import RunStatus
    from tests.conftest_v2 import make_container

    container = make_container(tmp_path)
    service = container.research_service
    run = completed_run(REPORT)
    run.output_language = "de"
    service._runs.save(run)
    md = service.export_markdown(run.id)
    assert md.startswith("# Atlas · Recherchebericht\n\n**Frage:** Why thermal runaway?\n\n**Modus:**")
    assert "## Quellen\n" in md and "(gesammelt, nicht zitiert)" in md
    assert service.get_run(run.id).final_report == REPORT  # storage untouched

    english = completed_run(REPORT)
    service._runs.save(english)
    md = service.export_markdown(english.id)
    assert md.startswith("# Atlas Research Report\n\n**Query:** Why thermal runaway?\n\n**Mode:** DEEP · **Completed:** ")
    assert md.endswith(REPORT)
    assert english.status is RunStatus.COMPLETED
