"""Repository for collections and their items."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from src.models.collections import Collection, CollectionItem
from src.persistence.db import Database, PersistenceError


def _iso(value: datetime) -> str:
    return value.isoformat()


def _collection_from(row: sqlite3.Row) -> Collection:
    return Collection.model_validate(dict(row))


def _item_from(row: sqlite3.Row) -> CollectionItem:
    data = dict(row)
    data["data"] = json.loads(data.get("data") or "{}")
    return CollectionItem.model_validate(data)


class CollectionsRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def _read(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        conn = self._db.connect()
        try:
            return conn.execute(sql, params).fetchall()
        except sqlite3.Error as exc:
            raise PersistenceError(f"Collection query failed: {exc}") from exc
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
            raise PersistenceError(f"Collection write failed: {exc}") from exc
        finally:
            self._db.release(conn)

    # -- collections --------------------------------------------------------------

    def save(self, collection: Collection) -> None:
        self._write(
            lambda conn: conn.execute(
                """
                INSERT INTO collections
                    (id, title, description, project_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title, description=excluded.description,
                    project_id=excluded.project_id, updated_at=excluded.updated_at
                """,
                (
                    collection.id, collection.title, collection.description,
                    collection.project_id, _iso(collection.created_at),
                    _iso(collection.updated_at),
                ),
            )
        )

    def get(self, collection_id: str) -> Collection | None:
        rows = self._read("SELECT * FROM collections WHERE id = ?", (collection_id,))
        return _collection_from(rows[0]) if rows else None

    def list(self) -> list[tuple[Collection, int]]:
        """Collections newest-first with their item counts."""
        rows = self._read(
            """
            SELECT c.*, (
                SELECT COUNT(*) FROM collection_items i WHERE i.collection_id = c.id
            ) AS item_count
            FROM collections c ORDER BY c.updated_at DESC
            """
        )
        out = []
        for row in rows:
            data = dict(row)
            count = data.pop("item_count")
            out.append((Collection.model_validate(data), count))
        return out

    def delete(self, collection_id: str) -> bool:
        def run(conn):
            conn.execute(
                "DELETE FROM collection_items WHERE collection_id = ?", (collection_id,)
            )
            return (
                conn.execute("DELETE FROM collections WHERE id = ?", (collection_id,)).rowcount > 0
            )

        return self._write(run)

    # -- items ---------------------------------------------------------------------

    def add_item(self, item: CollectionItem) -> tuple[CollectionItem, bool]:
        """Append an item; the same origin saved twice returns the existing
        item with ``created=False``."""
        existing = next(
            (
                candidate
                for candidate in self.items(item.collection_id)
                if candidate.type is item.type
                and candidate.reference_key() == item.reference_key()
            ),
            None,
        )
        if existing is not None and item.type.value != "note":
            return existing, False

        def run(conn):
            row = conn.execute(
                "SELECT COALESCE(MAX(position), 0) FROM collection_items WHERE collection_id = ?",
                (item.collection_id,),
            ).fetchone()
            item.position = int(row[0]) + 1
            conn.execute(
                """
                INSERT INTO collection_items
                    (id, collection_id, type, position, note, data, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.id, item.collection_id, item.type.value, item.position,
                    item.note, json.dumps(item.data, ensure_ascii=False),
                    _iso(item.created_at),
                ),
            )
            conn.execute(
                "UPDATE collections SET updated_at = ? WHERE id = ?",
                (_iso(item.created_at), item.collection_id),
            )
            return item

        return self._write(run), True

    def items(self, collection_id: str) -> list[CollectionItem]:
        rows = self._read(
            "SELECT * FROM collection_items WHERE collection_id = ? ORDER BY position",
            (collection_id,),
        )
        return [_item_from(r) for r in rows]

    def update_note(self, item_id: str, note: str) -> bool:
        def run(conn):
            row = conn.execute(
                "SELECT data FROM collection_items WHERE id = ?", (item_id,)
            ).fetchone()
            if row is None:
                return False
            return (
                conn.execute(
                    "UPDATE collection_items SET note = ? WHERE id = ?", (note, item_id)
                ).rowcount
                > 0
            )

        return self._write(run)

    def delete_item(self, item_id: str) -> bool:
        return self._write(
            lambda conn: conn.execute(
                "DELETE FROM collection_items WHERE id = ?", (item_id,)
            ).rowcount
            > 0
        )
