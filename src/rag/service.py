"""Document ingestion and retrieval service.

Upload safety: extension + size validation, sanitized filenames, content
checksum, and raw files stored under the configured upload directory with
server-generated names (no client path is ever used for filesystem access).
Document text is always treated as untrusted evidence, never instructions.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re

from src.config import AtlasConfig
from src.models.documents import DocumentRecord, DocumentStatus
from src.models.research import Evidence, EvidenceOrigin, Source
from src.persistence.documents import DocumentsRepository
from src.rag.chunking import chunk_pages
from src.rag.embeddings import EmbedFn
from src.rag.extract import ExtractionError, extract_pages, file_type_for

logger = logging.getLogger(__name__)


class UploadError(Exception):
    """User-facing upload validation failure."""


def sanitize_filename(filename: str) -> str:
    """Keep only the base name with safe characters (no path traversal)."""
    base = os.path.basename(filename.replace("\\", "/")).strip()
    base = re.sub(r"[^A-Za-z0-9._ -]", "_", base)
    return base[:120] or "document"


def document_source(doc: DocumentRecord, page: int | None) -> Source:
    """Deterministic Source for a document chunk (doc:// provenance URL)."""
    suffix = f"#p{page}" if page else ""
    return Source(
        title=doc.filename if not page else f"{doc.filename}, p. {page}",
        url=f"doc://{doc.id}{suffix}",
        domain="document",
        kind="document",
        document_id=doc.id,
        filename=doc.filename,
        page=page,
    )


class DocumentService:
    def __init__(
        self,
        config: AtlasConfig,
        repo: DocumentsRepository,
        embed_fn: EmbedFn,
    ) -> None:
        self._config = config
        self._repo = repo
        self._embed = embed_fn

    # -- ingestion ---------------------------------------------------------

    def ingest(self, filename: str, data: bytes, content_type: str = "") -> DocumentRecord:
        safe_name = sanitize_filename(filename)
        max_bytes = self._config.max_upload_mb * 1024 * 1024
        if not data:
            raise UploadError("The uploaded file is empty.")
        if len(data) > max_bytes:
            raise UploadError(
                f"File exceeds the {self._config.max_upload_mb} MB upload limit."
            )
        try:
            file_type = file_type_for(safe_name)
        except ExtractionError as exc:
            raise UploadError(str(exc)) from exc

        checksum = hashlib.sha256(data).hexdigest()
        existing = self._repo.find_by_checksum(checksum)
        if existing is not None and existing.status is DocumentStatus.READY:
            logger.info("Document %s already ingested; reusing.", safe_name)
            return existing

        doc = DocumentRecord(
            filename=safe_name,
            content_type=content_type,
            file_type=file_type,
            size_bytes=len(data),
            checksum=checksum,
        )
        self._repo.save(doc)
        self._store_raw(doc, data)
        try:
            pages = extract_pages(data, file_type)
            chunks = chunk_pages(
                doc.id,
                pages,
                chunk_size=self._config.chunk_size_chars,
                overlap=self._config.chunk_overlap_chars,
            )
            if not chunks:
                raise ExtractionError("No usable text chunks were produced.")
            embeddings = self._embed([c.content for c in chunks])
            self._repo.save_chunks(chunks, embeddings)
            doc.status = DocumentStatus.READY
            doc.chunk_count = len(chunks)
            doc.page_count = len([p for p, _ in pages if p is not None]) or 1
            self._repo.save(doc)
            logger.info(
                "Ingested %s: %d chunks, %d page(s).",
                safe_name,
                doc.chunk_count,
                doc.page_count,
            )
        except ExtractionError as exc:
            doc.status = DocumentStatus.FAILED
            doc.error = str(exc)
            self._repo.save(doc)
            raise UploadError(str(exc)) from exc
        except Exception as exc:
            doc.status = DocumentStatus.FAILED
            doc.error = f"Processing failed: {exc}"
            self._repo.save(doc)
            raise
        return doc

    def _store_raw(self, doc: DocumentRecord, data: bytes) -> None:
        os.makedirs(self._config.upload_dir, exist_ok=True)
        path = os.path.join(self._config.upload_dir, f"{doc.id}.{doc.file_type}")
        with open(path, "wb") as fh:
            fh.write(data)

    def delete(self, document_id: str) -> bool:
        doc = self._repo.get(document_id)
        removed = self._repo.delete(document_id)
        if doc is not None:
            path = os.path.join(
                self._config.upload_dir, f"{document_id}.{doc.file_type}"
            )
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                logger.warning("Could not remove stored file for %s.", document_id)
        return removed

    # -- retrieval ---------------------------------------------------------

    def retrieve(
        self, query: str, document_ids: list[str], top_k: int | None = None
    ) -> list[Evidence]:
        """Retrieve the most relevant chunks as document Evidence."""
        ready_ids = [
            d.id
            for d in (self._repo.get(i) for i in document_ids)
            if d is not None and d.status is DocumentStatus.READY
        ]
        if not ready_ids:
            return []
        k = top_k or self._config.rag_chunks_per_query
        try:
            query_vec = self._embed([query])[0]
        except Exception:
            logger.warning("Embedding failed for query %r; skipping documents.",
                           query, exc_info=True)
            return []
        results = self._repo.search_chunks(query_vec, ready_ids, k)
        evidence: list[Evidence] = []
        docs = {i: self._repo.get(i) for i in ready_ids}
        for chunk, score in results:
            doc = docs.get(chunk.document_id)
            if doc is None:
                continue
            evidence.append(
                Evidence(
                    source=document_source(doc, chunk.page),
                    content=chunk.content,
                    query=query,
                    relevance_score=score,
                    origin=EvidenceOrigin.DOCUMENT,
                )
            )
        return evidence
