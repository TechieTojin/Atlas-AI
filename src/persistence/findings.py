"""Repository for project research memory (cited findings + embeddings)."""

from __future__ import annotations

import json
import sqlite3

import numpy as np

from src.models.memory import FindingSource, ProjectFinding
from src.persistence.db import Database, PersistenceError


def _to_blob(vector: list[float] | None) -> bytes | None:
    if vector is None:
        return None
    return np.asarray(vector, dtype=np.float32).tobytes()


def _row_to_finding(row: sqlite3.Row) -> ProjectFinding:
    return ProjectFinding(
        id=row["id"],
        project_id=row["project_id"],
        run_id=row["run_id"],
        question=row["question"],
        section=row["section"],
        text=row["text"],
        sources=[FindingSource.model_validate(s) for s in json.loads(row["sources"])],
        created_at=row["created_at"],
    )


class FindingsRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def add_many(
        self, findings: list[ProjectFinding], embeddings: list[list[float]] | None = None
    ) -> int:
        """Insert findings, ignoring ones already stored for this project.

        The (project_id, text_norm) unique constraint makes storing
        idempotent, so re-indexing a run never duplicates its findings.
        """
        if not findings:
            return 0
        vectors = embeddings or [None] * len(findings)
        conn = self._db.connect()
        added = 0
        try:
            with self._db.write_lock:
                for finding, vector in zip(findings, vectors):
                    cur = conn.execute(
                        """
                        INSERT OR IGNORE INTO project_findings
                            (id, project_id, run_id, question, section, text,
                             text_norm, sources, created_at, embedding)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            finding.id,
                            finding.project_id,
                            finding.run_id,
                            finding.question,
                            finding.section,
                            finding.text,
                            finding.text_norm,
                            json.dumps([s.model_dump() for s in finding.sources]),
                            finding.created_at.isoformat(),
                            _to_blob(vector),
                        ),
                    )
                    added += cur.rowcount
                conn.commit()
        except sqlite3.Error as exc:
            raise PersistenceError(f"Failed to store project findings: {exc}") from exc
        finally:
            self._db.release(conn)
        return added

    def set_embedding(self, finding_id: str, vector: list[float]) -> None:
        conn = self._db.connect()
        try:
            with self._db.write_lock:
                conn.execute(
                    "UPDATE project_findings SET embedding = ? WHERE id = ?",
                    (_to_blob(vector), finding_id),
                )
                conn.commit()
        finally:
            self._db.release(conn)

    def list_for_project(self, project_id: str) -> list[ProjectFinding]:
        conn = self._db.connect()
        try:
            rows = conn.execute(
                "SELECT * FROM project_findings WHERE project_id = ? ORDER BY created_at",
                (project_id,),
            ).fetchall()
        finally:
            self._db.release(conn)
        return [_row_to_finding(r) for r in rows]

    def unembedded(self, project_id: str, limit: int = 64) -> list[ProjectFinding]:
        conn = self._db.connect()
        try:
            rows = conn.execute(
                "SELECT * FROM project_findings "
                "WHERE project_id = ? AND embedding IS NULL LIMIT ?",
                (project_id, limit),
            ).fetchall()
        finally:
            self._db.release(conn)
        return [_row_to_finding(r) for r in rows]

    def embeddings_for_project(self, project_id: str) -> dict:
        """{finding_id: vector} from stored embeddings — no model call."""
        conn = self._db.connect()
        try:
            rows = conn.execute(
                "SELECT id, embedding FROM project_findings "
                "WHERE project_id = ? AND embedding IS NOT NULL",
                (project_id,),
            ).fetchall()
        finally:
            self._db.release(conn)
        return {
            r["id"]: np.frombuffer(r["embedding"], dtype=np.float32) for r in rows
        }

    def run_ids_with_findings(self) -> set[str]:
        conn = self._db.connect()
        try:
            rows = conn.execute("SELECT DISTINCT run_id FROM project_findings").fetchall()
        finally:
            self._db.release(conn)
        return {r["run_id"] for r in rows}

    def search(
        self, project_id: str, query_embedding: list[float], top_k: int, threshold: float
    ) -> tuple[list[tuple[ProjectFinding, float]], int]:
        """Cosine search within ONE project. Returns (hits, candidates).

        Scoped by ``project_id`` in SQL, so findings from other projects can
        never be returned. Deterministic: ties break by recency then id.
        """
        conn = self._db.connect()
        try:
            rows = conn.execute(
                "SELECT * FROM project_findings "
                "WHERE project_id = ? AND embedding IS NOT NULL",
                (project_id,),
            ).fetchall()
        except sqlite3.Error as exc:
            raise PersistenceError(f"Failed to search project memory: {exc}") from exc
        finally:
            self._db.release(conn)
        if not rows:
            return [], 0
        q = np.asarray(query_embedding, dtype=np.float32)
        q_norm = float(np.linalg.norm(q))
        if q_norm == 0:
            return [], len(rows)
        scored: list[tuple[ProjectFinding, float]] = []
        for row in rows:
            vec = np.frombuffer(row["embedding"], dtype=np.float32)
            if vec.size != q.size:
                continue
            denom = float(np.linalg.norm(vec)) * q_norm
            score = float(np.dot(vec, q) / denom) if denom else 0.0
            if score >= threshold:
                scored.append((_row_to_finding(row), score))
        scored.sort(key=lambda pair: (-pair[1], pair[0].created_at, pair[0].id))
        return scored[:top_k], len(rows)

    def delete_for_project(self, project_id: str) -> None:
        conn = self._db.connect()
        try:
            with self._db.write_lock:
                conn.execute(
                    "DELETE FROM project_findings WHERE project_id = ?", (project_id,)
                )
                conn.commit()
        finally:
            self._db.release(conn)
