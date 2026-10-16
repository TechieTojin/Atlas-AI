"""Research Map: a truthful, deterministic view of how one run was produced.

Real runs are produced by the actual workflow with fake (offline) model,
search and embeddings; rare states (skips, timeouts, fallbacks, historical
runs without an event log) are built from stored records directly. Loading a
map must never call a model, an embedding, search or the network.
"""

from __future__ import annotations

import json
import socket
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.events.models import EventType, RunEvent
from src.models.research import CriticDecision, Evidence, EvidenceOrigin, Source, SourceQuality
from src.models.runs import ResearchRun, RunMode, RunStatus, SourceScope
from src.services.research_map import build_research_map
from tests.conftest import FakeLLM, make_critique, make_plan, make_search_fn
from tests.conftest_v2 import WEB_RESULTS, make_container

T0 = datetime(2026, 10, 9, 10, 0, tzinfo=timezone.utc)


class Counting:
    """Wraps the fakes so any model / search / embedding call is counted."""

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


def _container(tmp_path, llm=None, counting=None, **kwargs):
    counting = counting or Counting()
    return make_container(
        tmp_path, llm=llm, embed_fn=counting.embed,
        search_fn=counting.search_fn(make_search_fn(default=WEB_RESULTS)), **kwargs,
    ), counting


def _map(container, run_id):
    run = container.research_service.get_run(run_id)
    return build_research_map(run, container.events_repo.list(run_id))


def _types(rmap):
    out: dict[str, int] = {}
    for node in rmap["nodes"]:
        out[node["type"]] = out.get(node["type"], 0) + 1
    return out


def _node(rmap, node_id):
    return next(n for n in rmap["nodes"] if n["id"] == node_id)


def _edges(rmap, type_):
    return [(e["source"], e["target"]) for e in rmap["edges"] if e["type"] == type_]


# --- real runs ------------------------------------------------------------------------


def test_completed_web_run_maps_question_plan_queries_evidence_critic_synthesis_report(tmp_path):
    c, _ = _container(tmp_path)
    run = c.research_service.create_run("What is X?")
    rmap = _map(c, run.id)
    types = _types(rmap)
    assert types["question"] == types["plan"] == types["critic"] == types["synthesis"] == types["report"] == 1
    assert types["query"] == 2 and types["source"] >= 1 and types["evidence"] >= 1
    final = c.research_service.get_run(run.id)
    # Queries on the map are exactly the stored executed queries.
    assert [n["label"] for n in rmap["nodes"] if n["type"] == "query"] == final.executed_queries
    assert _node(rmap, "question")["data"]["question"] == "What is X?"
    plan = _node(rmap, "plan")["data"]
    assert plan["search_queries"] == final.plan.search_queries
    assert plan["subquestions"] == [t.subquestion for t in final.plan.tasks]
    assert _node(rmap, "critic:1")["status"] == "completed" and _node(rmap, "critic:1")["data"]["score"] == 9
    assert _node(rmap, "report")["data"]["citations"] >= 1
    assert rmap["summary"]["iterations"] == 1 and rmap["limitations"] == []
    assert rmap["run_status"] == "COMPLETED" and rmap["mode"] == final.mode.value


def test_citation_numbers_and_source_metadata_are_preserved(tmp_path):
    c, _ = _container(tmp_path)
    run = c.research_service.create_run("What is X?")
    final = c.research_service.get_run(run.id)
    rmap = _map(c, run.id)
    for number, source in enumerate(final.selected_sources, 1):
        data = _node(rmap, f"source:{number}")["data"]
        assert data["citation"] == number and data["url"] == source.url and data["title"] == source.title
        assert data["quality"] == (source.quality.model_dump(mode="json") if source.quality else None)
    for node in (n for n in rmap["nodes"] if n["type"] == "evidence"):
        stored = [e for e in final.evidence if e.content == node["data"]["content"]]
        assert stored, "evidence text is the stored excerpt, verbatim"
        if node["data"]["citation"]:
            assert (node["id"], f"source:{node['data']['citation']}") in _edges(rmap, "FROM_SOURCE")


