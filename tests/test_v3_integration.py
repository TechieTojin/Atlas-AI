"""Cross-feature V3 integration and database-migration tests."""

import sqlite3

from src.models.research import CriticDecision
from src.models.runs import RunStatus, SourceScope
from src.models.workspace import Project
from src.persistence.db import _MIGRATIONS, Database
from src.services.comparison_synthesis import (
    ComparisonPoint,
    ComparisonSynthesis,
    Conclusion,
)
from src.services.kg_service import KGExtraction, ProposedEntity, ProposedRelation
from src.tools.webpage import FetchedPage
from tests.conftest import FakeLLM, make_critique, make_plan, make_search_fn
from tests.conftest_v2 import make_container

WEB = [
    {"url": "https://nature.com/articles/tr1", "title": "Nature TR",
     "content": "Separator failure initiates thermal runaway.", "score": 0.9},
    {"url": "https://reddit.com/r/batteries/1", "title": "Reddit thread",
     "content": "Anecdotes about battery fires.", "score": 0.6},
]


class PageFetcherStub:
    def fetch(self, url):
        return FetchedPage(
            url=url,
            text="Full page content: separator melting cascades into thermal "
                 "runaway through exothermic reactions in lithium cells. " * 10,
        )


class TestMigration:
    def test_fresh_database_reaches_latest_version(self, tmp_path):
        db = Database(str(tmp_path / "fresh.db"))
        conn = db.connect()
        version = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()["v"]
        db.release(conn)
        assert version == len(_MIGRATIONS) == 3  # v3 adds project memory

    def test_v1_database_upgrades_preserving_data(self, tmp_path):
        """Simulate a pre-V3 database and verify a non-destructive upgrade."""
        path = str(tmp_path / "old.db")
        conn = sqlite3.connect(path)
        conn.executescript(
            "CREATE TABLE schema_version (version INTEGER NOT NULL);"
            "INSERT INTO schema_version VALUES (1);"
        )
        conn.executescript(_MIGRATIONS[0])  # v1 schema
        conn.execute(
            "INSERT INTO runs (id, query, mode, source_scope, status, created_at, "
            "updated_at, data) VALUES ('old1', 'old question', 'DEEP', 'WEB', "
            "'COMPLETED', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00', "
            "'{\"final_report\": \"old report\", \"evidence\": []}')"
        )
        conn.execute(
            "INSERT INTO memory (query_norm, url_norm, origin, fetched_at, evidence) "
            "VALUES ('old q', 'https://a.com/1', 'web', '2026-01-01T00:00:00+00:00', "
            "'{\"source\": {\"title\": \"A\", \"url\": \"https://a.com/1\"}, "
            "\"content\": \"c\"}')"
        )
        conn.commit()
        conn.close()

        db = Database(path)  # applies v2
        from src.persistence import MemoryRepository, RunsRepository

        run = RunsRepository(db).get("old1")
        assert run is not None
        assert run.final_report == "old report"
        assert run.project_id == "" and run.template == "STANDARD"
        hits = MemoryRepository(db).lookup("old q", ttl_hours=10**6)
        assert len(hits) == 1  # memory rows survived the table rebuild

    def test_migration_idempotent(self, tmp_path):
        path = str(tmp_path / "idem.db")
        Database(path)
        Database(path)  # reopening must not re-apply or fail
        conn = Database(path).connect()
        count = conn.execute("SELECT COUNT(*) AS n FROM schema_version").fetchone()["n"]
        assert count == len(_MIGRATIONS)  # each migration applied exactly once


