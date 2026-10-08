"""V3 entities: projects, follow-up threads, comparisons, knowledge graph."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field

from src.models.research import Source
from src.models.runs import utcnow


def new_id() -> str:
    return uuid4().hex


class Project(BaseModel):
    """A persistent research workspace grouping runs, documents, and memory."""

    id: str = Field(default_factory=new_id)
    name: str
    description: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class FollowUpKind(str, Enum):
    ANALYTICAL = "ANALYTICAL"  # answered from existing run evidence
    RESEARCH = "RESEARCH"  # may retrieve new web/document evidence


class FollowUpStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

    @property
    def is_terminal(self) -> bool:
        return self in (
            FollowUpStatus.COMPLETED,
            FollowUpStatus.FAILED,
            FollowUpStatus.CANCELLED,
        )


class FollowUp(BaseModel):
    """One follow-up question/answer on a completed research run.

    ``sources`` is the numbered source list for THIS answer: parent-run
    sources keep their original numbers [1..k]; newly retrieved sources
    continue [k+1..], so citations are never ambiguous.
    """

    id: str = Field(default_factory=new_id)
    run_id: str
    project_id: str = ""
    question: str
    kind: FollowUpKind = FollowUpKind.ANALYTICAL
    status: FollowUpStatus = FollowUpStatus.PENDING
    answer: str = ""
    sources: list[Source] = Field(default_factory=list)
    parent_source_count: int = 0  # sources[:n] are inherited from the run
    new_source_count: int = 0
    cited: list[int] = Field(default_factory=list)
    searched: bool = False
    #: The parent run's output language, fixed at creation. The question stays
    #: exactly as the user typed it; only the answer is written in this language.
    output_language: str = "en"
    error: str = ""
    duration_ms: int = 0
    created_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    #: The validated structured synthesis the report was rendered from. Empty
    #: for comparisons written before Synthesis V2, which keep their own report.
    synthesis: dict = Field(default_factory=dict)
    #: Execution metrics (model, phase, LLM calls, token counts, outcome).
    #: Token counts are ``None`` when Ollama never reported them, which is
    #: what happens when a request is aborted; they are never faked as 0.
    metrics: dict = Field(default_factory=dict)


class ComparisonStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    CANCELLING = "CANCELLING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"

    @property
    def is_terminal(self) -> bool:
        return self in (
            ComparisonStatus.COMPLETED,
            ComparisonStatus.FAILED,
            ComparisonStatus.CANCELLED,
            ComparisonStatus.TIMED_OUT,
        )

    @property
    def is_active(self) -> bool:
        """True while a worker may still be running for this comparison."""
        return not self.is_terminal


class ComparisonSource(BaseModel):
    """A deduplicated source in a comparison, tagged with its origin runs."""

    source: Source
    run_ids: list[str] = Field(default_factory=list)


class Comparison(BaseModel):
    """A persisted, cited comparison of two or more completed runs."""

    id: str = Field(default_factory=new_id)
    project_id: str = ""
    run_ids: list[str]
    run_queries: list[str] = Field(default_factory=list)
    title: str = ""
    #: Fixed at creation; never follows the UI language. Older comparisons are English.
    output_language: str = "en"
    status: ComparisonStatus = ComparisonStatus.PENDING
    report: str = ""
    sources: list[ComparisonSource] = Field(default_factory=list)
    overlap_stats: dict = Field(default_factory=dict)
    error: str = ""
    duration_ms: int = 0
    created_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    #: The validated structured synthesis the report was rendered from. Empty
    #: for comparisons written before Synthesis V2, which keep their own report.
    synthesis: dict = Field(default_factory=dict)
    #: Execution metrics (model, phase, LLM calls, token counts, outcome).
    #: Token counts are ``None`` when Ollama never reported them, which is
    #: what happens when a request is aborted; they are never faked as 0.
    metrics: dict = Field(default_factory=dict)


KG_NODE_TYPES = (
    "concept",
    "technology",
    "organization",
    "person",
    "location",
    "regulation",
    "standard",
    "material",
    "method",
    "risk",
    "finding",
)

KG_EDGE_TYPES = (
    "causes",
    "contributes_to",
    "mitigates",
    "regulates",
    "uses",
    "supports",
    "contradicts",
    "associated_with",
    "part_of",
)


class KGSupport(BaseModel):
    """Provenance for one edge: the real source that supports it."""

    source_url: str
    source_title: str = ""


class KGNode(BaseModel):
    id: str = Field(default_factory=new_id)
    run_id: str
    name: str
    norm_name: str
    type: str = "concept"
    description: str = ""


class KGEdge(BaseModel):
    id: str = Field(default_factory=new_id)
    run_id: str
    source_node_id: str
    target_node_id: str
    relation: str = "associated_with"
    support: list[KGSupport] = Field(default_factory=list)


class KnowledgeGraph(BaseModel):
    nodes: list[KGNode] = Field(default_factory=list)
    edges: list[KGEdge] = Field(default_factory=list)
    status: str = "NONE"  # NONE | RUNNING | READY | FAILED
    error: str = ""
