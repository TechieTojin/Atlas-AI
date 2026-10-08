"""Evidence-aware comparison of completed research runs.

The deterministic part builds the combined, deduplicated source list (each
tagged with the runs that used it) and overlap statistics directly from
persisted run data. The LLM only writes the narrative over that numbered
evidence; its output goes through the same cleanup/citation-validation
pipeline as reports, and the final source list is rendered in code.
"""

from __future__ import annotations

import logging
import threading
import time

from src.agents.synthesizer import render_sources_section
from src.cancellation import (
    CancelScope,
    RunCancelledError,
    StageTimeoutError,
    awake_clock,
)
from src.config import AtlasConfig
from src.events import EventType, RunEmitter, RunEventBus
from src.llm import AbortableLLM, LLMCallSink, make_llm, stage_limits
from src.models.runs import ResearchRun, RunStatus, utcnow
from src.models.workspace import Comparison, ComparisonSource, ComparisonStatus
from src.persistence.workspace import ComparisonsRepository
from src.prompts.research import (
    COMPARISON_REPAIR,
    COMPARISON_SYSTEM,
    COMPARISON_USER,
)
from src.services.comparison_synthesis import (
    ComparisonSynthesis,
    SourceRegistry,
    cited_numbers,
    build_evidence_block,
    build_registry,
    render_comparison,
    validate_synthesis,
)
from src.services.comparison_synthesis import ComparisonError as SynthesisError
from src.services.comparison_title import comparison_title
from src.artifact_text import artifact_text
from src.languages import language_instruction
from src.tools.selection import select_evidence

logger = logging.getLogger(__name__)

_MAX_EVIDENCE_PER_RUN = 8
_MAX_CHARS_PER_SOURCE = 600


class ComparisonError(Exception):
    pass


def build_comparison_sources(runs: list[ResearchRun]) -> list[ComparisonSource]:
    """Deduplicated combined source list tagged with origin runs.

    Delegates to the canonical registry so numbering and ownership cannot drift
    from what the prompt, the citations and the overlap statistics use.
    """
    return build_registry(runs).comparison_sources(runs)


def overlap_stats(runs: list[ResearchRun], sources: list[ComparisonSource]) -> dict:
    """Overlap figures from the same registry everything else reads."""
    return build_registry(runs).overlap_stats(runs)


