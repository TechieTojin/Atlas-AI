"""Repository for Website Chat: websites, versioned chunks, conversations.

Vector storage reuses the document-RAG approach (float32 BLOBs in SQLite,
cosine similarity with NumPy): one webpage yields at most a few hundred
chunks, so an in-process scan is fast and needs no vector database. All
access goes through this class, so a different vector backend could replace
``replace_index``/``search`` without touching the service.

Status updates are UPDATEs, never upserts: a worker that finishes after its
website was deleted cannot resurrect it, and chunk inserts for a deleted
website fail on the foreign key instead of leaving orphans.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

import numpy as np

from src.models.websites import (
    MessageStatus,
    WebsiteChunk,
    WebsiteConversation,
    WebsiteMessage,
    WebsiteSource,
    WebsiteStatus,
)
from src.persistence.db import Database, PersistenceError
from src.persistence.documents import _from_blob, _to_blob

_WEBSITE_COLUMNS = (
    "id", "submitted_url", "normalized_url", "final_url", "page_title", "domain",
    "status", "content_hash", "content_language", "word_count", "chunk_count",
    "index_version", "error", "error_code", "fetched_at", "indexed_at",
    "created_at", "updated_at", "metrics",
)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _website_row(site: WebsiteSource) -> tuple:
    data = site.model_dump(mode="json")
    data["metrics"] = json.dumps(site.metrics)
    data["status"] = site.status.value
    return tuple(data[column] for column in _WEBSITE_COLUMNS)


def _website_from(row: sqlite3.Row) -> WebsiteSource:
    data = dict(row)
    data["metrics"] = json.loads(data.get("metrics") or "{}")
    return WebsiteSource.model_validate(data)


def _chunk_from(row: sqlite3.Row) -> WebsiteChunk:
    data = {key: row[key] for key in row.keys() if key != "embedding"}
    data["heading_path"] = json.loads(data.get("heading_path") or "[]")
    return WebsiteChunk.model_validate(data)


class WebsitesRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    # -- helpers -------------------------------------------------------------

    def _read(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        conn = self._db.connect()
        try:
            return conn.execute(sql, params).fetchall()
        except sqlite3.Error as exc:
            raise PersistenceError(f"Website query failed: {exc}") from exc
        finally:
            self._db.release(conn)

    def _write(self, fn):
        conn = self._db.connect()
        try:
            with self._db.write_lock:
                try:
                    result = fn(conn)
                    conn.commit()
                    return result
                except BaseException:
                    conn.rollback()
                    raise
        except sqlite3.Error as exc:
            raise PersistenceError(f"Website write failed: {exc}") from exc
        finally:
            self._db.release(conn)

    # -- websites ------------------------------------------------------------

    def insert(self, site: WebsiteSource) -> WebsiteSource:
        """Insert a new website; returns the EXISTING row for a duplicate URL."""
        placeholders = ",".join("?" for _ in _WEBSITE_COLUMNS)

        def run(conn):
            try:
                conn.execute(
                    f"INSERT INTO websites ({','.join(_WEBSITE_COLUMNS)}) VALUES ({placeholders})",
                    _website_row(site),
                )
                return None
            except sqlite3.IntegrityError:
                return "duplicate"

        if self._write(run) == "duplicate":
            existing = self.get_by_normalized_url(site.normalized_url)
            if existing is None:  # pragma: no cover - concurrent delete
                raise PersistenceError("Website insert conflicted.")
            return existing
        return site

    def update(self, site: WebsiteSource) -> bool:
        """Update an existing row; False if it was deleted meanwhile."""
        columns = [c for c in _WEBSITE_COLUMNS if c != "id"]
        values = _website_row(site)[1:]
        sets = ",".join(f"{c} = ?" for c in columns)
        return self._write(
            lambda conn: conn.execute(
                f"UPDATE websites SET {sets} WHERE id = ?", (*values, site.id)
            ).rowcount
            > 0
        )

    def get(self, website_id: str) -> WebsiteSource | None:
        rows = self._read("SELECT * FROM websites WHERE id = ?", (website_id,))
        return _website_from(rows[0]) if rows else None

    def get_by_normalized_url(self, url: str) -> WebsiteSource | None:
        rows = self._read("SELECT * FROM websites WHERE normalized_url = ?", (url,))
        return _website_from(rows[0]) if rows else None

    def list(self) -> list[WebsiteSource]:
        return [_website_from(r) for r in self._read("SELECT * FROM websites ORDER BY updated_at DESC")]

    def list_active(self) -> list[WebsiteSource]:
        return [w for w in self.list() if w.status.is_active]

    def delete(self, website_id: str) -> bool:
        """Remove a website and everything derived from it, atomically."""

        def run(conn):
            conversation_ids = [
                r[0]
                for r in conn.execute(
                    "SELECT id FROM website_conversations WHERE website_id = ?", (website_id,)
                ).fetchall()
            ]
            for cid in conversation_ids:
                conn.execute("DELETE FROM website_messages WHERE conversation_id = ?", (cid,))
            conn.execute("DELETE FROM website_conversations WHERE website_id = ?", (website_id,))
            conn.execute("DELETE FROM website_chunks WHERE website_id = ?", (website_id,))
            return conn.execute("DELETE FROM websites WHERE id = ?", (website_id,)).rowcount > 0

        return self._write(run)

    # -- chunks / vectors ------------------------------------------------------

    def replace_index(
        self,
        site: WebsiteSource,
        chunks: list[WebsiteChunk],
        embeddings: list[list[float]],
    ) -> bool:
        """Atomically publish ``chunks`` as ``site.index_version`` and drop
        every older version, in ONE transaction with the website update.

        A failure anywhere leaves the previous index fully intact: retrieval
        can never see half-old/half-new chunks. Returns False when the
        website was deleted meanwhile (nothing is written).
        """
        if len(chunks) != len(embeddings):
            raise PersistenceError("Chunk/embedding count mismatch.")
        columns = [c for c in _WEBSITE_COLUMNS if c != "id"]
        values = _website_row(site)[1:]
        sets = ",".join(f"{c} = ?" for c in columns)

        def run(conn):
            if conn.execute("SELECT 1 FROM websites WHERE id = ?", (site.id,)).fetchone() is None:
                return False
            conn.executemany(
                """
                INSERT INTO website_chunks
                    (id, website_id, index_version, chunk_index, section_title,
                     heading_path, text, char_start, char_end, embedding)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        chunk.id, site.id, site.index_version, chunk.chunk_index,
                        chunk.section_title, json.dumps(chunk.heading_path, ensure_ascii=False),
                        chunk.text, chunk.char_start, chunk.char_end, _to_blob(vector),
                    )
                    for chunk, vector in zip(chunks, embeddings)
                ],
            )
            conn.execute(
                "DELETE FROM website_chunks WHERE website_id = ? AND index_version <> ?",
                (site.id, site.index_version),
            )
            conn.execute(f"UPDATE websites SET {sets} WHERE id = ?", (*values, site.id))
            return True

        return self._write(run)

    def chunks(self, website_id: str, index_version: int) -> list[WebsiteChunk]:
        rows = self._read(
            "SELECT * FROM website_chunks WHERE website_id = ? AND index_version = ? "
            "ORDER BY chunk_index",
            (website_id, index_version),
        )
        return [_chunk_from(r) for r in rows]

    def search(
        self, website_id: str, index_version: int, query_embeddings: list[list[float]]
    ) -> list[tuple[WebsiteChunk, float]]:
        """Cosine score of EVERY chunk of this website's live index version.

        Several query vectors may be given (e.g. the question alone and the
        question with conversational context); each chunk keeps its best
        score. Only rows of ``website_id`` are ever read.
        """
        rows = self._read(
            "SELECT * FROM website_chunks WHERE website_id = ? AND index_version = ?",
            (website_id, index_version),
        )
        if not rows or not query_embeddings:
            return []
        queries = np.asarray(query_embeddings, dtype=np.float32)
        norms = np.linalg.norm(queries, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        queries = queries / norms
        scored: list[tuple[WebsiteChunk, float]] = []
        for row in rows:
            vector = _from_blob(row["embedding"])
            if vector is None or vector.size != queries.shape[1]:
                continue
            norm = float(np.linalg.norm(vector)) or 1.0
            score = float(np.max(queries @ (vector / norm)))
            scored.append((_chunk_from(row), score))
        scored.sort(key=lambda pair: (-pair[1], pair[0].chunk_index))
        return scored

    def count_chunks(self, website_id: str | None = None) -> int:
        if website_id is None:
            return self._read("SELECT COUNT(*) FROM website_chunks")[0][0]
        return self._read(
            "SELECT COUNT(*) FROM website_chunks WHERE website_id = ?", (website_id,)
        )[0][0]

    # -- conversations ---------------------------------------------------------

    def save_conversation(self, conversation: WebsiteConversation) -> None:
        data = conversation.model_dump(mode="json")
        self._write(
            lambda conn: conn.execute(
                """
                INSERT INTO website_conversations
                    (id, website_id, title, output_language, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title, updated_at = excluded.updated_at
                """,
                # Never INSERT OR REPLACE here: REPLACE deletes the row first,
                # and ON DELETE CASCADE would delete the conversation's messages.
                # The language is never updated: it is fixed at creation.
                (
                    data["id"], data["website_id"], data["title"], data["output_language"],
                    data["created_at"], data["updated_at"],
                ),
            )
        )

    def get_conversation(self, conversation_id: str) -> WebsiteConversation | None:
        rows = self._read("SELECT * FROM website_conversations WHERE id = ?", (conversation_id,))
        return WebsiteConversation.model_validate(dict(rows[0])) if rows else None

    def list_conversations(self, website_id: str) -> list[WebsiteConversation]:
        rows = self._read(
            "SELECT * FROM website_conversations WHERE website_id = ? ORDER BY updated_at DESC",
            (website_id,),
        )
        return [WebsiteConversation.model_validate(dict(r)) for r in rows]

    def delete_conversation(self, conversation_id: str) -> bool:
        def run(conn):
            conn.execute("DELETE FROM website_messages WHERE conversation_id = ?", (conversation_id,))
            return (
                conn.execute("DELETE FROM website_conversations WHERE id = ?", (conversation_id,)).rowcount
                > 0
            )

        return self._write(run)

    # -- messages ------------------------------------------------------------------

    def add_message(self, message: WebsiteMessage) -> WebsiteMessage:
        """Append with the next sequence number of its conversation."""

        def run(conn):
            row = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) FROM website_messages WHERE conversation_id = ?",
                (message.conversation_id,),
            ).fetchone()
            message.seq = int(row[0]) + 1
            conn.execute(
                """
                INSERT INTO website_messages (id, conversation_id, seq, role, status, created_at, data)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message.id, message.conversation_id, message.seq, message.role.value,
                    message.status.value, message.created_at.isoformat(),
                    message.model_dump_json(),
                ),
            )
            conn.execute(
                "UPDATE website_conversations SET updated_at = ? WHERE id = ?",
                (message.created_at.isoformat(), message.conversation_id),
            )
            return message

        return self._write(run)

    def update_message(self, message: WebsiteMessage) -> bool:
        return self._write(
            lambda conn: conn.execute(
                "UPDATE website_messages SET status = ?, data = ? WHERE id = ?",
                (message.status.value, message.model_dump_json(), message.id),
            ).rowcount
            > 0
        )

    def get_message(self, message_id: str) -> WebsiteMessage | None:
        rows = self._read("SELECT data FROM website_messages WHERE id = ?", (message_id,))
        return WebsiteMessage.model_validate_json(rows[0][0]) if rows else None

    def list_messages(self, conversation_id: str) -> list[WebsiteMessage]:
        rows = self._read(
            "SELECT data FROM website_messages WHERE conversation_id = ? ORDER BY seq",
            (conversation_id,),
        )
        return [WebsiteMessage.model_validate_json(r[0]) for r in rows]

    def list_pending_messages(self) -> list[WebsiteMessage]:
        rows = self._read(
            "SELECT data FROM website_messages WHERE status = ?", (MessageStatus.PENDING.value,)
        )
        return [WebsiteMessage.model_validate_json(r[0]) for r in rows]

    def counts(self) -> dict[str, int]:
        return {
            table: self._read(f"SELECT COUNT(*) FROM {table}")[0][0]
            for table in ("websites", "website_chunks", "website_conversations", "website_messages")
        }


__all__ = ["WebsitesRepository", "WebsiteStatus"]
