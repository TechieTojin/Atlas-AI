"""Tests for the deterministic project knowledge graph.

The graph's value rests on two promises: it never invents knowledge, and it never
costs an LLM call. Both are asserted here rather than assumed.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.api.container import Container
from src.models.memory import FindingSource, ProjectFinding
from src.models.runs import ResearchRun, RunStatus
from src.models.workspace import Project
from src.services.project_graph import (
    ProjectGraphService,
    candidate_phrases,
    concept_id,
    extract_concepts,
)

BASE = datetime(2026, 10, 1, tzinfo=timezone.utc)


def make_finding(text: str, *, run_id: str = "run-1", section: str = "", index: int = 0,
                 project_id: str = "proj-1", question: str = "What are the barriers?",
                 sources: list[FindingSource] | None = None) -> ProjectFinding:
    return ProjectFinding(
        id=f"f{index}",
        project_id=project_id,
        run_id=run_id,
        question=question,
        section=section,
        text=text,
        sources=sources if sources is not None else [FindingSource(url="https://x.test/a", title="A")],
        created_at=BASE + timedelta(minutes=index),
    )


def battery_findings() -> list[ProjectFinding]:
    """A small corpus shaped like real Atlas findings: two runs, overlapping ideas."""
    rows = [
        ("run-a", "Interface Stability", "Interface stability limits solid-state cells because dendrites form at the boundary."),
        ("run-a", "Interface Stability", "Poor particle contact worsens interface stability across the electrolyte boundary."),
        ("run-a", "Manufacturing", "Manufacturing scalability is constrained by dry-room requirements and throughput."),
        ("run-b", "Interface Stability", "Interface stability remains the dominant barrier reported by independent groups."),
        ("run-b", "Manufacturing", "Manufacturing scalability suffers because isostatic pressing is slow and costly."),
        ("run-b", "Cost", "Raw material cost keeps solid-state cells less competitive than lithium-ion packs."),
    ]
    return [
        make_finding(text, run_id=run, section=section, index=i)
        for i, (run, section, text) in enumerate(rows)
    ]


# -- concept extraction ----------------------------------------------------------


def test_phrases_never_cross_punctuation_or_include_stopwords():
    phrases = candidate_phrases("Interface stability matters. Cost of materials is high.")
    assert "interface stability" in phrases
    # "stability matters" would span a sentence boundary; "cost of" contains a stopword.
    assert "stability cost" not in phrases
    assert not any(" of " in f" {p} " for p in phrases)


def test_concepts_emerge_from_the_findings_themselves():
    concepts = extract_concepts(battery_findings(), project_id="proj-1")
    labels = {c.label for c in concepts}
    assert "interface stability" in labels
    assert any("manufacturing scalability" in label for label in labels)


def test_generic_and_boilerplate_terms_are_excluded():
    findings = battery_findings() + [
        make_finding("This research report presents an analysis of the current system issue.",
                     run_id="run-a", section="Conclusion", index=90),
        make_finding("The research analysis shows the current system has an issue.",
                     run_id="run-b", section="Conclusion", index=91),
    ]
    labels = {c.label for c in extract_concepts(findings, project_id="proj-1")}
    for noise in ("research", "analysis", "current", "system", "issue", "report"):
        assert noise not in labels, f"generic term {noise!r} became a concept"


def test_project_name_words_do_not_become_concepts():
    findings = [
        make_finding("Battery technology research shows interface stability is the barrier.",
                     run_id="run-a", index=i)
        for i in range(3)
    ]
    labels = {c.label for c in extract_concepts(
        findings, project_id="proj-1", project_name="Battery Technology Research")}
    assert "battery" not in labels and "technology" not in labels


def test_a_single_mention_is_not_a_concept():
    findings = [make_finding("Niobium coatings appeared once in this corpus.", index=0)]
    assert extract_concepts(findings, project_id="proj-1") == []


def test_near_duplicate_phrasings_collapse_into_one_concept():
    findings = [
        make_finding("Manufacturing scalability is the limit.", run_id="run-a", index=0),
        make_finding("Scalability of manufacturing is the limit.", run_id="run-b", index=1),
        make_finding("Manufacturing scalability blocks mass production.", run_id="run-a", index=2),
    ]
    labels = [c.label for c in extract_concepts(findings, project_id="proj-1")]
    scalability = [label for label in labels if "scalab" in label]
    assert len(scalability) == 1, f"variants were not merged: {scalability}"


def test_a_longer_phrase_absorbs_a_redundant_shorter_one():
    findings = [
        make_finding("Interface stability is the barrier.", run_id="run-a", index=0),
        make_finding("Interface stability limits cells.", run_id="run-b", index=1),
        make_finding("Interface stability again.", run_id="run-a", index=2),
    ]
    labels = {c.label for c in extract_concepts(findings, project_id="proj-1")}
    # "stability" occurs only ever inside "interface stability", so it is redundant.
    assert "interface stability" in labels
    assert "stability" not in labels


def test_a_short_phrase_with_its_own_evidence_survives():
    findings = [
        make_finding("Interface stability is the barrier.", run_id="run-a", index=0),
        make_finding("Interface stability limits cells.", run_id="run-b", index=1),
        make_finding("Thermal stability is a separate concern entirely.", run_id="run-a", index=2),
        make_finding("Chemical stability degrades over cycling.", run_id="run-b", index=3),
        make_finding("Mechanical stability also varies by electrolyte.", run_id="run-a", index=4),
    ]
    labels = {c.label for c in extract_concepts(findings, project_id="proj-1")}
    assert "stability" in labels, "a phrase with independent evidence must not be absorbed"


def test_support_counts_are_findings_and_distinct_runs():
    concepts = {c.label: c for c in extract_concepts(battery_findings(), project_id="proj-1")}
    interface = concepts["interface stability"]
    assert interface.finding_count == 3
    assert interface.support_count == 2  # run-a and run-b


def test_duplicate_findings_from_one_run_do_not_inflate_the_run_count():
    findings = [
        make_finding(f"Interface stability is the barrier, restated {i}.", run_id="run-a", index=i)
        for i in range(5)
    ]
    concept = {c.label: c for c in extract_concepts(findings, project_id="proj-1")}["interface stability"]
    assert concept.finding_count == 5
    assert concept.support_count == 1, "five findings from one run is still one run of support"


def test_concept_ids_are_stable_across_rebuilds():
    first = extract_concepts(battery_findings(), project_id="proj-1")
    second = extract_concepts(battery_findings(), project_id="proj-1")
    assert [concept_id("proj-1", c.key) for c in first] == [concept_id("proj-1", c.key) for c in second]


def test_concept_ids_differ_between_projects():
    concepts = extract_concepts(battery_findings(), project_id="proj-1")
    key = concepts[0].key
    assert concept_id("proj-1", key) != concept_id("proj-2", key)


# -- graph assembly --------------------------------------------------------------


class FakeProject:
    def __init__(self, id: str, name: str, description: str = "") -> None:
        self.id, self.name, self.description = id, name, description


class FakeSummary:
    def __init__(self, id: str, status: RunStatus, title: str = "A question?") -> None:
        self.id, self.status, self.title, self.query = id, status, title, title


class FakeProjects:
    def __init__(self, projects): self._p = {p.id: p for p in projects}
    def get(self, project_id): return self._p.get(project_id)


class FakeRuns:
    def __init__(self, summaries): self._s = summaries
    def list(self, limit=200, project_id=None): return list(self._s), len(self._s)


class FakeFindings:
    def __init__(self, findings): self._f = findings
    def list_for_project(self, project_id):
        return [f for f in self._f if f.project_id == project_id]


def build_graph(findings, *, statuses=None, name="Battery Technology Research"):
    statuses = statuses or {"run-a": RunStatus.COMPLETED, "run-b": RunStatus.COMPLETED}
    service = ProjectGraphService(
        FakeProjects([FakeProject("proj-1", name), FakeProject("proj-2", "Other")]),
        FakeRuns([FakeSummary(rid, status) for rid, status in statuses.items()]),
        FakeFindings(findings),
    )
    return service.build("proj-1")


def test_a_project_with_findings_produces_a_graph():
    graph = build_graph(battery_findings())
    types = {node["type"] for node in graph["nodes"]}
    assert types == {"project", "concept", "finding"}
    assert graph["stats"]["concepts"] > 0
    assert graph["stats"]["runs"] == 2
    relations = {edge["relation"] for edge in graph["edges"]}
    assert "HAS_TOPIC" in relations and "SUPPORTED_BY" in relations


def test_an_empty_project_returns_a_valid_empty_graph():
    graph = build_graph([], statuses={})
    assert graph["stats"] == {"concepts": 0, "findings": 0, "runs": 0}
    assert [node["type"] for node in graph["nodes"]] == ["project"]
    assert graph["edges"] == []


def test_a_missing_project_returns_none():
    assert build_graph([]) is not None
    service = ProjectGraphService(FakeProjects([]), FakeRuns([]), FakeFindings([]))
    assert service.build("nope") is None


def test_no_cross_project_leakage():
    other = [
        make_finding("Photovoltaic efficiency rose sharply this decade.",
                     project_id="proj-2", run_id="run-a", index=50),
        make_finding("Photovoltaic efficiency gains continue to accrue.",
                     project_id="proj-2", run_id="run-b", index=51),
    ]
    graph = build_graph(battery_findings() + other)
    text = " ".join(node["label"] for node in graph["nodes"])
    assert "photovoltaic" not in text.lower()
    assert all(node["project_id"] == "proj-1" for node in graph["nodes"])


def test_failed_and_cancelled_runs_contribute_no_knowledge():
    findings = battery_findings() + [
        make_finding("Hydrogen fuel cells dominate heavy transport decisively.",
                     run_id="run-bad", index=60),
        make_finding("Hydrogen fuel cells will replace all batteries by 2027.",
                     run_id="run-bad", index=61),
    ]
    graph = build_graph(findings, statuses={
        "run-a": RunStatus.COMPLETED,
        "run-b": RunStatus.COMPLETED,
        "run-bad": RunStatus.FAILED,
    })
    text = " ".join(node["label"] for node in graph["nodes"]).lower()
    assert "hydrogen" not in text
    assert graph["stats"]["findings"] == 6
    assert graph["stats"]["runs"] == 2


def test_findings_keep_full_provenance():
    graph = build_graph(battery_findings())
    findings = [node for node in graph["nodes"] if node["type"] == "finding"]
    assert findings
    for node in findings:
        assert node["text"]
        assert node["source_run_id"] in {"run-a", "run-b"}
        assert node["source_question"] == "What are the barriers?"
        assert node["section"]
        assert node["sources"] and node["sources"][0]["url"].startswith("https://")


def test_relationships_are_deterministic_and_never_causal():
    graph = build_graph(battery_findings())
    relations = {edge["relation"] for edge in graph["edges"]}
    # Similarity and co-occurrence must never be dressed up as causation.
    assert relations <= {"HAS_TOPIC", "SUPPORTED_BY", "RELATED_TO"}
    for edge in graph["edges"]:
        assert edge["relation"] not in {"CAUSES", "PREVENTS", "PROVES"}


def test_every_edge_connects_real_nodes():
    graph = build_graph(battery_findings())
    ids = {node["id"] for node in graph["nodes"]}
    for edge in graph["edges"]:
        assert edge["source"] in ids and edge["target"] in ids
        assert edge["source"] != edge["target"]


def test_repeated_generation_is_idempotent():
    assert build_graph(battery_findings()) == build_graph(battery_findings())


def test_concept_counts_match_the_edges_drawn():
    graph = build_graph(battery_findings())
    supported = {}
    for edge in graph["edges"]:
        if edge["relation"] == "SUPPORTED_BY":
            supported.setdefault(edge["source"], set()).add(edge["target"])
    for node in graph["nodes"]:
        if node["type"] == "concept":
            assert node["finding_count"] == len(supported[node["id"]])


def test_the_default_view_stays_readable():
    """Many findings must not produce an unbounded concept list."""
    findings = [
        make_finding(f"Interface stability and manufacturing scalability interact in case {i}.",
                     run_id="run-a" if i % 2 else "run-b", index=i)
        for i in range(60)
    ]
    graph = build_graph(findings)
    concepts = [n for n in graph["nodes"] if n["type"] == "concept"]
    assert len(concepts) <= 10


# -- the real database -----------------------------------------------------------


def test_graph_builds_from_a_real_container_without_any_model(tmp_path, monkeypatch):
    """The endpoint path must work end to end with no LLM and no embedding call."""

    def explode(*args, **kwargs):  # pragma: no cover - only runs on regression
        raise AssertionError("the project graph must not call a model")

    container = Container(db_path=tmp_path / "atlas.db", embed_fn=explode, llm_factory=explode)
    project = Project(name="Battery Technology Research")
    container.projects_repo.save(project)
    run = ResearchRun(query="What are the barriers?", project_id=project.id,
                      status=RunStatus.COMPLETED)
    container.runs_repo.save(run)
    container.findings_repo.add_many([
        make_finding(text, run_id=run.id, section="Interface Stability",
                     index=i, project_id=project.id)
        for i, text in enumerate([
            "Interface stability limits solid-state cells at the boundary.",
            "Interface stability degrades with poor particle contact.",
        ])
    ])

    graph = container.project_graph_service.build(project.id)

    assert graph is not None
    assert graph["stats"]["findings"] == 2
    assert "interface stability" in {n["label"] for n in graph["nodes"]}


def test_findings_from_runs_outside_the_project_are_ignored(tmp_path):
    """Stored findings only count when a completed run of this project produced them."""
    container = Container(db_path=tmp_path / "atlas.db",
                          embed_fn=lambda texts: [[0.0] * 8 for _ in texts])
    project = Project(name="Battery Technology Research")
    container.projects_repo.save(project)
    container.findings_repo.add_many([
        make_finding("Interface stability limits solid-state cells.", run_id="ghost-run",
                     index=0, project_id=project.id),
        make_finding("Interface stability degrades over cycling.", run_id="ghost-run",
                     index=1, project_id=project.id),
    ])

    graph = container.project_graph_service.build(project.id)

    assert graph["stats"] == {"concepts": 0, "findings": 0, "runs": 0}


@pytest.mark.parametrize("missing", ["", "   "])
def test_blank_sections_and_text_are_tolerated(missing):
    findings = [
        make_finding("Interface stability is the barrier.", section=missing, run_id="run-a", index=0),
        make_finding("Interface stability limits cells.", section=missing, run_id="run-b", index=1),
    ]
    graph = build_graph(findings)
    assert graph["stats"]["concepts"] >= 1


# -- the HTTP endpoint -----------------------------------------------------------


class TestEndpoint:
    @pytest.fixture
    def client(self, tmp_path):
        from fastapi.testclient import TestClient

        from src.api.app import create_app
        from tests.conftest_v2 import make_container

        container = make_container(tmp_path)
        app = create_app(container)
        with TestClient(app) as test_client:
            test_client.container = container
            yield test_client

    def _seed(self, client) -> str:
        container = client.container
        project = Project(name="Battery Technology Research")
        container.projects_repo.save(project)
        run = ResearchRun(query="What are the barriers?", project_id=project.id,
                          status=RunStatus.COMPLETED)
        container.runs_repo.save(run)
        container.findings_repo.add_many([
            make_finding(text, run_id=run.id, section="Interface Stability",
                         index=i, project_id=project.id)
            for i, text in enumerate([
                "Interface stability limits solid-state cells at the boundary.",
                "Interface stability degrades badly with poor particle contact.",
            ])
        ])
        return project.id

    def test_returns_the_derived_graph(self, client):
        project_id = self._seed(client)

        response = client.get(f"/api/projects/{project_id}/knowledge-graph")

        assert response.status_code == 200
        body = response.json()
        assert body["stats"]["findings"] == 2
        assert "interface stability" in {node["label"] for node in body["nodes"]}
        assert body["nodes"][0]["type"] == "project"

    def test_unknown_project_is_a_404(self, client):
        response = client.get("/api/projects/missing/knowledge-graph")
        assert response.status_code == 404

    def test_a_project_without_research_returns_an_empty_graph(self, client):
        project = Project(name="Empty")
        client.container.projects_repo.save(project)

        body = client.get(f"/api/projects/{project.id}/knowledge-graph").json()

        assert body["stats"] == {"concepts": 0, "findings": 0, "runs": 0}
        assert body["edges"] == []
