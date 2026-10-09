"""Request/response schemas for the Atlas API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from src.models.documents import DocumentRecord
from src.models.runs import (
    EvaluationResult,
    ResearchRun,
    RunMetrics,
    RunMode,
    RunStatus,
    RunSummary,
    SourceScope,
)


class CreateRunRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    mode: RunMode = RunMode.DEEP
    source_scope: SourceScope = SourceScope.WEB
    document_ids: list[str] = Field(default_factory=list)
    approval_required: bool = False
    project_id: str = ""
    template: str = "STANDARD"
    custom_template: str = Field(default="", max_length=4000)
    use_memory: bool = True
    #: Canonical output-language code; omitted by older clients, meaning English.
    output_language: str | None = None


class RegenerateRequest(BaseModel):
    template: str
    custom_template: str = Field(default="", max_length=4000)


class CreateProjectRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)


class UpdateProjectRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)


class CreateWebsiteRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


class CreateWebsiteConversationRequest(BaseModel):
    #: Resolved, supported output language; omitted means English.
    output_language: str | None = None


class WebsiteQuestionRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class CreateFollowUpRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    mode: str = "auto"  # auto | analytical | research


class CreateComparisonRequest(BaseModel):
    run_ids: list[str] = Field(min_length=2, max_length=5)
    project_id: str = ""
    #: Canonical output-language code; omitted by older clients, meaning English.
    output_language: str | None = None


class EditPlanRequest(BaseModel):
    objective: str | None = None
    subquestions: list[str] | None = None
    search_queries: list[str] | None = None


class RunListResponse(BaseModel):
    runs: list[RunSummary]
    total: int
    limit: int
    offset: int


class PlanResponse(BaseModel):
    objective: str = ""
    subquestions: list[str] = Field(default_factory=list)
    search_queries: list[str] = Field(default_factory=list)


class QualityResponse(BaseModel):
    category: str
    tier: str
    score: int
    signals: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class SourceResponse(BaseModel):
    index: int
    title: str
    url: str
    domain: str
    kind: str
    filename: str | None = None
    page: int | None = None
    quality: QualityResponse | None = None


class EvidenceResponse(BaseModel):
    content: str
    query: str
    origin: str
    source_title: str
    source_url: str
    source_kind: str
    filename: str | None = None
    page: int | None = None
    relevance_score: float | None = None
    extraction: str = "snippet"
    fetched_at: str = ""
    quality_tier: str | None = None


class RunDetailResponse(BaseModel):
    id: str
    query: str
    title: str
    mode: RunMode
    status: RunStatus
    source_scope: SourceScope
    approval_required: bool
    project_id: str = ""
    template: str = "STANDARD"
    custom_template: str = ""
    use_memory: bool = True
    regenerated_from: str = ""
    output_language: str = "en"
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    iterations: int
    executed_queries: list[str]
    plan: PlanResponse | None
    sources: list[SourceResponse]
    evidence: list[EvidenceResponse]
    final_report: str
    error: str
    document_ids: list[str]
    metrics: RunMetrics
    evaluation: EvaluationResult | None

    @classmethod
    def from_run(cls, run: ResearchRun) -> "RunDetailResponse":
        plan = None
        if run.plan is not None:
            plan = PlanResponse(
                objective=run.plan.objective,
                subquestions=[t.subquestion for t in run.plan.tasks],
                search_queries=list(run.plan.search_queries),
            )
        sources = [
            SourceResponse(
                index=i,
                title=s.title,
                url=s.url,
                domain=s.domain,
                kind=s.kind,
                filename=s.filename,
                page=s.page,
                quality=(
                    QualityResponse(**s.quality.model_dump()) if s.quality else None
                ),
            )
            for i, s in enumerate(run.selected_sources, 1)
        ]
        evidence = [
            EvidenceResponse(
                content=e.content,
                query=e.query,
                origin=e.origin.value,
                source_title=e.source.title,
                source_url=e.source.url,
                source_kind=e.source.kind,
                filename=e.source.filename,
                page=e.source.page,
                relevance_score=e.relevance_score,
                extraction=e.extraction,
                fetched_at=e.fetched_at,
                quality_tier=e.source.quality.tier if e.source.quality else None,
            )
            for e in run.evidence
        ]
        return cls(
            id=run.id,
            query=run.query,
            title=run.title,
            mode=run.mode,
            status=run.status,
            source_scope=run.source_scope,
            approval_required=run.approval_required,
            project_id=run.project_id,
            template=run.template,
            custom_template=run.custom_template,
            use_memory=run.use_memory,
            regenerated_from=run.regenerated_from,
            output_language=run.output_language,
            created_at=run.created_at,
            started_at=run.started_at,
            completed_at=run.completed_at,
            iterations=run.iterations,
            executed_queries=run.executed_queries,
            plan=plan,
            sources=sources,
            evidence=evidence,
            final_report=run.final_report,
            error=run.error,
            document_ids=run.document_ids,
            metrics=run.metrics,
            evaluation=run.evaluation,
        )


class DocumentListResponse(BaseModel):
    documents: list[DocumentRecord]


class ErrorResponse(BaseModel):
    detail: str
