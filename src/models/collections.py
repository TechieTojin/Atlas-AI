"""Collections (research notebooks): user-curated references to Atlas truth.

A collection organises SELECTED knowledge — evidence excerpts, sources,
documents, website passages, runs — plus the user's own notes. Items keep a
stable reference to their origin AND a frozen snapshot of what was saved
(title/text/provenance), so a notebook stays readable even when the original
is later deleted; the UI then says the origin is gone instead of pretending.

A user note is always labelled a note. It is never presented as evidence.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from src.models.runs import utcnow
from src.models.workspace import new_id

#: Longest allowed user note / item annotation.
MAX_NOTE_CHARS = 4000


class CollectionItemType(str, Enum):
    RUN = "run"
    SOURCE = "source"
    EVIDENCE = "evidence"
    DOCUMENT = "document"
    DOCUMENT_PASSAGE = "document_passage"
    WEBSITE_PASSAGE = "website_passage"
    NOTE = "note"


class Collection(BaseModel):
    id: str = Field(default_factory=new_id)
    title: str
    description: str = ""
    project_id: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class CollectionItem(BaseModel):
    id: str = Field(default_factory=new_id)
    collection_id: str
    type: CollectionItemType
    #: Stable order inside the collection (insertion order).
    position: int = 0
    #: The user's own words about this item ("" for none). For NOTE items this
    #: IS the content.
    note: str = ""
    #: Frozen snapshot + origin reference. Keys depend on ``type``; typical:
    #: title, text, citation, url, domain, filename, page, section,
    #: run_id, document_id, website_id, conversation_id, message_id, quality.
    data: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)

    def reference_key(self) -> str:
        """Duplicate detection: the same origin saved twice is one item."""
        d = self.data
        parts = [
            self.type.value,
            str(d.get("run_id", "")),
            str(d.get("document_id", "")),
            str(d.get("website_id", "")),
            str(d.get("url", "")),
            str(d.get("page", "")),
            str(d.get("citation", "")),
            str(d.get("text", ""))[:200],
        ]
        return "\x1f".join(parts)
