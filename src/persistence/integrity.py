"""Repository for research integrity: claims, verification verdicts,
contradictions and quality scores.

All rows are *derived* artifacts: they are recomputed from a run's already
persisted report and evidence. Replacing a run's analysis therefore deletes
and rewrites only these derived rows — never the run, its report, its
evidence or any other historical artifact.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from src.models.integrity import (
    ClaimRecord,
    ClaimVerification,
    Contradiction,
    QualityComponent,
    QualityScore,
)
from src.persistence.db import Database, PersistenceError


def _iso(value: datetime) -> str:
    return value.isoformat()


def _claim_from(row: sqlite3.Row) -> ClaimRecord:
    data = dict(row)
    data["citations"] = json.loads(data.get("citations") or "[]")
    data["project_id"] = data.get("project_id") or None
    return ClaimRecord.model_validate(data)


def _verification_from(row: sqlite3.Row) -> ClaimVerification:
    data = dict(row)
    data["signals"] = json.loads(data.get("signals") or "[]")
    data["checked_citations"] = json.loads(data.get("checked_citations") or "[]")
    return ClaimVerification.model_validate(data)


def _contradiction_from(row: sqlite3.Row) -> Contradiction:
    data = dict(row)
    data["claim_id"] = data.get("claim_id") or None
    data["resolved"] = bool(data.get("resolved"))
    return Contradiction.model_validate(data)


def _quality_from(row: sqlite3.Row) -> QualityScore:
    data = dict(row)
    raw = json.loads(data.get("components") or "[]")
    data["components"] = [QualityComponent.model_validate(c) for c in raw]
    return QualityScore.model_validate(data)


class IntegrityRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def _read(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        conn = self._db.connect()
        try:
            return conn.execute(sql, params).fetchall()
        except sqlite3.Error as exc:
            raise PersistenceError(f"Integrity query failed: {exc}") from exc
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
            raise PersistenceError(f"Integrity write failed: {exc}") from exc
        finally:
            self._db.release(conn)

    # -- claims -------------------------------------------------------------------

    def replace_claims(self, run_id: str, claims: list[ClaimRecord]) -> None:
        """Atomically swap a run's derived claims.

        Cascades remove that run's verifications and contradictions too, so a
        re-analysis can never leave verdicts pointing at stale claim text.
        """

        def op(conn: sqlite3.Connection) -> None:
            conn.execute("DELETE FROM contradictions WHERE run_id = ?", (run_id,))
            conn.execute("DELETE FROM claim_verifications WHERE run_id = ?", (run_id,))
            conn.execute("DELETE FROM claims WHERE run_id = ?", (run_id,))
            for claim in claims:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO claims
                        (id, run_id, project_id, section, text, text_norm,
                         citations, position, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        claim.id,
                        claim.run_id,
                        claim.project_id or "",
                        claim.section,
                        claim.text,
                        claim.text_norm,
                        json.dumps(claim.citations),
                        claim.position,
                        _iso(claim.created_at),
                    ),
                )

        self._write(op)

    def claims_for_run(self, run_id: str) -> list[ClaimRecord]:
        rows = self._read(
            "SELECT * FROM claims WHERE run_id = ? ORDER BY position, id", (run_id,)
        )
        return [_claim_from(r) for r in rows]

    def claim(self, claim_id: str) -> ClaimRecord | None:
        rows = self._read("SELECT * FROM claims WHERE id = ?", (claim_id,))
        return _claim_from(rows[0]) if rows else None

    # -- verifications ------------------------------------------------------------

    def save_verifications(self, run_id: str, verifications: list[ClaimVerification]) -> None:
        def op(conn: sqlite3.Connection) -> None:
            conn.execute("DELETE FROM claim_verifications WHERE run_id = ?", (run_id,))
            for v in verifications:
                conn.execute(
                    """
                    INSERT INTO claim_verifications
                        (id, claim_id, run_id, status, confidence, verifier,
                         signals, explanation, checked_citations, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(claim_id) DO UPDATE SET
                        status = excluded.status,
                        confidence = excluded.confidence,
                        verifier = excluded.verifier,
                        signals = excluded.signals,
                        explanation = excluded.explanation,
                        checked_citations = excluded.checked_citations,
                        created_at = excluded.created_at
                    """,
                    (
                        v.id,
                        v.claim_id,
                        v.run_id,
                        v.status.value,
                        v.confidence.value,
                        v.verifier.value,
                        json.dumps([s.model_dump() for s in v.signals]),
                        v.explanation,
                        json.dumps(v.checked_citations),
                        _iso(v.created_at),
                    ),
                )

        self._write(op)

    def verifications_for_run(self, run_id: str) -> list[ClaimVerification]:
        rows = self._read(
            "SELECT * FROM claim_verifications WHERE run_id = ? ORDER BY id", (run_id,)
        )
        return [_verification_from(r) for r in rows]

    def verification_for_claim(self, claim_id: str) -> ClaimVerification | None:
        rows = self._read(
            "SELECT * FROM claim_verifications WHERE claim_id = ?", (claim_id,)
        )
        return _verification_from(rows[0]) if rows else None

    # -- contradictions -----------------------------------------------------------

    def save_contradictions(self, run_id: str, items: list[Contradiction]) -> None:
        def op(conn: sqlite3.Connection) -> None:
            conn.execute("DELETE FROM contradictions WHERE run_id = ?", (run_id,))
            for c in items:
                conn.execute(
                    """
                    INSERT INTO contradictions
                        (id, run_id, claim_id, kind, source_a, source_b,
                         excerpt_a, excerpt_b, explanation, resolved, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        c.id,
                        c.run_id,
                        c.claim_id or "",
                        c.kind.value,
                        c.source_a,
                        c.source_b,
                        c.excerpt_a,
                        c.excerpt_b,
                        c.explanation,
                        1 if c.resolved else 0,
                        _iso(c.created_at),
                    ),
                )

        self._write(op)

    def contradictions_for_run(self, run_id: str) -> list[Contradiction]:
        rows = self._read(
            "SELECT * FROM contradictions WHERE run_id = ? ORDER BY source_a, source_b, id",
            (run_id,),
        )
        return [_contradiction_from(r) for r in rows]

    def unresolved_contradiction_count(self) -> int:
        rows = self._read("SELECT COUNT(*) AS n FROM contradictions WHERE resolved = 0")
        return int(rows[0]["n"]) if rows else 0

    # -- quality ------------------------------------------------------------------

    def save_quality(self, score: QualityScore) -> None:
        self._write(
            lambda conn: conn.execute(
                """
                INSERT INTO quality_scores
                    (run_id, formula_version, overall, components, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    formula_version = excluded.formula_version,
                    overall = excluded.overall,
                    components = excluded.components,
                    created_at = excluded.created_at
                """,
                (
                    score.run_id,
                    score.formula_version,
                    score.overall,
                    json.dumps([c.model_dump() for c in score.components]),
                    _iso(score.created_at),
                ),
            )
        )

    def quality_for_run(self, run_id: str) -> QualityScore | None:
        rows = self._read("SELECT * FROM quality_scores WHERE run_id = ?", (run_id,))
        return _quality_from(rows[0]) if rows else None

    def unsupported_claim_count(self) -> int:
        rows = self._read(
            "SELECT COUNT(*) AS n FROM claim_verifications WHERE status IN ('UNSUPPORTED','CONTRADICTED')"
        )
        return int(rows[0]["n"]) if rows else 0
