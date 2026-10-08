"""Follow-up / conversational research on completed runs.

Two kinds:
- ANALYTICAL: answered from the parent run's existing evidence (no search).
- RESEARCH: additionally retrieves new web/document evidence for the
  follow-up question.

Source numbering is stable: parent-run sources keep their original numbers
[1..k]; newly retrieved sources are appended [k+1..]. Answers are cleaned by
the same deterministic pipeline as reports (reasoning stripping, invalid-
citation removal, LLM reference-section removal), and the source list shown
to the user is rendered from real Source objects only.
"""

from __future__ import annotations

import logging
import time

from src.agents.synthesizer import (
    build_numbered_sources,
    extract_valid_citations,
    strip_generated_reference_sections,
    strip_invalid_citations,
    strip_reasoning_artifacts,
)
from src.config import AtlasConfig
from src.events import EventType, RunEmitter, RunEventBus
from src.models.research import Evidence
from src.models.runs import RunStatus, utcnow
from src.models.workspace import FollowUp, FollowUpKind, FollowUpStatus
from src.persistence.workspace import FollowUpsRepository
from src.languages import language_instruction
from src.prompts.research import FOLLOWUP_SYSTEM, FOLLOWUP_USER
from src.scientific_text import plain_notation, scientific_text_issues
from src.tools.search import dedupe_evidence, run_searches
from src.tools.selection import select_evidence

logger = logging.getLogger(__name__)

_MAX_REPORT_CONTEXT_CHARS = 6000
_MAX_EVIDENCE_CHARS = 700
_RESEARCH_HINTS = (
    "research", "search", "find more", "go deeper", "dig deeper", "look up",
    "more sources", "latest", "recent", "new evidence", "investigate",
)


class FollowUpError(Exception):
    pass


def classify_followup(question: str, mode: str = "auto") -> FollowUpKind:
    """Deterministic kind selection; user mode overrides the heuristic."""
    mode = (mode or "auto").lower()
    if mode == "analytical":
        return FollowUpKind.ANALYTICAL
    if mode == "research":
        return FollowUpKind.RESEARCH
    lowered = question.lower()
    if any(hint in lowered for hint in _RESEARCH_HINTS):
        return FollowUpKind.RESEARCH
    return FollowUpKind.ANALYTICAL


