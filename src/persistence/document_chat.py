"""Repository for Document Chat conversations and messages.

Mirrors the Website Chat persistence conventions: conversations are upserted
with ``ON CONFLICT DO UPDATE`` (never ``INSERT OR REPLACE``, which would
cascade-delete messages), messages get a per-conversation sequence, and rich
message fields live in one JSON ``data`` column.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from src.models.document_chat import (
    DocumentChatMessage,
    DocumentConversation,
    MessageStatus,
)
from src.persistence.db import Database, PersistenceError


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


class DocumentChatRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def _read(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        conn = self._db.connect()
        try:
            return conn.execute(sql, params).fetchall()
        except sqlite3.Error as exc:
            raise PersistenceError(f"Document chat query failed: {exc}") from exc
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
            raise PersistenceError(f"Document chat write failed: {exc}") from exc
        finally:
            self._db.release(conn)

    # -- conversations ---------------------------------------------------------

    def save_conversation(self, conversation: DocumentConversation) -> None:
        self._write(
            lambda conn: conn.execute(
                """
                INSERT INTO document_conversations
                    (id, title, document_ids, output_language, project_id,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title, document_ids=excluded.document_ids,
                    output_language=excluded.output_language,
                    project_id=excluded.project_id, updated_at=excluded.updated_at
                """,
                (
                    conversation.id, conversation.title,
                    json.dumps(conversation.document_ids),
                    conversation.output_language, conversation.project_id,
                    _iso(conversation.created_at), _iso(conversation.updated_at),
                ),
            )
        )

    def get_conversation(self, conversation_id: str) -> DocumentConversation | None:
        rows = self._read(
            "SELECT * FROM document_conversations WHERE id = ?", (conversation_id,)
        )
        if not rows:
            return None
        data = dict(rows[0])
        data["document_ids"] = json.loads(data.get("document_ids") or "[]")
        return DocumentConversation.model_validate(data)

    def list_conversations(self) -> list[DocumentConversation]:
        rows = self._read(
            "SELECT * FROM document_conversations ORDER BY updated_at DESC"
        )
        out = []
        for row in rows:
            data = dict(row)
            data["document_ids"] = json.loads(data.get("document_ids") or "[]")
            out.append(DocumentConversation.model_validate(data))
        return out

    def delete_conversation(self, conversation_id: str) -> bool:
        def run(conn):
            conn.execute(
                "DELETE FROM document_messages WHERE conversation_id = ?", (conversation_id,)
            )
            return (
                conn.execute(
                    "DELETE FROM document_conversations WHERE id = ?", (conversation_id,)
                ).rowcount
                > 0
            )

        return self._write(run)

    # -- messages ---------------------------------------------------------------

    def add_message(self, message: DocumentChatMessage) -> DocumentChatMessage:
        """Append with the next sequence number of its conversation."""

        def run(conn):
            row = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) FROM document_messages WHERE conversation_id = ?",
                (message.conversation_id,),
            ).fetchone()
            message.seq = int(row[0]) + 1
            conn.execute(
                """
                INSERT INTO document_messages
                    (id, conversation_id, seq, role, status, created_at, data)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message.id, message.conversation_id, message.seq, message.role.value,
                    message.status.value, _iso(message.created_at),
                    message.model_dump_json(),
                ),
            )
            conn.execute(
                "UPDATE document_conversations SET updated_at = ? WHERE id = ?",
                (_iso(message.created_at), message.conversation_id),
            )
            return message

        return self._write(run)

    def update_message(self, message: DocumentChatMessage) -> bool:
        return self._write(
            lambda conn: conn.execute(
                "UPDATE document_messages SET status = ?, data = ? WHERE id = ?",
                (message.status.value, message.model_dump_json(), message.id),
            ).rowcount
            > 0
        )

    def get_message(self, message_id: str) -> DocumentChatMessage | None:
        rows = self._read("SELECT data FROM document_messages WHERE id = ?", (message_id,))
        return DocumentChatMessage.model_validate_json(rows[0][0]) if rows else None

    def list_messages(self, conversation_id: str) -> list[DocumentChatMessage]:
        rows = self._read(
            "SELECT data FROM document_messages WHERE conversation_id = ? ORDER BY seq",
            (conversation_id,),
        )
        return [DocumentChatMessage.model_validate_json(r[0]) for r in rows]

    def list_pending_messages(self) -> list[DocumentChatMessage]:
        rows = self._read(
            "SELECT data FROM document_messages WHERE status = ?",
            (MessageStatus.PENDING.value,),
        )
        return [DocumentChatMessage.model_validate_json(r[0]) for r in rows]
