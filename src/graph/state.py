"""Typed LangGraph state for the Atlas workflow."""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from src.models.research import Critique, Evidence, ResearchPlan


class AtlasState(TypedDict, total=False):
    """State threaded through the Atlas research graph.

    ``evidence`` accumulates across iterations via the ``operator.add``
    reducer; researcher nodes return only the *new, already-deduplicated*
    items. ``seen_urls`` is replaced wholesale each iteration. Counter
    fields with ``operator.add`` accumulate per-iteration metrics.
    """

    question: str
    plan: ResearchPlan
    pending_queries: list[str]
    executed_queries: Annotated[list[str], operator.add]
    evidence: Annotated[list[Evidence], operator.add]
    seen_urls: set[str]
    critique: Critique
    iteration: int
    max_iterations: int
    final_report: str
    error: str
    # V2 metric accumulators (populated by instrumented nodes/agents).
    memory_hits: Annotated[int, operator.add]
    document_chunks_retrieved: Annotated[int, operator.add]
    web_sources_new: Annotated[int, operator.add]
    pages_attempted: Annotated[int, operator.add]
    pages_fetched: Annotated[int, operator.add]
    pages_failed: Annotated[int, operator.add]
    snippet_fallbacks: Annotated[int, operator.add]
    node_timings: Annotated[list[dict], operator.add]
    citation_repair_ms: Annotated[int, operator.add]
    sources_selected: int
    sources_cited: int
    planner_attempts: int
    # Performance-budget outcomes (never silent: surfaced in metrics/events).
    critic_fallback: str
    synthesis_fallback: bool
    synthesis_fallback_reason: str
    repair_skipped: bool
