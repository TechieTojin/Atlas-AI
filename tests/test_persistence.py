"""Persistence tests: runs, events, memory, documents (in-memory SQLite)."""

from datetime import timedelta

import pytest

from src.events.models import EventType, RunEvent
from src.models.research import Critique, CriticDecision, Evidence, EvidenceOrigin
from src.models.runs import ResearchRun, RunMode, RunStatus, SourceScope, utcnow
from src.persistence import (
    Database,
    EventsRepository,
    MemoryRepository,
    RunsRepository,
)
from tests.conftest import make_critique, make_evidence, make_plan


@pytest.fixture
def db():
    return Database(":memory:")


@pytest.fixture
def runs(db):
    return RunsRepository(db)


def make_run(**overrides) -> ResearchRun:
    defaults = dict(query="What is X?", mode=RunMode.FAST)
    defaults.update(overrides)
    return ResearchRun(**defaults)


class TestRunsRepository:
    def test_create_and_retrieve_roundtrip(self, runs):
        run = make_run()
        run.plan = make_plan()
        run.evidence = [make_evidence("https://a.com/1")]
        run.critique = make_critique(CriticDecision.SYNTHESIZE, score=8)
        run.final_report = "Report [1].\n\n## Sources\n\n1. x"
        runs.save(run)

        loaded = runs.get(run.id)
        assert loaded is not None
        assert loaded.query == "What is X?"
        assert loaded.mode is RunMode.FAST
        assert loaded.plan.tasks[0].subquestion == run.plan.tasks[0].subquestion
        assert loaded.evidence[0].source.url == "https://a.com/1"
        assert loaded.critique.overall_score == 8
        assert loaded.critique.decision is CriticDecision.SYNTHESIZE
        assert loaded.final_report.startswith("Report [1].")

    def test_update_run(self, runs):
        run = make_run()
        runs.save(run)
        run.status = RunStatus.COMPLETED
        run.final_report = "done"
        run.metrics.total_ms = 1234
        run.metrics.critic_scores = [7]
        runs.save(run)
        loaded = runs.get(run.id)
        assert loaded.status is RunStatus.COMPLETED
        assert loaded.metrics.total_ms == 1234
        assert loaded.metrics.critic_scores == [7]

    def test_get_missing_returns_none(self, runs):
        assert runs.get("nope") is None

    def test_list_newest_first_with_pagination(self, runs):
        base = utcnow()
        for i in range(5):
            run = make_run(query=f"q{i}")
            run.created_at = base + timedelta(seconds=i)
            runs.save(run)
        page, total = runs.list(limit=2, offset=0)
        assert total == 5
        assert [r.query for r in page] == ["q4", "q3"]
        page2, _ = runs.list(limit=2, offset=2)
        assert [r.query for r in page2] == ["q2", "q1"]

    def test_search_filter(self, runs):
        runs.save(make_run(query="autonomous vehicles"))
        runs.save(make_run(query="quantum computing"))
        page, total = runs.list(search="quantum")
        assert total == 1
        assert page[0].query == "quantum computing"

    def test_delete(self, runs):
        run = make_run()
        runs.save(run)
        assert runs.delete(run.id) is True
        assert runs.get(run.id) is None
        assert runs.delete(run.id) is False

    def test_persistence_across_repository_instances(self, tmp_path):
        path = str(tmp_path / "atlas.db")
        run = make_run(query="durable?")
        RunsRepository(Database(path)).save(run)
        # Fresh Database + repository: data must still be there.
        loaded = RunsRepository(Database(path)).get(run.id)
        assert loaded is not None
        assert loaded.query == "durable?"


class TestEventsRepository:
    def test_events_roundtrip_ordered(self, db):
        repo = EventsRepository(db)
        for seq, type_ in enumerate(
            [EventType.RUN_STARTED, EventType.PLANNING_STARTED, EventType.RUN_COMPLETED],
            start=1,
        ):
            repo.append(RunEvent(type=type_, run_id="r1", seq=seq, message=f"m{seq}"))
        events = repo.list("r1")
        assert [e.type for e in events] == [
            EventType.RUN_STARTED,
            EventType.PLANNING_STARTED,
            EventType.RUN_COMPLETED,
        ]
        assert events[0].message == "m1"


class TestMemoryRepository:
    def test_store_and_lookup(self, db):
        repo = MemoryRepository(db)
        repo.store("What is X?", [make_evidence("https://a.com/1")])
        hits = repo.lookup("what is  x?", ttl_hours=24)  # normalized matching
        assert len(hits) == 1
        assert hits[0].source.url == "https://a.com/1"

    def test_ttl_zero_disables(self, db):
        repo = MemoryRepository(db)
        repo.store("q", [make_evidence("https://a.com/1")])
        assert repo.lookup("q", ttl_hours=0) == []

    def test_document_evidence_ignores_web_ttl(self, db):
        repo = MemoryRepository(db)
        doc_ev = Evidence(
            source=make_evidence("doc://d1#p1").source,
            content="c",
            origin=EvidenceOrigin.DOCUMENT,
        )
        repo.store("q", [doc_ev])
        # Simulate stale rows by querying with a tiny TTL: web rows would be
        # filtered by fetched_at, document rows must survive.
        hits = repo.lookup("q", ttl_hours=1)
        assert len(hits) == 1

    def test_delete_document_evidence(self, db):
        repo = MemoryRepository(db)
        doc_ev = Evidence(
            source=make_evidence("doc://d1#p1").source,
            content="c",
            origin=EvidenceOrigin.DOCUMENT,
        )
        repo.store("q", [doc_ev])
        repo.delete_document_evidence("d1")
        assert repo.lookup("q", ttl_hours=24) == []

    def test_upsert_replaces_same_query_url(self, db):
        repo = MemoryRepository(db)
        repo.store("q", [make_evidence("https://a.com/1", content="old")])
        repo.store("q", [make_evidence("https://a.com/1", content="new")])
        hits = repo.lookup("q", ttl_hours=24)
        assert len(hits) == 1
        assert hits[0].content == "new"
