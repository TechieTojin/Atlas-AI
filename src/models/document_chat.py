"""Document chat models: grounded conversations over SELECTED documents.

A conversation freezes its document scope at creation; every answer cites
exact stored passages (document, page, excerpt). Message lifecycle, stages
and statuses are shared with Website Chat so the UI and recovery logic treat
both the same way.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from src.models.runs import utcnow
from src.models.websites import AnswerStage, MessageRole, MessageStatus
from src.models.workspace import new_id

__all__ = [
    "AnswerStage",
    "DocumentCitation",
    "DocumentConversation",
    "DocumentChatMessage",
    "MessageRole",
    "MessageStatus",
]


class DocumentConversation(BaseModel):
    id: str = Field(default_factory=new_id)
    title: str = ""
    #: Frozen scope: the documents this conversation may answer from.
    document_ids: list[str] = Field(default_factory=list)
    #: Authoritative for every answer in this conversation.
    output_language: str = "en"
    project_id: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class DocumentCitation(BaseModel):
    """One [n] marker of an answer, frozen at answer time."""

    index: int
    document_id: str
    filename: str = ""
    #: 1-based page in the original document; None when the format has no pages.
    page: int | None = None
    #: The exact stored passage the model was shown (verbatim snapshot).
    text: str
    score: float = 0.0


class DocumentChatMessage(BaseModel):
    id: str = Field(default_factory=new_id)
    conversation_id: str
    seq: int = 0
    role: MessageRole
    content: str = ""
    status: MessageStatus = MessageStatus.COMPLETED
    #: Current step of a PENDING answer (survives a page refresh).
    stage: AnswerStage = AnswerStage.QUEUED
    error: str = ""
    error_code: str = ""
    insufficient_evidence: bool = False
    citations: list[DocumentCitation] = Field(default_factory=list)
    cited: list[int] = Field(default_factory=list)
    output_language: str = "en"
    metrics: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)
    completed_at: datetime | None = None