class ComparisonService:
    def __init__(
        self,
        config: AtlasConfig,
        repo: ComparisonsRepository,
        runs_repo,
        bus: RunEventBus,
        llm_factory,
        executor,
        languages=None,
    ) -> None:
        from src.model_capabilities import LanguageRouter

        self._config = config
        self._languages = languages or LanguageRouter(config)
        self._repo = repo
        self._runs = runs_repo
        self._bus = bus
        self._llm_factory = llm_factory
        self._executor = executor
        # Live scopes, so cancel/delete can abort the in-flight model request
        # instead of only rewriting a database row.
        self._state_lock = threading.Lock()
        self._active: dict[str, CancelScope] = {}

    def create(
        self, run_ids: list[str], project_id: str = "", output_language: str | None = None
    ) -> Comparison:
        from src.languages import parse_output_language

        # Strict, like research runs: unknown or unsupported languages are refused.
        language = self._languages.require(parse_output_language(output_language), "comparison")
        ids = list(dict.fromkeys(run_ids or []))
        if len(ids) < 2:
            raise ComparisonError("A comparison needs at least two distinct runs.")
        if len(ids) > 5:
            raise ComparisonError("A comparison supports at most five runs.")
        runs: list[ResearchRun] = []
        for run_id in ids:
            run = self._runs.get(run_id)
            if run is None:
                raise ComparisonError(f"Run {run_id} not found.")
            if run.status is not RunStatus.COMPLETED:
                raise ComparisonError(f"Run {run_id} is not completed.")
            if project_id and run.project_id != project_id:
                raise ComparisonError(
                    f"Run {run_id} does not belong to this project."
                )
            runs.append(run)
        comparison = Comparison(
            project_id=project_id,
            run_ids=ids,
            run_queries=[r.query for r in runs],
            title=comparison_title([r.query for r in runs], language),
            output_language=language,
        )
        self._repo.save(comparison)
        self._executor.submit(self._execute, comparison.id)
        return comparison

    def _writing_config(self, language: str) -> AtlasConfig:
        import dataclasses

        model = self._languages.model_for(language)
        return self._config if model == self._config.model else dataclasses.replace(
            self._config, model=model
        )

    def get(self, comparison_id: str) -> Comparison:
        comparison = self._repo.get(comparison_id)
        if comparison is None:
            raise ComparisonError("Comparison not found.")
        return comparison

    def list(self, project_id: str | None = None) -> list[Comparison]:
        return self._repo.list(project_id)

    def cancel(self, comparison_id: str) -> Comparison:
        """Ask a running comparison to stop, aborting its model request now."""
        comparison = self.get(comparison_id)
        if comparison.status.is_terminal:
            return comparison
        with self._state_lock:
            scope = self._active.get(comparison_id)
        if scope is None:
            # No worker owns this any more (e.g. a restart orphaned it), so it
            # can be closed out directly rather than left waiting for a reply.
            return self._finish(
                comparison_id,
                ComparisonStatus.CANCELLED,
                "Cancelled before it could start.",
            )
        comparison.status = ComparisonStatus.CANCELLING
        self._repo.save(comparison)
        scope.cancel()  # aborts the HTTP request, so Ollama stops generating
        return self.get(comparison_id)

    def delete(self, comparison_id: str) -> bool:
        """Delete a comparison, stopping its model request first if it is live.

        Without the abort, deleting a running comparison left Ollama generating
        for a report nobody would ever read, blocking every later request.
        """
        with self._state_lock:
            scope = self._active.get(comparison_id)
        if scope is not None:
            scope.cancel()
        return self._repo.delete(comparison_id)

    def recover_interrupted_comparisons(self) -> int:
        """Close out comparisons left active by a previous server process.

        Their worker threads died with that process, so they would otherwise
        show "Comparing 2 runs..." forever. Mirrors the research-run policy.
        Completed comparisons are never touched.
        """
        recovered = 0
        for comparison in self._repo.list(None):
            if comparison.status.is_terminal:
                continue
            with self._state_lock:
                if comparison.id in self._active:
                    continue
            self._finish(
                comparison.id,
                ComparisonStatus.CANCELLED
                if comparison.status is ComparisonStatus.CANCELLING
                else ComparisonStatus.FAILED,
                "Interrupted: the Atlas server stopped while this comparison "
                "was in progress.",
            )
            recovered += 1
        if recovered:
            logger.warning(
                "Closed out %d comparison(s) interrupted by a restart.", recovered
            )
        return recovered

    def _finish(
        self,
        comparison_id: str,
        status: ComparisonStatus,
        reason: str,
        metrics: dict | None = None,
    ) -> Comparison:
        """Write a terminal state. Safe to call when the row no longer exists."""
        comparison = self._repo.get(comparison_id)
        if comparison is None:
            # Deleted while running: honour the deletion rather than resurrecting
            # the row by saving a result for it.
            return Comparison(id=comparison_id, run_ids=[], status=status)
        comparison.status = status
        comparison.error = reason
        comparison.completed_at = utcnow()
        if metrics:
            comparison.metrics = {**comparison.metrics, **metrics}
        self._repo.save(comparison)
        return comparison

    # -- execution -----------------------------------------------------------

    def _execute(self, comparison_id: str) -> None:
        comparison = self.get(comparison_id)
        emitter = RunEmitter(self._bus, comparison_id)
        start = time.perf_counter()
        scope = CancelScope()
        sink = LLMCallSink()
        # Visible to the failure paths, so a repair that ran is still counted.
        self._repairs_used = 0
        with self._state_lock:
            self._active[comparison_id] = scope
        phase = "preparing"
        try:
            scope.check()
            comparison.status = ComparisonStatus.RUNNING
            comparison.started_at = utcnow()
            self._repo.save(comparison)
            emitter.emit(
                EventType.COMPARISON_STARTED,
                message=f"Comparing {len(comparison.run_ids)} runs...",
            )
            runs = [self._runs.get(rid) for rid in comparison.run_ids]
            runs = [r for r in runs if r is not None]
            if len(runs) < 2:
                raise ComparisonError("Input runs are no longer available.")

            # One canonical registry decides source numbering, run ownership and
            # every overlap figure, so the prompt, the citations, the Source
            # Differences section and the stats the UI shows cannot disagree.
            registry = build_registry(runs)
            sources = registry.comparison_sources(runs)
            stats = registry.overlap_stats(runs)
            run_labels = {run.id: f"Run {i}" for i, run in enumerate(runs, 1)}

            evidence = build_evidence_block(
                registry,
                runs,
                select_evidence,
                _MAX_EVIDENCE_PER_RUN,
                _MAX_CHARS_PER_SOURCE,
            )
            run_overview = "\n".join(
                f"{run_labels[r.id]}: \"{r.query}\" "
                f"(completed {r.completed_at.date() if r.completed_at else 'n/a'}, "
                f"{r.mode.value}, template {r.template})"
                for r in runs
            )

            # The model call is bounded and abortable. This was previously a bare
            # `llm.invoke` with no output cap and no deadline: httpx's timeout is
            # per-read, and a streaming generation resets it with every token, so
            # nothing could ever stop it. One such call ran for over 20 minutes,
            # holding Ollama against every other request.
            _max_tokens, timeout = stage_limits(self._config, "comparison")
            # The comparison's own language picks the model; the repair attempt
            # reuses this handle and prompt, so it inherits the language too.
            writing = self._writing_config(comparison.output_language)
            llm = AbortableLLM(
                lambda: make_llm(
                    self._llm_factory,
                    writing,
                    reasoning=False,
                    stage="comparison",
                    call_sink=sink,
                ),
                timeout=timeout,
                scope=scope,
                label="comparison",
                sink=sink,
            )
            # Structured output puts a JSON schema in Ollama's `format` field, so
            # decoding is grammar-constrained and the model cannot emit prose
            # outside the schema. `think: false` alone did not achieve this: it
            # hides Ollama's separate thinking field but leaves qwen3 free to
            # deliberate inline, which is how "We are comparing two research
            # runs..." ended up being the saved report.
            structured = llm.with_structured_output(ComparisonSynthesis)
            prompt = [
                ("system", COMPARISON_SYSTEM + language_instruction(comparison.output_language)),
                (
                    "user",
                    COMPARISON_USER.format(
                        run_overview=run_overview, evidence=evidence
                    ),
                ),
            ]

            phase = "synthesising"
            synthesis, repairs, validation_ms = self._synthesise(
                structured, prompt, registry, scope
            )

            phase = "rendering"
            report = render_comparison(
                synthesis,
                registry,
                runs,
                comparison.title or artifact_text(comparison.output_language, "comparison.title"),
                render_sources_section,
                comparison.output_language,
            )

            comparison.report = report
            comparison.synthesis = synthesis.model_dump(mode="json")
            comparison.sources = sources
            comparison.overlap_stats = stats
            comparison.status = ComparisonStatus.COMPLETED
            comparison.completed_at = utcnow()
            comparison.duration_ms = int((time.perf_counter() - start) * 1000)
            comparison.metrics = self._metrics(
                sink, start, outcome="completed", phase="done",
                repairs=repairs, validation_ms=validation_ms,
            )
            if self._repo.get(comparison_id) is None:
                # Deleted mid-flight: do not resurrect the row.
                logger.info("Comparison %s was deleted while running.", comparison_id)
                return
            self._repo.save(comparison)
            emitter.emit(
                EventType.COMPARISON_COMPLETED,
                message="Comparison complete.",
                sources=len(sources),
                cited=len(cited_numbers(synthesis)),
            )
        except RunCancelledError:
            self._finish(
                comparison_id,
                ComparisonStatus.CANCELLED,
                "Cancelled.",
                self._metrics(sink, start, outcome="cancelled", phase=phase,
                              repairs=self._repairs_used),
            )
            emitter.emit(EventType.COMPARISON_FAILED, message="Comparison cancelled.")
        except StageTimeoutError as exc:
            self._finish(
                comparison_id,
                ComparisonStatus.TIMED_OUT,
                f"Timed out: {exc}",
                self._metrics(sink, start, outcome="timed_out", phase=phase,
                              repairs=self._repairs_used),
            )
            emitter.emit(EventType.COMPARISON_FAILED, message="Comparison timed out.")
        except Exception as exc:
            logger.exception("Comparison %s failed.", comparison_id)
            self._finish(
                comparison_id,
                ComparisonStatus.FAILED,
                f"{type(exc).__name__}: {exc}",
                self._metrics(sink, start, outcome="failed", phase=phase,
                              repairs=self._repairs_used),
            )
            emitter.emit(EventType.COMPARISON_FAILED, message="Comparison failed.")
        finally:
            with self._state_lock:
                self._active.pop(comparison_id, None)

    def _synthesise(
        self, structured, prompt: list, registry: SourceRegistry, scope: CancelScope
    ) -> tuple[ComparisonSynthesis, int, int]:
        """Get validated structured output, with at most one repair attempt.

        The repair reuses the same AbortableLLM handle, so it inherits the
        cancel scope and what remains of the comparison deadline. If the budget
        is already spent the deadline simply fires again rather than starting a
        second unbounded generation.
        """
        problem = ""
        for attempt in (0, 1):
            self._repairs_used = attempt
            messages = prompt if attempt == 0 else [
                *prompt,
                (
                    "user",
                    COMPARISON_REPAIR.format(
                        problem=problem,
                        max_source=registry.count,
                        max_run=len(registry.run_labels),
                    ),
                ),
            ]
            try:
                raw = structured.invoke(messages)
            except (RunCancelledError, StageTimeoutError):
                raise
            except Exception as exc:
                # Malformed or unparseable output: worth one corrective attempt.
                problem = f"{type(exc).__name__}: {exc}"
                if attempt == 1:
                    raise ComparisonError(
                        f"The model did not return usable structured output. {problem}"
                    ) from exc
                logger.warning("Comparison output unusable, repairing: %s", problem)
                continue

            validation_start = time.perf_counter()
            try:
                synthesis = validate_synthesis(
                    raw if isinstance(raw, ComparisonSynthesis)
                    else ComparisonSynthesis.model_validate(raw),
                    registry,
                )
            except SynthesisError as exc:
                problem = str(exc)
                if attempt == 1:
                    # Never persist a comparison whose citations do not hold up.
                    raise ComparisonError(
                        f"The comparison could not be validated. {problem}"
                    ) from exc
                logger.warning("Comparison failed validation, repairing: %s", problem)
                continue
            validation_ms = int((time.perf_counter() - validation_start) * 1000)
            return synthesis, attempt, validation_ms

        raise ComparisonError("The comparison could not be produced.")

    def _metrics(
        self,
        sink: LLMCallSink,
        start: float,
        *,
        outcome: str,
        phase: str,
        repairs: int = 0,
        validation_ms: int | None = None,
    ) -> dict:
        """Execution metrics, reported only where Ollama actually supplied them.

        Anything the model never told us stays ``None``. Showing 0 for a token
        count after an aborted request would claim the model produced nothing,
        which is not something we know.
        """
        calls = sink.snapshot()

        def total(field: str) -> int | None:
            values = [c.get(field) for c in calls]
            known = [v for v in values if isinstance(v, int)]
            return sum(known) if known and len(known) == len(values) else None

        def first(field: str):
            return next((c.get(field) for c in calls if c.get(field) is not None), None)

        output_tokens = total("output_tokens")
        max_tokens, _timeout = stage_limits(self._config, "comparison")
        done_reasons = [c.get("done_reason") for c in calls]

        return {
            "model": self._config.model,
            "outcome": outcome,
            "phase": phase,
            "llm_calls": len(calls),
            "repair_calls": repairs,
            "elapsed_ms": int((time.perf_counter() - start) * 1000),
            "prompt_tokens": total("prompt_tokens"),
            "output_tokens": output_tokens,
            "prefill_ms": total("prompt_eval_ms"),
            "generation_ms": total("eval_ms"),
            "time_to_first_token_ms": first("first_token_ms"),
            "validation_ms": validation_ms,
            # "length" is Ollama's word for "stopped because num_predict ran out".
            # None rather than False when the model never reported a reason.
            "output_cap_reached": (
                any(reason == "length" for reason in done_reasons)
                or (output_tokens is not None and max_tokens is not None
                    and output_tokens >= max_tokens)
                if any(r is not None for r in done_reasons) or output_tokens is not None
                else None
            ),
            "deadline_reached": outcome == "timed_out",
        }
