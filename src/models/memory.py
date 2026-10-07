"""Project research memory models: compact cited findings from past runs."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from pydantic import BaseModel, Field

from src.models.runs import utcnow


def normalize_finding(text: str) -> str:
    """Deterministic dedupe key for a finding (stable across runs)."""
    import re

    return re.sub(r"[^a-z0-9 ]+", "", " ".join(text.lower().split()))


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