def test_critic_loop_is_shown_only_when_events_prove_it(tmp_path):
    llm = FakeLLM(
        plans=[make_plan(n_queries=1)],
        critiques=[
            make_critique(CriticDecision.MORE_RESEARCH, follow_ups=["deeper follow up"], score=4),
            make_critique(CriticDecision.SYNTHESIZE, score=9),
        ],
        synthesis="Findings [1].",
    )
    c, _ = _container(tmp_path, llm=llm)
    run = c.research_service.create_run("Loop?", mode=RunMode.DEEP)
    rmap = _map(c, run.id)
    assert rmap["summary"]["iterations"] == 2
    assert _node(rmap, "critic:1")["data"]["decision"] == "MORE_RESEARCH"
    assert _node(rmap, "critic:1")["data"]["follow_up_queries"] == ["deeper follow up"]
    assert _node(rmap, "critic:2")["data"]["decision"] == "SYNTHESIZE"
    loop = _edges(rmap, "REQUESTED_MORE_RESEARCH")
    assert loop and all(src == "critic:1" and tgt.startswith("query:2:") for src, tgt in loop)
    assert ("critic:2", "synthesis") in _edges(rmap, "PROCEEDED_TO_SYNTHESIS")
    # The second-iteration query is the real follow-up query.
    assert any(n["label"] == "deeper follow up" and n["iteration"] == 2 for n in rmap["nodes"] if n["type"] == "query")


def test_single_iteration_run_has_no_invented_loop(tmp_path):
    c, _ = _container(tmp_path)
    rmap = _map(c, c.research_service.create_run("What is X?").id)
    assert _edges(rmap, "REQUESTED_MORE_RESEARCH") == []
    assert not any(n["id"].startswith("critic:2") or n["id"].startswith("query:2") for n in rmap["nodes"])


def _ingest(c):
    return c.document_service.ingest("notes.txt", b"Separator melting at 150C was observed in testing. " * 20)


def test_document_only_run_shows_document_retrieval_and_pages(tmp_path):
    c, counting = _container(tmp_path)
    doc = _ingest(c)
    run = c.research_service.create_run("Why melting?", source_scope=SourceScope.DOCUMENTS, document_ids=[doc.id])
    rmap = _map(c, run.id)
    queries = [n for n in rmap["nodes"] if n["type"] == "query"]
    assert queries and all(q["data"]["retrieval"] == "documents" for q in queries)
    docs = [n for n in rmap["nodes"] if n["type"] == "evidence" and n["data"]["origin"] == "document"]
    assert docs and all(d["data"]["filename"] == "notes.txt" for d in docs)
    assert rmap["source_scope"] == "DOCUMENTS"


def test_web_and_documents_run(tmp_path):
    c, _ = _container(tmp_path)
    doc = _ingest(c)
    run = c.research_service.create_run("Both?", source_scope=SourceScope.WEB_AND_DOCUMENTS, document_ids=[doc.id])
    rmap = _map(c, run.id)
    origins = {n["data"]["origin"] for n in rmap["nodes"] if n["type"] == "evidence"}
    assert {"web", "document"} <= origins
    assert all(n["data"]["retrieval"] == "web_and_documents" for n in rmap["nodes"] if n["type"] == "query")


def test_memory_node_appears_only_when_project_findings_were_used(tmp_path):
    c, _ = _container(tmp_path)
    run = c.research_service.create_run("What is X?")
    assert "project_memory" not in _types(_map(c, run.id))  # enabled, zero hits → no node
    stored = c.research_service.get_run(run.id)
    stored.metrics.project_memory_hits = 1
    stored.metrics.memory_items = [{"text": "Earlier finding [1].", "question": "q", "run_id": "r0", "score": 0.8}]
    rmap = build_research_map(stored, c.events_repo.list(run.id))
    memory = _node(rmap, "memory:project")
    assert memory["data"]["items"][0]["text"] == "Earlier finding [1]."
    assert ("memory:project", "synthesis") in _edges(rmap, "PROVIDED_CONTEXT")


