"""Typed domain models for Atlas research artifacts."""

from __future__ import annotations

from enum import Enum
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

from pydantic import BaseModel, Field

# Query-string parameters that carry tracking noise and never change content.
_TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "gclid",
    "fbclid",
    "ref",
}


def normalize_url(url: str) -> str:
    """Deterministically normalize a URL for deduplication.

    Lowercases scheme/host, drops fragments, strips common tracking
    parameters and trailing slashes. Returns the input stripped if it
    cannot be parsed.
    """
    url = url.strip()
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if not parts.netloc:
        return url
    query_pairs = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in _TRACKING_PARAMS
    ]
    path = parts.path.rstrip("/") or ""
    return urlunsplit(
        (
            parts.scheme.lower() or "https",
            parts.netloc.lower(),
            path,
            urlencode(query_pairs),
            "",  # drop fragment
        )
    )


class SourceQuality(BaseModel):
    """Deterministic, explainable quality assessment of a source.

    This measures *authority/provenance class*, never truth: a high score
    means the publisher class is typically reliable, not that a specific
    claim is correct. Relevance is tracked separately on Evidence.
    """

    category: str = "unknown"
    tier: str = "unknown"  # high | medium | low | unknown
    score: int = Field(default=40, ge=0, le=100)
    signals: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class Source(BaseModel):
    """A single source discovered during research (web page or document).

    Document sources use a synthetic ``doc://{document_id}#p{page}`` URL so
    URL-based deduplication and citation provenance work uniformly; their
    rendering uses filename/page instead of a hyperlink.
    """

    title: str = ""
    url: str
    domain: str = ""
    kind: str = "web"  # "web" | "document"
    document_id: str | None = None
    filename: str | None = None
    page: int | None = None
    quality: SourceQuality | None = None

    @property
    def normalized_url(self) -> str:
        return normalize_url(self.url)


class EvidenceOrigin(str, Enum):
    WEB = "web"
    DOCUMENT = "document"
    MEMORY = "memory"


class Evidence(BaseModel):
    """A piece of evidence text tied to the source and query that found it."""

    source: Source
    content: str
    query: str = ""
    relevance_score: float | None = None
    origin: EvidenceOrigin = EvidenceOrigin.WEB
    # V3: full-page research provenance.
    extraction: str = "snippet"  # snippet | full_page | fallback_snippet
    fetched_at: str = ""  # ISO timestamp when page content was fetched


class ResearchTask(BaseModel):
    """One subquestion in the research plan."""

    subquestion: str = Field(description="A focused subquestion to investigate.")
    evidence_needed: str = Field(
        description="What evidence would satisfactorily answer this subquestion."
    )


class ResearchPlan(BaseModel):
    """Structured plan produced by the planner agent."""

    objective: str = Field(description="Restatement of the research objective.")
    tasks: list[ResearchTask] = Field(
        description="Subquestions covering the important dimensions of the problem."
    )
    search_queries: list[str] = Field(
        description="Initial web search queries, each targeting one task."
    )


class CriticDecision(str, Enum):
    MORE_RESEARCH = "MORE_RESEARCH"
    SYNTHESIZE = "SYNTHESIZE"


class Critique(BaseModel):
    """Structured evaluation of the collected evidence.

    Field order is deliberate: grammar-constrained decoding emits fields in
    schema order, so the written assessment comes BEFORE the score. With
    thinking disabled (FAST), a score-first schema forced the model to commit
    to a number before assessing anything and yielded 0/10 on good evidence.
    """

    coverage_assessment: str = Field(
        description="How well the evidence covers the plan's subquestions."
    )
    missing_information: list[str] = Field(
        default_factory=list,
        description="Specific gaps or unanswered subquestions.",
    )
    overall_score: int = Field(
        ge=0, le=10, description="Overall evidence quality/coverage score, 0-10."
    )
    decision: CriticDecision = Field(
        description="MORE_RESEARCH if important gaps remain, else SYNTHESIZE."
    )
    follow_up_queries: list[str] = Field(
        default_factory=list,
        description="Focused new search queries targeting the gaps (not repeats).",
    )
    reasoning: str = Field(description="Brief justification of the decision.")


class FinalReport(BaseModel):
    """The synthesized answer plus its programmatically-rendered sources."""

    markdown: str
    sources: list[Source] = Field(default_factory=list)
