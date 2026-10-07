"""Feature 3: follow-up / conversational research."""

import pytest

from src.events.models import EventType
from src.models.workspace import FollowUpKind, FollowUpStatus
from src.services.followup_service import FollowUpError, classify_followup
from tests.conftest import FakeLLM, make_critique, make_plan, make_search_fn
from tests.conftest_v2 import WEB_RESULTS, make_container
from src.models.research import CriticDecision

NEW_RESULTS = [
    {"url": "https://new.com/1", "title": "New1", "content": "Fresh evidence.", "score": 0.9},
    {"url": "https://a.com/1", "title": "A1", "content": "Duplicate of parent.", "score": 0.5},
]


def completed_run(tmp_path, synthesis_queue=None, search=None):
    llm = FakeLLM(
        plans=[make_plan()],
        critiques=[make_critique(CriticDecision.SYNTHESIZE, score=9)],
        synthesis=synthesis_queue or "Report body [1][2].",
    )
    search = search or make_search_fn(default=WEB_RESULTS)
    c = make_container(tmp_path, llm=llm, search_fn=search)
    run = c.research_service.create_run("Why thermal runaway?")
    return c, c.research_service.get_run(run.id), llm, search


class TestClassification:
    def test_analytical_default(self):
        assert classify_followup("Which source is strongest?") is FollowUpKind.ANALYTICAL

    def test_research_keywords(self):
        assert classify_followup("go deeper into battery chemistry") is FollowUpKind.RESEARCH
        assert classify_followup("find more about regulation") is FollowUpKind.RESEARCH

    def test_user_override_wins(self):
        assert classify_followup("go deeper", mode="analytical") is FollowUpKind.ANALYTICAL
        assert classify_followup("explain this", mode="research") is FollowUpKind.RESEARCH


class TestAnalyticalFollowUp:
    def test_answers_from_existing_evidence_without_search(self, tmp_path):
        c, run, llm, search = completed_run(
            tmp_path, synthesis_queue=["Report body [1][2].", "Source [2] is strongest."]
        )
        calls_before = len(search.calls)
        followup = c.followup_service.create(run.id, "Which source is strongest?")
        final = c.followup_service.get(followup.id)
        assert final.status is FollowUpStatus.COMPLETED
        assert final.kind is FollowUpKind.ANALYTICAL
        assert final.searched is False
        assert len(search.calls) == calls_before  # no new retrieval
        assert "[2]" in final.answer
        assert final.cited == [2]
        # Stable numbering: sources are exactly the parent's numbered sources.
        assert [s.url for s in final.sources] == [s.url for s in run.selected_sources]
        assert final.parent_source_count == len(run.selected_sources)
        assert final.new_source_count == 0

    def test_context_includes_parent_run(self, tmp_path):
        c, run, llm, _ = completed_run(
            tmp_path, synthesis_queue=["Report body [1][2].", "Answer [1]."]
        )
        c.followup_service.create(run.id, "Explain this more simply")
        followup_call = str(llm.invoke_calls[-1])
        assert "Why thermal runaway?" in followup_call  # original question
        assert "Report body" in followup_call  # parent report context
        assert "SOURCE [1]" in followup_call  # numbered parent sources

    def test_invalid_citations_stripped_from_answer(self, tmp_path):
        c, run, _, _ = completed_run(
            tmp_path, synthesis_queue=["Report body [1][2].", "Claim [1]. Fake [9]."]
        )
        followup = c.followup_service.create(run.id, "Summarize")
        final = c.followup_service.get(followup.id)
        assert "[9]" not in final.answer
        assert final.cited == [1]

    def test_reasoning_artifacts_stripped(self, tmp_path):
        c, run, _, _ = completed_run(
            tmp_path,
            synthesis_queue=["Report body [1][2].", "thinking...</think>Clean answer [1]."],
        )
        followup = c.followup_service.create(run.id, "Summarize")
        assert c.followup_service.get(followup.id).answer == "Clean answer [1]."


