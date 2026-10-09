"""FastAPI application for Atlas.

Long-running research executes on worker threads via the ResearchService,
so the event loop stays responsive. Expected domain errors map to clean
HTTP responses; unexpected errors return a generic 500 without internal
stack traces or paths.
"""

from __future__ import annotations

import json
import logging
import queue as queue_module

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse

from src.api.container import Container
from src.api.schemas import (
    CreateComparisonRequest,
    CreateFollowUpRequest,
    CreateProjectRequest,
    CreateRunRequest,
    DocumentListResponse,
    EditPlanRequest,
    RegenerateRequest,
    RunDetailResponse,
    RunListResponse,
    UpdateProjectRequest,
    CreateWebsiteConversationRequest,
    CreateWebsiteRequest,
    WebsiteQuestionRequest,
)
from src.website.errors import WebsiteError
from src.config import ConfigError
from src.languages import UnknownLanguageError
from src.model_capabilities import UnsupportedOutputLanguageError
from src.events.bus import STREAM_END
from src.persistence.db import PersistenceError
from src.rag.service import UploadError
from src.services.comparison_service import ComparisonError
from src.services.followup_service import FollowUpError
from src.services.kg_service import KGError
from src.services.research_service import (
    InvalidRunStateError,
    PlanValidationError,
    RunNotFoundError,
)
from src.templates import TemplateError, list_templates

logger = logging.getLogger(__name__)

API_VERSION = "2.0"


