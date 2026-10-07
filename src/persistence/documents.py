"""Repository for uploaded documents and their embedded chunks."""

from __future__ import annotations

import sqlite3

import numpy as np

from src.models.documents import DocumentChunk, DocumentRecord, DocumentStatus
from src.persistence.db import Database, PersistenceError


def _to_blob(vector: list[float] | None) -> bytes | None:
    if vector is None:
        return None
    return np.asarray(vector, dtype=np.float32).tobytes()


def _from_blob(blob: bytes | None) -> np.ndarray | None:
    if blob is None:
        return None
    return np.frombuffer(blob, dtype=np.float32)


class DocumentsRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def save(self, doc: DocumentRecord) -> None:
        conn = self._db.connect()
        try:
            with self._db.write_lock:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO documents
                        (id, filename, content_type, file_type, size_bytes, checksum,
                         status, error, chunk_count, page_count, project_id, uploaded_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        doc.id,
                        doc.filename,
                        doc.content_type,
                        doc.file_type,
                        doc.size_bytes,
                        doc.checksum,
                        doc.status.value,
                        doc.error,
                        doc.chunk_count,
                        doc.page_count,
                        doc.project_id,
                        doc.uploaded_at.isoformat(),
                    ),
                )
                conn.commit()
        except sqlite3.Error as exc:
            raise PersistenceError(f"Failed to save document: {exc}") from exc
        finally:
            self._db.release(conn)

    def get(self, document_id: str) -> DocumentRecord | None:
        conn = self._db.connect()
        try:
            row = conn.execute(
                "SELECT * FROM documents WHERE id = ?", (document_id,)
            ).fetchone()
        finally:
            self._db.release(conn)
        return DocumentRecord.model_validate(dict(row)) if row else None

    def list(self, project_id: str | None = None) -> list[DocumentRecord]:
        where = ""
        params: list = []
        if project_id is not None:
            # A project sees its own documents plus global (unassigned) ones.
            where = "WHERE project_id IN (?, '')" if project_id else "WHERE project_id = ''"
            params = [project_id] if project_id else []
        conn = self._db.connect()
        try:
            rows = conn.execute(
                f"SELECT * FROM documents {where} ORDER BY uploaded_at DESC", params
            ).fetchall()
        finally:
            self._db.release(conn)
        return [DocumentRecord.model_validate(dict(r)) for r in rows]

    def set_project(self, document_id: str, project_id: str) -> bool:
        conn = self._db.connect()
        try:
            with self._db.write_lock:
                cur = conn.execute(
                    "UPDATE documents SET project_id = ? WHERE id = ?",
                    (project_id, document_id),
                )
                conn.commit()
                return cur.rowcount > 0
        finally:
            self._db.release(conn)

    def find_by_checksum(self, checksum: str) -> DocumentRecord | None:
        conn = self._db.connect()
        try:
            row = conn.execute(
                "SELECT * FROM documents WHERE checksum = ?", (checksum,)
            ).fetchone()
        finally:
            self._db.release(conn)
        return DocumentRecord.model_validate(dict(row)) if row else None

    def delete(self, document_id: str) -> bool:
        conn = self._db.connect()
        try:
            with self._db.write_lock:
                cur = conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
                conn.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
                conn.commit()
                return cur.rowcount > 0
        except sqlite3.Error as exc:
            raise PersistenceError(f"Failed to delete document: {exc}") from exc
        finally:
            self._db.release(conn)

    def set_status(
        self, document_id: str, status: DocumentStatus, error: str = ""
    ) -> None:
        conn = self._db.connect()
        try:
            with self._db.write_lock:
                conn.execute(
                    "UPDATE documents SET status = ?, error = ? WHERE id = ?",
                    (status.value, error, document_id),
                )
                conn.commit()
        finally:
            self._db.release(conn)

    # -- chunks / vectors -------------------------------------------------

    def save_chunks(
        self, chunks: list[DocumentChunk], embeddings: list[list[float]]
    ) -> None:
        if len(chunks) != len(embeddings):
            raise PersistenceError("Chunk/embedding count mismatch.")
        conn = self._db.connect()
        try:
            with self._db.write_lock:
                for chunk, vector in zip(chunks, embeddings):
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO chunks
                            (document_id, chunk_index, page, content, embedding)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            chunk.document_id,
                            chunk.chunk_index,
                            chunk.page,
                            chunk.content,
                            _to_blob(vector),
                        ),
                    )
                conn.commit()
        except sqlite3.Error as exc:
            raise PersistenceError(f"Failed to save chunks: {exc}") from exc
        finally:
            self._db.release(conn)

    def search_chunks(
        self,
        query_embedding: list[float],
        document_ids: list[str],
        top_k: int,
    ) -> list[tuple[DocumentChunk, float]]:
        """Cosine-similarity search over the given documents' chunks.

        Local document counts are small, so a NumPy scan over SQLite-stored
        vectors is simple, deterministic, and dependency-light — no external
        vector database needed for this workload.
        """
        if not document_ids:
            return []
        placeholders = ",".join("?" for _ in document_ids)
        conn = self._db.connect()
        try:
            rows = conn.execute(
                f"SELECT * FROM chunks WHERE document_id IN ({placeholders})",
                document_ids,
            ).fetchall()
        finally:
            self._db.release(conn)
        if not rows:
            return []

        q = np.asarray(query_embedding, dtype=np.float32)
        q_norm = np.linalg.norm(q)
        if q_norm == 0:
            return []
        scored: list[tuple[DocumentChunk, float]] = []
        for row in rows:
            vec = _from_blob(row["embedding"])
            if vec is None or vec.size != q.size:
                continue
            denom = float(np.linalg.norm(vec)) * float(q_norm)
            score = float(np.dot(vec, q) / denom) if denom else 0.0
            scored.append(
                (
                    DocumentChunk(
                        document_id=row["document_id"],
                        chunk_index=row["chunk_index"],
                        page=row["page"],
                        content=row["content"],
                    ),
                    score,
                )
            )
        scored.sort(key=lambda pair: -pair[1])
        return scored[:top_k]
