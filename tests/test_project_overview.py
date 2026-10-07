"""Project Overview: deterministic stats, deduplication, gaps, provenance.

The Overview must be derivable from persisted data alone, so these tests
build containers whose embedder raises if called.
"""

import numpy as np
import pytest

from src.models.memory import FindingSource, ProjectFinding
from src.models.research import Critique, CriticDecision, Source
from src.models.runs import ResearchRun, RunMode, RunStatus
from src.models.workspace import Project
from src.services.overview_service import (
    DUPLICATE_THRESHOLD,
    ProjectOverviewService,
    cluster_findings,
    knowledge_gaps,
    rank_clusters,
)
from tests.conftest_v2 import make_container


class EmbedGuard:
    """Allows embeddings during setup, forbids them once armed.

    Lets a test ingest documents normally, then prove the Overview itself
    needs no LLM and no embedding.
    """

    def __init__(self):
        self.armed = False

    def __call__(self, texts):
        if self.armed:
            raise AssertionError("Overview must not generate embeddings on load")
        return [[float(len(t) % 7), 1.0, 0.0] for t in texts]


def container(tmp_path):
    guard = EmbedGuard()
    c = make_container(tmp_path, embed_fn=guard)
    c.embed_guard = guard
    return c


def add_project(c, name="Battery Technology Research"):
    project = Project(name=name, description="Solid-state battery research")
    c.projects_repo.save(project)
    return project


def add_run(c, project_id, query, status=RunStatus.COMPLETED, sources=(), **kw):
    run = ResearchRun(query=query, project_id=project_id, status=status, mode=RunMode.FAST)
    run.selected_sources = [Source(title=f"S{i}", url=u, domain=u.split("/")[2])
                            for i, u in enumerate(sources, 1)]
    for key, value in kw.items():
        setattr(run, key, value)
    c.runs_repo.save(run)
    return run


def add_finding(c, project, run, text, section="Findings", vector=None, sources=("https://a.com/1",)):
    finding = ProjectFinding(
        project_id=project.id, run_id=run.id, question=run.query,
        section=section, text=text,
        sources=[FindingSource(url=u, title="S") for u in sources],
    )
    c.findings_repo.add_many([finding], [vector] if vector else None)
    return finding


class TestStats:
    def test_counts_are_real_and_scoped(self, tmp_path):
        c = container(tmp_path)
        project = add_project(c)
        other = add_project(c, "Solar Project")
        r1 = add_run(c, project.id, "Q1", sources=["https://a.com/1", "https://b.com/2"])
        r2 = add_run(c, project.id, "Q2", sources=["https://a.com/1", "https://c.com/3"])
        add_run(c, project.id, "Q3", status=RunStatus.FAILED)
        add_run(c, other.id, "Other", sources=["https://z.com/9"])
        add_finding(c, project, r1, "Finding one about batteries and electrolytes.")
        add_finding(c, project, r2, "Finding two about manufacturing scale-up costs.")

        c.embed_guard.armed = True  # the Overview itself must need no model
        stats = c.overview_service.build(project.id)["stats"]
        assert stats["runs"] == 3  # all statuses, scoped to the project
        assert stats["completed_runs"] == 2
        assert stats["findings"] == 2
        # https://a.com/1 appears in both runs but counts once.
        assert stats["unique_sources"] == 3
        assert stats["documents"] == 0

    def test_unique_sources_normalize_urls(self, tmp_path):
        c = container(tmp_path)
        project = add_project(c)
        add_run(c, project.id, "Q1", sources=["https://a.com/page", "https://a.com/page/"])
        assert c.overview_service.build(project.id)["stats"]["unique_sources"] == 1

    def test_only_completed_runs_contribute_sources(self, tmp_path):
        c = container(tmp_path)
        project = add_project(c)
        add_run(c, project.id, "done", sources=["https://a.com/1"])
        add_run(c, project.id, "failed", status=RunStatus.FAILED,
                sources=["https://ghost.com/1"])
        assert c.overview_service.build(project.id)["stats"]["unique_sources"] == 1

    def test_documents_counted_for_this_project_only(self, tmp_path):
        c = container(tmp_path)
        project, other = add_project(c), add_project(c, "Other")
        mine = c.document_service.ingest("a.txt", b"useful project text " * 30)
        theirs = c.document_service.ingest("b.txt", b"different project text " * 30)
        c.documents_repo.set_project(mine.id, project.id)
        c.documents_repo.set_project(theirs.id, other.id)
        assert c.overview_service.build(project.id)["stats"]["documents"] == 1

    def test_unknown_project_returns_none(self, tmp_path):
        assert container(tmp_path).overview_service.build("nope") is None


