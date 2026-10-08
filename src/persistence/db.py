"""SQLite database bootstrap for Atlas.

Local-first by design: SQLite needs no server and keeps Atlas free to run.
All data access goes through repository classes (no SQL in agents/services),
so a different backend (e.g. PostgreSQL) can be added later by swapping the
repository implementations.

Schema changes are applied through an ordered migration list guarded by a
``schema_version`` table.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading

logger = logging.getLogger(__name__)


class PersistenceError(Exception):
    """Raised when the database cannot be opened or a query fails."""


_MIGRATIONS: list[str] = [
    # v1 — initial V2 schema
    """
    CREATE TABLE IF NOT EXISTS runs (
        id TEXT PRIMARY KEY,
        query TEXT NOT NULL,
        title TEXT NOT NULL DEFAULT '',
        mode TEXT NOT NULL,
        source_scope TEXT NOT NULL,
        status TEXT NOT NULL,
        approval_required INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        started_at TEXT,
        completed_at TEXT,
        updated_at TEXT NOT NULL,
        duration_ms INTEGER NOT NULL DEFAULT 0,
        data TEXT NOT NULL DEFAULT '{}'
    );
    CREATE INDEX IF NOT EXISTS idx_runs_created ON runs(created_at DESC);

    CREATE TABLE IF NOT EXISTS events (
        run_id TEXT NOT NULL,
        seq INTEGER NOT NULL,
        type TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        agent TEXT NOT NULL DEFAULT '',
        message TEXT NOT NULL DEFAULT '',
        iteration INTEGER NOT NULL DEFAULT 0,
        payload TEXT NOT NULL DEFAULT '{}',
        PRIMARY KEY (run_id, seq)
    );

    CREATE TABLE IF NOT EXISTS memory (
        query_norm TEXT NOT NULL,
        url_norm TEXT NOT NULL,
        origin TEXT NOT NULL,
        fetched_at TEXT NOT NULL,
        evidence TEXT NOT NULL,
        PRIMARY KEY (query_norm, url_norm)
    );
    CREATE INDEX IF NOT EXISTS idx_memory_query ON memory(query_norm);

    CREATE TABLE IF NOT EXISTS documents (
        id TEXT PRIMARY KEY,
        filename TEXT NOT NULL,
        content_type TEXT NOT NULL DEFAULT '',
        file_type TEXT NOT NULL DEFAULT '',
        size_bytes INTEGER NOT NULL DEFAULT 0,
        checksum TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL,
        error TEXT NOT NULL DEFAULT '',
        chunk_count INTEGER NOT NULL DEFAULT 0,
        page_count INTEGER NOT NULL DEFAULT 0,
        uploaded_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS chunks (
        document_id TEXT NOT NULL,
        chunk_index INTEGER NOT NULL,
        page INTEGER,
        content TEXT NOT NULL,
        embedding BLOB,
        PRIMARY KEY (document_id, chunk_index)
    );
    """,
    # v2 — Atlas V3: projects, follow-ups, comparisons, knowledge graph,
    # project/semantic memory. Non-destructive: existing rows are preserved
    # (the memory table is rebuilt in place to extend its primary key).
    """
    CREATE TABLE IF NOT EXISTS projects (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    ALTER TABLE runs ADD COLUMN project_id TEXT NOT NULL DEFAULT '';
    ALTER TABLE runs ADD COLUMN template TEXT NOT NULL DEFAULT 'STANDARD';
    CREATE INDEX IF NOT EXISTS idx_runs_project ON runs(project_id);

    ALTER TABLE documents ADD COLUMN project_id TEXT NOT NULL DEFAULT '';
    CREATE INDEX IF NOT EXISTS idx_documents_project ON documents(project_id);

    CREATE TABLE memory_v3 (
        query_norm TEXT NOT NULL,
        url_norm TEXT NOT NULL,
        project_id TEXT NOT NULL DEFAULT '',
        origin TEXT NOT NULL,
        fetched_at TEXT NOT NULL,
        evidence TEXT NOT NULL,
        embedding BLOB,
        PRIMARY KEY (query_norm, url_norm, project_id)
    );
    INSERT INTO memory_v3 (query_norm, url_norm, project_id, origin, fetched_at, evidence)
        SELECT query_norm, url_norm, '', origin, fetched_at, evidence FROM memory;
    DROP TABLE memory;
    ALTER TABLE memory_v3 RENAME TO memory;
    CREATE INDEX IF NOT EXISTS idx_memory_query ON memory(query_norm);
    CREATE INDEX IF NOT EXISTS idx_memory_project ON memory(project_id);

    CREATE TABLE IF NOT EXISTS followups (
        id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        project_id TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        data TEXT NOT NULL DEFAULT '{}'
    );
    CREATE INDEX IF NOT EXISTS idx_followups_run ON followups(run_id, created_at);

    CREATE TABLE IF NOT EXISTS comparisons (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        data TEXT NOT NULL DEFAULT '{}'
    );
    CREATE INDEX IF NOT EXISTS idx_comparisons_project ON comparisons(project_id, created_at);

    CREATE TABLE IF NOT EXISTS kg_nodes (
        id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        name TEXT NOT NULL,
        norm_name TEXT NOT NULL,
        type TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        UNIQUE (run_id, norm_name, type)
    );
    CREATE INDEX IF NOT EXISTS idx_kg_nodes_run ON kg_nodes(run_id);

    CREATE TABLE IF NOT EXISTS kg_edges (
        id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        source_node_id TEXT NOT NULL,
        target_node_id TEXT NOT NULL,
        relation TEXT NOT NULL,
        support TEXT NOT NULL DEFAULT '[]',
        UNIQUE (run_id, source_node_id, target_node_id, relation)
    );
    CREATE INDEX IF NOT EXISTS idx_kg_edges_run ON kg_edges(run_id);

    CREATE TABLE IF NOT EXISTS kg_status (
        run_id TEXT PRIMARY KEY,
        status TEXT NOT NULL,
        error TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL
    );
    """,
    # v3 — project research memory: compact, cited findings distilled from
    # completed project runs, so later runs in the same project build on
    # earlier ones. Additive: no existing table is touched.
    """
    CREATE TABLE IF NOT EXISTS project_findings (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        run_id TEXT NOT NULL,
        question TEXT NOT NULL DEFAULT '',
        section TEXT NOT NULL DEFAULT '',
        text TEXT NOT NULL,
        text_norm TEXT NOT NULL,
        sources TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL,
        embedding BLOB,
        UNIQUE (project_id, text_norm)
    );
    CREATE INDEX IF NOT EXISTS idx_findings_project ON project_findings(project_id);
    CREATE INDEX IF NOT EXISTS idx_findings_run ON project_findings(run_id);
    """,
    # v4 — output language of each research run. Every existing run was written
    # in English, which the column default records; no row data is rewritten.
    # Follow-ups and comparisons keep their records in JSON documents whose
    # model default is also English, so they need no schema change.
    """
    ALTER TABLE runs ADD COLUMN output_language TEXT NOT NULL DEFAULT 'en';
    """,
]


class Database:
    """Owns the SQLite file: connections, migrations, and a write lock.

    SQLite serializes writers anyway; the lock keeps multi-statement writes
    atomic across our worker threads.
    """

    def __init__(self, path: str) -> None:
        self.path = path
        self.write_lock = threading.Lock()
        try:
            if path != ":memory:":
                os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            self._memory_conn: sqlite3.Connection | None = (
                self._new_connection() if path == ":memory:" else None
            )
            self._migrate()
        except sqlite3.Error as exc:
            raise PersistenceError(f"Cannot open Atlas database at {path}: {exc}") from exc

    def _new_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, check_same_thread=False, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        if self.path != ":memory:":
            conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def connect(self) -> sqlite3.Connection:
        """Connection for one operation. In-memory DBs share one connection."""
        if self._memory_conn is not None:
            return self._memory_conn
        return self._new_connection()

    def release(self, conn: sqlite3.Connection) -> None:
        if conn is not self._memory_conn:
            conn.close()

    def _migrate(self) -> None:
        conn = self.connect()
        try:
            with self.write_lock:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS schema_version "
                    "(version INTEGER NOT NULL)"
                )
                row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
                current = row["v"] or 0
                for version, script in enumerate(_MIGRATIONS, start=1):
                    if version > current:
                        conn.executescript(script)
                        conn.execute(
                            "INSERT INTO schema_version (version) VALUES (?)", (version,)
                        )
                        logger.info("Applied database migration v%d.", version)
                conn.commit()
        finally:
            self.release(conn)
