"""Canonical output languages for generated Atlas artifacts.

This is the single backend definition of the languages Atlas can be asked to
write in. It is deliberately separate from:

* the UI language (frontend only; never sent to the backend),
* the sources' language (search finds the best evidence in any language),
* model capability (``src.model_capabilities`` decides what can actually be
  generated well with the configured models).

Every generated artifact (research run, follow-up, comparison) records the
language it was written in. Historical artifacts predate the field and are
English.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OutputLanguage:
    code: str
    english_name: str
    native_name: str


ENGLISH = "en"
DEFAULT_OUTPUT_LANGUAGE = ENGLISH

OUTPUT_LANGUAGES: dict[str, OutputLanguage] = {
    language.code: language
    for language in (
        OutputLanguage("en", "English", "English"),
        OutputLanguage("ml", "Malayalam", "മലയാളം"),
        OutputLanguage("hi", "Hindi", "हिन्दी"),
        OutputLanguage("es", "Spanish", "Español"),
        OutputLanguage("fr", "French", "Français"),
        OutputLanguage("de", "German", "Deutsch"),
    )
}

OUTPUT_LANGUAGE_CODES: tuple[str, ...] = tuple(OUTPUT_LANGUAGES)


class UnknownLanguageError(ValueError):
    """An output language code Atlas does not know."""


def parse_output_language(value: object) -> str:
    """Validate an output-language code; missing means the default (English).

    Accepts only canonical lower-case codes, so ``"EN"`` or ``"en-US"`` are
    rejected rather than guessed at.
    """
    if value is None or value == "":
        return DEFAULT_OUTPUT_LANGUAGE
    if not isinstance(value, str) or value not in OUTPUT_LANGUAGES:
        allowed = ", ".join(OUTPUT_LANGUAGE_CODES)
        raise UnknownLanguageError(
            f"Unknown output language {value!r}. Supported codes: {allowed}."
        )
    return value


def stored_output_language(value: object) -> str:
    """Language of an artifact read back from storage.

    Rows written before languages existed have no value and are English. An
    unrecognised stored value is also treated as English rather than crashing
    a read, but it is never produced by Atlas itself.
    """
    return value if isinstance(value, str) and value in OUTPUT_LANGUAGES else DEFAULT_OUTPUT_LANGUAGE


# --- Prompt-language contract --------------------------------------------------

_INSTRUCTION = """

OUTPUT LANGUAGE: {name} ({code})
- Write every heading and all explanatory prose in {name}. Do not write it in English.
- Citation markers stay EXACTLY as ASCII bracketed digits: [1], [2], [12].
  Never use other numerals inside them (no [१] or [൧]) and never write (1) or 【1】.
- Keep these exactly as they appear in the sources, untranslated: source titles,
  URLs, numbers and percentages, units, chemical formulas, standard identifiers,
  model and product names, and other technical identifiers.
- Write formulas, units and numbers as plain text, as the sources write them:
  ordinary digits for subscripts and the ° sign for degrees. Never use LaTeX,
  $...$ math or backslash commands.
- Proper nouns may stay in their original form.
- Do not add a References, Bibliography or Sources list in any language: the
  verified source list is appended by the system.
- Use natural, professional {name} suited to a research report."""


def language_instruction(code: str) -> str:
    """The one place generated-language instructions are written.

    It names categories only, never concrete examples: an earlier draft cited
    "IEC 61215" as an example identifier and a real follow-up answer then
    claimed that standard although no source mentioned it.

    English returns an empty string, so every existing English prompt is sent
    byte-for-byte as before.
    """
    language = OUTPUT_LANGUAGES[parse_output_language(code)]
    if language.code == ENGLISH:
        return ""
    return _INSTRUCTION.format(name=language.english_name, code=language.code)


_PLAN_INSTRUCTION = """

PLAN LANGUAGE: {name} ({code})
- Write the objective, every subquestion and every evidence_needed in {name}:
  the user reads the plan in {name}.
- Write search_queries in whatever language will find the most authoritative
  sources, usually English. Never translate technical identifiers in them.
  Retrieval quality matters more than matching the report language."""


def plan_language_instruction(code: str) -> str:
    """Planner instruction for the user-visible plan text ("" for English)."""
    language = OUTPUT_LANGUAGES[parse_output_language(code)]
    if language.code == ENGLISH:
        return ""
    return _PLAN_INSTRUCTION.format(name=language.english_name, code=language.code)