class TestDeduplication:
    def _vec(self, *values):
        return list(values)

    def test_near_duplicates_collapse_with_support_count(self, tmp_path):
        c = container(tmp_path)
        project = add_project(c)
        r1 = add_run(c, project.id, "Q1")
        r2 = add_run(c, project.id, "Q2")
        # Two runs restate one claim (near-identical vectors), plus a distinct one.
        add_finding(c, project, r1, "High raw material cost limits competitiveness.",
                    vector=[1.0, 0.0, 0.0])
        add_finding(c, project, r2, "Additionally, high raw material cost limits it.",
                    vector=[0.99, 0.02, 0.0])
        add_finding(c, project, r1, "Dendrite formation causes short circuits.",
                    vector=[0.0, 1.0, 0.0])

        overview = c.overview_service.build(project.id)
        shown = overview["current_understanding"] + overview["key_findings"]
        assert len(shown) == 2  # three findings, two distinct claims
        corroborated = next(i for i in shown if i["support"] == 2)
        assert set(corroborated["run_ids"]) == {r1.id, r2.id}

    def test_repeated_runs_do_not_make_overview_repetitive(self, tmp_path):
        c = container(tmp_path)
        project = add_project(c)
        # Five acceptance-test reruns producing the same two claims.
        for n in range(5):
            run = add_run(c, project.id, f"Repeated question {n}")
            add_finding(c, project, run, f"Interface instability is the main barrier ({n}).",
                        vector=[1.0, 0.01 * n, 0.0])
            add_finding(c, project, run, f"Manufacturing scale-up remains costly ({n}).",
                        vector=[0.0, 1.0, 0.01 * n])
        overview = c.overview_service.build(project.id)
        shown = overview["current_understanding"] + overview["key_findings"]
        assert len(shown) == 2
        assert all(item["support"] == 5 for item in shown)

    def test_sections_are_diversified_in_current_understanding(self, tmp_path):
        c = container(tmp_path)
        project = add_project(c)
        run = add_run(c, project.id, "Q")
        for i in range(4):
            add_finding(c, project, run, f"Interface claim number {i} about stability.",
                        section="Interface", vector=[1.0, 0.1 * i, 0.0])
        add_finding(c, project, run, "Manufacturing claim about dry rooms and cost.",
                    section="Manufacturing", vector=[0.0, 0.0, 1.0])
        understanding = c.overview_service.build(project.id)["current_understanding"]
        assert "Manufacturing" in {i["section"] for i in understanding}

    def test_selection_is_deterministic(self, tmp_path):
        c = container(tmp_path)
        project = add_project(c)
        run = add_run(c, project.id, "Q")
        for i in range(8):
            add_finding(c, project, run, f"Distinct finding number {i} about batteries.",
                        vector=[float(i), 1.0, 0.0])
        first = c.overview_service.build(project.id)
        second = c.overview_service.build(project.id)
        assert first == second

    def test_findings_without_embeddings_fall_back_to_text_match(self):
        a = ProjectFinding(project_id="p", run_id="r1", text="Same sentence here.")
        b = ProjectFinding(project_id="p", run_id="r2", text="Same sentence here.")
        c_ = ProjectFinding(project_id="p", run_id="r1", text="A different sentence.")
        clusters = cluster_findings([a, b, c_], {})
        assert len(clusters) == 2
        assert rank_clusters(clusters)[0].support == 2

    def test_threshold_matches_measured_values(self):
        # Recorded from this project's real findings (nomic-embed-text), so
        # changing the threshold is a deliberate act.
        restatement, same_fact_two_runs = 0.932, 0.906
        different_claims = 0.869
        assert restatement > DUPLICATE_THRESHOLD
        assert same_fact_two_runs > DUPLICATE_THRESHOLD  # merged, support=2
        assert different_claims < DUPLICATE_THRESHOLD  # kept apart

    def test_sections_never_hide_findings(self, tmp_path):
        c = container(tmp_path)
        project = add_project(c)
        run = add_run(c, project.id, "Q")
        unit = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
        for i in range(3):
            add_finding(c, project, run, f"Only section claim {i} with enough words here.",
                        section="Same", vector=unit[i])
        overview = c.overview_service.build(project.id)
        assert len(overview["current_understanding"]) == 3  # topped up past diversity


class TestProvenance:
    def test_every_finding_traces_to_its_run_and_question(self, tmp_path):
        c = container(tmp_path)
        project = add_project(c)
        run = add_run(c, project.id, "What limits solid-state production?")
        add_finding(c, project, run, "Interface instability dominates the failure modes.",
                    sources=("https://nature.com/x",))
        item = c.overview_service.build(project.id)["current_understanding"][0]
        assert item["run_id"] == run.id
        assert item["question"] == "What limits solid-state production?"
        assert item["sources"][0]["url"] == "https://nature.com/x"
        assert item["run_ids"] == [run.id]


