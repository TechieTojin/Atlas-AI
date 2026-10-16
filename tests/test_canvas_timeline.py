"""Canvas V2 branching and the Research Timeline: provenance-safe, deterministic."""

from __future__ import annotations

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.models.research import CriticDecision
from src.models.runs import BranchOrigin, ResearchRun, RunMode, RunStatus
from src.services.research_map import BRANCHABLE_TYPES, branch_context_for, build_research_map
from src.services.research_timeline import build_timeline
from tests.conftest import FakeLLM, make_critique, make_plan, make_search_fn
from tests.conftest_v2 import WEB_RESULTS, make_container


class Counting:
    def __init__(self):
        self.embeds = 0
        self.searches = 0

    def embed(self, texts):
        self.embeds += 1
        return [[float(len(t) % 7), 1.0, 0.5] for t in texts]

    def search_fn(self, inner):
        def run(query, n):
            self.searches += 1
            return inner(query, n)

        return run


def _container(tmp_path, llm=None, **kwargs):
    counting = Counting()
    llm = llm or FakeLLM(
        plans=[make_plan(n_queries=2), make_plan(n_queries=1)],
        critiques=[
            make_critique(CriticDecision.SYNTHESIZE, score=9),
            make_critique(CriticDecision.SYNTHESIZE, score=8),
        ],
        synthesis="Findings [1].",
    )
    container = make_container(
        tmp_path, llm=llm, embed_fn=counting.embed,
        search_fn=counting.search_fn(make_search_fn(default=WEB_RESULTS)), **kwargs,
    )
    return container, counting, llm


def _map_node(container, run_id, node_type):
    run = container.research_service.get_run(run_id)
    rmap = build_research_map(run, container.events_repo.list(run_id))
    return next(n for n in rmap["nodes"] if n["type"] == node_type)


def _run_row(container, run_id):
    conn = sqlite3.connect(container.db.path)
    try:
        return conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    finally:
        conn.close()


# --- branch context ---------------------------------------------------------------------


def test_branchable_types_are_research_material_only():
    assert BRANCHABLE_TYPES == {"question", "plan", "query", "source", "evidence", "critic"}
    for bad in ("synthesis", "report", "terminal", "project_memory", "branch"):
        with pytest.raises(ValueError):
            branch_context_for({"type": bad, "data": {}})


def test_branch_context_is_bounded_verbatim_stored_content():
    label, text = branch_context_for(
        {"type": "evidence", "data": {"content": "Stability drops in moisture. " * 60,
                                      "source_title": "Paper", "citation": 3}}
    )
    assert label == "an evidence excerpt of the parent run"
    assert text.startswith("From Paper [3]:") and "Stability drops in moisture." in text
    assert len(text) <= 700
    label, text = branch_context_for({"type": "query", "data": {"query": "perovskite encapsulation"}})
    assert text == "perovskite encapsulation"
    label, text = branch_context_for(
        {"type": "critic", "data": {"coverage": "Good", "missing_information": ["costs", "lifetime"]}}
    )
    assert "costs" in text and "lifetime" in text
    label, text = branch_context_for(
        {"type": "plan", "data": {"objective": "Understand X", "subquestions": ["A?", "B?"]}}
    )
    assert "Understand X" in text and "A?" in text


def test_planner_prompt_carries_branch_context_as_background():
    from src.agents.planner import PlannerAgent

    class Recording:
        def __init__(self):
            self.prompts = []

        def with_structured_output(self, schema):
            return self

        def invoke(self, messages):
            self.prompts.append(messages)
            return make_plan(n_queries=1)

    llm = Recording()
    planner = PlannerAgent(
        llm, 3, branch_context="From Paper [3]: stability drops in moisture.",
        branch_label="an evidence excerpt of the parent run",
    )
    planner({"question": "Investigate encapsulation methods."})
    user = llm.prompts[0][1][1]
    assert "BRANCH CONTEXT (an evidence excerpt of the parent run)" in user
    assert "stability drops in moisture" in user
    assert "newly retrieved sources" in user


# --- branch creation --------------------------------------------------------------------


def test_branching_from_evidence_creates_a_linked_child_and_leaves_the_parent_alone(tmp_path):
    container, counting, llm = _container(tmp_path, db_path=str(tmp_path / "runs.db"))
    parent = container.research_service.create_run("What is X?", mode=RunMode.FAST)
    evidence_node = _map_node(container, parent.id, "evidence")
    before = _run_row(container, parent.id)

    with TestClient(create_app(container)) as client:
        response = client.post(
            f"/api/runs/{parent.id}/branches",
            json={"node_id": evidence_node["id"],
                  "instruction": "Investigate the most effective encapsulation methods."},
        )
        assert response.status_code == 201
        child = response.json()
    assert child["query"] == "Investigate the most effective encapsulation methods."
    assert child["status"] == "COMPLETED"
    branch = child["branch"]
    assert branch["parent_run_id"] == parent.id
    assert branch["node_id"] == evidence_node["id"]
    assert branch["node_type"] == "evidence"
    assert branch["context_text"]
    # The child's citations come from its OWN retrieval, never inherited text.
    child_urls = {s["url"] for s in child["sources"]}
    assert child_urls <= {r["url"] for r in WEB_RESULTS}
    # Parent row is byte-identical: branching never mutates history.
    assert _run_row(container, parent.id) == before


