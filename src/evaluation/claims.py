"""Deterministic claim ↔ citation mapping for the evidence inspector.

Claims are extracted mechanically from the final report: a claim is a
sentence (or list item) in the report body that carries at least one valid
``[n]`` citation marker. No LLM is involved, so the mapping can never be
fabricated — it is exactly what the report says.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from src.unicode_text import CANONICAL_CITATION_RE, SENTENCE_BOUNDARY_RE

_CITATION_RE = CANONICAL_CITATION_RE
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
# Sentence boundary: ., !, ?, Devanagari । and ॥ followed by whitespace.
_SENTENCE_SPLIT_RE = SENTENCE_BOUNDARY_RE


class Claim(BaseModel):
    text: str
    citations: list[int] = Field(default_factory=list)
    section: str = ""


def extract_claims(report: str, valid_max: int) -> list[Claim]:
    """All cited claims in the report body, in document order.

    ``valid_max`` is the number of real sources; markers outside [1..max]
    are ignored (they should already have been stripped upstream).
    """
    body = report.split("## Sources")[0]
    claims: list[Claim] = []
    section = ""
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        heading = _HEADING_RE.match(line)
        if heading:
            section = heading.group(2).strip()
            continue
        # List items are one claim each; prose lines split into sentences.
        if line.startswith(("- ", "* ")) or re.match(r"^\d+\.\s", line):
            pieces = [line.lstrip("-* ").strip()]
        else:
            pieces = _SENTENCE_SPLIT_RE.split(line)
        for piece in pieces:
            piece = piece.strip()
            if not piece:
                continue
            cites = sorted(
                {
                    int(n)
                    for n in _CITATION_RE.findall(piece)
                    if 1 <= int(n) <= valid_max
                }
            )
            if cites:
                claims.append(Claim(text=piece, citations=cites, section=section))
    return claims


def claims_for_source(claims: list[Claim], source_index: int) -> list[Claim]:
    """Every claim a given source number supports."""
    return [c for c in claims if source_index in c.citations]
