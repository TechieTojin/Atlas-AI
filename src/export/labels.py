"""Labels Atlas writes into exported files, in the report's own language.

Applied at export time only: the stored report keeps the internal ``## Sources``
protocol marker and is never rewritten. English strings match the historical
English exports exactly.
"""

from __future__ import annotations

import re

from src.languages import stored_output_language

SOURCES_MARKER = "## Sources"
NOT_CITED_MARKER = "*(collected, not cited)*"

EXPORT_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "md_title": "Atlas Research Report", "query": "Query", "completed": "Completed",
        "sources": "Sources", "not_cited": "(collected, not cited)",
        "runtime": "Total runtime: {seconds}s · Iterations: {iterations} · Queries: {queries}",
        "counts": "Sources collected/selected/cited: {collected}/{selected}/{cited} · Citation coverage: {coverage}",
        "tiers": "Source quality tiers: {tiers}",
        "pages": "Pages fetched: {fetched}/{attempted} (snippet fallbacks: {fallbacks})",
    },
    "es": {
        "md_title": "Atlas · Informe de investigación", "query": "Pregunta", "completed": "Completado",
        "sources": "Fuentes", "not_cited": "(recopilada, no citada)",
        "runtime": "Tiempo total: {seconds} s · Iteraciones: {iterations} · Consultas: {queries}",
        "counts": "Fuentes recopiladas/seleccionadas/citadas: {collected}/{selected}/{cited} · Cobertura de citas: {coverage}",
        "tiers": "Niveles de calidad de las fuentes: {tiers}",
        "pages": "Páginas obtenidas: {fetched}/{attempted} (fragmentos de respaldo: {fallbacks})",
    },
    "fr": {
        "md_title": "Atlas · Rapport de recherche", "query": "Question", "completed": "Terminé",
        "sources": "Sources", "not_cited": "(collectée, non citée)",
        "runtime": "Durée totale : {seconds} s · Itérations : {iterations} · Requêtes : {queries}",
        "counts": "Sources collectées/sélectionnées/citées : {collected}/{selected}/{cited} · Couverture des citations : {coverage}",
        "tiers": "Niveaux de qualité des sources : {tiers}",
        "pages": "Pages récupérées : {fetched}/{attempted} (extraits de secours : {fallbacks})",
    },
    "de": {
        "md_title": "Atlas · Recherchebericht", "query": "Frage", "completed": "Abgeschlossen",
        "sources": "Quellen", "not_cited": "(gesammelt, nicht zitiert)",
        "runtime": "Gesamtlaufzeit: {seconds} s · Iterationen: {iterations} · Suchanfragen: {queries}",
        "counts": "Quellen gesammelt/ausgewählt/zitiert: {collected}/{selected}/{cited} · Zitierabdeckung: {coverage}",
        "tiers": "Qualitätsstufen der Quellen: {tiers}",
        "pages": "Abgerufene Seiten: {fetched}/{attempted} (Snippet-Ersatz: {fallbacks})",
    },
    "hi": {
        "md_title": "Atlas · अनुसंधान रिपोर्ट", "query": "प्रश्न", "completed": "पूरा हुआ",
        "sources": "स्रोत", "not_cited": "(एकत्रित, उद्धृत नहीं)",
        "runtime": "कुल समय: {seconds} सेकंड · पुनरावृत्तियाँ: {iterations} · खोज क्वेरी: {queries}",
        "counts": "स्रोत एकत्रित/चयनित/उद्धृत: {collected}/{selected}/{cited} · उद्धरण कवरेज: {coverage}",
        "tiers": "स्रोत गुणवत्ता स्तर: {tiers}",
        "pages": "प्राप्त पृष्ठ: {fetched}/{attempted} (स्निपेट विकल्प: {fallbacks})",
    },
    "ml": {
        "md_title": "Atlas · ഗവേഷണ റിപ്പോർട്ട്", "query": "ചോദ്യം", "completed": "പൂർത്തിയായത്",
        "sources": "ഉറവിടങ്ങൾ", "not_cited": "(ശേഖരിച്ചത്, ഉദ്ധരിച്ചിട്ടില്ല)",
        "runtime": "ആകെ സമയം: {seconds} സെക്കൻഡ് · ആവർത്തനങ്ങൾ: {iterations} · തിരയലുകൾ: {queries}",
        "counts": "ഉറവിടങ്ങൾ ശേഖരിച്ചത്/തിരഞ്ഞെടുത്തത്/ഉദ്ധരിച്ചത്: {collected}/{selected}/{cited} · ഉദ്ധരണി കവറേജ്: {coverage}",
        "tiers": "ഉറവിട ഗുണനിലവാര തലങ്ങൾ: {tiers}",
        "pages": "ലഭിച്ച പേജുകൾ: {fetched}/{attempted} (സ്നിപ്പറ്റ് പകരം: {fallbacks})",
    },
}


def export_labels(language: str) -> dict[str, str]:
    return EXPORT_LABELS[stored_output_language(language)]


def localize_report_markers(report: str, language: str) -> str:
    """The stored report's English protocol markers, in the export's language.

    Only the code-written ``## Sources`` heading line and the code-written
    not-cited marker change; model prose and source titles are untouched.
    """
    labels = export_labels(language)
    if labels is EXPORT_LABELS["en"]:
        return report
    report = re.sub(r"(?m)^## Sources\s*$", f"## {labels['sources']}", report)
    return report.replace(NOT_CITED_MARKER, f"*{labels['not_cited']}*")
