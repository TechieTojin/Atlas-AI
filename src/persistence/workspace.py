"""Repositories for V3 entities: projects, follow-ups, comparisons, graph."""

from __future__ import annotations

import json
import sqlite3

from src.models.workspace import (
    Comparison,
    FollowUp,
    KGEdge,
    KGNode,
    KGSupport,
    KnowledgeGraph,
    Project,
)
from src.models.runs import utcnow
from src.persistence.db import Database, PersistenceError


class ProjectsRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def save(self, project: Project) -> None:
        conn = self._db.connect()
        try:
            with self._db.write_lock:
                conn.execute(
                    """
                    INSERT INTO projects (id, name, description, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        name=excluded.name, description=excluded.description,
                        updated_at=excluded.updated_at
                    """,
                    (
                        project.id,
                        project.name,
                        project.description,
                        project.created_at.isoformat(),
                        project.updated_at.isoformat(),
                    ),
                )
                conn.commit()
        except sqlite3.Error as exc:
            raise PersistenceError(f"Failed to save project: {exc}") from exc
        finally:
            self._db.release(conn)

    def get(self, project_id: str) -> Project | None:
        conn = self._db.connect()
        try:
            row = conn.execute(
                "SELECT * FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
        finally:
            self._db.release(conn)
        return Project.model_validate(dict(row)) if row else None

    def list(self) -> list[Project]:
        conn = self._db.connect()
        try:
            rows = conn.execute(
                "SELECT * FROM projects ORDER BY updated_at DESC"
            ).fetchall()
        finally:
            self._db.release(conn)
        return [Project.model_validate(dict(r)) for r in rows]

    def counts(self, project_id: str) -> dict:
        conn = self._db.connect()
        try:
            runs = conn.execute(
                "SELECT COUNT(*) AS n FROM runs WHERE project_id = ?", (project_id,)
            ).fetchone()["n"]
            docs = conn.execute(
                "SELECT COUNT(*) AS n FROM documents WHERE project_id = ?",
                (project_id,),
            ).fetchone()["n"]
            comparisons = conn.execute(
                "SELECT COUNT(*) AS n FROM comparisons WHERE project_id = ?",
                (project_id,),
            ).fetchone()["n"]
        finally:
            self._db.release(conn)
        return {"runs": runs, "documents": docs, "comparisons": comparisons}

    def delete(self, project_id: str) -> bool:
        """Delete a project, DETACHING its runs/documents (non-destructive).

        Runs, documents, and comparisons survive as global items; only
        project-scoped memory rows (duplicable caches) are removed.
        """
        conn = self._db.connect()
        try:
            with self._db.write_lock:
                cur = conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
                conn.execute(
                    "UPDATE runs SET project_id = '' WHERE project_id = ?",
                    (project_id,),
                )
                conn.execute(
                    "UPDATE documents SET project_id = '' WHERE project_id = ?",
                    (project_id,),
                )
                conn.execute(
                    "UPDATE comparisons SET project_id = '' WHERE project_id = ?",
                    (project_id,),
                )
                conn.execute("DELETE FROM memory WHERE project_id = ?", (project_id,))
                conn.commit()
                return cur.rowcount > 0
        except sqlite3.Error as exc:
            raise PersistenceError(f"Failed to delete project: {exc}") from exc
        finally:
            self._db.release(conn)


class _JsonEntityRepository:
    """Shared id + JSON-document persistence for follow-ups/comparisons."""

    table = ""
    model: type

    def __init__(self, db: Database) -> None:
        self._db = db

    def _save(self, entity, extra: dict) -> None:
        payload = entity.model_dump(mode="json")
        conn = self._db.connect()
        try:
            with self._db.write_lock:
                columns = ["id", "created_at", "data", *extra.keys()]
                values = [
                    entity.id,
                    entity.created_at.isoformat(),
                    json.dumps(payload),
                    *extra.values(),
                ]
                placeholders = ", ".join("?" for _ in columns)
                updates = ", ".join(
                    f"{c}=excluded.{c}" for c in columns if c != "id"
                )
                conn.execute(
                    f"INSERT INTO {self.table} ({', '.join(columns)}) "
                    f"VALUES ({placeholders}) "
                    f"ON CONFLICT(id) DO UPDATE SET {updates}",
                    values,
                )
                conn.commit()
        except sqlite3.Error as exc:
            raise PersistenceError(f"Failed to save {self.table} row: {exc}") from exc
        finally:
            self._db.release(conn)

    def get(self, entity_id: str):
        conn = self._db.connect()
        try:
            row = conn.execute(
                f"SELECT data FROM {self.table} WHERE id = ?", (entity_id,)
            ).fetchone()
        finally:
            self._db.release(conn)
        return self.model.model_validate(json.loads(row["data"])) if row else None

    def delete(self, entity_id: str) -> bool:
        conn = self._db.connect()
        try:
            with self._db.write_lock:
                cur = conn.execute(
                    f"DELETE FROM {self.table} WHERE id = ?", (entity_id,)
                )
                conn.commit()
                return cur.rowcount > 0
        finally:
            self._db.release(conn)

    def _list(self, where: str, params: list) -> list:
        conn = self._db.connect()
        try:
            rows = conn.execute(
                f"SELECT data FROM {self.table} {where} ORDER BY created_at ASC",
                params,
            ).fetchall()
        finally:
            self._db.release(conn)
        return [self.model.model_validate(json.loads(r["data"])) for r in rows]


class FollowUpsRepository(_JsonEntityRepository):
    table = "followups"
    model = FollowUp

    def save(self, followup: FollowUp) -> None:
        self._save(
            followup,
            {"run_id": followup.run_id, "project_id": followup.project_id},
        )

    def list_for_run(self, run_id: str) -> list[FollowUp]:
        return self._list("WHERE run_id = ?", [run_id])


class ComparisonsRepository(_JsonEntityRepository):
    table = "comparisons"
    model = Comparison

    def save(self, comparison: Comparison) -> None:
        self._save(comparison, {"project_id": comparison.project_id})

    def list(self, project_id: str | None = None) -> list[Comparison]:
        if project_id is None:
            return self._list("", [])
        return self._list("WHERE project_id = ?", [project_id])


class KGRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def save_graph(self, run_id: str, nodes: list[KGNode], edges: list[KGEdge]) -> None:
        conn = self._db.connect()
        try:
            with self._db.write_lock:
                conn.execute("DELETE FROM kg_nodes WHERE run_id = ?", (run_id,))
                conn.execute("DELETE FROM kg_edges WHERE run_id = ?", (run_id,))
                for node in nodes:
                    conn.execute(
                        "INSERT OR IGNORE INTO kg_nodes "
                        "(id, run_id, name, norm_name, type, description) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (node.id, run_id, node.name, node.norm_name, node.type,
                         node.description),
                    )
                for edge in edges:
                    conn.execute(
                        "INSERT OR IGNORE INTO kg_edges "
                        "(id, run_id, source_node_id, target_node_id, relation, support) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            edge.id,
                            run_id,
                            edge.source_node_id,
                            edge.target_node_id,
                            edge.relation,
                            json.dumps([s.model_dump() for s in edge.support]),
                        ),
                    )
                conn.commit()
        except sqlite3.Error as exc:
            raise PersistenceError(f"Failed to save knowledge graph: {exc}") from exc
        finally:
            self._db.release(conn)

    def set_status(self, run_id: str, status: str, error: str = "") -> None:
        conn = self._db.connect()
        try:
            with self._db.write_lock:
                conn.execute(
                    "INSERT OR REPLACE INTO kg_status (run_id, status, error, updated_at) "
                    "VALUES (?, ?, ?, ?)",
                    (run_id, status, error, utcnow().isoformat()),
                )
                conn.commit()
        finally:
            self._db.release(conn)

    def get_graph(self, run_id: str) -> KnowledgeGraph:
        conn = self._db.connect()
        try:
            status_row = conn.execute(
                "SELECT status, error FROM kg_status WHERE run_id = ?", (run_id,)
            ).fetchone()
            node_rows = conn.execute(
                "SELECT * FROM kg_nodes WHERE run_id = ?", (run_id,)
            ).fetchall()
            edge_rows = conn.execute(
                "SELECT * FROM kg_edges WHERE run_id = ?", (run_id,)
            ).fetchall()
        finally:
            self._db.release(conn)
        nodes = [KGNode.model_validate(dict(r)) for r in node_rows]
        edges = [
            KGEdge(
                id=r["id"],
                run_id=r["run_id"],
                source_node_id=r["source_node_id"],
                target_node_id=r["target_node_id"],
                relation=r["relation"],
                support=[KGSupport.model_validate(s) for s in json.loads(r["support"])],
            )
            for r in edge_rows
        ]
        return KnowledgeGraph(
            nodes=nodes,
            edges=edges,
            status=status_row["status"] if status_row else "NONE",
            error=status_row["error"] if status_row else "",
        )
