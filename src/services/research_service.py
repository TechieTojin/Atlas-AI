"""Research run orchestration.

Owns the run lifecycle: persistence, background execution on a worker pool
(so the API event loop never blocks on local LLM work), typed progress
events, human-in-the-loop plan approval (a persisted pause — the worker
thread ends at AWAITING_APPROVAL and a fresh one resumes the research-entry
graph after approval), cooperative cancellation, metrics, evaluation, and
export.
"""

from __future__ import annotations

import dataclasses
import logging
import threading
import time
from concurrent.futures import Executor, ThreadPoolExecutor

from src.agents.planner import PlannerAgent, PlanningError
from src.cancellation import CancelScope, awake_clock
from src.llm import AbortableLLM, LLMCallSink, stage_limits
from src.config import AtlasConfig
from src.events import EventType, RunEmitter, RunEventBus
from src.evaluation import evaluate_report
from src.graph.workflow import (
    RunCancelledError,
    build_workflow,
    initial_state,
    recursion_limit,
)
from src.memory.service import MemoryService
from src.models.research import ResearchPlan, ResearchTask
from src.models.runs import (
    ResearchRun,
    RunMetrics,
    RunMode,
    RunStatus,
    SourceScope,
    utcnow,
)
from src.languages import language_instruction, parse_output_language
from src.model_capabilities import LanguageRouter
from src.modes import apply_mode
from src.persistence import EventsRepository, RunsRepository
from src.rag.service import DocumentService
from src.tools.search import create_tavily_search
from src.tools.selection import select_evidence, select_synthesis_evidence
from src.agents.synthesizer import build_numbered_sources

logger = logging.getLogger(__name__)

_STATUS_BY_EVENT = {
    EventType.PLANNING_STARTED: RunStatus.PLANNING,
    EventType.SEARCH_STARTED: RunStatus.RESEARCHING,
    EventType.CRITIC_STARTED: RunStatus.CRITIQUING,
    EventType.SYNTHESIS_STARTED: RunStatus.SYNTHESIZING,
}


class RunNotFoundError(Exception):
    pass


class InvalidRunStateError(Exception):
    pass


class PlanValidationError(Exception):
    pass


def _memory_block_from_report(report) -> str:
    """Rebuild the memory block from a persisted MemoryReport (no new call)."""
    from src.memory.project_memory import format_memory_block
    from src.models.memory import MemoryHit, ProjectFinding

    return format_memory_block([
        MemoryHit(
            finding=ProjectFinding(
                project_id="",
                run_id=item.get("run_id", ""),
                question=item.get("question", ""),
                text=item["text"],
            ),
            score=item.get("score", 0.0),
        )
        for item in report.items
    ])