class TestKnowledgeGaps:
    def test_failed_and_cancelled_runs_become_honest_gaps(self, tmp_path):
        c = container(tmp_path)
        project = add_project(c)
        add_run(c, project.id, "Unfinished battery question?", status=RunStatus.FAILED)
        add_run(c, project.id, "Abandoned question?", status=RunStatus.CANCELLED)
        gaps = c.overview_service.build(project.id)["knowledge_gaps"]
        texts = {g["text"] for g in gaps}
        assert "Unfinished battery question?" in texts
        assert "Abandoned question?" in texts
        assert any("cancelled" in g["reason"].lower() for g in gaps)
        assert all(g["run_id"] for g in gaps)  # traceable

    def test_critic_missing_information_is_used(self, tmp_path):
        c = container(tmp_path)
        project = add_project(c)
        critique = Critique(
            coverage_assessment="partial", missing_information=["Cost data after 2025"],
            overall_score=7, decision=CriticDecision.SYNTHESIZE, reasoning="ok")
        add_run(c, project.id, "Q", critique=critique)
        gaps = c.overview_service.build(project.id)["knowledge_gaps"]
        assert gaps[0]["text"] == "Cost data after 2025"
        assert "critic" in gaps[0]["reason"].lower()

    def test_unreached_follow_up_queries_become_gaps(self, tmp_path):
        c = container(tmp_path)
        project = add_project(c)
        critique = Critique(
            coverage_assessment="thin", missing_information=[], overall_score=4,
            decision=CriticDecision.MORE_RESEARCH,
            follow_up_queries=["pilot line yield data 2026"], reasoning="needs more")
        add_run(c, project.id, "Q", critique=critique)
        gaps = c.overview_service.build(project.id)["knowledge_gaps"]
        assert gaps[0]["text"] == "pilot line yield data 2026"
        assert "iteration limit" in gaps[0]["reason"]

    def test_completed_run_without_report_is_a_gap(self, tmp_path):
        c = container(tmp_path)
        project = add_project(c)
        run = add_run(c, project.id, "Timed-out question?")
        run.metrics.synthesis_fallback = True
        c.runs_repo.save(run)
        gaps = c.overview_service.build(project.id)["knowledge_gaps"]
        assert any("no narrative report" in g["reason"] for g in gaps)

    def test_healthy_project_has_no_fabricated_gaps(self, tmp_path):
        c = container(tmp_path)
        project = add_project(c)
        critique = Critique(coverage_assessment="good", missing_information=[],
                            overall_score=9, decision=CriticDecision.SYNTHESIZE,
                            reasoning="ok")
        add_run(c, project.id, "Answered question?", critique=critique)
        assert c.overview_service.build(project.id)["knowledge_gaps"] == []

    def test_gaps_are_deduplicated(self, tmp_path):
        c = container(tmp_path)
        project = add_project(c)
        for _ in range(3):
            add_run(c, project.id, "Same failed question?", status=RunStatus.FAILED)
        gaps = c.overview_service.build(project.id)["knowledge_gaps"]
        assert len(gaps) == 1

    def test_planner_subquestions_are_not_used_as_gaps(self, tmp_path):
        """Measured as unreliable: an off-topic control scored 0.527 against
        this project's findings while an answered subquestion scored 0.590."""
        from src.models.research import ResearchPlan, ResearchTask

        c = container(tmp_path)
        project = add_project(c)
        plan = ResearchPlan(objective="o",
                            tasks=[ResearchTask(subquestion="Why is this the biggest obstacle?",
                                                evidence_needed="e")],
                            search_queries=["q"])
        critique = Critique(coverage_assessment="good", missing_information=[],
                            overall_score=9, decision=CriticDecision.SYNTHESIZE, reasoning="ok")
        add_run(c, project.id, "Q", plan=plan, critique=critique)
        gaps = c.overview_service.build(project.id)["knowledge_gaps"]
        assert all("biggest obstacle" not in g["text"] for g in gaps)


class TestRecentRuns:
    def test_contribution_counts_and_ordering(self, tmp_path):
        c = container(tmp_path)
        project = add_project(c)
        done = add_run(c, project.id, "Completed question?")
        add_finding(c, project, done, "A finding that this run contributed here.")
        add_finding(c, project, done, "Another finding from the very same run.")
        failed = add_run(c, project.id, "Failed question?", status=RunStatus.FAILED)

        recent = c.overview_service.build(project.id)["recent_runs"]
        by_id = {r["id"]: r for r in recent}
        assert by_id[done.id]["findings_added"] == 2
        assert by_id[failed.id]["findings_added"] == 0  # never claims findings
        assert by_id[failed.id]["status"] == "FAILED"
        assert [r["id"] for r in recent] == sorted(
            by_id, key=lambda i: by_id[i]["created_at"], reverse=True)

    def test_limited_to_five(self, tmp_path):
        c = container(tmp_path)
        project = add_project(c)
        for i in range(8):
            add_run(c, project.id, f"Question {i}?")
        assert len(c.overview_service.build(project.id)["recent_runs"]) == 5


