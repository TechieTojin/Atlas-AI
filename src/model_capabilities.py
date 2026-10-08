"""Which output languages the configured models can actually write well.

The backend is authoritative. A language is generation-supported only when a
local, bounded benchmark of that exact model/language pair passed Atlas's
acceptance criteria (see ``docs`` in the multilingual report and the
``_VALIDATED`` table below). Emitting characters in a script is not enough.

Lookups are pure configuration: no model call, network request, embedding or
benchmark ever runs on page load or startup.

English is the baseline Atlas has always generated with whatever model is
configured, so it is never gated: an unvalidated custom model keeps working
in English exactly as before. Every other language is unsupported until
validated.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.config import AtlasConfig
from src.languages import ENGLISH, OUTPUT_LANGUAGE_CODES, OUTPUT_LANGUAGES, parse_output_language

#: Kinds of generated artifact. A language can pass for one and fail another:
#: comparisons are structured, attribution-checked output and are harder.
FEATURES = ("report", "followup", "comparison")

SUPPORTED = "supported"
UNSUPPORTED = "unsupported"
UNVALIDATED = "unvalidated"
#: Generates acceptably but with a stated limitation (e.g. much slower runs).
LIMITED = "limited"

#: The validated production route per language: the one place model names are
#: chosen for a language. A language absent here uses the configured default
#: model (``ATLAS_MODEL``, qwen3:4b), which is how English and Spanish run.
#: ``ATLAS_LANGUAGE_MODELS`` may override an entry for experiments.
DEFAULT_LANGUAGE_ROUTES: dict[str, str] = {
    "hi": "gemma4:e4b",
    "de": "gemma4:e4b",
}


@dataclass(frozen=True)
class LanguageCapability:
    language: str
    model: str
    status: str
    reason: str = ""
    feature: str = "report"

    @property
    def supported(self) -> bool:
        return self.status in (SUPPORTED, LIMITED)


class UnsupportedOutputLanguageError(ValueError):
    """A known language the routed model cannot generate acceptably."""


#: Benchmark verdicts per (model, language). Anything absent is UNVALIDATED.
#: Evidence: Phase 0 and the Phase 4 bounded benchmark (fixed evidence package,
#: production FAST synthesis settings); results are summarised in the
#: multilingual acceptance report.
_VALIDATED: dict[tuple[str, str], tuple[str, str]] = {
    ("qwen3:4b", "ml"): (
        UNSUPPORTED,
        "Benchmark failed: about 45 words in 300 s (timed out), with repetition, "
        "dropped numbers and formulas, and poor terminology.",
    ),
    ("qwen3:4b", "hi"): (
        UNSUPPORTED,
        "Benchmark failed: timed out at about 118 words in 300 s, with meaning-changing "
        "terminology errors and dropped numbers.",
    ),
    ("qwen3:4b", "fr"): (
        UNSUPPORTED,
        "Benchmark failed on accuracy: fluent and on time, but meaning-changing "
        "terminology errors (e.g. 'vacances d'iode' for iodide vacancies).",
    ),
    ("qwen3:4b", "de"): (
        UNSUPPORTED,
        "Benchmark failed on accuracy: invented a technique absent from the sources "
        "and made several meaning-changing word choices.",
    ),
    ("qwen3:4b", "es"): (
        SUPPORTED,
        "Benchmark passed: grounded, correctly cited Spanish at FAST length; verified end "
        "to end (report, regeneration, follow-up). Runs ~1.3x slower than English.",
    ),
    ("qwen3:8b", "ml"): (
        UNSUPPORTED,
        "Benchmark failed: about 62 words in 600 s (timed out), with 22% repeated phrasing.",
    ),
    ("qwen3:8b", "hi"): (
        UNSUPPORTED,
        "Benchmark failed: 105 words took 470 s (5.6 tokens per word), far beyond the "
        "FAST budget, and every number in the evidence was dropped.",
    ),
    # Phase 7, gemma4:e4b (Q4_K_M). A route only, never the default model.
    ("gemma4:e4b", "ml"): (
        UNSUPPORTED,
        "Benchmark failed: words mixed Malayalam with Devanagari and Bengali letters, "
        "invented terminology and English leakage.",
    ),
    ("gemma4:e4b", "fr"): (
        UNSUPPORTED,
        "Benchmark failed on accuracy: it moved the irreversible PbI2 decomposition from "
        "~100 hours to 'within hours', and used wrong terms ('lacunes iodurelles', "
        "'électrode de transport de trous').",
    ),
    ("gemma4:e4b", "hi"): (
        LIMITED,
        "Slower: benchmark passed (grounded, correctly cited Hindi with formulas and numbers "
        "intact) and verified end to end, but the local model writes ~3.5 tokens/s, so a "
        "FAST run takes about 8 minutes.",
    ),
    # Validated, but not routed: qwen3:4b already writes Spanish, faster.
    ("gemma4:e4b", "es"): (
        LIMITED,
        "Benchmark passed: grounded, correctly cited Spanish with formulas and numbers intact; "
        "verified end to end. Slower than the validated qwen3:4b route (~9 minutes per FAST run).",
    ),
    ("gemma4:e4b", "de"): (
        LIMITED,
        "Slower: benchmark passed (grounded, correctly cited German; the targeted "
        "thermal-stability check kept the substitution direction and every number) and "
        "verified end to end, but a FAST run takes about 8 minutes.",
    ),
}

#: Per-(model, language, mode) config overrides for validated languages whose
#: tokens-per-word differ from English, so a report fits the same output-token
#: cap and time budget. English never has an entry: its budgets are untouched.
#: Feature-specific downgrades of a supported language: (model, language,
#: feature) -> verdict. Absent means the language verdict applies.
_FEATURE_VERDICTS: dict[tuple[str, str, str], tuple[str, str]] = {
    ("qwen3:4b", "es", "comparison"): (
        UNSUPPORTED,
        "Not validated: both Spanish comparisons failed Atlas's attribution checks, and "
        "the English control failed the same checks on the same run pairs, so a "
        "Spanish comparison cannot yet be shown to be reliable.",
    ),
    **{
        ("gemma4:e4b", code, "comparison"): (
            UNSUPPORTED,
            "Not validated: no comparison has been verified with this model in this language.",
        )
        for code in ("hi", "es", "de")
    },
}

_BUDGETS: dict[tuple[str, str, str], dict[str, int]] = {
    # Spanish uses ~2.2 output tokens per word versus ~1.75 for English, so the
    # English FAST ceiling (600 words) would always hit the 900-token cap and
    # lose the conclusion. This keeps a complete report inside the same cap.
    ("qwen3:4b", "es", "FAST"): {"report_target_words": 330, "synthesis_max_words": 380},
    # gemma4:e4b writes ~3.4 tokens/s on this CPU (qwen3:4b ~4.6 in English) and plans
    # with the same model, so the English 540 s FAST promise cannot hold. The longer
    # budget is reported as a LIMITED (speed) verdict, never hidden. Word ceilings
    # keep a complete report under the 900-token cap at each language's
    # measured tokens-per-word (hi 1.9, es 1.85, de 2.6).
    ("gemma4:e4b", "hi", "FAST"): {
        "report_target_words": 330, "synthesis_max_words": 380,
        "run_budget_seconds": 1200, "planner_timeout_seconds": 300,
    },
    ("gemma4:e4b", "es", "FAST"): {
        "report_target_words": 330, "synthesis_max_words": 380,
        "run_budget_seconds": 1200, "planner_timeout_seconds": 300,
    },
    ("gemma4:e4b", "de", "FAST"): {
        "report_target_words": 260, "synthesis_max_words": 300,
        "run_budget_seconds": 1200, "planner_timeout_seconds": 300,
    },
}


def _verdict(model: str, language: str) -> tuple[str, str]:
    if language == ENGLISH:
        return SUPPORTED, "Baseline language for every configured model."
    return _VALIDATED.get(
        (model, language),
        (UNVALIDATED, f"{OUTPUT_LANGUAGES[language].english_name} output has not been validated for {model}."),
    )


class LanguageRouter:
    """Routes each output language to a model and reports its capability."""

    def __init__(self, config: AtlasConfig) -> None:
        self._default_model = config.model
        self._routes = {**DEFAULT_LANGUAGE_ROUTES, **dict(config.language_models)}

    def model_for(self, language: str) -> str:
        language = parse_output_language(language)
        return self._routes.get(language, self._default_model)

    def capability(self, language: str, feature: str = "report") -> LanguageCapability:
        language = parse_output_language(language)
        if feature not in FEATURES:
            raise ValueError(f"Unknown artifact feature {feature!r}.")
        model = self.model_for(language)
        status, reason = _verdict(model, language)
        if status in (SUPPORTED, LIMITED) and language != ENGLISH:
            status, reason = _FEATURE_VERDICTS.get((model, language, feature), (status, reason))
        return LanguageCapability(language=language, model=model, status=status, reason=reason, feature=feature)

    def budget_overrides(self, language: str, mode: str) -> dict[str, int]:
        """Config overrides for a run in ``language`` and ``mode`` (FAST/DEEP)."""
        language = parse_output_language(language)
        if language == ENGLISH:
            return {}
        return dict(_BUDGETS.get((self.model_for(language), language, mode), {}))

    def is_supported(self, language: str, feature: str = "report") -> bool:
        return self.capability(language, feature).supported

    def require(self, language: str, feature: str = "report") -> str:
        """Validated language code, or a clear error if it cannot be generated."""
        capability = self.capability(language, feature)
        if not capability.supported:
            name = OUTPUT_LANGUAGES[capability.language].english_name
            what = "output" if feature == "report" else f"{feature} output"
            raise UnsupportedOutputLanguageError(
                f"{name} ({capability.language}) {what} is not supported with the "
                f"configured model {capability.model}: {capability.reason}"
            )
        return capability.language

    def describe(self) -> dict:
        """The capability snapshot served by ``GET /api/capabilities/languages``."""
        return {
            "default_output_language": ENGLISH,
            "model": self._default_model,
            "languages": [
                {
                    "code": cap.language,
                    "english_name": OUTPUT_LANGUAGES[cap.language].english_name,
                    "native_name": OUTPUT_LANGUAGES[cap.language].native_name,
                    "model": cap.model,
                    "status": cap.status,
                    "supported": cap.supported,
                    "reason": cap.reason,
                    "features": {
                        feature: {
                            "status": self.capability(cap.language, feature).status,
                            "supported": self.capability(cap.language, feature).supported,
                            "reason": self.capability(cap.language, feature).reason,
                        }
                        for feature in FEATURES
                    },
                }
                for cap in (self.capability(code) for code in OUTPUT_LANGUAGE_CODES)
            ],
        }
