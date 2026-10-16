"""Website Chat models: an indexed website, its pages/chunks, conversations.

A ``WebsiteSource`` is either ONE submitted webpage (``SINGLE``, the V1
behaviour and still the default) or a user-selected, bounded set of same-site
pages (``SITE``). It is never an open-ended crawl. Its extracted
text is split into ``WebsiteChunk`` rows that carry section provenance, and
every Atlas answer cites those chunks. Generated text lives in conversations
(each with its own ``output_language``); the website record itself only
stores the source's content language as declared by the page.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from src.models.runs import utcnow
from src.models.workspace import new_id


class WebsiteStatus(str, Enum):
    PENDING = "PENDING"
    FETCHING = "FETCHING"
    EXTRACTING = "EXTRACTING"
    CHUNKING = "CHUNKING"
    EMBEDDING = "EMBEDDING"
    READY = "READY"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

    @property
    def is_active(self) -> bool:
        return self in _ACTIVE


_ACTIVE = {
    WebsiteStatus.PENDING,
    WebsiteStatus.FETCHING,
    WebsiteStatus.EXTRACTING,
    WebsiteStatus.CHUNKING,
    WebsiteStatus.EMBEDDING,
}


class WebsiteMode(str, Enum):
    #: Exactly the V1 behaviour: the one submitted page.
    SINGLE = "SINGLE"
    #: A bounded, user-selected set of same-site pages.
    SITE = "SITE"


class PageStatus(str, Enum):
    INDEXED = "INDEXED"
    FAILED = "FAILED"


class WebsitePage(BaseModel):
    """One page of a SITE-mode website, versioned together with its chunks."""

    id: str = Field(default_factory=new_id)
    website_id: str
    index_version: int
    #: Stable user-selection order; also the tiebreaker everywhere.
    position: int
    url: str
    final_url: str = ""
    title: str = ""
    status: PageStatus = PageStatus.INDEXED
    error: str = ""
    error_code: str = ""
    content_hash: str = ""
    content_language: str = ""
    word_count: int = 0
    chunk_count: int = 0
    fetched_at: datetime | None = None


class WebsiteSource(BaseModel):
    id: str = Field(default_factory=new_id)
    submitted_url: str
    normalized_url: str
    final_url: str = ""
    page_title: str = ""
    domain: str = ""
    status: WebsiteStatus = WebsiteStatus.PENDING
    #: Hash of the cleaned meaningful content of the current index.
    content_hash: str = ""
    #: Language the page declares (``<html lang>``), e.g. "en"; "" if absent.
    content_language: str = ""
    word_count: int = 0
    chunk_count: int = 0
    #: Version of the live chunk set; 0 = never indexed. Refreshes write a new
    #: version and swap it in atomically.
    index_version: int = 0
    error: str = ""
    #: Stable machine code for ``error`` (the UI translates it).
    error_code: str = ""
    fetched_at: datetime | None = None
    indexed_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    #: Per-stage ingestion timings and counts (no LLM calls, ever).
    metrics: dict = Field(default_factory=dict)
    #: SINGLE (V1, default) or SITE (bounded multi-page). Never changes.
    mode: WebsiteMode = WebsiteMode.SINGLE
    #: Successfully indexed pages of the live version (0 for SINGLE mode).
    page_count: int = 0

    @property
    def is_indexed(self) -> bool:
        return self.index_version > 0


class WebsiteChunk(BaseModel):
    id: str = Field(default_factory=new_id)
    website_id: str
    index_version: int
    chunk_index: int
    section_title: str = ""
    #: Heading trail, e.g. ["Battery report", "Results"].
    heading_path: list[str] = Field(default_factory=list)
    text: str
    #: Character offsets into the cleaned page text (provenance).
    char_start: int = 0
    char_end: int = 0
    #: SITE mode: which page this chunk came from ("" for SINGLE-mode chunks).
    page_id: str = ""
    page_url: str = ""
    page_title: str = ""


class WebsiteConversation(BaseModel):
    id: str = Field(default_factory=new_id)
    website_id: str
    title: str = ""
    #: Authoritative for every answer in this conversation; the UI language
    #: never changes it.
    output_language: str = "en"
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"


class MessageStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class AnswerStage(str, Enum):
    """What a PENDING answer is doing right now (real backend steps only)."""

    QUEUED = ""
    RETRIEVING = "RETRIEVING"
    GENERATING = "GENERATING"
    VALIDATING = "VALIDATING"


class WebsiteCitation(BaseModel):
    """One [n] marker of an answer, frozen at answer time.

    The passage text is a snapshot, so a citation keeps showing the exact
    text it was based on even after the page is re-indexed.
    """

    index: int
    chunk_id: str
    index_version: int
    chunk_index: int
    section_title: str = ""
    heading_path: list[str] = Field(default_factory=list)
    text: str
    score: float = 0.0
    url: str = ""
    page_title: str = ""


class WebsiteMessage(BaseModel):
    id: str = Field(default_factory=new_id)
    conversation_id: str
    seq: int = 0
    role: MessageRole
    content: str = ""
    status: MessageStatus = MessageStatus.COMPLETED
    #: Current step of a PENDING answer, persisted so a page refresh shows it.
    stage: AnswerStage = AnswerStage.QUEUED
    error: str = ""
    error_code: str = ""
    #: True when the page did not contain enough evidence to answer.
    insufficient_evidence: bool = False
    #: Numbered excerpts shown to the model; ``cited`` lists the ones used.
    citations: list[WebsiteCitation] = Field(default_factory=list)
    cited: list[int] = Field(default_factory=list)
    output_language: str = "en"
    metrics: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)
    completed_at: datetime | None = None
