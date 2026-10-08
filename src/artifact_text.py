"""Fixed text that Atlas itself writes INTO generated artifacts.

Most report prose comes from the model. A few strings are rendered by code:
comparison section headings and empty-section sentences, the extractive
fallback report's framing, and the no-evidence report. A non-English artifact
must not mix model prose in its language with code-written English, so those
strings live here, keyed by output language.

Rules:

* English values are byte-identical to the strings Atlas has always written,
  so English artifacts are unchanged.
* ``## Sources`` is NOT here: it is the internal protocol marker that report
  processing depends on, rendered by ``render_sources_section`` in English for
  every language. The UI labels it in the reader's language.
* Missing keys fall back to English; translations were written for Atlas and
  are pending native-speaker review (Malayalam and Hindi especially).
"""

from __future__ import annotations

from src.languages import ENGLISH, parse_output_language

_TEXT: dict[str, dict[str, str]] = {
    "en": {
        "comparison.title": "Comparison",
        "comparison.title_prefix": "Comparison: ",
        "comparison.versus": " vs ",
        "comparison.overview": "Overview",
        "comparison.agreements": "Agreements",
        "comparison.no_agreements": "No finding was supported by more than one of the selected research runs.",
        "comparison.contradictions": "Contradictions",
        "comparison.no_contradictions": "No direct contradiction was identified between the selected research runs.",
        "comparison.unique": "New or Unique Evidence",
        "comparison.no_unique": "Neither run contributed evidence the other did not also reach.",
        "comparison.conclusion": "Conclusion",
        "comparison.source_differences": "Source Differences",
        "comparison.combined": "Combined unique sources: {count}",
        "comparison.shared": "Shared across runs: {count}",
        "comparison.unique_to": "Unique to {label}: {count}",
        "comparison.run": "Run {number}",
        "comparison.and": " and ",
        "report.no_evidence": (
            "# Research Report\n\n**Question:** {question}\n\n"
            "Atlas was unable to collect any evidence for this question "
            "(searches failed or returned no results), so no supported "
            "answer can be given. Please retry, refine the question, or "
            "check search API availability."
        ),
        "fallback.heading": "Evidence Summary",
        "fallback.note": (
            "*Atlas could not finish writing a narrative report within this run's "
            "time budget. Below are the key findings from the collected sources, "
            "quoted verbatim and cited. Regenerate the report or re-run in DEEP "
            "mode for a full synthesis.*"
        ),
        "fallback.group": "Collected evidence",
        "fallback.none": (
            "No claim-bearing excerpts could be extracted from the "
            "collected sources; see the source list below."
        ),
    },
    "es": {
        "comparison.title": "Comparación",
        "comparison.title_prefix": "Comparación: ",
        "comparison.versus": " frente a ",
        "comparison.overview": "Visión general",
        "comparison.agreements": "Coincidencias",
        "comparison.no_agreements": "Ningún hallazgo fue respaldado por más de una de las investigaciones seleccionadas.",
        "comparison.contradictions": "Contradicciones",
        "comparison.no_contradictions": "No se identificó ninguna contradicción directa entre las investigaciones seleccionadas.",
        "comparison.unique": "Evidencia nueva o exclusiva",
        "comparison.no_unique": "Ninguna investigación aportó evidencia que la otra no hubiera encontrado también.",
        "comparison.conclusion": "Conclusión",
        "comparison.source_differences": "Diferencias de fuentes",
        "comparison.combined": "Fuentes únicas combinadas: {count}",
        "comparison.shared": "Compartidas entre investigaciones: {count}",
        "comparison.unique_to": "Exclusivas de {label}: {count}",
        "comparison.run": "Investigación {number}",
        "comparison.and": " y ",
        "report.no_evidence": (
            "# Informe de investigación\n\n**Pregunta:** {question}\n\n"
            "Atlas no pudo recopilar evidencia para esta pregunta (las búsquedas "
            "fallaron o no devolvieron resultados), por lo que no puede darse una "
            "respuesta fundamentada. Vuelve a intentarlo, reformula la pregunta o "
            "comprueba la disponibilidad de la API de búsqueda."
        ),
        "fallback.heading": "Resumen de evidencia",
        "fallback.note": (
            "*Atlas no pudo terminar de redactar un informe narrativo dentro del "
            "tiempo disponible para esta investigación. A continuación se muestran "
            "los hallazgos clave de las fuentes recopiladas, citados textualmente. "
            "Regenera el informe o vuelve a ejecutarlo en modo DEEP para obtener una "
            "síntesis completa.*"
        ),
        "fallback.group": "Evidencia recopilada",
        "fallback.none": (
            "No se pudieron extraer fragmentos con afirmaciones de las fuentes "
            "recopiladas; consulta la lista de fuentes a continuación."
        ),
    },
    "fr": {
        "comparison.title": "Comparaison",
        "comparison.title_prefix": "Comparaison : ",
        "comparison.versus": " contre ",
        "comparison.overview": "Vue d’ensemble",
        "comparison.agreements": "Points d’accord",
        "comparison.no_agreements": "Aucun constat n’est étayé par plus d’une des recherches sélectionnées.",
        "comparison.contradictions": "Contradictions",
        "comparison.no_contradictions": "Aucune contradiction directe n’a été relevée entre les recherches sélectionnées.",
        "comparison.unique": "Éléments nouveaux ou propres à une recherche",
        "comparison.no_unique": "Aucune recherche n’a apporté d’éléments que l’autre n’ait pas également trouvés.",
        "comparison.conclusion": "Conclusion",
        "comparison.source_differences": "Différences de sources",
        "comparison.combined": "Sources uniques combinées : {count}",
        "comparison.shared": "Communes aux recherches : {count}",
        "comparison.unique_to": "Propres à {label} : {count}",
        "comparison.run": "Recherche {number}",
        "comparison.and": " et ",
        "report.no_evidence": (
            "# Rapport de recherche\n\n**Question :** {question}\n\n"
            "Atlas n’a pu recueillir aucune source pour cette question (les "
            "recherches ont échoué ou n’ont donné aucun résultat) ; aucune réponse "
            "étayée ne peut donc être fournie. Réessayez, reformulez la question ou "
            "vérifiez la disponibilité de l’API de recherche."
        ),
        "fallback.heading": "Synthèse des éléments",
        "fallback.note": (
            "*Atlas n’a pas pu terminer la rédaction d’un rapport dans le temps "
            "imparti pour cette recherche. Voici les principaux constats des sources "
            "recueillies, cités textuellement. Régénérez le rapport ou relancez-le en "
            "mode DEEP pour une synthèse complète.*"
        ),
        "fallback.group": "Éléments recueillis",
        "fallback.none": (
            "Aucun extrait contenant une affirmation n’a pu être tiré des sources "
            "recueillies ; consultez la liste des sources ci-dessous."
        ),
    },
    "de": {
        "comparison.title": "Vergleich",
        "comparison.title_prefix": "Vergleich: ",
        "comparison.versus": " vs. ",
        "comparison.overview": "Überblick",
        "comparison.agreements": "Übereinstimmungen",
        "comparison.no_agreements": "Keine Erkenntnis wurde von mehr als einer der ausgewählten Recherchen gestützt.",
        "comparison.contradictions": "Widersprüche",
        "comparison.no_contradictions": "Zwischen den ausgewählten Recherchen wurde kein direkter Widerspruch festgestellt.",
        "comparison.unique": "Neue oder eigenständige Belege",
        "comparison.no_unique": "Keine Recherche lieferte Belege, die die andere nicht ebenfalls gefunden hat.",
        "comparison.conclusion": "Fazit",
        "comparison.source_differences": "Unterschiede bei den Quellen",
        "comparison.combined": "Eindeutige Quellen insgesamt: {count}",
        "comparison.shared": "Von mehreren Recherchen genutzt: {count}",
        "comparison.unique_to": "Nur in {label}: {count}",
        "comparison.run": "Recherche {number}",
        "comparison.and": " und ",
        "report.no_evidence": (
            "# Recherchebericht\n\n**Frage:** {question}\n\n"
            "Atlas konnte zu dieser Frage keine Belege sammeln (die Suchen sind "
            "fehlgeschlagen oder lieferten keine Ergebnisse), daher ist keine "
            "belegte Antwort möglich. Bitte erneut versuchen, die Frage präzisieren "
            "oder die Verfügbarkeit der Such-API prüfen."
        ),
        "fallback.heading": "Zusammenfassung der Belege",
        "fallback.note": (
            "*Atlas konnte innerhalb des Zeitbudgets dieser Recherche keinen "
            "ausformulierten Bericht fertigstellen. Unten stehen die wichtigsten "
            "Erkenntnisse aus den gesammelten Quellen, wörtlich zitiert und belegt. "
            "Erstellen Sie den Bericht neu oder führen Sie die Recherche im DEEP-Modus "
            "erneut aus, um eine vollständige Synthese zu erhalten.*"
        ),
        "fallback.group": "Gesammelte Belege",
        "fallback.none": (
            "Aus den gesammelten Quellen ließen sich keine Auszüge mit Aussagen "
            "entnehmen; siehe die Quellenliste unten."
        ),
    },
    "hi": {
        "comparison.title": "तुलना",
        "comparison.title_prefix": "तुलना: ",
        "comparison.versus": " बनाम ",
        "comparison.overview": "सारांश",
        "comparison.agreements": "सहमतियाँ",
        "comparison.no_agreements": "चुने गए अनुसंधान रन में से एक से अधिक ने किसी निष्कर्ष का समर्थन नहीं किया।",
        "comparison.contradictions": "विरोधाभास",
        "comparison.no_contradictions": "चुने गए अनुसंधान रन के बीच कोई सीधा विरोधाभास नहीं मिला।",
        "comparison.unique": "नए या विशिष्ट साक्ष्य",
        "comparison.no_unique": "किसी भी रन ने ऐसा साक्ष्य नहीं दिया जो दूसरे रन को भी न मिला हो।",
        "comparison.conclusion": "निष्कर्ष",
        "comparison.source_differences": "स्रोतों में अंतर",
        "comparison.combined": "कुल विशिष्ट स्रोत: {count}",
        "comparison.shared": "रन के बीच साझा: {count}",
        "comparison.unique_to": "केवल {label} में: {count}",
        "comparison.run": "रन {number}",
        "comparison.and": " और ",
        "report.no_evidence": (
            "# अनुसंधान रिपोर्ट\n\n**प्रश्न:** {question}\n\n"
            "Atlas इस प्रश्न के लिए कोई साक्ष्य एकत्र नहीं कर सका (खोज विफल रही या "
            "कोई परिणाम नहीं मिला), इसलिए कोई समर्थित उत्तर नहीं दिया जा सकता। कृपया "
            "दोबारा प्रयास करें, प्रश्न को स्पष्ट करें, या खोज API की उपलब्धता जाँचें।"
        ),
        "fallback.heading": "साक्ष्य सारांश",
        "fallback.note": (
            "*Atlas इस रन के समय-बजट में पूरी रिपोर्ट नहीं लिख सका। नीचे एकत्र स्रोतों "
            "के मुख्य निष्कर्ष, शब्दशः उद्धृत और संदर्भित, दिए गए हैं। पूर्ण संश्लेषण के "
            "लिए रिपोर्ट दोबारा बनाएँ या DEEP मोड में फिर से चलाएँ।*"
        ),
        "fallback.group": "एकत्र साक्ष्य",
        "fallback.none": "एकत्र स्रोतों से कोई दावा-युक्त अंश नहीं निकाला जा सका; नीचे स्रोत सूची देखें।",
    },
    "ml": {
        "comparison.title": "താരതമ്യം",
        "comparison.title_prefix": "താരതമ്യം: ",
        "comparison.versus": " vs ",
        "comparison.overview": "അവലോകനം",
        "comparison.agreements": "യോജിപ്പുകൾ",
        "comparison.no_agreements": "തിരഞ്ഞെടുത്ത ഒന്നിലധികം ഗവേഷണ റണ്ണുകൾ ഒരു കണ്ടെത്തലിനെയും പിന്തുണച്ചില്ല.",
        "comparison.contradictions": "വൈരുദ്ധ്യങ്ങൾ",
        "comparison.no_contradictions": "തിരഞ്ഞെടുത്ത ഗവേഷണ റണ്ണുകൾക്കിടയിൽ നേരിട്ടുള്ള വൈരുദ്ധ്യം കണ്ടെത്തിയില്ല.",
        "comparison.unique": "പുതിയതോ സവിശേഷമോ ആയ തെളിവുകൾ",
        "comparison.no_unique": "മറ്റേ റണ്ണും കണ്ടെത്താത്ത തെളിവുകൾ ഒരു റണ്ണും നൽകിയില്ല.",
        "comparison.conclusion": "നിഗമനം",
        "comparison.source_differences": "ഉറവിടങ്ങളിലെ വ്യത്യാസങ്ങൾ",
        "comparison.combined": "ആകെ വ്യത്യസ്ത ഉറവിടങ്ങൾ: {count}",
        "comparison.shared": "റണ്ണുകൾ പങ്കിട്ടവ: {count}",
        "comparison.unique_to": "{label}-ൽ മാത്രം: {count}",
        "comparison.run": "റൺ {number}",
        "comparison.and": ", ",
        "report.no_evidence": (
            "# ഗവേഷണ റിപ്പോർട്ട്\n\n**ചോദ്യം:** {question}\n\n"
            "ഈ ചോദ്യത്തിന് Atlas-ന് തെളിവുകളൊന്നും ശേഖരിക്കാനായില്ല (തിരയലുകൾ "
            "പരാജയപ്പെട്ടു അല്ലെങ്കിൽ ഫലങ്ങളൊന്നും ലഭിച്ചില്ല), അതിനാൽ പിന്തുണയുള്ള ഉത്തരം "
            "നൽകാനാവില്ല. വീണ്ടും ശ്രമിക്കുക, ചോദ്യം വ്യക്തമാക്കുക, അല്ലെങ്കിൽ തിരയൽ API "
            "ലഭ്യമാണോ എന്ന് പരിശോധിക്കുക."
        ),
        "fallback.heading": "തെളിവുകളുടെ സംഗ്രഹം",
        "fallback.note": (
            "*ഈ റണ്ണിന്റെ സമയപരിധിക്കുള്ളിൽ Atlas-ന് പൂർണ്ണ റിപ്പോർട്ട് എഴുതി "
            "പൂർത്തിയാക്കാനായില്ല. ശേഖരിച്ച ഉറവിടങ്ങളിലെ പ്രധാന കണ്ടെത്തലുകൾ അതേപടി "
            "ഉദ്ധരിച്ച് താഴെ നൽകുന്നു. പൂർണ്ണ സംശ്ലേഷണത്തിനായി റിപ്പോർട്ട് "
            "പുനഃസൃഷ്ടിക്കുക അല്ലെങ്കിൽ DEEP മോഡിൽ വീണ്ടും പ്രവർത്തിപ്പിക്കുക.*"
        ),
        "fallback.group": "ശേഖരിച്ച തെളിവുകൾ",
        "fallback.none": "ശേഖരിച്ച ഉറവിടങ്ങളിൽ നിന്ന് അവകാശവാദങ്ങളുള്ള ഭാഗങ്ങൾ കണ്ടെത്താനായില്ല; താഴെയുള്ള ഉറവിട പട്ടിക കാണുക.",
    },
}


def artifact_text(language: str, key: str, **params: object) -> str:
    """Code-written artifact text in ``language`` (English if untranslated)."""
    table = _TEXT.get(parse_output_language(language), _TEXT[ENGLISH])
    template = table.get(key, _TEXT[ENGLISH][key])
    return template.format(**params) if params else template
