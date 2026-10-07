"""Typed progress events for research runs.

Events describe workflow state transitions only — never model reasoning or
other private content. Payloads are small, explicitly whitelisted dicts.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from src.models.runs import utcnow


class EventType(str, Enum):
    RUN_STARTED = "RUN_STARTED"
    PLANNING_STARTED = "PLANNING_STARTED"
    PLANNING_REPAIR_STARTED = "PLANNING_REPAIR_STARTED"
    PLAN_CREATED = "PLAN_CREATED"
    WAITING_FOR_PLAN_APPROVAL = "WAITING_FOR_PLAN_APPROVAL"
    PLAN_APPROVED = "PLAN_APPROVED"
    PLAN_EDITED = "PLAN_EDITED"
    SEARCH_STARTED = "SEARCH_STARTED"
    SEARCH_QUERY_STARTED = "SEARCH_QUERY_STARTED"
    SEARCH_QUERY_COMPLETED = "SEARCH_QUERY_COMPLETED"
    EVIDENCE_COLLECTED = "EVIDENCE_COLLECTED"
    CRITIC_STARTED = "CRITIC_STARTED"
    CRITIC_COMPLETED = "CRITIC_COMPLETED"
    MORE_RESEARCH_REQUESTED = "MORE_RESEARCH_REQUESTED"
    SYNTHESIS_STARTED = "SYNTHESIS_STARTED"
    CITATION_REPAIR_STARTED = "CITATION_REPAIR_STARTED"
    CITATION_REPAIR_COMPLETED = "CITATION_REPAIR_COMPLETED"
    RUN_COMPLETED = "RUN_COMPLETED"
    RUN_FAILED = "RUN_FAILED"
    RUN_CANCELLED = "RUN_CANCELLED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    # V3 additions (additive; old persisted events replay unchanged).
    PAGE_FETCH_STARTED = "PAGE_FETCH_STARTED"
    PAGE_FETCH_COMPLETED = "PAGE_FETCH_COMPLETED"
    PAGE_FETCH_FAILED = "PAGE_FETCH_FAILED"
    REPORT_REGENERATED = "REPORT_REGENERATED"
    FOLLOWUP_STARTED = "FOLLOWUP_STARTED"
    FOLLOWUP_COMPLETED = "FOLLOWUP_COMPLETED"
    FOLLOWUP_FAILED = "FOLLOWUP_FAILED"
    COMPARISON_STARTED = "COMPARISON_STARTED"
    COMPARISON_COMPLETED = "COMPARISON_COMPLETED"
    COMPARISON_FAILED = "COMPARISON_FAILED"
    KNOWLEDGE_GRAPH_STARTED = "KNOWLEDGE_GRAPH_STARTED"
    KNOWLEDGE_GRAPH_COMPLETED = "KNOWLEDGE_GRAPH_COMPLETED"
    KNOWLEDGE_GRAPH_FAILED = "KNOWLEDGE_GRAPH_FAILED"

    @property
    def is_terminal(self) -> bool:
        return self in (
            EventType.RUN_COMPLETED,
            EventType.RUN_FAILED,
            EventType.RUN_CANCELLED,
            EventType.FOLLOWUP_COMPLETED,
            EventType.FOLLOWUP_FAILED,
            EventType.COMPARISON_COMPLETED,
            EventType.COMPARISON_FAILED,
            EventType.KNOWLEDGE_GRAPH_COMPLETED,
            EventType.KNOWLEDGE_GRAPH_FAILED,
        )


class RunEvent(BaseModel):
    """One progress event on a research run."""

    type: EventType
    run_id: str
    seq: int = 0
    timestamp: datetime = Field(default_factory=utcnow)
    agent: str = ""
    message: str = ""
    iteration: int = 0
    payload: dict = Field(default_factory=dict)
