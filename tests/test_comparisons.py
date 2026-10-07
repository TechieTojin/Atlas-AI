"""Feature 9: evidence-aware research comparison."""

import pytest

from src.events.models import EventType
from src.models.research import CriticDecision
from src.models.runs import RunStatus
from src.models.workspace import ComparisonStatus, Project
from src.services.comparison_service import (
    ComparisonError,
    build_comparison_sources,
    overlap_stats,
)
from src.services.comparison_synthesis import (
    ComparisonPoint,
    ComparisonSynthesis,
    Conclusion,
    UniqueEvidencePoint,
)
from tests.conftest import FakeLLM, make_critique, make_plan, make_search_fn
from tests.conftest_v2 import make_container

RUN1_RESULTS = [
    {"url": "https://shared.com/x", "title": "Shared", "content": "Shared evidence.", "score": 0.9},
    {"url": "https://only1.com/a", "title": "Only1", "content": "Unique to run one.", "score": 0.8},
]
RUN2_RESULTS = [
    {"url": "https://shared.com/x/", "title": "Shared", "content": "Shared again.", "score": 0.9},
    {"url": "https://only2.com/b", "title": "Only2", "content": "Contradicting data.", "score": 0.8},
]


def synthesis(
    agreements=None,
    contradictions=None,
    unique_evidence=None,
    overview="The runs converge on the same barrier but cite different evidence.",
    conclusion=None,
):
    """A valid structured comparison for the two-run fixture.

    Source 1 is the shared URL (collected by runs 1 and 2), source 2 is unique
    to run 1 and source 3 to run 2, so these citations satisfy the V2.1 rules:
    an agreement needs evidence from both runs, unique evidence needs a source
    only its run collected, and the conclusion must reference real point ids.
    """
    return ComparisonSynthesis(
        overview=overview,
        agreements=[ComparisonPoint(**a) for a in (
            agreements if agreements is not None
            else [{"id": "A1", "text": "Both runs rely on the shared source.",
                   "runs": [1, 2], "citations": [1]}]
        )],
        contradictions=contradictions or [],
        unique_evidence=[UniqueEvidencePoint(**u) for u in (
            unique_evidence if unique_evidence is not None
            else [{"id": "U1", "run": 1,
                   "text": "Run 1 alone reached its own source.",
                   "citations": [2]}]
        )],
        conclusion=conclusion or Conclusion(
            text="The runs agree on the shared finding.", based_on=["A1", "U1"]
        ),
    )


def two_runs(tmp_path, comparison=None):
    synth = ["R1 report [1][2].", "R2 report [1][2].", "unused"]
    llm = FakeLLM(
        plans=[make_plan(n_queries=1), make_plan(n_queries=1)],
        critiques=[
            make_critique(CriticDecision.SYNTHESIZE, score=9),
            make_critique(CriticDecision.SYNTHESIZE, score=9),
        ],
        synthesis=synth,
    )
    # Memory disabled so run2 doesn't legitimately reuse run1's evidence
    # (same fixture queries) and blur the overlap stats under test.
    c = make_container(tmp_path, llm=llm,
                       search_fn=make_search_fn(default=RUN1_RESULTS),
                       memory_ttl_hours=0)
    run1 = c.research_service.create_run("q one")
    # Second run with different results: swap the search function.
    c.research_service._search_factory = (
        lambda cfg: make_search_fn(default=RUN2_RESULTS)
    )
    run2 = c.research_service.create_run("q two")
    llm.queue_structured(
        ComparisonSynthesis, [comparison if comparison is not None else synthesis()]
    )
    return c, c.research_service.get_run(run1.id), c.research_service.get_run(run2.id)


class TestDeterministicParts:
    def test_sources_deduplicated_with_run_origins(self, tmp_path):
        c, r1, r2 = two_runs(tmp_path)
        sources = build_comparison_sources([r1, r2])
        by_url = {s.source.normalized_url: s for s in sources}
        shared = by_url["https://shared.com/x"]
        assert set(shared.run_ids) == {r1.id, r2.id}  # origin preserved
        assert len(sources) == 3  # shared deduped, uniques kept

    def test_overlap_stats(self, tmp_path):
        c, r1, r2 = two_runs(tmp_path)
        sources = build_comparison_sources([r1, r2])
        stats = overlap_stats([r1, r2], sources)
        assert stats["total_sources"] == 3
        assert stats["shared_sources"] == 1
        assert stats["unique_per_run"][r1.id] == 1
        assert stats["unique_per_run"][r2.id] == 1


