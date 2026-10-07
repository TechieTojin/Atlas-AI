"""Deterministic post-run evaluation of a final report.

No LLM involved: these are mechanical integrity checks persisted with the
run so report quality is inspectable in the UI and regressions are visible.
"""

from __future__ import annotations

import re

from src.models.research import Source
from src.models.runs import EvaluationResult
from src.unicode_text import CANONICAL_CITATION_RE

# Stored reports use canonical ASCII markers; see src.unicode_text.
_CITATION_RE = CANONICAL_CITATION_RE
_SOURCES_HEADING_RE = re.compile(r"^##\s+Sources\s*$", re.MULTILINE)
_REASONING_MARKERS = ("<think>", "</think>")


def evaluate_report(report: str, sources: list[Source]) -> EvaluationResult:
    result = EvaluationResult()
    if not report:
        result.notes.append("Report is empty.")
        return result

    body = report.split("## Sources")[0]
    citations = [int(n) for n in _CITATION_RE.findall(body)]
    n = len(sources)

    result.has_citations = bool(citations)
    if not citations:
        result.notes.append("No inline citations in the report body.")

    invalid = sorted({c for c in citations if not (1 <= c <= n)})
    result.citations_valid = not invalid
    if invalid:
        result.notes.append(f"Invalid citation numbers: {invalid}.")

    result.single_sources_section = len(_SOURCES_HEADING_RE.findall(report)) == 1
    if not result.single_sources_section:
        result.notes.append("Report does not contain exactly one '## Sources' section.")

    cited = {c for c in citations if 1 <= c <= n}
    result.citation_coverage = round(len(cited) / n, 3) if n else 0.0

    lowered = report.lower()
    result.no_reasoning_markers = not any(m in lowered for m in _REASONING_MARKERS)
    if not result.no_reasoning_markers:
        result.notes.append("Reasoning markers found in the report.")

    # Provenance: every web source needs a real URL; every document source
    # needs document identity and the deterministic rendering present.
    provenance_ok = True
    for i, source in enumerate(sources, 1):
        if source.kind == "document":
            if not source.document_id or not source.filename:
                provenance_ok = False
                result.notes.append(f"Source {i} missing document provenance.")
        elif not source.url.startswith(("http://", "https://")):
            provenance_ok = False
            result.notes.append(f"Source {i} has a non-HTTP URL: {source.url!r}.")
    result.provenance_valid = provenance_ok

    result.passed = all(
        (
            result.has_citations,
            result.citations_valid,
            result.single_sources_section,
            result.no_reasoning_markers,
            result.provenance_valid,
        )
    )
    return result
