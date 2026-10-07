"""Repository for durable run events (replay for reopened runs / SSE)."""

from __future__ import annotations

import json
import sqlite3

from src.events.models import RunEvent
from src.persistence.db import Database, PersistenceError


class EventsRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def append(self, event: RunEvent) -> None:
        conn = self._db.connect()
        try:
            with self._db.write_lock:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO events
                        (run_id, seq, type, timestamp, agent, message, iteration, payload)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.run_id,
                        event.seq,
                        event.type.value,
                        event.timestamp.isoformat(),
                        event.agent,
                        event.message,
                        event.iteration,
                        json.dumps(event.payload),
                    ),
                )
                conn.commit()
        except sqlite3.Error as exc:
            raise PersistenceError(f"Failed to persist event: {exc}") from exc
        finally:
            self._db.release(conn)

    def list(self, run_id: str) -> list[RunEvent]:
        conn = self._db.connect()
        try:
            rows = conn.execute(
                "SELECT * FROM events WHERE run_id = ? ORDER BY seq", (run_id,)
            ).fetchall()
        except sqlite3.Error as exc:
            raise PersistenceError(f"Failed to load events: {exc}") from exc
        finally:
            self._db.release(conn)
        return [
            RunEvent(
                type=r["type"],
                run_id=r["run_id"],
                seq=r["seq"],
                timestamp=r["timestamp"],
                agent=r["agent"],
                message=r["message"],
                iteration=r["iteration"],
                payload=json.loads(r["payload"]),
            )
            for r in rows
        ]
