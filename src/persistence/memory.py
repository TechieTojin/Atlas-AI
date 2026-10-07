"""Repository for research evidence memory (cross-run evidence reuse).

V3: rows are scoped to a project (``''`` = global), and each row can carry a
query embedding so semantically similar queries can reuse evidence. Exact
normalized-query matching remains the fast path.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import timedelta

import numpy as np

from src.models.research import Evidence, normalize_url
from src.models.runs import utcnow
from src.persistence.db import Database, PersistenceError


def normalize_query(query: str) -> str:
    """Deterministic query key: lowercase, collapsed whitespace."""
    return " ".join(query.lower().split())


def _to_blob(vector: list[float] | None) -> bytes | None:
    if vector is None:
        return None
    return np.asarray(vector, dtype=np.float32).tobytes()


class MemoryRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def store(
        self,
        query: str,
        evidence_items: list[Evidence],
        project_id: str = "",
        embedding: list[float] | None = None,
    ) -> int:
        """Store evidence found by a query; replaces stale rows per key."""
        q = normalize_query(query)
        blob = _to_blob(embedding)
        stored = 0
        conn = self._db.connect()
        try:
            with self._db.write_lock:
                for item in evidence_items:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO memory
                            (query_norm, url_norm, project_id, origin,
                             fetched_at, evidence, embedding)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            q,
                            normalize_url(item.source.url),
                            project_id,
                            item.origin.value,
                            utcnow().isoformat(),
                            item.model_dump_json(),
                            blob,
                        ),
                    )
                    stored += 1
                conn.commit()
        except sqlite3.Error as exc:
            raise PersistenceError(f"Failed to store memory: {exc}") from exc
        finally:
            self._db.release(conn)
        return stored

    def _scope_clause(self, project_id: str) -> tuple[str, list]:
        # Project scope sees its own rows plus global rows.
        if project_id:
            return "project_id IN (?, '')", [project_id]
        return "project_id = ''", []

    def lookup(
        self, query: str, ttl_hours: int, limit: int = 10, project_id: str = ""
    ) -> list[Evidence]:
        """Fresh evidence previously collected for this exact normalized query.

        Web evidence expires after ``ttl_hours`` (0 disables reuse); document
        evidence stays reusable until its document is removed.
        """
        if ttl_hours <= 0:
            return []
        cutoff = (utcnow() - timedelta(hours=ttl_hours)).isoformat()
        scope_sql, scope_params = self._scope_clause(project_id)
        conn = self._db.connect()
        try:
            rows = conn.execute(
                f"""
                SELECT evidence FROM memory
                WHERE query_norm = ? AND {scope_sql}
                  AND (origin != 'web' OR fetched_at >= ?)
                ORDER BY fetched_at DESC LIMIT ?
                """,
                (normalize_query(query), *scope_params, cutoff, limit),
            ).fetchall()
        except sqlite3.Error as exc:
            raise PersistenceError(f"Failed to query memory: {exc}") from exc
        finally:
            self._db.release(conn)
        return [Evidence.model_validate(json.loads(r["evidence"])) for r in rows]

    def lookup_semantic(
        self,
        query_embedding: list[float],
        ttl_hours: int,
        threshold: float,
        limit: int = 10,
        project_id: str = "",
        exclude_query: str = "",
    ) -> list[tuple[Evidence, float]]:
        """Evidence whose originating query is semantically similar.

        Deterministic NumPy cosine scan over stored query embeddings, ordered
        by similarity (ties by recency); rows below ``threshold`` are missed
        on purpose.
        """
        if ttl_hours <= 0 or not query_embedding:
            return []
        cutoff = (utcnow() - timedelta(hours=ttl_hours)).isoformat()
        scope_sql, scope_params = self._scope_clause(project_id)
        conn = self._db.connect()
        try:
            rows = conn.execute(
                f"""
                SELECT evidence, embedding, fetched_at FROM memory
                WHERE embedding IS NOT NULL AND query_norm != ? AND {scope_sql}
                  AND (origin != 'web' OR fetched_at >= ?)
                """,
                (normalize_query(exclude_query), *scope_params, cutoff),
            ).fetchall()
        except sqlite3.Error as exc:
            raise PersistenceError(f"Failed to query memory: {exc}") from exc
        finally:
            self._db.release(conn)
        if not rows:
            return []
        q = np.asarray(query_embedding, dtype=np.float32)
        q_norm = float(np.linalg.norm(q))
        if q_norm == 0:
            return []
        scored = []
        for row in rows:
            vec = np.frombuffer(row["embedding"], dtype=np.float32)
            if vec.size != q.size:
                continue
            denom = float(np.linalg.norm(vec)) * q_norm
            sim = float(np.dot(vec, q) / denom) if denom else 0.0
            if sim >= threshold:
                scored.append((row, sim))
        scored.sort(key=lambda pair: (-pair[1], pair[0]["fetched_at"]))
        return [
            (Evidence.model_validate(json.loads(row["evidence"])), sim)
            for row, sim in scored[:limit]
        ]

    def delete_document_evidence(self, document_id: str) -> None:
        """Remove memory rows whose evidence came from a deleted document."""
        conn = self._db.connect()
        try:
            with self._db.write_lock:
                conn.execute(
                    "DELETE FROM memory WHERE url_norm LIKE ?",
                    (f"doc://{document_id}%",),
                )
                conn.commit()
        except sqlite3.Error as exc:
            raise PersistenceError(f"Failed to prune memory: {exc}") from exc
        finally:
            self._db.release(conn)

    def delete_project_memory(self, project_id: str) -> None:
        if not project_id:
            return
        conn = self._db.connect()
        try:
            with self._db.write_lock:
                conn.execute("DELETE FROM memory WHERE project_id = ?", (project_id,))
                conn.commit()
        finally:
            self._db.release(conn)
