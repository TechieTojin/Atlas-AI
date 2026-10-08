"""Run lifecycle models: status, mode, metrics, and the persisted run record."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field

from src.models.research import Critique, Evidence, ResearchPlan, Source


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_run_id() -> str:
    return uuid4().hex


class RunStatus(str, Enum):
    PENDING = "PENDING"
    PLANNING = "PLANNING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    RESEARCHING = "RESEARCHING"
    CRITIQUING = "CRITIQUING"
    SYNTHESIZING = "SYNTHESIZING"
    # Cancel requested; the worker is aborting its in-flight request.
    CANCELLING = "CANCELLING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

    @property
    def is_terminal(self) -> bool:
        return self in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED)


class RunMode(str, Enum):
    FAST = "FAST"
    DEEP = "DEEP"


class SourceScope(str, Enum):
    WEB = "WEB"
    DOCUMENTS = "DOCUMENTS"
    WEB_AND_DOCUMENTS = "WEB_AND_DOCUMENTS"

    @property
    def uses_web(self) -> bool:
        return self in (SourceScope.WEB, SourceScope.WEB_AND_DOCUMENTS)

    @property
    def uses_documents(self) -> bool:
        return self in (SourceScope.DOCUMENTS, SourceScope.WEB_AND_DOCUMENTS)


class RunMetrics(BaseModel):
    """Real measured durations and counters for one run."""

    planner_ms: int = 0
    planner_attempts: int = 1
    search_ms: int = 0
    critic_ms: int = 0
    synthesis_ms: int = 0
    citation_repair_ms: int = 0
    total_ms: int = 0
    iterations: int = 0
    search_queries_executed: int = 0
    sources_collected: int = 0
    sources_selected: int = 0
    sources_cited: int = 0
    citation_coverage: float = 0.0
    memory_hits: int = 0
    # Project research memory (findings reused from earlier runs in the
    # same project). Distinct from memory_hits, which counts reused raw
    # web evidence. ``memory_error`` separates a retrieval failure from a
    # genuine "nothing relevant found".
    memory_enabled: bool = False
    memory_scope: str = "NONE"  # PROJECT | NONE
    memory_candidates: int = 0
    project_memory_hits: int = 0
    memory_threshold: float = 0.0
    memory_error: str = ""
    memory_items: list[dict] = Field(default_factory=list)
    document_chunks_retrieved: int = 0
    web_sources_reused: int = 0
    # V3: full-page research and source quality.
    pages_attempted: int = 0
    pages_fetched: int = 0
    pages_failed: int = 0
    snippet_fallbacks: int = 0
    source_quality_tiers: dict = Field(default_factory=dict)
    # LLM performance diagnostics (from Ollama's own per-call statistics).
    llm_calls: int = 0
    llm_prompt_tokens: int = 0
    llm_output_tokens: int = 0
    # False when any call ended without Ollama's statistics (e.g. aborted):
    # the token totals above are then a lower bound, not a genuine count.
    llm_tokens_complete: bool = True
    # Wall time the machine spent asleep/in standby during the run. Budgets
    # and deadlines measure awake time, so this is excluded from them.
    suspended_ms: int = 0
    # FAST budget allocation: critic ran/skipped, reserve and remaining
    # budget estimates (seconds), and the budget synthesis started with.
    budget_decisions: dict = Field(default_factory=dict)
    llm_stage_stats: dict = Field(default_factory=dict)
    llm_call_log: list[dict] = Field(default_factory=list)
    # Performance-budget outcomes.
    budget_seconds: int = 0
    critic_fallback: str = ""
    synthesis_fallback: bool = False
    synthesis_fallback_reason: str = ""
    repair_skipped: bool = False
    critic_scores: list[int] = Field(default_factory=list)
    critic_decisions: list[str] = Field(default_factory=list)
    node_timings: list[dict] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class EvaluationResult(BaseModel):
    """Deterministic post-run quality checks."""

    has_citations: bool = False
    citations_valid: bool = False
    single_sources_section: bool = False
    citation_coverage: float = 0.0
    no_reasoning_markers: bool = False
    provenance_valid: bool = False
    passed: bool = False
    notes: list[str] = Field(default_factory=list)


class ResearchRun(BaseModel):
    """The persisted record of one research run."""

    id: str = Field(default_factory=new_run_id)
    query: str
    title: str = ""
    mode: RunMode = RunMode.DEEP
    source_scope: SourceScope = SourceScope.WEB
    project_id: str = ""
    template: str = "STANDARD"
    custom_template: str = ""
    use_memory: bool = True
    regenerated_from: str = ""
    #: Language the report is written in (``src.languages``). Fixed when the run
    #: is created and inherited by regeneration and follow-ups; never derived
    #: from the UI language. Runs from before this field existed are English.
    output_language: str = "en"
    status: RunStatus = RunStatus.PENDING
    approval_required: bool = False
    created_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime = Field(default_factory=utcnow)
    plan: ResearchPlan | None = None
    executed_queries: list[str] = Field(default_factory=list)
    iterations: int = 0
    critique: Critique | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    selected_sources: list[Source] = Field(default_factory=list)
    final_report: str = ""
    error: str = ""
    document_ids: list[str] = Field(default_factory=list)
    metrics: RunMetrics = Field(default_factory=RunMetrics)
    evaluation: EvaluationResult | None = None


class RunSummary(BaseModel):
    """Lightweight listing row for research history."""

    id: str
    query: str
    title: str = ""
    mode: RunMode
    status: RunStatus
    source_scope: SourceScope
    project_id: str = ""
    template: str = "STANDARD"
    output_language: str = "en"
    created_at: datetime
    completed_at: datetime | None = None
    duration_ms: int = 0