class TestIsolationAndEmptyStates:
    def test_no_cross_project_leakage(self, tmp_path):
        c = container(tmp_path)
        battery, solar = add_project(c), add_project(c, "Solar")
        b_run = add_run(c, battery.id, "Battery?", sources=["https://b.com/1"])
        s_run = add_run(c, solar.id, "Solar?", sources=["https://s.com/1"])
        add_finding(c, battery, b_run, "Battery finding about electrolyte interfaces.")
        add_finding(c, solar, s_run, "Solar finding about rooftop payback periods.")

        overview = c.overview_service.build(battery.id)
        shown = overview["current_understanding"] + overview["key_findings"]
        assert all("Solar" not in i["text"] for i in shown)
        assert all(i["run_id"] == b_run.id for i in shown)
        assert overview["stats"]["unique_sources"] == 1
        assert [r["id"] for r in overview["recent_runs"]] == [b_run.id]

    def test_brand_new_project(self, tmp_path):
        c = container(tmp_path)
        overview = c.overview_service.build(add_project(c, "Empty").id)
        assert overview["stats"] == {"runs": 0, "completed_runs": 0, "findings": 0,
                                     "unique_sources": 0, "documents": 0}
        assert overview["current_understanding"] == []
        assert overview["key_findings"] == []
        assert overview["knowledge_gaps"] == []
        assert overview["recent_runs"] == []

    def test_runs_but_no_findings(self, tmp_path):
        c = container(tmp_path)
        project = add_project(c)
        add_run(c, project.id, "In progress?", status=RunStatus.RESEARCHING)
        overview = c.overview_service.build(project.id)
        assert overview["stats"]["runs"] == 1 and overview["stats"]["findings"] == 0
        assert overview["current_understanding"] == []
        assert overview["recent_runs"][0]["findings_added"] == 0

    def test_documents_but_no_runs(self, tmp_path):
        c = container(tmp_path)
        project = add_project(c)
        doc = c.document_service.ingest("notes.txt", b"project reference material " * 30)
        c.documents_repo.set_project(doc.id, project.id)
        overview = c.overview_service.build(project.id)
        assert overview["stats"]["documents"] == 1
        assert overview["stats"]["runs"] == 0 and overview["recent_runs"] == []


class TestApiAndPerformance:
    def test_endpoint_returns_full_view_model(self, tmp_path):
        from fastapi.testclient import TestClient

        from src.api.app import create_app

        c = container(tmp_path)
        project = add_project(c)
        run = add_run(c, project.id, "Battery question?", sources=["https://a.com/1"])
        add_finding(c, project, run, "A clear finding about electrolyte interfaces.")
        with TestClient(create_app(c)) as client:
            response = client.get(f"/api/projects/{project.id}/overview")
            assert response.status_code == 200
            body = response.json()
            assert set(body) == {"project", "stats", "current_understanding",
                                 "key_findings", "knowledge_gaps", "recent_runs"}
            assert body["project"]["name"] == project.name
            assert body["stats"]["findings"] == 1
            assert client.get("/api/projects/missing/overview").status_code == 404

    def test_no_model_call_on_build(self, tmp_path):
        """The container's embedder raises if used, so a clean build proves
        the Overview needs neither an LLM nor an embedding."""
        c = container(tmp_path)
        project = add_project(c)
        run = add_run(c, project.id, "Q", sources=["https://a.com/1"])
        add_finding(c, project, run, "Finding text with enough words to be useful.",
                    vector=[1.0, 0.0, 0.0])
        c.embed_guard.armed = True
        assert c.overview_service.build(project.id)["stats"]["findings"] == 1

    def test_build_is_bounded_for_many_runs(self, tmp_path):
        c = container(tmp_path)
        project = add_project(c)
        for i in range(25):
            run = add_run(c, project.id, f"Question {i}?", sources=[f"https://s{i}.com/a"])
            add_finding(c, project, run, f"Finding number {i} about battery chemistry.",
                        vector=[float(i), 1.0, 0.0])
        overview = c.overview_service.build(project.id)
        assert overview["stats"]["runs"] == 25
        assert overview["stats"]["unique_sources"] == 25
        assert len(overview["recent_runs"]) == 5
        assert len(overview["key_findings"]) <= 6