def test_cancelled_run_shows_only_what_happened(tmp_path):
    c, _ = _container(tmp_path)
    run = c.research_service.create_run("Wait for me", approval_required=True)
    c.research_service.cancel(run.id)
    rmap = _map(c, run.id)
    types = _types(rmap)
    assert types.get("terminal") == 1 and _node(rmap, "terminal")["status"] == "cancelled"
    for absent in ("synthesis", "report", "critic", "query"):
        assert absent not in types


# --- stored-record states ---------------------------------------------------------------


def _event(seq, type_, *, iteration=0, payload=None, message="", seconds=0):
    return RunEvent(type=type_, run_id="r1", seq=seq, iteration=iteration, payload=payload or {},
                    message=message, timestamp=T0 + timedelta(seconds=seconds))


def _stored_run(**overrides):
    source = Source(title="Paper", url="https://journal.example/p", domain="journal.example",
                    quality=SourceQuality(category="academic", tier="high", score=90))
    run = ResearchRun(
        id="r1", query="What is X?", mode=RunMode.FAST, status=RunStatus.COMPLETED,
        plan=make_plan(n_queries=1), executed_queries=["av barriers query 0"], iterations=1,
        evidence=[Evidence(source=source, content="Stored excerpt.", query="av barriers query 0")],
        selected_sources=[source], final_report="Finding [1].\n\n## Sources\n1. Paper",
        created_at=T0, started_at=T0, completed_at=T0 + timedelta(seconds=90),
    )
    for key, value in overrides.items():
        setattr(run, key, value)
    return run


def _events_one_iteration(critic_payload, critic_message=""):
    return [
        _event(1, EventType.RUN_STARTED),
        _event(2, EventType.PLANNING_STARTED, seconds=1),
        _event(3, EventType.PLAN_CREATED, payload={"subquestions": ["s"], "queries": ["av barriers query 0"]}, seconds=5),
        _event(4, EventType.SEARCH_STARTED, iteration=1, payload={"queries": ["av barriers query 0"]}, seconds=6),
        _event(5, EventType.SEARCH_QUERY_STARTED, iteration=1, payload={"query": "av barriers query 0"}, seconds=6),
        _event(6, EventType.SEARCH_QUERY_COMPLETED, iteration=1,
               payload={"query": "av barriers query 0", "results": 2, "memory_hits": 0, "document_chunks": 0}, seconds=9),
        _event(7, EventType.CRITIC_STARTED, iteration=1, seconds=10),
        _event(8, EventType.CRITIC_COMPLETED, iteration=1, payload=critic_payload, message=critic_message, seconds=30),
        _event(9, EventType.SYNTHESIS_STARTED, seconds=31),
    ]


@pytest.mark.parametrize(
    ("payload", "status"),
    [
        ({"score": 8, "decision": "SYNTHESIZE"}, "completed"),
        ({"decision": "SYNTHESIZE", "fallback": "skipped: FAST budget reserved for synthesis"}, "skipped"),
        ({"decision": "SYNTHESIZE", "fallback": "timed out after 150 s"}, "timed_out"),
    ],
)
def test_critic_status_follows_the_recorded_outcome(payload, status):
    rmap = build_research_map(_stored_run(), _events_one_iteration(payload))
    critic = _node(rmap, "critic:1")
    assert critic["status"] == status
    if status != "completed":
        assert critic["data"]["fallback_reason"] == payload["fallback"]
        assert critic["data"]["score"] is None  # a skipped critic never had a score