def create_app(container: Container | None = None) -> FastAPI:
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(app_: FastAPI):
        app_.state.container = container if container is not None else Container()
        logger.info("Atlas API started (db: %s).", app_.state.container.db.path)
        # Runs whose worker died with a previous server process would
        # otherwise show "Planning…" forever.
        app_.state.container.research_service.recover_interrupted_runs()
        app_.state.container.comparison_service.recover_interrupted_comparisons()
        app_.state.container.website_chat_service.recover_interrupted()
        # Makes research completed before project memory existed reusable.
        app_.state.container.research_service.backfill_project_memory()
        yield

    app = FastAPI(
        title="Atlas Research API",
        version=API_VERSION,
        description="Multi-agent research & knowledge engine.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def ctn(request: Request) -> Container:
        return request.app.state.container

    # -- error handling ------------------------------------------------------

    @app.exception_handler(RunNotFoundError)
    def run_not_found(request, exc):
        return JSONResponse(status_code=404, content={"detail": "Run not found."})

    @app.exception_handler(InvalidRunStateError)
    def invalid_state(request, exc):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(PlanValidationError)
    def plan_invalid(request, exc):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(UploadError)
    def upload_error(request, exc):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(TemplateError)
    def template_error(request, exc):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    def _domain_404_or_422(exc):
        message = str(exc)
        status = 404 if "not found" in message.lower() else 422
        return JSONResponse(status_code=status, content={"detail": message})

    @app.exception_handler(FollowUpError)
    def followup_error(request, exc):
        message = str(exc)
        if "already finished" in message or "requires a completed" in message:
            return JSONResponse(status_code=409, content={"detail": message})
        return _domain_404_or_422(exc)

    @app.exception_handler(ComparisonError)
    def comparison_error(request, exc):
        return _domain_404_or_422(exc)

    @app.exception_handler(KGError)
    def kg_error(request, exc):
        message = str(exc)
        if "already running" in message:
            return JSONResponse(status_code=409, content={"detail": message})
        return _domain_404_or_422(exc)

    @app.exception_handler(WebsiteError)
    def website_error(request, exc):
        # A stable code the UI translates, plus plain English for API clients.
        return JSONResponse(
            status_code=exc.http_status, content={"detail": exc.message, "code": exc.code}
        )

    @app.exception_handler(UnknownLanguageError)
    def unknown_language(request, exc):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(UnsupportedOutputLanguageError)
    def unsupported_language(request, exc):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(PersistenceError)
    def persistence_error(request, exc):
        logger.error("Persistence error: %s", exc)
        return JSONResponse(
            status_code=503, content={"detail": "Storage is unavailable."}
        )

    @app.exception_handler(ConfigError)
    def config_error(request, exc):
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @app.exception_handler(Exception)
    def unexpected(request, exc):
        logger.exception("Unhandled API error.")
        return JSONResponse(
            status_code=500, content={"detail": "Internal server error."}
        )

    # -- health --------------------------------------------------------------

    @app.get("/api/health")
    def health(request: Request):
        c = ctn(request)
        return {
            "status": "ok",
            "version": API_VERSION,
            "model": c.config.model,
            "database": "ok",
        }

    # -- runs ------------------------------------------------------------------

    @app.post("/api/runs", response_model=RunDetailResponse, status_code=201)
    def create_run(request: Request, body: CreateRunRequest):
        run = ctn(request).research_service.create_run(
            query=body.query,
            mode=body.mode,
            source_scope=body.source_scope,
            document_ids=body.document_ids,
            approval_required=body.approval_required,
            project_id=body.project_id,
            template=body.template,
            custom_template=body.custom_template,
            use_memory=body.use_memory,
            output_language=body.output_language,
        )
        return RunDetailResponse.from_run(run)

    @app.get("/api/runs", response_model=RunListResponse)
    def list_runs(
        request: Request,
        limit: int = 20,
        offset: int = 0,
        search: str = "",
        project_id: str | None = None,
    ):
        limit = max(1, min(limit, 100))
        offset = max(0, offset)
        runs, total = ctn(request).runs_repo.list(
            limit=limit, offset=offset, search=search, project_id=project_id
        )
        return RunListResponse(runs=runs, total=total, limit=limit, offset=offset)

    @app.get("/api/capabilities/languages")
    def language_capabilities(request: Request):
        """Which output languages the configured models can write. Pure config."""
        return ctn(request).languages.describe()

    @app.get("/api/templates")
    def templates(request: Request):
        return {"templates": list_templates()}

    @app.post(
        "/api/runs/{run_id}/regenerate",
        response_model=RunDetailResponse,
        status_code=201,
    )
    def regenerate(request: Request, run_id: str, body: RegenerateRequest):
        run = ctn(request).research_service.regenerate_report(
            run_id, body.template, body.custom_template
        )
        return RunDetailResponse.from_run(run)

    @app.get("/api/runs/{run_id}/claims")
    def run_claims(request: Request, run_id: str):
        from src.evaluation.claims import extract_claims

        run = ctn(request).research_service.get_run(run_id)
        claims = extract_claims(run.final_report, len(run.selected_sources))
        return {"claims": [c.model_dump() for c in claims]}

    @app.get("/api/runs/{run_id}", response_model=RunDetailResponse)
    def get_run(request: Request, run_id: str):
        return RunDetailResponse.from_run(ctn(request).research_service.get_run(run_id))

    @app.delete("/api/runs/{run_id}", status_code=204)
    def delete_run(request: Request, run_id: str):
        if not ctn(request).runs_repo.delete(run_id):
            raise RunNotFoundError(run_id)

    @app.post("/api/runs/{run_id}/plan/approve", response_model=RunDetailResponse)
    def approve_plan(request: Request, run_id: str):
        return RunDetailResponse.from_run(
            ctn(request).research_service.approve_plan(run_id)
        )

    @app.post("/api/runs/{run_id}/plan/edit", response_model=RunDetailResponse)
    def edit_plan(request: Request, run_id: str, body: EditPlanRequest):
        return RunDetailResponse.from_run(
            ctn(request).research_service.edit_plan(
                run_id,
                subquestions=body.subquestions,
                search_queries=body.search_queries,
                objective=body.objective,
            )
        )

    @app.post("/api/runs/{run_id}/cancel", response_model=RunDetailResponse)
    def cancel_run(request: Request, run_id: str):
        return RunDetailResponse.from_run(ctn(request).research_service.cancel(run_id))

    @app.get("/api/runs/{run_id}/metrics")
    def run_metrics(request: Request, run_id: str):
        run = ctn(request).research_service.get_run(run_id)
        return {
            "metrics": run.metrics.model_dump(),
            "evaluation": run.evaluation.model_dump() if run.evaluation else None,
        }

    @app.get("/api/runs/{run_id}/export")
    def export_run(request: Request, run_id: str, format: str = "markdown"):
        c = ctn(request)
        if format == "markdown":
            markdown = c.research_service.export_markdown(run_id)
            return PlainTextResponse(
                markdown,
                media_type="text/markdown; charset=utf-8",
                headers={
                    "Content-Disposition": f'attachment; filename="atlas-{run_id[:8]}.md"'
                },
            )
        if format == "pdf":
            from fastapi.responses import Response

            from src.export.pdf import pdf_content_disposition, render_run_pdf
            from src.models.runs import RunStatus

            run = c.research_service.get_run(run_id)
            if run.status is not RunStatus.COMPLETED or not run.final_report:
                raise InvalidRunStateError("Only completed runs can be exported.")
            pdf_bytes = render_run_pdf(run, font_path=c.config.pdf_font_path)
            return Response(
                content=pdf_bytes,
                media_type="application/pdf",
                headers={"Content-Disposition": pdf_content_disposition(run)},
            )
        raise HTTPException(
            status_code=400, detail="Supported export formats: markdown, pdf."
        )

    # -- streaming (SSE) ---------------------------------------------------------

    def _sse_stream(c: Container, key: str) -> StreamingResponse:
        """SSE stream for any event key (runs, follow-ups, comparisons, KG)."""

        def sse(event) -> str:
            return (
                f"event: {event.type.value}\n"
                f"data: {json.dumps(event.model_dump(mode='json'))}\n\n"
            )

        def generate():
            history, live = c.bus.subscribe(key)
            if not history:
                # Process restarted: replay the durable event log instead.
                history = c.events_repo.list(key)
            try:
                terminal_seen = False
                for event in history:
                    terminal_seen = terminal_seen or event.type.is_terminal
                    yield sse(event)
                if live is None or terminal_seen:
                    return
                while True:
                    try:
                        event = live.get(timeout=30)
                    except queue_module.Empty:
                        yield ": keep-alive\n\n"
                        continue
                    if event is STREAM_END:
                        return
                    yield sse(event)
                    if event.type.is_terminal:
                        return
            finally:
                if live is not None:
                    c.bus.unsubscribe(key, live)

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/runs/{run_id}/events")
    def stream_events(request: Request, run_id: str):
        c = ctn(request)
        c.research_service.get_run(run_id)  # 404 if unknown
        return _sse_stream(c, run_id)

    # -- projects -----------------------------------------------------------

    @app.post("/api/projects", status_code=201)
    def create_project(request: Request, body: CreateProjectRequest):
        from src.models.workspace import Project

        project = Project(name=body.name.strip(), description=body.description.strip())
        ctn(request).projects_repo.save(project)
        return project.model_dump(mode="json")

    @app.get("/api/projects")
    def list_projects(request: Request):
        c = ctn(request)
        projects = []
        for project in c.projects_repo.list():
            payload = project.model_dump(mode="json")
            payload["counts"] = c.projects_repo.counts(project.id)
            projects.append(payload)
        return {"projects": projects}

    def _get_project(c: Container, project_id: str):
        project = c.projects_repo.get(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found.")
        return project

    @app.get("/api/projects/{project_id}")
    def get_project(request: Request, project_id: str):
        c = ctn(request)
        project = _get_project(c, project_id)
        payload = project.model_dump(mode="json")
        payload["counts"] = c.projects_repo.counts(project_id)
        return payload

    @app.patch("/api/projects/{project_id}")
    def update_project(request: Request, project_id: str, body: UpdateProjectRequest):
        from src.models.runs import utcnow

        c = ctn(request)
        project = _get_project(c, project_id)
        if body.name is not None:
            project.name = body.name.strip()
        if body.description is not None:
            project.description = body.description.strip()
        project.updated_at = utcnow()
        c.projects_repo.save(project)
        return project.model_dump(mode="json")

    @app.delete("/api/projects/{project_id}", status_code=204)
    def delete_project(request: Request, project_id: str):
        # Non-destructive: runs/documents/comparisons are detached, not deleted.
        if not ctn(request).projects_repo.delete(project_id):
            raise HTTPException(status_code=404, detail="Project not found.")

    @app.put("/api/projects/{project_id}/documents/{document_id}", status_code=204)
    def add_document_to_project(request: Request, project_id: str, document_id: str):
        c = ctn(request)
        _get_project(c, project_id)
        if not c.documents_repo.set_project(document_id, project_id):
            raise HTTPException(status_code=404, detail="Document not found.")

    @app.delete("/api/projects/{project_id}/documents/{document_id}", status_code=204)
    def remove_document_from_project(request: Request, project_id: str, document_id: str):
        c = ctn(request)
        _get_project(c, project_id)
        if not c.documents_repo.set_project(document_id, ""):
            raise HTTPException(status_code=404, detail="Document not found.")

    @app.get("/api/projects/{project_id}/overview")
    def project_overview(request: Request, project_id: str):
        """Research-intelligence view model, built from persisted data only."""
        overview = ctn(request).overview_service.build(project_id)
        if overview is None:
            raise HTTPException(status_code=404, detail="Project not found.")
        return overview

    @app.get("/api/projects/{project_id}/knowledge-graph")
    def project_knowledge_graph(request: Request, project_id: str):
        """What the project knows, derived from its stored findings.

        This is not the per-run graph: it is built deterministically from
        ``project_findings`` on request, so it needs no LLM, no web access and no
        generation step. The run-level graph endpoints below are unchanged.
        """
        graph = ctn(request).project_graph_service.build(project_id)
        if graph is None:
            raise HTTPException(status_code=404, detail="Project not found.")
        return graph

    # -- follow-ups -----------------------------------------------------------

    @app.post("/api/runs/{run_id}/followups", status_code=201)
    def create_followup(request: Request, run_id: str, body: CreateFollowUpRequest):
        followup = ctn(request).followup_service.create(
            run_id, body.question, body.mode
        )
        return followup.model_dump(mode="json")

    @app.get("/api/runs/{run_id}/followups")
    def list_followups(request: Request, run_id: str):
        c = ctn(request)
        c.research_service.get_run(run_id)
        return {
            "followups": [
                f.model_dump(mode="json")
                for f in c.followup_service.list_for_run(run_id)
            ]
        }

    @app.get("/api/followups/{followup_id}")
    def get_followup(request: Request, followup_id: str):
        return ctn(request).followup_service.get(followup_id).model_dump(mode="json")

    @app.post("/api/followups/{followup_id}/cancel")
    def cancel_followup(request: Request, followup_id: str):
        return ctn(request).followup_service.cancel(followup_id).model_dump(mode="json")

    @app.get("/api/followups/{followup_id}/events")
    def followup_events(request: Request, followup_id: str):
        c = ctn(request)
        c.followup_service.get(followup_id)
        return _sse_stream(c, followup_id)

    # -- comparisons ------------------------------------------------------------

    @app.post("/api/comparisons", status_code=201)
    def create_comparison(request: Request, body: CreateComparisonRequest):
        comparison = ctn(request).comparison_service.create(
            body.run_ids, body.project_id, body.output_language
        )
        return comparison.model_dump(mode="json")

    @app.get("/api/comparisons")
    def list_comparisons(request: Request, project_id: str | None = None):
        return {
            "comparisons": [
                c.model_dump(mode="json")
                for c in ctn(request).comparison_service.list(project_id)
            ]
        }

    @app.get("/api/comparisons/{comparison_id}")
    def get_comparison(request: Request, comparison_id: str):
        return ctn(request).comparison_service.get(comparison_id).model_dump(mode="json")

    @app.post("/api/comparisons/{comparison_id}/cancel")
    def cancel_comparison(request: Request, comparison_id: str):
        """Stop a running comparison, aborting its in-flight model request."""
        comparison = ctn(request).comparison_service.cancel(comparison_id)
        return comparison.model_dump(mode="json")

    @app.delete("/api/comparisons/{comparison_id}", status_code=204)
    def delete_comparison(request: Request, comparison_id: str):
        if not ctn(request).comparison_service.delete(comparison_id):
            raise HTTPException(status_code=404, detail="Comparison not found.")

    @app.get("/api/comparisons/{comparison_id}/claims")
    def comparison_claims(request: Request, comparison_id: str):
        from src.evaluation.claims import extract_claims

        comparison = ctn(request).comparison_service.get(comparison_id)
        claims = extract_claims(comparison.report, len(comparison.sources))
        return {"claims": [c.model_dump() for c in claims]}

    @app.get("/api/comparisons/{comparison_id}/export")
    def export_comparison(request: Request, comparison_id: str):
        comparison = ctn(request).comparison_service.get(comparison_id)
        if not comparison.report:
            raise HTTPException(status_code=409, detail="Comparison not completed.")
        header = (
            f"# Atlas Research Comparison\n\n"
            f"**Runs:** {', '.join(comparison.run_queries)}\n\n---\n\n"
        )
        return PlainTextResponse(
            header + comparison.report,
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="atlas-comparison-{comparison_id[:8]}.md"'
            },
        )

    @app.get("/api/comparisons/{comparison_id}/events")
    def comparison_events(request: Request, comparison_id: str):
        c = ctn(request)
        c.comparison_service.get(comparison_id)
        return _sse_stream(c, comparison_id)

    # -- knowledge graph ---------------------------------------------------------

    @app.post("/api/runs/{run_id}/knowledge-graph", status_code=202)
    def generate_knowledge_graph(request: Request, run_id: str):
        ctn(request).kg_service.generate(run_id)
        return {"status": "RUNNING"}

    @app.get("/api/runs/{run_id}/knowledge-graph")
    def get_knowledge_graph(request: Request, run_id: str):
        c = ctn(request)
        c.research_service.get_run(run_id)
        return c.kg_service.get(run_id).model_dump(mode="json")

    @app.get("/api/runs/{run_id}/knowledge-graph/events")
    def knowledge_graph_events(request: Request, run_id: str):
        c = ctn(request)
        c.research_service.get_run(run_id)
        return _sse_stream(c, f"kg-{run_id}")

    # -- website chat -----------------------------------------------------------

    def _website_json(site):
        data = site.model_dump(mode="json")
        data["is_indexed"] = site.is_indexed
        return data

    @app.post("/api/websites")
    def create_website(request: Request, body: CreateWebsiteRequest):
        site, created = ctn(request).website_chat_service.submit(body.url)
        return JSONResponse(
            status_code=201 if created else 200,
            content={**_website_json(site), "existing": not created},
        )

    @app.get("/api/websites")
    def list_websites(request: Request):
        return {"websites": [_website_json(w) for w in ctn(request).website_chat_service.list()]}

    @app.get("/api/websites/{website_id}")
    def get_website(request: Request, website_id: str):
        return _website_json(ctn(request).website_chat_service.get(website_id))

    @app.post("/api/websites/{website_id}/refresh")
    def refresh_website(request: Request, website_id: str):
        return _website_json(ctn(request).website_chat_service.refresh(website_id))

    @app.post("/api/websites/{website_id}/cancel")
    def cancel_website(request: Request, website_id: str):
        return _website_json(ctn(request).website_chat_service.cancel(website_id))

    @app.delete("/api/websites/{website_id}", status_code=204)
    def delete_website(request: Request, website_id: str):
        ctn(request).website_chat_service.delete(website_id)

    @app.get("/api/websites/{website_id}/conversations")
    def list_website_conversations(request: Request, website_id: str):
        conversations = ctn(request).website_chat_service.list_conversations(website_id)
        return {"conversations": [c.model_dump(mode="json") for c in conversations]}

    @app.post("/api/websites/{website_id}/conversations", status_code=201)
    def create_website_conversation(
        request: Request, website_id: str, body: CreateWebsiteConversationRequest
    ):
        conversation = ctn(request).website_chat_service.create_conversation(
            website_id, body.output_language
        )
        return {"conversation": conversation.model_dump(mode="json"), "messages": []}

    @app.get("/api/website-conversations/{conversation_id}")
    def get_website_conversation(request: Request, conversation_id: str):
        conversation, messages = ctn(request).website_chat_service.get_conversation(conversation_id)
        return {
            "conversation": conversation.model_dump(mode="json"),
            "messages": [m.model_dump(mode="json") for m in messages],
        }

    @app.delete("/api/website-conversations/{conversation_id}", status_code=204)
    def delete_website_conversation(request: Request, conversation_id: str):
        ctn(request).website_chat_service.delete_conversation(conversation_id)

    @app.post("/api/website-conversations/{conversation_id}/messages", status_code=202)
    def ask_website(request: Request, conversation_id: str, body: WebsiteQuestionRequest):
        user, answer = ctn(request).website_chat_service.ask(conversation_id, body.question)
        return {"user": user.model_dump(mode="json"), "answer": answer.model_dump(mode="json")}

    @app.post("/api/website-messages/{message_id}/cancel")
    def cancel_website_message(request: Request, message_id: str):
        return ctn(request).website_chat_service.cancel_message(message_id).model_dump(mode="json")

    # -- documents ------------------------------------------------------------

    @app.post("/api/documents", status_code=201)
    async def upload_document(
        request: Request, file: UploadFile = File(...), project_id: str = ""
    ):
        data = await file.read()
        c = ctn(request)
        if project_id:
            _get_project(c, project_id)
        import anyio

        doc = await anyio.to_thread.run_sync(
            lambda: c.document_service.ingest(
                file.filename or "document", data, file.content_type or ""
            )
        )
        if project_id:
            c.documents_repo.set_project(doc.id, project_id)
            doc = c.documents_repo.get(doc.id) or doc
        return doc.model_dump(mode="json")

    @app.get("/api/documents", response_model=DocumentListResponse)
    def list_documents(request: Request, project_id: str | None = None):
        return DocumentListResponse(
            documents=ctn(request).documents_repo.list(project_id)
        )

    @app.get("/api/documents/{document_id}")
    def get_document(request: Request, document_id: str):
        doc = ctn(request).documents_repo.get(document_id)
        if doc is None:
            raise HTTPException(status_code=404, detail="Document not found.")
        return doc.model_dump(mode="json")

    @app.delete("/api/documents/{document_id}", status_code=204)
    def delete_document(request: Request, document_id: str):
        c = ctn(request)
        if not c.document_service.delete(document_id):
            raise HTTPException(status_code=404, detail="Document not found.")
        c.memory_repo.delete_document_evidence(document_id)

    return app