class ResearchService:
    def __init__(
        self,
        config: AtlasConfig,
        runs: RunsRepository,
        events: EventsRepository,
        bus: RunEventBus,
        memory: MemoryService | None = None,
        project_memory=None,
        documents: DocumentService | None = None,
        llm_factory=None,
        search_factory=None,
        executor: Executor | None = None,
        projects=None,
        page_fetcher_factory=None,
        languages: LanguageRouter | None = None,
    ) -> None:
        self._config = config
        self._languages = languages or LanguageRouter(config)
        self._runs = runs
        self._events = events
        self._bus = bus
        self._memory = memory
        self._project_memory = project_memory
        self._documents = documents
        self._projects = projects
        self._page_fetcher_factory = page_fetcher_factory or self._default_fetcher
        self._llm_factory = llm_factory or self._default_llm_factory
        self._search_factory = search_factory or (
            lambda cfg: create_tavily_search(cfg.tavily_api_key)
        )
        self._executor = executor or ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="atlas-run"
        )
        self._scopes: dict[str, CancelScope] = {}
        # Run ids with a live worker thread. A cancel for any other active
        # run (queued, awaiting approval, orphaned by a restart) completes
        # immediately because nothing is executing it.
        self._active_workers: set[str] = set()
        # Serializes status transitions (cancel vs. finish vs. events).
        self._state_lock = threading.RLock()
        self._call_sinks: dict[str, LLMCallSink] = {}
        # Absolute awake-clock deadline of each run's time budget (FAST); every
        # stage request is bounded by min(stage limit, time left in budget).
        self._run_deadlines: dict[str, float] = {}
        self._budgets: dict = {}  # run_id -> RunBudget (FAST allocation)
        self._memory_reports: dict = {}  # run_id -> MemoryReport
        # Awake-clock time each run started, to report time spent suspended.
        self._awake_started: dict[str, float] = {}
        self._bus.add_listener(self._on_event)

    @staticmethod
    def _default_llm_factory(
        config: AtlasConfig, *, reasoning: bool, stage: str = "default", call_sink=None
    ):
        from src.llm import create_llm

        return create_llm(config, reasoning=reasoning, stage=stage, call_sink=call_sink)

    def _stage_llm(
        self,
        config: AtlasConfig,
        stage: str,
        reasoning: bool,
        sink,
        run_id: str = "",
        run_deadline=None,
    ):
        """Stage model handle with a hard deadline and run cancellation.

        A fresh model/connection is built per request, so aborting one request
        (timeout or cancel) closes only that request's connection.
        """
        from src.llm import make_llm

        def build():
            return make_llm(
                self._llm_factory, config, reasoning=reasoning, stage=stage, call_sink=sink
            )

        return AbortableLLM(
            build,
            timeout=stage_limits(config, stage)[1],
            scope=self._scope_for(run_id) if run_id else None,
            label=stage,
            run_deadline=run_deadline
            or ((lambda: self._run_deadlines.get(run_id)) if run_id else None),
            sink=sink,
        )

    @staticmethod
    def _default_fetcher(config: AtlasConfig):
        if config.page_fetch_per_query <= 0:
            return None
        from src.tools.webpage import SafePageFetcher

        return SafePageFetcher(
            timeout=config.page_timeout_seconds, max_bytes=config.page_max_bytes
        )

    # -- event listener: durable events + live status transitions ----------

    def _on_event(self, event) -> None:
        try:
            self._events.append(event)
        except Exception:
            logger.warning("Failed to persist event.", exc_info=True)
        status = _STATUS_BY_EVENT.get(event.type)
        if status is not None:
            with self._state_lock:
                run = self._runs.get(event.run_id)
                # Never overwrite a terminal status or a pending cancellation.
                if (
                    run is not None
                    and not run.status.is_terminal
                    and run.status is not RunStatus.CANCELLING
                ):
                    run.status = status
                    run.updated_at = utcnow()
                    self._runs.save(run)

    # -- lifecycle ----------------------------------------------------------

    def create_run(
        self,
        query: str,
        mode: RunMode = RunMode.DEEP,
        source_scope: SourceScope = SourceScope.WEB,
        document_ids: list[str] | None = None,
        approval_required: bool = False,
        project_id: str = "",
        template: str = "STANDARD",
        custom_template: str = "",
        use_memory: bool = True,
        output_language: str | None = None,
    ) -> ResearchRun:
        from src.templates import resolve_template

        # Strict: an unknown code or a language the routed model cannot write is
        # rejected here, before anything runs. Nothing is ever generated in
        # English and labelled as another language.
        language = self._languages.require(parse_output_language(output_language))
        query = query.strip()
        if not query:
            raise PlanValidationError("A non-empty research question is required.")
        if source_scope.uses_documents and not document_ids:
            raise PlanValidationError(
                "Document research requires at least one selected document."
            )
        if project_id and self._projects is not None:
            if self._projects.get(project_id) is None:
                raise PlanValidationError("Project not found.")
        template_id, _ = resolve_template(template, custom_template)  # validates
        run = ResearchRun(
            query=query,
            title=query if len(query) <= 90 else query[:87] + "...",
            mode=mode,
            source_scope=source_scope,
            approval_required=approval_required,
            document_ids=list(document_ids or []),
            project_id=project_id,
            template=template_id,
            custom_template=custom_template if template_id == "CUSTOM" else "",
            use_memory=use_memory,
            output_language=language,
        )
        self._runs.save(run)
        self._scope_for(run.id)
        self._executor.submit(self._execute_start, run.id)
        return run

    def get_run(self, run_id: str) -> ResearchRun:
        run = self._runs.get(run_id)
        if run is None:
            raise RunNotFoundError(run_id)
        return run

    def _run_config(self, run: ResearchRun) -> AtlasConfig:
        config = apply_mode(self._config, run.mode)
        # A validated non-English language may carry its own word ceiling (its
        # tokens-per-word differs from English). English is never overridden.
        overrides = self._languages.budget_overrides(run.output_language, run.mode.value)
        return dataclasses.replace(config, **overrides) if overrides else config

    def _planning_config(self, config: AtlasConfig, run: ResearchRun) -> AtlasConfig:
        """The planner writes the user-visible plan, so a non-English run plans
        with the model that writes that language. English is unchanged."""
        return config if run.output_language == "en" else self._writing_config(config, run)

    def _writing_config(self, config: AtlasConfig, run: ResearchRun) -> AtlasConfig:
        """Config for the stages that write prose (synthesis, citation repair).

        The run's output language selects the model through the central router.
        For English this is ``config`` itself, so English runs are unchanged.
        Planning, critique and search keep the run config: the evidence Atlas
        looks for does not depend on the language it reports in.
        """
        model = self._languages.model_for(run.output_language)
        return config if model == config.model else dataclasses.replace(config, model=model)

    def _start_budget(self, run_id: str, config: AtlasConfig, spent: float = 0.0) -> None:
        now = awake_clock()
        self._awake_started.setdefault(run_id, now - spent)
        if config.run_budget_seconds > 0:
            self._run_deadlines[run_id] = now + config.run_budget_seconds - spent
        else:
            self._run_deadlines.pop(run_id, None)

    def _recall_project_memory(self, run: ResearchRun):
        """Relevant findings from earlier runs in THIS project.

        Returns (memory block text, report). Disabled runs, non-project runs
        and failures all produce an empty block, never an exception: memory
        is an enhancement and must never break a run.
        """
        from src.models.memory import MemoryReport

        if self._project_memory is None or not run.use_memory:
            return "", MemoryReport(enabled=run.use_memory, scope="NONE")
        if not run.project_id:
            return "", MemoryReport(enabled=True, scope="NONE")
        from src.memory.project_memory import format_memory_block

        hits, report = self._project_memory.recall(run.query, run.project_id)
        return format_memory_block(hits), report

    def _scope_for(self, run_id: str) -> CancelScope:
        with self._state_lock:
            return self._scopes.setdefault(run_id, CancelScope())

    def _cancel_check_for(self, run_id: str):
        return self._scope_for(run_id).check

    def _run_worker(self, run_id: str, emitter: RunEmitter, body) -> None:
        """Execute one worker phase with cancellation-safe outcome mapping.

        RunCancelledError (or any failure caused by an abort after the user
        cancelled) always ends as CANCELLED, never FAILED or COMPLETED.
        """
        with self._state_lock:
            current = self._runs.get(run_id)
            if current is None or current.status.is_terminal:
                return  # cancelled (or deleted) before the worker started
            self._active_workers.add(run_id)
        try:
            self._scope_for(run_id).check()
            body()
        except RunCancelledError:
            self._mark_cancelled(run_id, emitter)
        except Exception as exc:
            if self._scope_for(run_id).cancelled:
                self._mark_cancelled(run_id, emitter)
            else:
                self._mark_failed(run_id, emitter, exc)
        finally:
            with self._state_lock:
                self._active_workers.discard(run_id)

    # -- phase 1: start (plan, then either pause or continue) ---------------

    def _execute_start(self, run_id: str) -> None:
        emitter = RunEmitter(self._bus, run_id)
        self._run_worker(run_id, emitter, lambda: self._start_body(run_id, emitter))

    def _start_body(self, run_id: str, emitter: RunEmitter) -> None:
        with self._state_lock:
            run = self.get_run(run_id)
            if run.status is not RunStatus.PENDING:
                return  # cancelled while queued
            run.started_at = utcnow()
            run.status = RunStatus.PLANNING
            self._runs.save(run)
        self._start_budget(run_id, self._run_config(run))
        emitter.emit(
            EventType.RUN_STARTED,
            message=f"Run started ({run.mode.value}, {run.source_scope.value}).",
            mode=run.mode.value,
            source_scope=run.source_scope.value,
        )
        config = self._run_config(run)

        if run.approval_required:
            emitter.emit(
                EventType.PLANNING_STARTED,
                message="Planning research...",
                agent="planner",
            )
            self._cancel_check_for(run_id)()
            start = time.perf_counter()
            sink = LLMCallSink()
            llm = self._stage_llm(
                self._planning_config(config, run), "planner",
                config.ollama_structured_reasoning, sink, run_id,
            )
            memory_context, memory_report = self._recall_project_memory(run)
            self._memory_reports[run_id] = memory_report
            planner = PlannerAgent(
                llm,
                config.max_queries_per_iteration,
                emitter=emitter,
                max_tasks=config.planner_max_tasks,
                memory_context=memory_context,
                output_language=run.output_language,
            )
            result = planner({"question": run.query})
            planner_ms = int((time.perf_counter() - start) * 1000)
            with self._state_lock:
                self._scope_for(run_id).check()  # cancel during planning wins
                run = self.get_run(run_id)
                run.plan = result["plan"]
                run.metrics.planner_ms = planner_ms
                run.metrics.planner_attempts = result.get("planner_attempts", 1)
                run.metrics.llm_call_log = sink.snapshot()
                run.status = RunStatus.AWAITING_APPROVAL
                run.updated_at = utcnow()
                self._runs.save(run)
            emitter.emit(
                EventType.PLAN_CREATED,
                message=f"Plan ready: {len(run.plan.tasks)} subquestions.",
                agent="planner",
                subquestions=[t.subquestion for t in run.plan.tasks],
                queries=list(result.get("pending_queries", [])),
            )
            emitter.emit(
                EventType.WAITING_FOR_PLAN_APPROVAL,
                message="Waiting for plan approval.",
            )
            return  # persisted pause; a new worker resumes on approval

        self._execute_graph(run_id, emitter, config, resume_plan=None)

    # -- phase 2: research/synthesis (full graph or resume after approval) --

    def _execute_graph(
        self,
        run_id: str,
        emitter: RunEmitter,
        config: AtlasConfig,
        resume_plan: ResearchPlan | None,
    ) -> None:
        from src.templates import resolve_template

        run = self.get_run(run_id)
        sink = LLMCallSink()
        self._call_sinks[run_id] = sink
        structured_reasoning = config.ollama_structured_reasoning
        budget = None
        if config.budget_allocation:
            from src.budget import RunBudget

            # REPORT COMPLETION > optional critique > optional repair.
            budget = RunBudget(config, sink.snapshot, lambda: self._run_deadlines.get(run_id))
            self._budgets[run_id] = budget
        llm = self._stage_llm(
            self._planning_config(config, run), "planner", structured_reasoning, sink, run_id
        )
        critic_llm = self._stage_llm(
            config, "critic", structured_reasoning, sink, run_id,
            run_deadline=budget.critic_deadline if budget else None,
        )
        writing = self._writing_config(config, run)
        synthesis_llm = self._stage_llm(
            writing, "synthesis", False, sink, run_id,
            run_deadline=budget.synthesis_deadline if budget else None,
        )
        repair_llm = self._stage_llm(
            writing, "repair", False, sink, run_id,
            run_deadline=budget.repair_deadline if budget else None,
        )
        if resume_plan is not None:
            # Time spent planning (HITL phase 1) counts against the budget;
            # time the user spends reviewing the plan does not.
            self._start_budget(run_id, config, spent=run.metrics.planner_ms / 1000)
        elif run_id not in self._run_deadlines:
            self._start_budget(run_id, config)
        deadline = self._run_deadlines.get(run_id)
        search_fn = (
            self._search_factory(config) if run.source_scope.uses_web else None
        )
        documents = self._documents if run.source_scope.uses_documents else None
        _, structure = resolve_template(run.template, run.custom_template)
        structure += language_instruction(run.output_language)

        memory_report = self._memory_reports.get(run_id)
        if memory_report is None or resume_plan is None:
            memory_context, memory_report = self._recall_project_memory(run)
            self._memory_reports[run_id] = memory_report
        else:
            # Resuming after plan approval: reuse what phase 1 retrieved
            # instead of paying for a second embedding call.
            memory_context = _memory_block_from_report(memory_report)

        app = build_workflow(
            llm,
            search_fn,
            config,
            synthesis_llm,
            emitter=emitter,
            cancel_check=self._cancel_check_for(run_id),
            include_planner=resume_plan is None,
            memory=self._memory if run.use_memory else None,
            documents=documents,
            document_ids=run.document_ids,
            page_fetcher=self._page_fetcher_factory(config) if search_fn else None,
            structure=structure,
            project_id=run.project_id,
            critic_llm=critic_llm,
            repair_llm=repair_llm,
            deadline=deadline,
            budget=budget,
            memory_context=memory_context,
            output_language=run.output_language,
        )
        state = initial_state(run.query, config)
        if resume_plan is not None:
            queries = [q.strip() for q in resume_plan.search_queries if q.strip()]
            state["plan"] = resume_plan
            state["pending_queries"] = queries[: config.max_queries_per_iteration]

        # Stream full-state snapshots so a cancelled run keeps what it had
        # collected (plan/evidence) even though no report is produced.
        latest: dict = state
        try:
            for snapshot in app.stream(
                state,
                config={"recursion_limit": recursion_limit(config)},
                stream_mode="values",
            ):
                latest = snapshot
        except RunCancelledError:
            self._mark_cancelled(run_id, emitter, partial=latest)
            return
        self._finish(run_id, emitter, latest)

    def _finish(self, run_id: str, emitter: RunEmitter, state: dict) -> None:
        with self._state_lock:
            if self._scope_for(run_id).cancelled:
                self._mark_cancelled(run_id, emitter, partial=state)
                return
            self._complete(run_id, emitter, state)

    def _complete(self, run_id: str, emitter: RunEmitter, state: dict) -> None:
        run = self.get_run(run_id)
        run.plan = state.get("plan", run.plan)
        run.executed_queries = list(state.get("executed_queries", []))
        run.iterations = state.get("iteration", 0)
        run.critique = state.get("critique")
        run.evidence = list(state.get("evidence", []))
        run.final_report = state.get("final_report", "")

        from src.tools.quality import with_quality

        run_config = self._run_config(run)
        selected = select_synthesis_evidence(
            run.evidence,
            run_config.max_evidence_for_synthesis,
            require_claims=run_config.synthesis_clean_evidence,
        )
        run.selected_sources = [
            with_quality(s) for s in build_numbered_sources(selected)
        ]

        run.metrics = self._build_metrics(run, state)
        run.evaluation = evaluate_report(run.final_report, run.selected_sources)
        run.status = RunStatus.COMPLETED
        run.completed_at = utcnow()
        run.updated_at = utcnow()
        self._runs.save(run)
        if self._project_memory is not None and run.project_id:
            try:
                self._project_memory.remember_run(run)
            except Exception:  # memory is an enhancement, never fatal
                logger.warning("Storing project memory failed.", exc_info=True)
        emitter.emit(
            EventType.RUN_COMPLETED,
            message="Research complete.",
            sources=len(run.selected_sources),
            cited=run.metrics.sources_cited,
            iterations=run.iterations,
            total_ms=run.metrics.total_ms,
        )

    def _build_metrics(self, run: ResearchRun, state: dict) -> RunMetrics:
        metrics = run.metrics.model_copy()
        by_node: dict[str, int] = {}
        for timing in state.get("node_timings", []):
            by_node[timing["node"]] = by_node.get(timing["node"], 0) + timing["ms"]
        metrics.planner_ms = metrics.planner_ms or by_node.get("planner", 0)
        metrics.planner_attempts = state.get(
            "planner_attempts", metrics.planner_attempts
        )
        metrics.search_ms = by_node.get("researcher", 0)
        metrics.critic_ms = by_node.get("critic", 0)
        metrics.synthesis_ms = by_node.get("synthesizer", 0)
        metrics.citation_repair_ms = state.get("citation_repair_ms", 0)
        if run.started_at:
            metrics.total_ms = int((utcnow() - run.started_at).total_seconds() * 1000)
        metrics.iterations = state.get("iteration", 0)
        metrics.search_queries_executed = len(state.get("executed_queries", []))
        metrics.sources_collected = len(state.get("evidence", []))
        metrics.sources_selected = state.get("sources_selected", 0)
        metrics.sources_cited = state.get("sources_cited", 0)
        if metrics.sources_selected:
            metrics.citation_coverage = round(
                metrics.sources_cited / metrics.sources_selected, 3
            )
        metrics.memory_hits = state.get("memory_hits", 0)
        metrics.document_chunks_retrieved = state.get("document_chunks_retrieved", 0)
        metrics.web_sources_reused = state.get("memory_hits", 0)
        metrics.pages_attempted = state.get("pages_attempted", 0)
        metrics.pages_fetched = state.get("pages_fetched", 0)
        metrics.pages_failed = state.get("pages_failed", 0)
        metrics.snippet_fallbacks = state.get("snippet_fallbacks", 0)
        from src.tools.quality import quality_tier_distribution

        metrics.source_quality_tiers = quality_tier_distribution(run.selected_sources)
        metrics.node_timings = list(state.get("node_timings", []))
        metrics.critic_fallback = state.get("critic_fallback", "") or ""
        metrics.synthesis_fallback = bool(state.get("synthesis_fallback"))
        metrics.synthesis_fallback_reason = state.get("synthesis_fallback_reason", "") or ""
        metrics.repair_skipped = bool(state.get("repair_skipped"))
        metrics.budget_seconds = self._run_config(run).run_budget_seconds
        critique = state.get("critique")
        if critique is not None:
            # A skipped critic evaluated nothing: record its decision but
            # never its placeholder score.
            if not metrics.critic_fallback:
                metrics.critic_scores.append(critique.overall_score)
            metrics.critic_decisions.append(critique.decision.value)

        # LLM diagnostics: planner-phase calls (HITL) + this graph's calls.
        sink = self._call_sinks.pop(run.id, None)
        calls = list(metrics.llm_call_log) + (sink.snapshot() if sink else [])
        combined = LLMCallSink()
        for call in calls:
            combined.add(call)
        summary = combined.summary()
        metrics.llm_call_log = calls
        metrics.llm_calls = summary["llm_calls"]
        metrics.llm_prompt_tokens = summary["llm_prompt_tokens"]
        metrics.llm_output_tokens = summary["llm_output_tokens"]
        metrics.llm_tokens_complete = summary["llm_tokens_complete"]
        memory_report = self._memory_reports.pop(run.id, None)
        if memory_report is not None:
            metrics.memory_enabled = memory_report.enabled
            metrics.memory_scope = memory_report.scope
            metrics.memory_candidates = memory_report.candidates
            metrics.project_memory_hits = memory_report.hits
            metrics.memory_threshold = memory_report.threshold
            metrics.memory_error = memory_report.error
            metrics.memory_items = list(memory_report.items)
        budget = self._budgets.pop(run.id, None)
        if budget is not None:
            metrics.budget_decisions = dict(budget.decisions)
        metrics.llm_stage_stats = summary["llm_stage_stats"]
        awake_start = self._awake_started.pop(run.id, None)
        self._run_deadlines.pop(run.id, None)
        if awake_start is not None and run.started_at:
            awake_ms = int((awake_clock() - awake_start) * 1000)
            metrics.suspended_ms = max(0, metrics.total_ms - awake_ms)
        return metrics

    def _mark_cancelled(
        self, run_id: str, emitter: RunEmitter, partial: dict | None = None
    ) -> None:
        """Terminal CANCELLED transition (idempotent: emits at most once).

        Keeps the plan/queries/evidence collected so far, but never a report.
        """
        with self._state_lock:
            run = self._runs.get(run_id)
            if run is None or run.status.is_terminal:
                return
            if partial:
                run.plan = partial.get("plan", run.plan)
                run.executed_queries = list(partial.get("executed_queries", []))
                run.evidence = list(partial.get("evidence", []))
                run.iterations = partial.get("iteration", run.iterations)
            run.final_report = ""
            run.status = RunStatus.CANCELLED
            run.completed_at = utcnow()
            run.updated_at = utcnow()
            if run.started_at:
                run.metrics.total_ms = int(
                    (run.completed_at - run.started_at).total_seconds() * 1000
                )
            self._call_sinks.pop(run_id, None)
            self._runs.save(run)
            emitter.emit(EventType.RUN_CANCELLED, message="Cancelled by user.")

    def _mark_failed(self, run_id: str, emitter: RunEmitter, exc: Exception) -> None:
        logger.exception("Run %s failed.", run_id)
        # Domain errors carry a user-facing message; everything else keeps
        # the exception type for debuggability (never a traceback).
        if isinstance(exc, PlanningError):
            message = str(exc)
        else:
            message = f"{type(exc).__name__}: {exc}"
        with self._state_lock:
            if self._scope_for(run_id).cancelled:
                # The failure came from (or raced with) a user cancel.
                self._mark_cancelled(run_id, emitter)
                return
            run = self._runs.get(run_id)
            if run is None or run.status.is_terminal:
                return
            run.status = RunStatus.FAILED
            run.error = message
            run.metrics.errors.append(message)
            run.completed_at = utcnow()
            run.updated_at = utcnow()
            self._runs.save(run)
            emitter.emit(EventType.RUN_FAILED, message=message)

    # -- human-in-the-loop ---------------------------------------------------

    def approve_plan(self, run_id: str) -> ResearchRun:
        run = self.get_run(run_id)
        if run.status is not RunStatus.AWAITING_APPROVAL or run.plan is None:
            raise InvalidRunStateError(
                f"Run {run_id} is not awaiting plan approval (status {run.status.value})."
            )
        emitter = RunEmitter(self._bus, run_id)
        emitter.emit(EventType.PLAN_APPROVED, message="Plan approved; researching.")
        run.status = RunStatus.RESEARCHING
        run.updated_at = utcnow()
        self._runs.save(run)
        plan = run.plan
        config = self._run_config(run)

        def resume() -> None:
            self._run_worker(
                run_id,
                emitter,
                lambda: self._execute_graph(run_id, emitter, config, resume_plan=plan),
            )

        self._executor.submit(resume)
        return run

    def edit_plan(
        self,
        run_id: str,
        subquestions: list[str] | None = None,
        search_queries: list[str] | None = None,
        objective: str | None = None,
    ) -> ResearchRun:
        run = self.get_run(run_id)
        if run.status is not RunStatus.AWAITING_APPROVAL or run.plan is None:
            raise InvalidRunStateError(
                f"Run {run_id} is not awaiting plan approval (status {run.status.value})."
            )
        plan = run.plan
        if subquestions is not None:
            cleaned = [s.strip() for s in subquestions if s.strip()]
            if not cleaned:
                raise PlanValidationError("At least one subquestion is required.")
            plan = plan.model_copy(
                update={
                    "tasks": [
                        ResearchTask(subquestion=s, evidence_needed="")
                        for s in cleaned
                    ]
                }
            )
        if search_queries is not None:
            cleaned = [q.strip() for q in search_queries if q.strip()]
            if not cleaned:
                raise PlanValidationError("At least one search query is required.")
            plan = plan.model_copy(update={"search_queries": cleaned})
        if objective is not None and objective.strip():
            plan = plan.model_copy(update={"objective": objective.strip()})
        run.plan = plan
        run.updated_at = utcnow()
        self._runs.save(run)
        RunEmitter(self._bus, run_id).emit(
            EventType.PLAN_EDITED,
            message="Plan edited.",
            subquestions=[t.subquestion for t in plan.tasks],
            queries=list(plan.search_queries),
        )
        return run

    def cancel(self, run_id: str) -> ResearchRun:
        """Cancel a run. Idempotent; aborts the in-flight LLM request.

        - already CANCELLED / CANCELLING: returns the run unchanged;
        - COMPLETED / FAILED: InvalidRunStateError (it finished first);
        - running on a worker: CANCELLING now; the abort makes the worker
          stop within seconds and record CANCELLED;
        - no live worker (queued, awaiting approval, orphaned by a server
          restart): CANCELLED immediately.
        """
        emitter = RunEmitter(self._bus, run_id)
        with self._state_lock:
            run = self.get_run(run_id)
            if run.status in (RunStatus.CANCELLED, RunStatus.CANCELLING):
                return run
            if run.status.is_terminal:
                raise InvalidRunStateError(f"Run {run_id} already finished.")
            # Closes the active request's connection; Ollama stops generating.
            self._scope_for(run_id).cancel()
            if run_id not in self._active_workers:
                self._mark_cancelled(run_id, emitter)
            else:
                run.status = RunStatus.CANCELLING
                run.updated_at = utcnow()
                self._runs.save(run)
                emitter.emit(EventType.CANCEL_REQUESTED, message="Cancelling…")
            return self.get_run(run_id)

    def backfill_project_memory(self) -> int:
        """Index completed project runs that predate project memory.

        Idempotent: already-indexed runs are skipped and duplicate findings
        are ignored by the store, so calling it on every startup is safe.
        """
        if self._project_memory is None:
            return 0
        try:
            summaries, _ = self._runs.list(limit=500)
            runs = []
            for summary in summaries:
                if not summary.project_id or summary.status is not RunStatus.COMPLETED:
                    continue
                run = self._runs.get(summary.id)
                if run is not None:
                    runs.append(run)
            return self._project_memory.backfill(runs)
        except Exception:
            logger.warning("Project memory backfill failed.", exc_info=True)
            return 0

    def recover_interrupted_runs(self) -> int:
        """Close out runs left active by a previous server process.

        Their worker threads died with that process, so they would otherwise
        show "Planning…" forever. Runs awaiting plan approval are untouched
        (they are resumable). Call once at API startup.
        """
        recovered = 0
        stuck = (
            RunStatus.PENDING,
            RunStatus.PLANNING,
            RunStatus.RESEARCHING,
            RunStatus.CRITIQUING,
            RunStatus.SYNTHESIZING,
            RunStatus.CANCELLING,
        )
        for run_id in self._runs.ids_with_status([s.value for s in stuck]):
            emitter = RunEmitter(self._bus, run_id)
            with self._state_lock:
                if run_id in self._active_workers:
                    continue
                run = self._runs.get(run_id)
                if run is None or run.status not in stuck:
                    continue
                if run.status is RunStatus.CANCELLING:
                    self._mark_cancelled(run_id, emitter)
                else:
                    run.status = RunStatus.FAILED
                    run.error = (
                        "Interrupted: the Atlas server stopped while this run "
                        "was in progress."
                    )
                    run.completed_at = utcnow()
                    run.updated_at = utcnow()
                    self._runs.save(run)
                    emitter.emit(EventType.RUN_FAILED, message=run.error)
                recovered += 1
        if recovered:
            logger.warning("Closed out %d run(s) interrupted by a restart.", recovered)
        return recovered

    # -- report regeneration (template feature) --------------------------------

    def regenerate_report(
        self, run_id: str, template: str, custom_template: str = ""
    ) -> ResearchRun:
        """Create a new run that re-synthesizes an existing run's evidence
        with a different template — no new web/document research."""
        from src.templates import resolve_template

        source = self.get_run(run_id)
        if source.status is not RunStatus.COMPLETED or not source.evidence:
            raise InvalidRunStateError(
                "Only completed runs with evidence can be regenerated."
            )
        template_id, structure = resolve_template(template, custom_template)
        # Regeneration keeps the original run's language, whatever the UI shows
        # now. If the model can no longer write it, refuse rather than downgrade.
        language = self._languages.require(source.output_language)
        structure += language_instruction(language)
        run = ResearchRun(
            query=source.query,
            title=source.title,
            mode=source.mode,
            source_scope=source.source_scope,
            project_id=source.project_id,
            document_ids=list(source.document_ids),
            template=template_id,
            custom_template=custom_template if template_id == "CUSTOM" else "",
            use_memory=source.use_memory,
            regenerated_from=source.id,
            output_language=language,
            plan=source.plan,
            evidence=list(source.evidence),
            executed_queries=list(source.executed_queries),
            iterations=source.iterations,
            status=RunStatus.PENDING,
        )
        self._runs.save(run)
        emitter = RunEmitter(self._bus, run.id)
        config = self._run_config(run)
        writing = self._writing_config(config, run)

        def synthesize_body() -> None:
            with self._state_lock:
                current = self.get_run(run.id)
                if current.status is not RunStatus.PENDING:
                    return  # cancelled before the worker started
                current.started_at = utcnow()
                current.status = RunStatus.SYNTHESIZING
                self._runs.save(current)
            emitter.emit(
                EventType.RUN_STARTED,
                message=f"Regenerating report with the {template_id} template.",
                mode=current.mode.value,
                source_scope=current.source_scope.value,
                regenerated_from=source.id,
            )
            emitter.emit(
                EventType.SYNTHESIS_STARTED,
                message="Synthesizing report from existing evidence...",
                agent="synthesizer",
            )
            from src.agents.synthesizer import SynthesizerAgent

            sink = LLMCallSink()
            self._call_sinks[run.id] = sink
            self._start_budget(run.id, config)
            synthesizer = SynthesizerAgent(
                self._stage_llm(writing, "synthesis", False, sink, run.id),
                max_evidence=config.max_evidence_for_synthesis,
                target_words=config.report_target_words,
                emitter=emitter,
                structure=structure,
                repair_llm=self._stage_llm(writing, "repair", False, sink, run.id),
                chars_per_source=config.synthesis_chars_per_source,
                context_chars=config.synthesis_context_chars,
                max_words=config.synthesis_max_words,
                json_mode=config.synthesis_json_mode,
                output_language=language,
            )
            synth_start = time.perf_counter()
            result = synthesizer(
                {"question": current.query, "evidence": current.evidence}
            )
            synth_ms = int((time.perf_counter() - synth_start) * 1000)
            state = {
                "evidence": current.evidence,
                "executed_queries": current.executed_queries,
                "iteration": current.iterations,
                "critique": source.critique,
                "node_timings": [
                    {"node": "synthesizer", "ms": synth_ms, "iteration": 0}
                ],
                **result,
            }
            emitter.emit(
                EventType.REPORT_REGENERATED,
                message="Report regenerated.",
                template=template_id,
                source_run=source.id,
            )
            self._finish(run.id, emitter, state)

        self._scope_for(run.id)
        self._executor.submit(
            lambda: self._run_worker(run.id, emitter, synthesize_body)
        )
        return run

    # -- export ---------------------------------------------------------------

    def export_markdown(self, run_id: str) -> str:
        run = self.get_run(run_id)
        if run.status is not RunStatus.COMPLETED or not run.final_report:
            raise InvalidRunStateError("Only completed runs can be exported.")
        from src.export.labels import export_labels, localize_report_markers
        from src.export.pdf import pdf_labels

        labels = export_labels(run.output_language)
        header = (
            f"# {labels['md_title']}\n\n"
            f"**{labels['query']}:** {run.query}\n\n"
            f"**{pdf_labels(run.output_language)['mode']}:** {run.mode.value} · **{labels['completed']}:** "
            f"{run.completed_at.isoformat() if run.completed_at else ''}\n\n---\n\n"
        )
        return header + localize_report_markers(run.final_report, run.output_language)