def test_critic_that_never_finished_in_a_failed_run_is_failed_not_completed():
    events = _events_one_iteration({})[:7] + [_event(10, EventType.RUN_FAILED, message="boom", seconds=40)]
    run = _stored_run(status=RunStatus.FAILED, final_report="", error="RuntimeError: boom")
    rmap = build_research_map(run, events)
    assert _node(rmap, "critic:1")["status"] == "failed"
    assert _node(rmap, "terminal")["status"] == "failed" and _node(rmap, "terminal")["data"]["error"] == "RuntimeError: boom"
    assert "report" not in _types(rmap) and "synthesis" not in _types(rmap)


def test_synthesis_fallback_is_explicit():
    run = _stored_run()
    run.metrics.synthesis_fallback = True
    run.metrics.synthesis_fallback_reason = "synthesis timed out"
    rmap = build_research_map(run, _events_one_iteration({"score": 8, "decision": "SYNTHESIZE"}))
    synthesis = _node(rmap, "synthesis")
    assert synthesis["status"] == "fallback" and synthesis["data"]["fallback_reason"] == "synthesis timed out"
    assert _node(rmap, "report")["data"]["fallback"] is True


def test_historical_run_without_events_degrades_honestly():
    run = _stored_run()
    rmap = build_research_map(run, [])
    assert rmap["limitations"] == ["events_not_recorded", "iterations_not_recorded"]
    assert rmap["summary"]["incomplete_history"] is True
    queries = [n for n in rmap["nodes"] if n["type"] == "query"]
    assert [q["label"] for q in queries] == run.executed_queries
    assert all(q["iteration"] is None and q["started_at"] is None for q in queries)  # no invented timings
    assert not any(n["id"].startswith("critic:") and n["iteration"] for n in rmap["nodes"])


def test_no_plan_no_evidence_run():
    run = _stored_run(plan=None, executed_queries=[], evidence=[], selected_sources=[], final_report="",
                      status=RunStatus.FAILED, error="PlanningError: no plan")
    rmap = build_research_map(run, [_event(1, EventType.RUN_STARTED), _event(2, EventType.RUN_FAILED, message="x")])
    assert _types(rmap) == {"question": 1, "terminal": 1}
    assert ("question", "terminal") in _edges(rmap, "ENDED")


def test_unicode_question_and_evidence_round_trip():
    source = Source(title="सौर सेल", url="https://hi.example/a", domain="hi.example")
    run = _stored_run(query="सौर सेल की दक्षता क्या है? ഇത് എന്താണ്?",
                      evidence=[Evidence(source=source, content="दक्षता 3.8% थी।", query="av barriers query 0")],
                      selected_sources=[source])
    rmap = build_research_map(run, _events_one_iteration({"score": 8, "decision": "SYNTHESIZE"}))
    assert _node(rmap, "question")["label"] == run.query
    assert any(n["data"].get("content") == "दक्षता 3.8% थी।" for n in rmap["nodes"])
    json.dumps(rmap, ensure_ascii=False)


def test_model_reasoning_is_never_exposed():
    run = _stored_run(critique=make_critique(CriticDecision.SYNTHESIZE, score=8))
    run.critique.reasoning = "SECRET-INTERNAL-REASONING"
    rmap = build_research_map(run, _events_one_iteration({"score": 8, "decision": "SYNTHESIZE"}))
    assert "SECRET-INTERNAL-REASONING" not in json.dumps(rmap)
    assert _node(rmap, "critic:1")["data"]["coverage"] == run.critique.coverage_assessment


def test_cited_in_report_edges_only_for_sources_the_report_cites():
    second = Source(title="Uncited", url="https://other.example/u", domain="other.example")
    run = _stored_run()
    run.selected_sources = run.selected_sources + [second]
    rmap = build_research_map(run, _events_one_iteration({"score": 8, "decision": "SYNTHESIZE"}))
    assert _edges(rmap, "CITED_IN_REPORT") == [("source:1", "report")]
    assert _node(rmap, "source:1")["data"]["claims"][0]["text"].startswith("Finding")
    assert "claims" not in _node(rmap, "source:2")["data"]
    assert not any(e["type"] == "SUPPORTS" for e in rmap["edges"])