class TestComparisonRuns:
    def test_two_run_comparison_completes_with_citations(self, tmp_path):
        c, r1, r2 = two_runs(tmp_path)
        comparison = c.comparison_service.create([r1.id, r2.id])
        final = c.comparison_service.get(comparison.id)
        assert final.status is ComparisonStatus.COMPLETED
        assert "[1]" in final.report
        assert "## Source Differences" in final.report
        assert final.report.count("## Sources") == 1
        # Final sources rendered only from real collected URLs.
        assert "https://shared.com/x" in final.report
        assert final.overlap_stats["shared_sources"] == 1
        types = [e.type for e in c.bus.history(comparison.id)]
        assert types[-1] is EventType.COMPARISON_COMPLETED

    def test_invalid_citations_stripped(self, tmp_path):
        c, r1, r2 = two_runs(tmp_path, comparison=synthesis(
            agreements=[{"id": "A1", "text": "Claim about the shared source.",
                         "runs": [1, 2], "citations": [1]}]))
        comparison = c.comparison_service.create([r1.id, r2.id])
        assert "[77]" not in c.comparison_service.get(comparison.id).report

    def test_three_run_comparison(self, tmp_path):
        c, r1, r2 = two_runs(
            tmp_path
        )
        # Reuse run1's evidence for a third run via regeneration.
        llm = c.research_service._llm_factory(c.config, reasoning=False)
        llm._syntheses = ["Regen [1].", "Three-way [1][2][3]."]
        r3 = c.research_service.regenerate_report(r1.id, "EXECUTIVE")
        # Run 3 regenerates run 1, so it shares run 1's sources: the only honest
        # agreement spans all three, and nothing is unique to run 1 any more.
        llm.queue_structured(ComparisonSynthesis, [synthesis(
            agreements=[{"id": "A1", "text": "All three runs share the evidence.",
                         "runs": [1, 2, 3], "citations": [1]}],
            unique_evidence=[],
            conclusion=Conclusion(text="All three agree.", based_on=["A1"]),
        )])
        comparison = c.comparison_service.create([r1.id, r2.id, r3.id])
        final = c.comparison_service.get(comparison.id)
        assert final.status is ComparisonStatus.COMPLETED
        assert len(final.run_ids) == 3

    def test_persistence_and_deleted_input_run(self, tmp_path):
        c, r1, r2 = two_runs(tmp_path)
        comparison = c.comparison_service.create([r1.id, r2.id])
        c.runs_repo.delete(r1.id)
        reloaded = c.comparison_service.get(comparison.id)
        assert reloaded.status is ComparisonStatus.COMPLETED
        assert reloaded.report  # comparison retains its own copy


class TestValidation:
    def test_requires_two_distinct_completed_runs(self, tmp_path):
        c, r1, r2 = two_runs(tmp_path)
        with pytest.raises(ComparisonError, match="two distinct"):
            c.comparison_service.create([r1.id])
        with pytest.raises(ComparisonError, match="two distinct"):
            c.comparison_service.create([r1.id, r1.id])

    def test_unknown_or_incomplete_runs_rejected(self, tmp_path):
        c, r1, _ = two_runs(tmp_path)
        with pytest.raises(ComparisonError, match="not found"):
            c.comparison_service.create([r1.id, "missing"])
        pending = c.research_service.create_run("q", approval_required=True)
        with pytest.raises(ComparisonError, match="not completed"):
            c.comparison_service.create([r1.id, pending.id])

    def test_project_restriction(self, tmp_path):
        c, r1, r2 = two_runs(tmp_path)
        project = Project(name="P")
        c.projects_repo.save(project)
        with pytest.raises(ComparisonError, match="does not belong"):
            c.comparison_service.create([r1.id, r2.id], project_id=project.id)


class TestComparisonApi:
    def test_api_flow(self, tmp_path):
        from fastapi.testclient import TestClient
        from src.api.app import create_app

        c, r1, r2 = two_runs(tmp_path)
        with TestClient(create_app(c)) as client:
            created = client.post(
                "/api/comparisons", json={"run_ids": [r1.id, r2.id]}
            )
            assert created.status_code == 201
            cid = created.json()["id"]
            detail = client.get(f"/api/comparisons/{cid}").json()
            assert detail["status"] == "COMPLETED"
            assert client.get("/api/comparisons").json()["comparisons"]
            claims = client.get(f"/api/comparisons/{cid}/claims").json()["claims"]
            assert claims and claims[0]["citations"]
            export = client.get(f"/api/comparisons/{cid}/export")
            assert export.status_code == 200
            assert "# Atlas Research Comparison" in export.text
            assert client.post(
                "/api/comparisons", json={"run_ids": [r1.id]}
            ).status_code == 422
            assert client.delete(f"/api/comparisons/{cid}").status_code == 204
            assert client.get(f"/api/comparisons/{cid}").status_code == 404
