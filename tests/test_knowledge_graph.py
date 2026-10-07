"""Feature 10: evidence-grounded knowledge graph."""

import pytest

from src.events.models import EventType
from src.models.research import CriticDecision, Source
from src.services.kg_service import (
    KGError,
    KGExtraction,
    ProposedEntity,
    ProposedRelation,
    normalize_entity_name,
    validate_extraction,
)
from tests.conftest import FakeLLM, make_critique, make_plan
from tests.conftest_v2 import make_container

SOURCES = [
    Source(title="A", url="https://a.com/1", domain="a.com"),
    Source(title="B", url="https://b.com/2", domain="b.com"),
]


def extraction(**kwargs):
    defaults = dict(
        entities=[
            ProposedEntity(name="Thermal runaway", type="risk"),
            ProposedEntity(name="Separator failure", type="finding"),
        ],
        relations=[
            ProposedRelation(
                source="Separator failure",
                target="Thermal runaway",
                relation="causes",
                evidence_numbers=[1],
            )
        ],
    )
    defaults.update(kwargs)
    return KGExtraction(**defaults)


class TestValidation:
    def test_valid_extraction_persisted_shape(self):
        nodes, edges = validate_extraction(extraction(), "r1", SOURCES, 40, 60)
        assert len(nodes) == 2
        assert len(edges) == 1
        edge = edges[0]
        assert edge.relation == "causes"
        assert edge.support[0].source_url == "https://a.com/1"  # real URL only

    def test_relation_without_valid_evidence_discarded(self):
        bad = extraction(
            relations=[
                ProposedRelation(source="Separator failure", target="Thermal runaway",
                                 relation="causes", evidence_numbers=[]),
                ProposedRelation(source="Separator failure", target="Thermal runaway",
                                 relation="mitigates", evidence_numbers=[99]),
            ]
        )
        _, edges = validate_extraction(bad, "r1", SOURCES, 40, 60)
        assert edges == []  # unsupported facts never persisted

    def test_relation_with_unknown_entity_discarded(self):
        bad = extraction(
            relations=[
                ProposedRelation(source="Ghost entity", target="Thermal runaway",
                                 relation="causes", evidence_numbers=[1])
            ]
        )
        _, edges = validate_extraction(bad, "r1", SOURCES, 40, 60)
        assert edges == []

    def test_entity_dedup_by_normalized_name(self):
        dup = extraction(
            entities=[
                ProposedEntity(name="Thermal Runaway", type="risk"),
                ProposedEntity(name="thermal  runaway", type="risk"),
                ProposedEntity(name="Separator failure", type="finding"),
            ]
        )
        nodes, _ = validate_extraction(dup, "r1", SOURCES, 40, 60)
        assert len(nodes) == 2
        assert normalize_entity_name("Thermal  Runaway") == "thermal runaway"

    def test_edge_dedup_and_multi_source_support(self):
        multi = extraction(
            relations=[
                ProposedRelation(source="Separator failure", target="Thermal runaway",
                                 relation="causes", evidence_numbers=[1, 2]),
                ProposedRelation(source="Separator failure", target="Thermal runaway",
                                 relation="causes", evidence_numbers=[2]),
            ]
        )
        _, edges = validate_extraction(multi, "r1", SOURCES, 40, 60)
        assert len(edges) == 1
        assert {s.source_url for s in edges[0].support} == {
            "https://a.com/1", "https://b.com/2",
        }

    def test_unknown_types_coerced(self):
        weird = extraction(
            entities=[ProposedEntity(name="X", type="galaxy"),
                      ProposedEntity(name="Y", type="risk")],
            relations=[ProposedRelation(source="X", target="Y",
                                        relation="teleports", evidence_numbers=[1])],
        )
        nodes, edges = validate_extraction(weird, "r1", SOURCES, 40, 60)
        assert nodes[0].type == "concept"
        assert edges[0].relation == "associated_with"

    def test_limits_enforced(self):
        big = extraction(
            entities=[ProposedEntity(name=f"E{i}", type="concept") for i in range(100)],
            relations=[],
        )
        nodes, _ = validate_extraction(big, "r1", SOURCES, 10, 5)
        assert len(nodes) == 10

    def test_self_loop_discarded(self):
        loop = extraction(
            relations=[ProposedRelation(source="Thermal runaway",
                                        target="thermal runaway",
                                        relation="causes", evidence_numbers=[1])]
        )
        _, edges = validate_extraction(loop, "r1", SOURCES, 40, 60)
        assert edges == []


