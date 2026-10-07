"""Document models for private-document (RAG) research."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field

from src.models.runs import utcnow


def new_document_id() -> str:
    return uuid4().hex


class DocumentStatus(str, Enum):
    PROCESSING = "PROCESSING"
    READY = "READY"
    FAILED = "FAILED"


class DocumentRecord(BaseModel):
    """Metadata for one uploaded document."""

    id: str = Field(default_factory=new_document_id)
    filename: str
    content_type: str = ""
    file_type: str = ""  # pdf | txt | md
    size_bytes: int = 0
    checksum: str = ""
    status: DocumentStatus = DocumentStatus.PROCESSING
    error: str = ""
    chunk_count: int = 0
    page_count: int = 0
    project_id: str = ""
    uploaded_at: datetime = Field(default_factory=utcnow)


class DocumentChunk(BaseModel):
    """One embedded chunk of an uploaded document."""

    document_id: str
    chunk_index: int
    page: int | None = None
    content: str
