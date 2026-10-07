"""Feature 6: semantic research memory."""

from src.memory.service import MemoryService
from src.models.research import Evidence, EvidenceOrigin
from src.persistence import Database, MemoryRepository
from tests.conftest import make_evidence


def embedder(table):
    """Deterministic fake query embedder keyed by exact text."""
    def embed(query: str) -> list[float]:
        return table[query]
    return embed


def service(ttl=24, threshold=0.8, table=None):
    repo = MemoryRepository(Database(":memory:"))
    return (
        MemoryService(
            repo, ttl,
            embed_query=embedder(table) if table else None,
            semantic_threshold=threshold,
        ),
        repo,
    )


A = [1.0, 0.0, 0.0]
A_CLOSE = [0.95, 0.1, 0.0]
B = [0.0, 1.0, 0.0]

TABLE = {
    "battery thermal runaway": A,
    "li-ion battery fire risk": A_CLOSE,
    "giraffe habitats": B,
}


class TestSemanticRecall:
    def test_exact_hit_fast_path(self):
        svc, _ = service(table=TABLE)
        svc.remember("battery thermal runaway", [make_evidence("https://a.com/1")])
        hits = svc.recall("Battery  Thermal   Runaway", limit=5)
        assert len(hits) == 1
        assert hits[0].origin is EvidenceOrigin.MEMORY

    def test_semantic_hit_above_threshold(self):
        svc, _ = service(table=TABLE)
        svc.remember("battery thermal runaway", [make_evidence("https://a.com/1")])
        hits = svc.recall("li-ion battery fire risk", limit=5)
        assert len(hits) == 1
        # Provenance preserved: original web source untouched.
        assert hits[0].source.url == "https://a.com/1"
        assert hits[0].origin is EvidenceOrigin.MEMORY

    def test_below_threshold_misses(self):
        svc, _ = service(table=TABLE, threshold=0.8)
        svc.remember("battery thermal runaway", [make_evidence("https://a.com/1")])
        assert svc.recall("giraffe habitats", limit=5) == []

    def test_exact_and_semantic_deduplicate(self):
        svc, _ = service(table=TABLE)
        svc.remember("battery thermal runaway", [make_evidence("https://a.com/1")])
        svc.remember("li-ion battery fire risk", [make_evidence("https://a.com/1/")])
        hits = svc.recall("battery thermal runaway", limit=5)
        assert len(hits) == 1  # same normalized URL once

    def test_without_embedder_exact_only(self):
        svc, _ = service(table=None)
        svc.remember("battery thermal runaway", [make_evidence("https://a.com/1")])
        assert svc.recall("li-ion battery fire risk", limit=5) == []
        assert len(svc.recall("battery thermal runaway", limit=5)) == 1

    def test_ttl_zero_disables_everything(self):
        svc, _ = service(ttl=0, table=TABLE)
        assert svc.remember("battery thermal runaway", [make_evidence("https://a.com/1")]) == 0
        assert svc.recall("battery thermal runaway", limit=5) == []

    def test_embedding_cached_not_recomputed(self):
        calls = []

        def counting_embed(query):
            calls.append(query)
            return A

        repo = MemoryRepository(Database(":memory:"))
        svc = MemoryService(repo, 24, embed_query=counting_embed)
        svc.remember("battery thermal runaway", [make_evidence("https://a.com/1")])
        svc.recall("battery thermal runaway", limit=5)
        svc.recall("battery thermal runaway", limit=5)
        assert len(calls) == 1


class TestScopingAndLifecycle:
    def test_project_scope_sees_project_and_global(self):
        svc, _ = service(table=TABLE)
        svc.remember("battery thermal runaway", [make_evidence("https://global.com/1")])
        svc.remember("battery thermal runaway", [make_evidence("https://proj.com/1")],
                     project_id="p1")
        in_project = svc.recall("battery thermal runaway", limit=5, project_id="p1")
        assert {h.source.url for h in in_project} == {"https://global.com/1",
                                                      "https://proj.com/1"}
        global_only = svc.recall("battery thermal runaway", limit=5)
        assert {h.source.url for h in global_only} == {"https://global.com/1"}

    def test_document_deletion_prunes_memory(self):
        svc, repo = service(table=TABLE)
        doc_ev = Evidence(
            source=make_evidence("doc://d9#p2").source,
            content="c",
            origin=EvidenceOrigin.DOCUMENT,
        )
        svc.remember("battery thermal runaway", [doc_ev])
        repo.delete_document_evidence("d9")
        assert svc.recall("battery thermal runaway", limit=5) == []

    def test_semantic_ranking_deterministic(self):
        svc, _ = service(table=TABLE, threshold=0.5)
        svc.remember("battery thermal runaway", [make_evidence("https://a.com/1")])
        first = svc.recall("li-ion battery fire risk", limit=5)
        second = svc.recall("li-ion battery fire risk", limit=5)
        assert [h.source.url for h in first] == [h.source.url for h in second]
