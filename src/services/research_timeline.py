"""Research Timeline: what happened during one run, in chronological order.

The Research Map answers "how are the stages connected?"; the timeline
answers "what happened, and when?". Both are deterministic views over the
SAME stored truth — the persisted run and its event log. Nothing is
re-interpreted, estimated or generated: an entry exists only because an event
was recorded, and replay (in the UI) just steps through these entries.
No LLM, embedding or network call is ever made here.
"""

from __future__ import annotations

from typing import Any

from src.events.models import RunEvent
from src.models.runs import ResearchRun

#: Payload fields worth showing per event type (everything else is dropped so
#: the response stays small; the full payload remains in the events table).
_DETAIL_FIELDS: dict[str, tuple[str, ...]] = {
    "PLAN_CREATED": ("subquestions", "queries"),
    "PLAN_EDITED": ("subquestions", "queries"),
    "SEARCH_STARTED": ("queries",),
    "SEARCH_QUERY_STARTED": ("query", "position", "total"),
    "SEARCH_QUERY_COMPLETED": ("query", "results", "memory_hits", "document_chunks"),
    "EVIDENCE_COLLECTED": ("new_items", "total_items", "memory_hits", "document_chunks"),
    "PAGE_FETCH_STARTED": ("url",),
    "PAGE_FETCH_COMPLETED": ("url", "chunks"),
    "PAGE_FETCH_FAILED": ("url",),
    "CRITIC_COMPLETED": ("score", "decision", "fallback"),
    "MORE_RESEARCH_REQUESTED": ("follow_up_queries",),
    "CITATION_REPAIR_COMPLETED": ("cited", "succeeded"),
    "RUN_COMPLETED": ("cited", "total_ms"),
    "PLANNING_REPAIR_STARTED": ("problems",),
    "RUN_STARTED": ("mode", "source_scope"),
}


def _detail(event: RunEvent) -> dict[str, Any]:
    fields = _DETAIL_FIELDS.get(str(event.type.value), ())
    out = {k: event.payload.get(k) for k in fields if k in event.payload}
    # Failure text is the stored message; it is shown as stored.
    if event.type.value in ("RUN_FAILED", "RUN_CANCELLED") and event.message:
        out["message"] = event.message
    return out


def build_timeline(run: ResearchRun, events: list[RunEvent]) -> dict[str, Any]:
    """Chronological entries for one run. Pure function of stored data."""
    events = sorted(
        (e for e in events if e.run_id == run.id),
        key=lambda e: (e.timestamp, e.seq),
    )
    origin = events[0].timestamp if events else (run.started_at or run.created_at)
    entries = [
        {
            "seq": event.seq,
            "at": event.timestamp.isoformat(),
            "offset_ms": max(0, int((event.timestamp - origin).total_seconds() * 1000)),
            "kind": event.type.value,
            "agent": event.agent,
            "iteration": event.iteration,
            "detail": _detail(event),
        }
        for event in events
    ]
    duration_ms = None
    if run.started_at and run.completed_at:
        duration_ms = max(0, int((run.completed_at - run.started_at).total_seconds() * 1000))
    return {
        "run_id": run.id,
        "run_status": run.status.value,
        "question": run.query,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "duration_ms": duration_ms,
        "entries": entries,
        "iterations": run.iterations or None,
        #: True when this (historical) run has no recorded events: the UI says
        #: so instead of inventing a chronology.
        "incomplete": not entries,
    }