class TestEndToEndPipeline:
    def test_project_full_pipeline(self, tmp_path):
        """Project → document → research (full-page + quality + memory) →
        claims → follow-up → regenerate → comparison → KG → PDF."""
        llm = FakeLLM(
            plans=[make_plan(n_queries=1)],
            critiques=[make_critique(CriticDecision.SYNTHESIZE, score=9)],
            synthesis=[
                "## Findings\n\nSeparator failure causes runaway [1]. Community "
                "reports agree [2]. Documents confirm [3].",
                "Follow-up answer [1].",
                "Regenerated [1][2].",
                "Comparison: both agree [1].",
            ],
        )
        llm.queue_structured(
            KGExtraction,
            [KGExtraction(
                entities=[ProposedEntity(name="Separator failure", type="finding"),
                          ProposedEntity(name="Thermal runaway", type="risk")],
                relations=[ProposedRelation(source="Separator failure",
                                            target="Thermal runaway",
                                            relation="causes",
                                            evidence_numbers=[1])],
            )],
        )
        c = make_container(
            tmp_path, llm=llm,
            search_fn=make_search_fn(default=WEB),
            page_fetcher=PageFetcherStub(),
            page_fetch_per_query=1,
        )

        # Project + document
        project = Project(name="Battery Safety")
        c.projects_repo.save(project)
        doc = c.document_service.ingest(
            "safety.txt", b"Internal testing shows separator melting at 150C. " * 20
        )
        c.documents_repo.set_project(doc.id, project.id)

        # Research with web + documents inside the project
        run = c.research_service.create_run(
            "Why thermal runaway?",
            source_scope=SourceScope.WEB_AND_DOCUMENTS,
            document_ids=[doc.id],
            project_id=project.id,
            template="TECHNICAL",
        )
        final = c.research_service.get_run(run.id)
        assert final.status is RunStatus.COMPLETED
        assert final.project_id == project.id

        # Feature 2: page content enriched one web evidence item.
        assert final.metrics.pages_fetched == 1
        full_page = [e for e in final.evidence if e.extraction == "full_page"]
        assert full_page and full_page[0].fetched_at

        # Feature 1: quality attached and distributed in metrics.
        tiers = final.metrics.source_quality_tiers
        assert tiers.get("high", 0) >= 2  # nature.com + user document
        assert tiers.get("low", 0) == 1  # reddit

        # Feature 6: evidence remembered into project-scoped memory.
        hits = c.memory_service.recall(
            "av barriers query 0", 5, project_id=project.id
        )
        assert hits and hits[0].origin.value == "memory"

        # Feature 5: claims map deterministically to citations.
        from src.evaluation.claims import extract_claims

        claims = extract_claims(final.final_report, len(final.selected_sources))
        assert any(c_.citations == [1] for c_ in claims)

        # Feature 3: analytical follow-up with stable numbering.
        followup = c.followup_service.create(run.id, "Explain simply")
        done = c.followup_service.get(followup.id)
        assert done.status.value == "COMPLETED"
        assert [s.url for s in done.sources] == [s.url for s in final.selected_sources]

        # Feature 4: regeneration from existing evidence, linked to source.
        regen = c.research_service.regenerate_report(run.id, "EXECUTIVE")
        regen_final = c.research_service.get_run(regen.id)
        assert regen_final.regenerated_from == run.id
        assert regen_final.status is RunStatus.COMPLETED

        # Feature 9: compare original and regenerated runs inside the project.
        # Comparison synthesis returns structured data; Atlas renders the report.
        llm.queue_structured(ComparisonSynthesis, [ComparisonSynthesis(
            overview="The runs converge on the same finding from shared evidence.",
            agreements=[ComparisonPoint(
                id="A1", text="Both runs rely on the same evidence.",
                runs=[1, 2], citations=[1],
            )],
            contradictions=[],
            unique_evidence=[],
            conclusion=Conclusion(
                text="The regenerated run reaches the same conclusion.",
                based_on=["A1"],
            ),
        )])
        comparison = c.comparison_service.create(
            [run.id, regen.id], project_id=project.id
        )
        comp_final = c.comparison_service.get(comparison.id)
        assert comp_final.status.value == "COMPLETED"
        assert comp_final.overlap_stats["shared_sources"] >= 1

        # Feature 10: knowledge graph with real provenance.
        c.kg_service.generate(run.id)
        graph = c.kg_service.get(run.id)
        assert graph.status == "READY"
        assert graph.edges[0].support[0].source_url in {
            s.url for s in final.selected_sources
        }
        project_graph = c.kg_service.get_for_project([run.id, regen.id])
        assert project_graph.nodes

        # Feature 8: PDF export of the completed run.
        from src.export.pdf import render_run_pdf

        pdf = render_run_pdf(final)
        assert pdf[:5] == b"%PDF-"

        # Provenance integrity across the board: every rendered source URL
        # in the report is a really collected one.
        import re

        urls = set(re.findall(r"\((https?://[^)]+)\)", final.final_report))
        collected = {e.source.url for e in final.evidence}
        assert urls <= collected

    def test_force_fresh_research_bypasses_memory(self, tmp_path):
        llm1 = FakeLLM(
            plans=[make_plan(n_queries=1)],
            critiques=[make_critique(CriticDecision.SYNTHESIZE, score=9)],
        )
        search = make_search_fn(default=WEB)
        path = str(tmp_path / "m.db")
        c = make_container(tmp_path, llm=llm1, search_fn=search, db_path=path)
        c.research_service.create_run("q one")
        calls_after_first = len(search.calls)

        llm2 = FakeLLM(
            plans=[make_plan(n_queries=1)],
            critiques=[make_critique(CriticDecision.SYNTHESIZE, score=9)],
        )
        c2 = make_container(tmp_path, llm=llm2, search_fn=search, db_path=path)
        run = c2.research_service.create_run("q two", use_memory=False)
        final = c2.research_service.get_run(run.id)
        assert final.metrics.memory_hits == 0
        assert len(search.calls) > calls_after_first  # really searched again
