"""Planner agent: decomposes the research question into a structured plan.

A plan that is Pydantic-valid can still be semantically unusable (live bug:
qwen3:4b returned ``tasks=[]`` and ``search_queries=[]``, and Atlas researched
zero queries). The planner therefore normalizes and semantically validates
every plan, performs at most ONE repair attempt that tells the model what was
wrong, and raises :class:`PlanningError` if the plan is still unusable — the
run fails cleanly instead of producing an evidence-free report.

Research queries drive ALL retrieval (web search, document retrieval, and
memory recall), so every source scope — including documents-only — requires
at least one usable query.
"""

from __future__ import annotations

import logging
from typing import Any

from src.events import EventType, NullEmitter
from src.graph.state import AtlasState
from src.models.research import ResearchPlan, ResearchTask
from src.prompts.research import (
    PLANNER_MEMORY_NOTE,
    PLANNER_REPAIR_USER,
    PLANNER_SYSTEM,
    PLANNER_USER,
)

logger = logging.getLogger(__name__)

MAX_PLANNER_ATTEMPTS = 2  # one initial attempt + at most one repair

PLANNER_FAILURE_MESSAGE = (
    "Planner failed to generate a usable research plan. "
    "Please try again or rephrase the question."
)


class PlanningError(Exception):
    """The planner could not produce a semantically usable plan."""


def normalize_plan(plan: ResearchPlan, max_queries: int) -> ResearchPlan:
    """Deterministically trim and drop blank entries; cap query count."""
    tasks = [
        ResearchTask(
            subquestion=t.subquestion.strip(),
            evidence_needed=t.evidence_needed.strip(),
        )
        for t in plan.tasks
        if t.subquestion.strip()
    ]
    queries: list[str] = []
    for query in plan.search_queries:
        cleaned = query.strip()
        if cleaned and cleaned not in queries:
            queries.append(cleaned)
    return plan.model_copy(
        update={"tasks": tasks, "search_queries": queries[:max_queries]}
    )


def plan_problems(plan: ResearchPlan) -> list[str]:
    """Semantic validation problems of an already-normalized plan."""
    problems: list[str] = []
    if not plan.search_queries:
        problems.append("it contained no usable (non-empty) search queries")
    if not plan.tasks:
        problems.append("it contained no usable (non-empty) subquestions")
    return problems


class PlannerAgent:
    """Produces a :class:`ResearchPlan` via structured LLM output.

    ``llm`` is any LangChain chat model; it is injected so tests can pass a
    fake. The planner never performs research itself.
    """

    def __init__(
        self,
        llm: Any,
        max_queries: int = 5,
        emitter: Any = None,
        max_tasks: int = 0,
        memory_context: str = "",
        output_language: str = "en",
    ) -> None:
        self._planner = llm.with_structured_output(ResearchPlan)
        self._max_queries = max_queries
        self._max_tasks = max_tasks
        # Findings previous runs in this project already established; the
        # planner targets the gaps instead of re-confirming them.
        self._memory_context = memory_context
        # User-visible plan text in the run's language; queries stay retrieval-first.
        from src.languages import plan_language_instruction

        self._plan_language = plan_language_instruction(output_language)
        self._emitter = emitter or NullEmitter()

    def _size_hint(self) -> str:
        if self._max_tasks <= 0:
            return ""
        return (
            f"\n\nKeep the plan compact: at most {self._max_tasks} subquestions "
            f"and at most {self._max_queries} search queries; keep each "
            "evidence_needed to one short sentence."
        )

    def _invoke(self, question: str, problems: list[str] | None = None) -> ResearchPlan:
        if problems:
            user = PLANNER_REPAIR_USER.format(
                problems="; ".join(problems), question=question
            )
        else:
            user = PLANNER_USER.format(question=question)
            if self._memory_context:
                user += PLANNER_MEMORY_NOTE.format(memory=self._memory_context)
        plan: ResearchPlan = self._planner.invoke(
            [("system", PLANNER_SYSTEM + self._plan_language), ("user", user + self._size_hint())]
        )
        plan = normalize_plan(plan, self._max_queries)
        if self._max_tasks > 0:
            plan = plan.model_copy(update={"tasks": plan.tasks[: self._max_tasks]})
        return plan

    def _attempt(self, question: str, problems: list[str] | None = None):
        """One planner call. Malformed/truncated structured output counts as
        an unusable plan (repairable); a timeout fails planning cleanly."""
        from src.llm import is_llm_timeout, is_malformed_output

        try:
            plan = self._invoke(question, problems)
        except Exception as exc:
            if is_llm_timeout(exc):
                logger.error("Planner exceeded its time budget.")
                raise PlanningError(
                    "Planner exceeded its time budget. The local model may be "
                    "overloaded; please try again."
                ) from exc
            if is_malformed_output(exc):
                logger.warning("Planner returned malformed structured output.")
                return None, ["its output was not valid, complete structured JSON"]
            raise
        return plan, plan_problems(plan)

    def __call__(self, state: AtlasState) -> dict[str, Any]:
        question = state["question"]
        logger.info("Planning research...")
        plan, problems = self._attempt(question)
        attempts = 1

        if problems:
            # Exactly one bounded repair attempt, telling the model why the
            # previous plan was rejected. No unbounded loop, and no queries
            # are ever fabricated in Python.
            logger.warning(
                "Planner produced an unusable plan (%s); attempting one repair.",
                "; ".join(problems),
            )
            self._emitter.emit(
                EventType.PLANNING_REPAIR_STARTED,
                message="Initial plan was unusable; repairing the research plan...",
                agent="planner",
                problems=problems,
            )
            plan, problems = self._attempt(question, problems=problems)
            attempts = 2

        if problems:
            logger.error(
                "Planner repair still unusable (%s); failing the run.",
                "; ".join(problems),
            )
            raise PlanningError(PLANNER_FAILURE_MESSAGE)

        logger.info(
            "Plan ready: %d subquestions, %d research queries.",
            len(plan.tasks),
            len(plan.search_queries),
        )
        return {
            "plan": plan,
            "pending_queries": list(plan.search_queries),
            "iteration": 0,
            "planner_attempts": attempts,
        }