class FollowUpService:
    def __init__(
        self,
        config: AtlasConfig,
        repo: FollowUpsRepository,
        runs_repo,
        bus: RunEventBus,
        llm_factory,
        search_factory=None,
        documents=None,
        executor=None,
        languages=None,
    ) -> None:
        from src.model_capabilities import LanguageRouter

        self._config = config
        self._languages = languages or LanguageRouter(config)
        self._repo = repo
        self._runs = runs_repo
        self._bus = bus
        self._llm_factory = llm_factory
        self._search_factory = search_factory
        self._documents = documents
        self._executor = executor
        self._cancelled: set[str] = set()

    def create(self, run_id: str, question: str, mode: str = "auto") -> FollowUp:
        question = (question or "").strip()
        if not question:
            raise FollowUpError("A non-empty follow-up question is required.")
        if len(question) > 2000:
            raise FollowUpError("Follow-up question is too long (max 2000 chars).")
        run = self._runs.get(run_id)
        if run is None:
            raise FollowUpError("Run not found.")
        if run.status is not RunStatus.COMPLETED:
            raise FollowUpError("Follow-ups require a completed run.")
        # The answer is written in the run's language, never the UI's. If that
        # language can no longer be generated, refuse instead of answering in
        # another language.
        language = self._languages.require(run.output_language, "followup")
        followup = FollowUp(
            run_id=run_id,
            project_id=run.project_id,
            question=question,
            kind=classify_followup(question, mode),
            output_language=language,
        )
        self._repo.save(followup)
        self._executor.submit(self._execute, followup.id)
        return followup

    def _writing_config(self, language: str) -> AtlasConfig:
        import dataclasses

        model = self._languages.model_for(language)
        return self._config if model == self._config.model else dataclasses.replace(
            self._config, model=model
        )

    def get(self, followup_id: str) -> FollowUp:
        followup = self._repo.get(followup_id)
        if followup is None:
            raise FollowUpError("Follow-up not found.")
        return followup

    def list_for_run(self, run_id: str) -> list[FollowUp]:
        return self._repo.list_for_run(run_id)

    def cancel(self, followup_id: str) -> FollowUp:
        followup = self.get(followup_id)
        if followup.status.is_terminal:
            raise FollowUpError("Follow-up already finished.")
        self._cancelled.add(followup_id)
        return followup

    # -- execution -----------------------------------------------------------

    def _check_cancel(self, followup: FollowUp, emitter: RunEmitter) -> bool:
        if followup.id in self._cancelled:
            followup.status = FollowUpStatus.CANCELLED
            followup.completed_at = utcnow()
            self._repo.save(followup)
            emitter.emit(EventType.FOLLOWUP_FAILED, message="Follow-up cancelled.")
            return True
        return False

    def _format_sources(self, sources, evidence_by_url) -> str:
        blocks = []
        for i, source in enumerate(sources, 1):
            texts = evidence_by_url.get(source.normalized_url, [])
            body = "\n".join(t[:_MAX_EVIDENCE_CHARS] for t in texts[:2]) or "(no excerpt)"
            blocks.append(f"SOURCE [{i}]\nTitle: {source.title}\nEvidence: {body}")
        return "\n\n".join(blocks)

    def _execute(self, followup_id: str) -> None:
        followup = self.get(followup_id)
        emitter = RunEmitter(self._bus, followup_id)
        start = time.perf_counter()
        try:
            run = self._runs.get(followup.run_id)
            followup.status = FollowUpStatus.RUNNING
            self._repo.save(followup)
            emitter.emit(
                EventType.FOLLOWUP_STARTED,
                message=f"Answering follow-up ({followup.kind.value.lower()})...",
                kind=followup.kind.value,
            )

            # Parent context: the run's selected sources keep their numbers.
            parent_evidence = select_evidence(
                run.evidence, self._config.max_evidence_for_synthesis
            )
            parent_sources = run.selected_sources or build_numbered_sources(
                parent_evidence
            )
            evidence_by_url: dict[str, list[str]] = {}
            for item in run.evidence:
                evidence_by_url.setdefault(item.source.normalized_url, []).append(
                    item.content
                )

            all_sources = list(parent_sources)
            new_count = 0
            if followup.kind is FollowUpKind.RESEARCH:
                new_items = self._retrieve_new(followup, run, parent_sources)
                for item in new_items:
                    evidence_by_url.setdefault(
                        item.source.normalized_url, []
                    ).append(item.content)
                new_sources = build_numbered_sources(new_items)
                all_sources.extend(new_sources)
                new_count = len(new_sources)
                followup.searched = True

            if self._check_cancel(followup, emitter):
                return

            llm = self._llm_factory(self._writing_config(followup.output_language), reasoning=False)
            report_context = run.final_report[:_MAX_REPORT_CONTEXT_CHARS]
            response = llm.invoke(
                [
                    ("system", FOLLOWUP_SYSTEM + language_instruction(followup.output_language)),
                    (
                        "user",
                        FOLLOWUP_USER.format(
                            question=run.query,
                            report=report_context,
                            evidence=self._format_sources(all_sources, evidence_by_url),
                            followup=followup.question,
                        ),
                    ),
                ]
            )
            body = str(getattr(response, "content", response))
            body = strip_reasoning_artifacts(body)
            body = strip_generated_reference_sections(body)
            body = strip_invalid_citations(body, len(all_sources))
            body = plain_notation(body)
            issues = scientific_text_issues(body)
            if issues:
                # Never persist corrupted scientific notation as an answer.
                raise ValueError("The model's answer was unusable: " + "; ".join(issues) + ".")
            cited = extract_valid_citations(body, len(all_sources))

            followup.answer = body.strip()
            followup.sources = all_sources
            followup.parent_source_count = len(parent_sources)
            followup.new_source_count = new_count
            followup.cited = sorted(cited)
            followup.status = FollowUpStatus.COMPLETED
            followup.completed_at = utcnow()
            followup.duration_ms = int((time.perf_counter() - start) * 1000)
            self._repo.save(followup)
            emitter.emit(
                EventType.FOLLOWUP_COMPLETED,
                message="Follow-up answered.",
                cited=len(cited),
                new_sources=new_count,
            )
        except Exception as exc:
            logger.exception("Follow-up %s failed.", followup_id)
            followup = self.get(followup_id)
            followup.status = FollowUpStatus.FAILED
            followup.error = f"{type(exc).__name__}: {exc}"
            followup.completed_at = utcnow()
            self._repo.save(followup)
            emitter.emit(EventType.FOLLOWUP_FAILED, message="Follow-up failed.")

    def _retrieve_new(self, followup: FollowUp, run, parent_sources) -> list[Evidence]:
        """Bounded new retrieval for RESEARCH follow-ups (one query)."""
        new_items: list[Evidence] = []
        seen = {s.normalized_url for s in parent_sources}
        if run.source_scope.uses_web and self._search_factory is not None:
            try:
                search_fn = self._search_factory(self._config)
                found = run_searches(
                    search_fn, [followup.question], self._config.search_results_per_query
                )
                unique, _ = dedupe_evidence(found, seen)
                new_items.extend(unique)
                seen |= {e.source.normalized_url for e in unique}
            except Exception:
                logger.warning("Follow-up web search failed.", exc_info=True)
        if (
            run.source_scope.uses_documents
            and self._documents is not None
            and run.document_ids
        ):
            try:
                chunks = self._documents.retrieve(followup.question, run.document_ids)
                unique, _ = dedupe_evidence(chunks, seen)
                new_items.extend(unique)
            except Exception:
                logger.warning("Follow-up document retrieval failed.", exc_info=True)
        return new_items
