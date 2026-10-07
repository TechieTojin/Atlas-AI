"""Repository for persisted research runs."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from src.models.runs import ResearchRun, RunSummary
from src.persistence.db import Database, PersistenceError

# Lightweight columns kept relational for listing/filtering; everything rich
# (plan, evidence, metrics, report, ...) lives in the JSON `data` column.
_LIGHT_FIELDS = {
    "id",
    "query",
    "title",
    "mode",
    "source_scope",
    "status",
    "approval_required",
    "created_at",
    "started_at",
    "completed_at",
    "updated_at",
    "project_id",
    "template",
}


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


class RunsRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def save(self, run: ResearchRun) -> None:
        """Insert or fully replace a run record."""
        payload = run.model_dump(mode="json")
        data = {k: v for k, v in payload.items() if k not in _LIGHT_FIELDS}
        duration = 0
        if run.started_at and run.completed_at:
            duration = int((run.completed_at - run.started_at).total_seconds() * 1000)
        conn = self._db.connect()
        try:
            with self._db.write_lock:
                conn.execute(
                    """
                    INSERT INTO runs (id, query, title, mode, source_scope, status,
                        approval_required, created_at, started_at, completed_at,
                        updated_at, duration_ms, project_id, template, data)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        query=excluded.query, title=excluded.title,
                        mode=excluded.mode, source_scope=excluded.source_scope,
                        status=excluded.status,
                        approval_required=excluded.approval_required,
                        started_at=excluded.started_at,
                        completed_at=excluded.completed_at,
                        updated_at=excluded.updated_at,
                        duration_ms=excluded.duration_ms,
                        project_id=excluded.project_id,
                        template=excluded.template,
                        data=excluded.data
                    """,
                    (
                        run.id,
                        run.query,
                        run.title,
                        run.mode.value,
                        run.source_scope.value,
                        run.status.value,
                        int(run.approval_required),
                        _dt(run.created_at),
                        _dt(run.started_at),
                        _dt(run.completed_at),
                        _dt(run.updated_at),
                        duration,
                        run.project_id,
                        run.template,
                        json.dumps(data),
                    ),
                )
                conn.commit()
        except sqlite3.Error as exc:
            raise PersistenceError(f"Failed to save run {run.id}: {exc}") from exc
        finally:
            self._db.release(conn)

    def get(self, run_id: str) -> ResearchRun | None:
        conn = self._db.connect()
        try:
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        except sqlite3.Error as exc:
            raise PersistenceError(f"Failed to load run {run_id}: {exc}") from exc
        finally:
            self._db.release(conn)
        if row is None:
            return None
        payload = json.loads(row["data"])
        payload.update(
            {
                "id": row["id"],
                "query": row["query"],
                "title": row["title"],
                "mode": row["mode"],
                "source_scope": row["source_scope"],
                "status": row["status"],
                "approval_required": bool(row["approval_required"]),
                "created_at": row["created_at"],
                "started_at": row["started_at"],
                "completed_at": row["completed_at"],
                "updated_at": row["updated_at"],
                "project_id": row["project_id"],
                "template": row["template"],
            }
        )
        return ResearchRun.model_validate(payload)

    def list(
        self,
        limit: int = 20,
        offset: int = 0,
        search: str = "",
        project_id: str | None = None,
    ) -> tuple[list[RunSummary], int]:
        """Newest-first history page plus the total row count."""
        clauses: list[str] = []
        params: list = []
        if search:
            clauses.append("(query LIKE ? OR title LIKE ?)")
            like = f"%{search}%"
            params += [like, like]
        if project_id is not None:
            clauses.append("project_id = ?")
            params.append(project_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        conn = self._db.connect()
        try:
            total = conn.execute(
                f"SELECT COUNT(*) AS n FROM runs {where}", params
            ).fetchone()["n"]
            rows = conn.execute(
                f"""
                SELECT id, query, title, mode, status, source_scope, project_id,
                       template, created_at, completed_at, duration_ms
                FROM runs {where}
                ORDER BY created_at DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                [*params, limit, offset],
            ).fetchall()
        except sqlite3.Error as exc:
            raise PersistenceError(f"Failed to list runs: {exc}") from exc
        finally:
            self._db.release(conn)
        return [RunSummary.model_validate(dict(r)) for r in rows], total

    def ids_with_status(self, statuses: list[str]) -> list[str]:
        if not statuses:
            return []
        placeholders = ",".join("?" for _ in statuses)
        conn = self._db.connect()
        try:
            rows = conn.execute(
                f"SELECT id FROM runs WHERE status IN ({placeholders})", statuses
            ).fetchall()
        except sqlite3.Error as exc:
            raise PersistenceError(f"Failed to query runs by status: {exc}") from exc
        finally:
            self._db.release(conn)
        return [r["id"] for r in rows]

    def delete(self, run_id: str) -> bool:
        conn = self._db.connect()
        try:
            with self._db.write_lock:
                cur = conn.execute("DELETE FROM runs WHERE id = ?", (run_id,))
                conn.execute("DELETE FROM events WHERE run_id = ?", (run_id,))
                conn.commit()
                return cur.rowcount > 0
        except sqlite3.Error as exc:
            raise PersistenceError(f"Failed to delete run {run_id}: {exc}") from exc
        finally:
            self._db.release(conn)