class TestServiceAndPersistence:
    def _completed(self, tmp_path):
        llm = FakeLLM(
            plans=[make_plan()],
            critiques=[make_critique(CriticDecision.SYNTHESIZE, score=9)],
            synthesis="Report [1][2].",
        )
        llm.queue_structured(KGExtraction, [extraction()])
        c = make_container(tmp_path, llm=llm)
        run = c.research_service.create_run("q")
        return c, c.research_service.get_run(run.id)

    def test_generate_persist_and_reload(self, tmp_path):
        c, run = self._completed(tmp_path)
        c.kg_service.generate(run.id)
        graph = c.kg_service.get(run.id)
        assert graph.status == "READY"
        assert len(graph.nodes) == 2
        assert len(graph.edges) == 1
        assert graph.edges[0].support[0].source_url.startswith("https://")
        types = [e.type for e in c.bus.history(f"kg-{run.id}")]
        assert types == [EventType.KNOWLEDGE_GRAPH_STARTED,
                         EventType.KNOWLEDGE_GRAPH_COMPLETED]

    def test_empty_graph_state(self, tmp_path):
        c, run = self._completed(tmp_path)
        graph = c.kg_service.get(run.id)
        assert graph.status == "NONE"
        assert graph.nodes == []

    def test_requires_completed_run(self, tmp_path):
        c = make_container(tmp_path)
        run = c.research_service.create_run("q", approval_required=True)
        with pytest.raises(KGError):
            c.kg_service.generate(run.id)
        with pytest.raises(KGError, match="not found"):
            c.kg_service.generate("missing")

    def test_project_aggregation_merges_nodes_and_support(self, tmp_path):
        c, run = self._completed(tmp_path)
        c.kg_service.generate(run.id)
        # Second run with overlapping entity names.
        llm2 = FakeLLM(
            plans=[make_plan()],
            critiques=[make_critique(CriticDecision.SYNTHESIZE, score=9)],
            synthesis="Report2 [1][2].",
        )
        llm2.queue_structured(KGExtraction, [extraction()])
        c.research_service._llm_factory = lambda cfg, reasoning: llm2
        c.kg_service._llm_factory = lambda cfg, reasoning: llm2
        run2 = c.research_service.create_run("q2")
        c.kg_service.generate(run2.id)

        merged = c.kg_service.get_for_project([run.id, run2.id])
        assert merged.status == "READY"
        assert len(merged.nodes) == 2  # entities merged by name+type
        assert len(merged.edges) == 1

    def test_extraction_failure_marks_failed(self, tmp_path):
        llm = FakeLLM(
            plans=[make_plan()],
            critiques=[make_critique(CriticDecision.SYNTHESIZE, score=9)],
            synthesis="Report [1][2].",
        )
        # No KGExtraction queued -> structured invoke raises IndexError.
        c = make_container(tmp_path, llm=llm)
        run = c.research_service.create_run("q")
        c.kg_service.generate(run.id)
        graph = c.kg_service.get(run.id)
        assert graph.status == "FAILED"


class TestKgApi:
    def test_api_flow(self, tmp_path):
        from fastapi.testclient import TestClient
        from src.api.app import create_app

        llm = FakeLLM(
            plans=[make_plan()],
            critiques=[make_critique(CriticDecision.SYNTHESIZE, score=9)],
            synthesis="Report [1][2].",
        )
        llm.queue_structured(KGExtraction, [extraction()])
        c = make_container(tmp_path, llm=llm)
        with TestClient(create_app(c)) as client:
            run_id = client.post("/api/runs", json={"query": "q"}).json()["id"]
            empty = client.get(f"/api/runs/{run_id}/knowledge-graph").json()
            assert empty["status"] == "NONE"
            assert client.post(f"/api/runs/{run_id}/knowledge-graph").status_code == 202
            graph = client.get(f"/api/runs/{run_id}/knowledge-graph").json()
            assert graph["status"] == "READY"
            assert len(graph["nodes"]) == 2
            assert graph["edges"][0]["support"][0]["source_url"] == "https://a.com/1"
            assert client.get("/api/runs/missing/knowledge-graph").status_code == 404
