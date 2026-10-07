"""Project research memory models: compact cited findings from past runs."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from pydantic import BaseModel, Field

from src.models.runs import utcnow


def normalize_finding(text: str) -> str:
    """Deterministic dedupe key for a finding (stable across runs).

    Stored in ``findings.text_norm`` (unique per project), so for ASCII text it
    reproduces the original key exactly: lower-case, whitespace collapsed,
    every character other than letters, digits and spaces removed. Letters,
    combining marks and decimal digits of every script are now kept too; the
    old ``[^a-z0-9 ]`` filter erased Malayalam/Hindi entirely, collapsing
    unrelated findings onto one key. The finding text itself is never modified.

    Normalization is NFC (canonical composition only), not NFKC, and case
    folding stays ``lower()``: both leave every key already stored for Latin
    text unchanged (NFKC would turn "H₂S" into "h2s" where the stored key is
    "hs"). Subscripts and other non-decimal numerals are dropped as before.
    """
    import unicodedata

    collapsed = " ".join(unicodedata.normalize("NFC", text).lower().split())
    return "".join(
        char
        for char in collapsed
        if char == " "
        or (char.isascii() and char.isalnum())
        or (not char.isascii() and unicodedata.category(char) in _KEY_CATEGORIES)
    )


#: Non-ASCII characters a finding key keeps: letters, combining marks, decimal digits.
_KEY_CATEGORIES = frozenset({"Lu", "Ll", "Lt", "Lm", "Lo", "Mn", "Mc", "Me", "Nd"})


class FindingSource(BaseModel):
    """Provenance of a finding: a real source from the originating run."""

    url: str
    title: str = ""


class ProjectFinding(BaseModel):
    """One reusable, cited claim distilled from a completed project run."""

    id: str = Field(default_factory=lambda: uuid4().hex)
    project_id: str
    run_id: str
    question: str = ""
    section: str = ""
    text: str
    sources: list[FindingSource] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)

    @property
    def text_norm(self) -> str:
        return normalize_finding(self.text)


class MemoryHit(BaseModel):
    """A retrieved finding with its relevance score."""

    finding: ProjectFinding
    score: float


class MemoryReport(BaseModel):
    """What project memory did for one run — recorded in metrics.

    ``error`` distinguishes a technical retrieval failure from a genuine
    "nothing relevant was found" (both otherwise look like zero hits).
    """

    enabled: bool = False
    scope: str = "NONE"  # PROJECT | NONE
    candidates: int = 0
    hits: int = 0
    threshold: float = 0.0
    error: str = ""
    items: list[dict] = Field(default_factory=list)
