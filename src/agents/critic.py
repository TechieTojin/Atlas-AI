"""Critic agent: decides whether the evidence suffices or more research is needed."""

from __future__ import annotations

import logging
import time
from typing import Any

from src.cancellation import awake_clock
from src.graph.state import AtlasState
from src.models.research import Critique, CriticDecision, Evidence
from src.prompts.research import CRITIC_SYSTEM, CRITIC_USER
from src.tools.selection import select_evidence

logger = logging.getLogger(__name__)

_MAX_EVIDENCE_CHARS = 700


_FINAL_PASS_NOTE = (
    "\n\nThis is the FINAL research pass: no further searches are possible. "
    "Leave follow_up_queries empty and keep every field brief."
)


def _format_evidence(
    evidence: list[Evidence], max_chars: int = _MAX_EVIDENCE_CHARS
) -> str:
    lines = []
    for i, item in enumerate(evidence, 1):
        snippet = item.content[:max_chars]
        lines.append(
            f"[{i}] {item.source.title} ({item.source.domain})\n"
            f"    found by query: {item.query}\n    {snippet}"
        )
    return "\n\n".join(lines) if lines else "(no evidence collected)"


def fallback_critique(reason: str) -> Critique:
    """Deterministic stand-in when the LLM critic cannot run.

    It never claims an evaluation happened: the score is not recorded in
    metrics, and the reasoning states why the critic was skipped. Routing
    then proceeds to synthesis with the evidence already collected.
    """
    return Critique(
        overall_score=0,
        coverage_assessment="Not evaluated: " + reason,
        missing_information=[],
        decision=CriticDecision.SYNTHESIZE,
        follow_up_queries=[],
        reasoning=f"Critic skipped ({reason}); synthesizing collected evidence.",
    )


def normalize_critique(critique: Critique, sufficiency_threshold: int) -> Critique:
    """Enforce the deterministic sufficiency invariant on LLM output.

    SYNTHESIZE is only valid when the critic's own score meets the
    threshold; contradictory output (e.g. SYNTHESIZE with score 0) is
    normalized to MORE_RESEARCH. MORE_RESEARCH is never overridden here —
    only the iteration cap in routing may force synthesis.
    """
    if (
        critique.decision is CriticDecision.SYNTHESIZE
        and critique.overall_score < sufficiency_threshold
    ):
        logger.warning(
            "Critic returned contradictory output (SYNTHESIZE with score "
            "%d/10 < threshold %d); normalizing to MORE_RESEARCH.",
            critique.overall_score,
            sufficiency_threshold,
        )
        return critique.model_copy(update={"decision": CriticDecision.MORE_RESEARCH})
    return critique


class CriticAgent:
    """Evaluates collected evidence with structured LLM output."""

    def __init__(
        self,
        llm: Any,
        max_follow_up_queries: int = 5,
        sufficiency_threshold: int = 7,
        max_evidence: int = 12,
        chars_per_evidence: int = _MAX_EVIDENCE_CHARS,
        deadline: float | None = None,
        min_seconds_required: float = 0.0,
        skip_check=None,
    ) -> None:
        self._critic = llm.with_structured_output(Critique)
        self._max_follow_up_queries = max_follow_up_queries
        self._sufficiency_threshold = sufficiency_threshold
        self._max_evidence = max_evidence
        self._chars_per_evidence = chars_per_evidence
        # Run-level budget: skip the (optional) critic when the remaining
        # time could not also cover synthesis.
        self._deadline = deadline
        self._min_seconds_required = min_seconds_required
        # Returns a reason string when the critic must be skipped (FAST
        # budget allocation protects the synthesis reserve).
        self._skip_check = skip_check

    def __call__(self, state: AtlasState) -> dict[str, Any]:
        logger.info("Evaluating evidence...")
        evidence = state.get("evidence", [])
        plan = state.get("plan")
        subquestions = (
            "\n".join(f"- {t.subquestion}" for t in plan.tasks) if plan else "(no plan)"
        )
        executed = state.get("executed_queries", [])
        unique_domains = {e.source.domain for e in evidence}
        fallback_reason = ""

        if not evidence:
            # Nothing to evaluate — let routing decide based on iterations left.
            critique = Critique(
                overall_score=0,
                coverage_assessment="No evidence was collected.",
                missing_information=["All subquestions remain unanswered."],
                decision=CriticDecision.MORE_RESEARCH,
                follow_up_queries=list(plan.search_queries) if plan else [],
                reasoning="No search results were obtained; retry research if possible.",
            )
        elif self._skip_check is not None and (reason := self._skip_check()):
            logger.info("Critic %s.", reason)
            fallback_reason = reason
            critique = fallback_critique(fallback_reason)
        elif self._skip_check is None and self._budget_exhausted():
            logger.warning("Run time budget too low for the critic; skipping it.")
            fallback_reason = "run time budget exhausted"
            critique = fallback_critique(fallback_reason)
        else:
            # Budget the LLM context deterministically; all evidence stays
            # in state and the counts below still describe the full set.
            shown = select_evidence(evidence, self._max_evidence)
            final_pass = state.get("iteration", 0) >= state.get("max_iterations", 1)
            user = CRITIC_USER.format(
                question=state["question"],
                subquestions=subquestions,
                queries="\n".join(f"- {q}" for q in executed) or "(none)",
                evidence_count=len(evidence),
                source_count=len(unique_domains),
                evidence=_format_evidence(shown, self._chars_per_evidence),
            )
            if final_pass:
                user += _FINAL_PASS_NOTE
            try:
                critique = self._critic.invoke([("system", CRITIC_SYSTEM), ("user", user)])
                critique = normalize_critique(critique, self._sufficiency_threshold)
            except Exception as exc:
                from src.llm import is_llm_timeout, is_malformed_output

                if is_llm_timeout(exc):
                    fallback_reason = "critic exceeded its time budget"
                elif is_malformed_output(exc):
                    fallback_reason = "critic returned malformed output"
                else:
                    raise
                logger.warning("%s; proceeding to synthesis.", fallback_reason.capitalize())
                critique = fallback_critique(fallback_reason)

        follow_ups = [
            q.strip()
            for q in critique.follow_up_queries
            if q.strip() and q.strip() not in executed
        ][: self._max_follow_up_queries]

        if critique.decision is CriticDecision.MORE_RESEARCH:
            logger.info("Critic requested additional research (score %d/10).",
                        critique.overall_score)
        else:
            logger.info("Critic deemed evidence sufficient (score %d/10).",
                        critique.overall_score)
        return {
            "critique": critique,
            "pending_queries": follow_ups,
            "critic_fallback": fallback_reason,
        }

    def _budget_exhausted(self) -> bool:
        if self._deadline is None:
            return False
        return (self._deadline - awake_clock()) < self._min_seconds_required


def route_after_critic(state: AtlasState) -> str:
    """Deterministic conditional routing after the critic node.

    Continues research only when the critic asked for it, follow-up queries
    exist, and the iteration budget is not exhausted.
    """
    critique = state.get("critique")
    iteration = state.get("iteration", 0)
    max_iterations = state.get("max_iterations", 1)
    if (
        critique is not None
        and critique.decision is CriticDecision.MORE_RESEARCH
        and state.get("pending_queries")
        and iteration < max_iterations
    ):
        return "researcher"
    if critique is not None and critique.decision is CriticDecision.MORE_RESEARCH:
        logger.info(
            "Iteration budget exhausted (%d/%d); synthesizing with best evidence.",
            iteration,
            max_iterations,
        )
    return "synthesizer"