def test_branching_is_rejected_for_presentation_nodes_and_unknown_nodes(tmp_path):
    container, _, _ = _container(tmp_path)
    parent = container.research_service.create_run("What is X?")
    with TestClient(create_app(container)) as client:
        bad = client.post(f"/api/runs/{parent.id}/branches",
                          json={"node_id": "synthesis", "instruction": "go"})
        assert bad.status_code == 422
        missing = client.post(f"/api/runs/{parent.id}/branches",
                              json={"node_id": "nope", "instruction": "go"})
        assert missing.status_code == 422
        no_parent = client.post("/api/runs/missing/branches",
                                json={"node_id": "question", "instruction": "go"})
        assert no_parent.status_code == 404


def test_child_inherits_scope_project_and_language_unless_overridden(tmp_path):
    container, _, _ = _container(tmp_path)
    from src.models.workspace import Project

    project = Project(name="P")
    container.projects_repo.save(project)
    parent = container.research_service.create_run("What is X?", project_id=project.id)
    node = _map_node(container, parent.id, "query")
    with TestClient(create_app(container)) as client:
        child = client.post(
            f"/api/runs/{parent.id}/branches",
            json={"node_id": node["id"], "instruction": "Dig deeper into query results."},
        ).json()
    assert child["project_id"] == project.id
    assert child["source_scope"] == "WEB" and child["output_language"] == "en"
    assert child["mode"] == "FAST"  # branches default to the bounded mode


def test_parent_map_shows_the_branch_and_children_lookup_is_ordered(tmp_path):
    container, _, _ = _container(tmp_path)
    parent = container.research_service.create_run("What is X?")
    node = _map_node(container, parent.id, "evidence")
    with TestClient(create_app(container)) as client:
        child = client.post(
            f"/api/runs/{parent.id}/branches",
            json={"node_id": node["id"], "instruction": "Explore further."},
        ).json()
        rmap = client.get(f"/api/runs/{parent.id}/research-map").json()
    branch_nodes = [n for n in rmap["nodes"] if n["type"] == "branch"]
    assert len(branch_nodes) == 1
    assert branch_nodes[0]["data"]["run_id"] == child["id"]
    assert branch_nodes[0]["status"] == "completed"
    assert any(
        e["source"] == node["id"] and e["target"] == f"branch:{child['id']}" and e["type"] == "BRANCHED"
        for e in rmap["edges"]
    )
    children = container.runs_repo.list_children(parent.id)
    assert [c.id for c in children] == [child["id"]]
    # And the child's own map never absorbs the parent's graph.
    child_map = build_research_map(
        container.research_service.get_run(child["id"]),
        container.events_repo.list(child["id"]),
    )
    assert not any(n["type"] == "branch" for n in child_map["nodes"])


def test_branched_child_uses_the_normal_run_lifecycle(tmp_path):
    container, _, _ = _container(tmp_path)
    parent = container.research_service.create_run("What is X?")
    node = _map_node(container, parent.id, "question")
    with TestClient(create_app(container)) as client:
        child = client.post(
            f"/api/runs/{parent.id}/branches",
            json={"node_id": node["id"], "instruction": "Wait for approval first.",
                  "mode": "DEEP"},
        ).json()
    # ImmediateExecutor ran it synchronously through the ordinary engine.
    stored = container.research_service.get_run(child["id"])
    assert stored.status is RunStatus.COMPLETED
    assert stored.branch is not None and stored.branch.parent_title


def test_branch_provenance_survives_persistence_round_trip(tmp_path):
    container, _, _ = _container(tmp_path)
    run = ResearchRun(
        query="child", branch=BranchOrigin(
            parent_run_id="p1", node_id="evidence:abc", node_type="evidence",
            context_label="an evidence excerpt of the parent run",
            context_text="From Paper [3]: stability drops.", instruction="child",
        ),
    )
    container.runs_repo.save(run)
    loaded = container.runs_repo.get(run.id)
    assert loaded.branch.parent_run_id == "p1"
    assert loaded.branch.context_text == "From Paper [3]: stability drops."
    assert container.runs_repo.list_children("p1")[0].id == run.id
    # Old rows without the field read as branch=None (no migration needed).
    plain = ResearchRun(query="old")
    container.runs_repo.save(plain)
    assert container.runs_repo.get(plain.id).branch is None