def test_ids_and_order_are_deterministic_and_grouping_is_stable():
    events = _events_one_iteration({"score": 8, "decision": "SYNTHESIZE"})
    first = build_research_map(_stored_run(), events)
    second = build_research_map(_stored_run(), list(reversed(events)))  # input order must not matter
    assert first == second
    assert [n["id"] for n in first["nodes"]][:3] == ["question", "plan", "query:1:0"]
    groups = {g["key"]: g for g in first["groups"]}
    grouped = {m for g in first["groups"] for m in g["members"]}
    # Every grouped node is still a full node: grouping never hides data.
    assert grouped <= {n["id"] for n in first["nodes"]}
    assert groups["sources"]["members"] == ["source:1"]


def test_duplicate_evidence_gets_distinct_stable_ids():
    run = _stored_run()
    run.evidence = run.evidence + [run.evidence[0].model_copy()]
    rmap = build_research_map(run, [])
    ids = [n["id"] for n in rmap["nodes"] if n["type"] == "evidence"]
    assert len(ids) == len(set(ids)) == 2 and ids[1] == ids[0] + "-2"


def test_unsafe_urls_are_passed_as_data_not_trusted():
    bad = Source(title="x", url="javascript:alert(1)", domain="")
    run = _stored_run(selected_sources=[bad], evidence=[])
    rmap = build_research_map(run, [])
    assert _node(rmap, "source:1")["data"]["url"] == "javascript:alert(1)"  # the UI refuses to link it


# --- endpoint ---------------------------------------------------------------------------


def test_endpoint_returns_the_map_and_404_for_unknown_runs(tmp_path):
    c, _ = _container(tmp_path)
    run = c.research_service.create_run("What is X?")
    with TestClient(create_app(c)) as client:
        body = client.get(f"/api/runs/{run.id}/research-map").json()
        assert body["run_id"] == run.id and body["summary"]["node_count"] == len(body["nodes"])
        assert {"nodes", "edges", "groups", "summary", "limitations", "question", "mode"} <= set(body)
        assert client.get("/api/runs/missing/research-map").status_code == 404
        assert client.get(f"/api/runs/{run.id}/research-map").json() == body


def test_loading_the_map_does_no_model_embedding_search_or_network_work(tmp_path, monkeypatch):
    llm = FakeLLM(plans=[make_plan(n_queries=2)], critiques=[make_critique(CriticDecision.SYNTHESIZE, score=9)],
                  synthesis="Findings [1].")
    c, counting = _container(tmp_path, llm=llm)
    run = c.research_service.create_run("What is X?")
    calls_before = (len(llm.invoke_calls), counting.embeds, counting.searches)

    def refuse(*args, **kwargs):
        raise AssertionError("network access during map load")

    with TestClient(create_app(c)) as client:
        # Armed after startup: the test client's own event loop uses a local socketpair.
        monkeypatch.setattr(socket, "create_connection", refuse)
        monkeypatch.setattr(socket.socket, "connect", refuse)
        assert client.get(f"/api/runs/{run.id}/research-map").status_code == 200
        monkeypatch.undo()
    assert (len(llm.invoke_calls), counting.embeds, counting.searches) == calls_before


def test_map_build_is_fast_for_a_large_run():
    source = Source(title="S", url="https://s.example/", domain="s.example")
    run = _stored_run(evidence=[Evidence(source=Source(title=f"t{i}", url=f"https://e{i}.example/", domain="e"),
                                         content=f"excerpt {i}", query="av barriers query 0") for i in range(400)],
                      selected_sources=[source] * 1)
    start = time.perf_counter()
    rmap = build_research_map(run, _events_one_iteration({"score": 8, "decision": "SYNTHESIZE"}))
    assert (time.perf_counter() - start) < 0.2
    assert rmap["summary"]["evidence_count"] == 400