class TestResearchFollowUp:
    def test_new_retrieval_appends_sources_without_renumbering_parents(self, tmp_path):
        search = make_search_fn(
            results_by_query={
                "av barriers query 0": WEB_RESULTS,
                "av barriers query 1": WEB_RESULTS,
                "research deeper into chemistry": NEW_RESULTS,
            }
        )
        c, run, llm, search = completed_run(
            tmp_path,
            synthesis_queue=["Report body [1][2].", "Old [1] and new [3]."],
            search=search,
        )
        parent_count = len(run.selected_sources)
        followup = c.followup_service.create(
            run.id, "research deeper into chemistry"
        )
        final = c.followup_service.get(followup.id)
        assert final.kind is FollowUpKind.RESEARCH
        assert final.searched is True
        # Parent sources keep numbers 1..k; the new unique source is k+1.
        assert [s.url for s in final.sources[:parent_count]] == [
            s.url for s in run.selected_sources
        ]
        assert final.new_source_count == 1  # duplicate URL was deduplicated
        assert final.sources[-1].url == "https://new.com/1"
        assert final.cited == [1, 3]

    def test_events_emitted_and_persisted(self, tmp_path):
        c, run, _, _ = completed_run(
            tmp_path, synthesis_queue=["Report body [1][2].", "Answer [1]."]
        )
        followup = c.followup_service.create(run.id, "Summarize")
        types = [e.type for e in c.bus.history(followup.id)]
        assert types[0] is EventType.FOLLOWUP_STARTED
        assert types[-1] is EventType.FOLLOWUP_COMPLETED
        stored = c.events_repo.list(followup.id)
        assert stored[-1].type is EventType.FOLLOWUP_COMPLETED


class TestLifecycleAndErrors:
    def test_requires_completed_run(self, tmp_path):
        c = make_container(tmp_path)
        run = c.research_service.create_run("q", approval_required=True)
        with pytest.raises(FollowUpError, match="completed run"):
            c.followup_service.create(run.id, "why?")

    def test_unknown_run(self, tmp_path):
        c = make_container(tmp_path)
        with pytest.raises(FollowUpError, match="not found"):
            c.followup_service.create("missing", "why?")

    def test_empty_question_rejected(self, tmp_path):
        c, run, _, _ = completed_run(tmp_path)
        with pytest.raises(FollowUpError):
            c.followup_service.create(run.id, "   ")

    def test_llm_failure_marks_failed(self, tmp_path):
        class Exploding(FakeLLM):
            def invoke(self, messages):
                if len(self.invoke_calls) >= 1:
                    raise RuntimeError("llm down")
                return super().invoke(messages)

        llm = Exploding(
            plans=[make_plan()],
            critiques=[make_critique(CriticDecision.SYNTHESIZE, score=9)],
            synthesis="Report body [1][2].",
        )
        c = make_container(tmp_path, llm=llm)
        run = c.research_service.create_run("q")
        followup = c.followup_service.create(run.id, "Summarize")
        final = c.followup_service.get(followup.id)
        assert final.status is FollowUpStatus.FAILED
        assert "llm down" in final.error

    def test_persistence_across_instances(self, tmp_path):
        path = str(tmp_path / "f.db")
        c, run, _, _ = None, None, None, None
        llm = FakeLLM(
            plans=[make_plan()],
            critiques=[make_critique(CriticDecision.SYNTHESIZE, score=9)],
            synthesis=["Report body [1][2].", "Persisted answer [1]."],
        )
        c = make_container(tmp_path, llm=llm, db_path=path)
        run = c.research_service.create_run("q")
        followup = c.followup_service.create(run.id, "Summarize")
        c2 = make_container(tmp_path, db_path=path)
        reloaded = c2.followup_service.get(followup.id)
        assert reloaded.answer == "Persisted answer [1]."
        assert reloaded.status is FollowUpStatus.COMPLETED
        assert c2.followup_service.list_for_run(run.id)[0].id == followup.id


class TestFollowUpApi:
    def test_api_flow(self, tmp_path):
        from fastapi.testclient import TestClient
        from src.api.app import create_app

        llm = FakeLLM(
            plans=[make_plan()],
            critiques=[make_critique(CriticDecision.SYNTHESIZE, score=9)],
            synthesis=["Report body [1][2].", "API answer [1]."],
        )
        c = make_container(tmp_path, llm=llm)
        with TestClient(create_app(c)) as client:
            run_id = client.post("/api/runs", json={"query": "q"}).json()["id"]
            created = client.post(
                f"/api/runs/{run_id}/followups",
                json={"question": "Which is strongest?", "mode": "analytical"},
            )
            assert created.status_code == 201
            fid = created.json()["id"]
            detail = client.get(f"/api/followups/{fid}").json()
            assert detail["status"] == "COMPLETED"
            assert "API answer [1]" in detail["answer"]
            listing = client.get(f"/api/runs/{run_id}/followups").json()
            assert len(listing["followups"]) == 1
            with client.stream("GET", f"/api/followups/{fid}/events") as stream:
                body = "".join(stream.iter_text())
            assert "FOLLOWUP_COMPLETED" in body
            assert client.post(
                f"/api/runs/{run_id}/followups", json={"question": ""}
            ).status_code == 422