# --- timeline ---------------------------------------------------------------------------


def test_timeline_is_chronological_and_matches_stored_events(tmp_path):
    container, counting, llm = _container(tmp_path)
    run = container.research_service.create_run("What is X?")
    stored = container.research_service.get_run(run.id)
    events = container.events_repo.list(run.id)
    timeline = build_timeline(stored, events)
    kinds = [e["kind"] for e in timeline["entries"]]
    assert kinds[0] == "RUN_STARTED" and kinds[-1] == "RUN_COMPLETED"
    for expected in ("PLAN_CREATED", "SEARCH_STARTED", "SEARCH_QUERY_COMPLETED",
                     "EVIDENCE_COLLECTED", "CRITIC_COMPLETED", "SYNTHESIS_STARTED"):
        assert expected in kinds
    offsets = [e["offset_ms"] for e in timeline["entries"]]
    assert offsets == sorted(offsets) and offsets[0] == 0
    seqs = [e["seq"] for e in timeline["entries"]]
    assert seqs == sorted(seqs)  # equal timestamps keep event order
    plan_entry = next(e for e in timeline["entries"] if e["kind"] == "PLAN_CREATED")
    assert plan_entry["detail"]["queries"] == stored.plan.search_queries
    critic = next(e for e in timeline["entries"] if e["kind"] == "CRITIC_COMPLETED")
    assert critic["detail"]["score"] == 9 and critic["detail"]["decision"] == "SYNTHESIZE"
    assert timeline["incomplete"] is False and timeline["duration_ms"] is not None


def test_timeline_shows_the_second_iteration_only_when_it_happened(tmp_path):
    llm = FakeLLM(
        plans=[make_plan(n_queries=1)],
        critiques=[
            make_critique(CriticDecision.MORE_RESEARCH, follow_ups=["deeper"], score=4),
            make_critique(CriticDecision.SYNTHESIZE, score=9),
        ],
        synthesis="Findings [1].",
    )
    container, _, _ = _container(tmp_path, llm=llm)
    run = container.research_service.create_run("Loop?", mode=RunMode.DEEP)
    timeline = build_timeline(
        container.research_service.get_run(run.id), container.events_repo.list(run.id)
    )
    more = [e for e in timeline["entries"] if e["kind"] == "MORE_RESEARCH_REQUESTED"]
    assert len(more) == 1 and more[0]["detail"]["follow_up_queries"] == ["deeper"]
    assert [e["iteration"] for e in timeline["entries"] if e["kind"] == "SEARCH_STARTED"] == [1, 2]


def test_timeline_of_cancelled_and_failed_runs_is_truthful(tmp_path):
    container, _, _ = _container(tmp_path)
    run = container.research_service.create_run("Wait", approval_required=True)
    container.research_service.cancel(run.id)
    timeline = build_timeline(
        container.research_service.get_run(run.id), container.events_repo.list(run.id)
    )
    kinds = [e["kind"] for e in timeline["entries"]]
    assert "RUN_CANCELLED" in kinds and "SYNTHESIS_STARTED" not in kinds
    assert timeline["run_status"] == "CANCELLED"

    failing = FakeLLM(plans=[], critiques=[], synthesis="x")  # planner has nothing queued
    container2, _, _ = _container(tmp_path / "f", llm=failing)
    bad = container2.research_service.create_run("Fail")
    stored = container2.research_service.get_run(bad.id)
    timeline2 = build_timeline(stored, container2.events_repo.list(bad.id))
    assert timeline2["run_status"] == "FAILED"
    failed_entry = next(e for e in timeline2["entries"] if e["kind"] == "RUN_FAILED")
    assert failed_entry["detail"]["message"]


def test_timeline_without_events_is_marked_incomplete_never_invented(tmp_path):
    container, _, _ = _container(tmp_path)
    run = ResearchRun(query="historic", status=RunStatus.COMPLETED, final_report="R [1].")
    container.runs_repo.save(run)
    timeline = build_timeline(run, [])
    assert timeline["incomplete"] is True and timeline["entries"] == []


def test_timeline_endpoint_is_deterministic_and_does_no_model_work(tmp_path):
    container, counting, llm = _container(tmp_path)
    run = container.research_service.create_run("What is X?")
    calls_before = (len(llm.invoke_calls), counting.embeds, counting.searches)
    with TestClient(create_app(container)) as client:
        first = client.get(f"/api/runs/{run.id}/timeline")
        assert first.status_code == 200
        assert client.get(f"/api/runs/{run.id}/timeline").json() == first.json()
        assert client.get("/api/runs/missing/timeline").status_code == 404
    assert (len(llm.invoke_calls), counting.embeds, counting.searches) == calls_before
    body = first.json()
    assert json.dumps(body)  # serializable, stable shape
    assert body["entries"] and body["question"] == "What is X?"
