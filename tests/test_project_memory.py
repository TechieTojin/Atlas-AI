"""Project-scoped research memory: storage, retrieval, scoping, injection.

Embeddings are faked deterministically (topic vectors) so the suite stays
offline; the thresholds they exercise are the ones measured on real
nomic-embed-text vectors — recorded in TestRealEmbeddingCalibration.
"""

import pytest

from src.agents.planner import PlannerAgent
from src.agents.synthesizer import SynthesizerAgent
from src.evaluation import evaluate_report
from src.memory.project_memory import (
    DEFAULT_RELEVANCE_THRESHOLD,
    ProjectMemoryService,
    extract_findings,
    format_memory_block,
)
from src.models.memory import MemoryHit, ProjectFinding
from src.models.research import CriticDecision, ResearchPlan, Source
from src.models.runs import ResearchRun, RunMode, RunStatus
from src.models.workspace import Project
from src.persistence import Database
from src.persistence.findings import FindingsRepository
from tests.conftest import FakeLLM, make_critique, make_plan, make_search_fn
from tests.conftest_v2 import make_container

BATTERY_REPORT = """\
## Interface Stability

Interface instability between the solid electrolyte and the lithium metal anode
remains the single largest barrier to commercial solid-state cells [1].
Dendrite formation through grain boundaries causes short circuits during fast
charging in prototype cells [2].

## Manufacturing

Manufacturing scalability is limited because sulfide electrolytes require dry
rooms and specialised stacking equipment that no gigafactory runs at scale [1].

## Sources

1. [A](https://a.com/1)
2. [B](https://b.com/2)
"""

SOLAR_REPORT = """\
## Findings

Rooftop solar reduces household electricity bills substantially in sunny
regions and pays back installation costs within a decade [1].

## Sources

1. [S](https://solar.com/1)
"""

BATTERY_Q = ("Which of the technical barriers previously identified for solid-state "
             "batteries is currently the biggest obstacle to mass production?")
SOLAR_Q = "What are the main advantages of solar energy?"


def make_run(report, query, project_id, sources, status=RunStatus.COMPLETED):
    run = ResearchRun(query=query, project_id=project_id, status=status)
    run.final_report = report
    run.selected_sources = sources
    return run


BATTERY_SOURCES = [Source(title="A", url="https://a.com/1", domain="a.com"),
                   Source(title="B", url="https://b.com/2", domain="b.com")]
SOLAR_SOURCES = [Source(title="S", url="https://solar.com/1", domain="solar.com")]


def topic_embed(texts):
    """Deterministic 3-D topic vectors: battery / solar / other."""
    out = []
    for text in texts:
        low = text.lower()
        battery = sum(low.count(w) for w in
                      ("solid-state", "battery", "batteries", "electrolyte",
                       "dendrite", "anode", "manufactur", "barrier"))
        solar = sum(low.count(w) for w in ("solar", "rooftop", "photovoltaic",
                                           "electricity bill"))
        out.append([float(battery), float(solar), 0.4])
    return out


def memory_service(embed=topic_embed, **kw):
    repo = FindingsRepository(Database(":memory:"))
    return ProjectMemoryService(repo, embed_texts=embed, **kw), repo


class TestExtraction:
    def test_completed_project_run_becomes_cited_findings(self):
        run = make_run(BATTERY_REPORT, BATTERY_Q, "proj-A", BATTERY_SOURCES)
        findings = extract_findings(run)
        assert len(findings) >= 3
        first = findings[0]
        assert "Interface instability" in first.text
        assert first.project_id == "proj-A" and first.run_id == run.id
        assert first.question == BATTERY_Q and first.section == "Interface Stability"
        # Provenance: the real source the claim cited.
        assert [s.url for s in first.sources] == ["https://a.com/1"]
        multi = next(f for f in findings if "Dendrite" in f.text)
        assert [s.url for s in multi.sources] == ["https://b.com/2"]

    def test_uncited_text_and_sources_section_excluded(self):
        run = make_run(BATTERY_REPORT, BATTERY_Q, "proj-A", BATTERY_SOURCES)
        texts = " ".join(f.text for f in extract_findings(run))
        assert "a.com" not in texts  # the Sources list is never a finding
        assert all(f.sources for f in extract_findings(run))

    def test_incomplete_or_non_project_runs_yield_nothing(self):
        assert extract_findings(make_run(BATTERY_REPORT, BATTERY_Q, "", BATTERY_SOURCES)) == []
        empty = make_run("", BATTERY_Q, "proj-A", BATTERY_SOURCES)
        assert extract_findings(empty) == []

    def test_no_reasoning_content_stored(self):
        run = make_run("Thinking out loud</think>\n\nReal finding about batteries [1].",
                       BATTERY_Q, "proj-A", BATTERY_SOURCES)
        assert all("</think>" not in f.text for f in extract_findings(run))


class TestStorage:
    def test_remember_is_idempotent(self):
        service, repo = memory_service()
        run = make_run(BATTERY_REPORT, BATTERY_Q, "proj-A", BATTERY_SOURCES)
        first = service.remember_run(run)
        assert first >= 3
        assert service.remember_run(run) == 0  # no duplicates on re-index
        assert len(repo.list_for_project("proj-A")) == first

    def test_only_completed_runs_are_stored(self):
        service, repo = memory_service()
        for status in (RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.SYNTHESIZING):
            run = make_run(BATTERY_REPORT, BATTERY_Q, "proj-A", BATTERY_SOURCES, status)
            assert service.remember_run(run) == 0
        assert repo.list_for_project("proj-A") == []

    def test_backfill_indexes_existing_runs_once(self):
        service, repo = memory_service()
        runs = [make_run(BATTERY_REPORT, BATTERY_Q, "proj-A", BATTERY_SOURCES),
                make_run(SOLAR_REPORT, SOLAR_Q, "proj-B", SOLAR_SOURCES)]
        added = service.backfill(runs)
        assert added > 0
        assert service.backfill(runs) == 0  # idempotent across restarts
        assert len(repo.list_for_project("proj-A")) + len(repo.list_for_project("proj-B")) == added

    def test_findings_stored_even_if_embedding_fails_then_embedded_later(self):
        calls = {"n": 0}

        def flaky(texts):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("ollama down")
            return topic_embed(texts)

        service, repo = memory_service(embed=flaky)
        run = make_run(BATTERY_REPORT, BATTERY_Q, "proj-A", BATTERY_SOURCES)
        assert service.remember_run(run) > 0
        assert repo.unembedded("proj-A")  # stored without vectors
        hits, report = service.recall(BATTERY_Q, "proj-A")
        assert not repo.unembedded("proj-A")  # embedded lazily on recall
        assert hits and report.hits == len(hits)


class TestRetrievalAndScoping:
    def _loaded(self):
        service, repo = memory_service()
        service.remember_run(make_run(BATTERY_REPORT, BATTERY_Q, "proj-A", BATTERY_SOURCES))
        service.remember_run(make_run(SOLAR_REPORT, SOLAR_Q, "proj-B", SOLAR_SOURCES))
        return service, repo

    def test_related_followup_retrieves_prior_findings(self):
        service, _ = self._loaded()
        hits, report = service.recall(BATTERY_Q, "proj-A")
        assert hits and report.hits == len(hits)
        assert report.scope == "PROJECT" and report.enabled
        assert report.candidates >= len(hits)
        assert all(h.score >= report.threshold for h in hits)
        assert any("Interface instability" in h.finding.text for h in hits)

    def test_memory_from_another_project_cannot_leak(self):
        service, _ = self._loaded()
        hits, report = service.recall(SOLAR_Q, "proj-B")
        assert hits  # project B sees its own
        assert all(h.finding.project_id == "proj-B" for h in hits)
        # A battery question inside project B must not reach project A.
        hits_b, report_b = service.recall(BATTERY_Q, "proj-B")
        assert all(h.finding.project_id == "proj-B" for h in hits_b)
        assert report_b.candidates == len(service._repo.list_for_project("proj-B"))

    def test_unrelated_topic_in_same_project_not_selected(self):
        service, _ = memory_service()
        # Both topics live in ONE project (as after earlier testing).
        service.remember_run(make_run(BATTERY_REPORT, BATTERY_Q, "proj-A", BATTERY_SOURCES))
        service.remember_run(make_run(SOLAR_REPORT, SOLAR_Q, "proj-A", SOLAR_SOURCES))
        hits, report = service.recall(BATTERY_Q, "proj-A")
        assert hits
        assert all("solar" not in h.finding.text.lower() for h in hits)
        assert report.candidates > report.hits  # solar were candidates, not hits

    def test_no_relevant_matches_is_a_clean_zero(self):
        service, _ = self._loaded()
        hits, report = service.recall("What are the best hiking trails in the Alps?", "proj-A")
        assert hits == [] and report.hits == 0
        assert report.error == "" and report.candidates > 0  # searched, found nothing

    def test_retrieval_failure_is_distinguishable_from_zero(self):
        def broken(texts):
            raise RuntimeError("embedding service unavailable")

        service, _ = memory_service(embed=broken)
        service._repo.add_many(
            [ProjectFinding(project_id="proj-A", run_id="r", text="x" * 80)], [[1.0, 0.0, 0.0]]
        )
        hits, report = service.recall(BATTERY_Q, "proj-A")
        assert hits == [] and report.hits == 0
        assert "embedding service unavailable" in report.error

    def test_no_embedder_reports_error_not_silent_zero(self):
        service, _ = memory_service(embed=None)
        hits, report = service.recall(BATTERY_Q, "proj-A")
        assert hits == [] and "No embedding model" in report.error

    def test_non_project_run_scope_is_none(self):
        service, _ = self._loaded()
        hits, report = service.recall(BATTERY_Q, "")
        assert hits == [] and report.scope == "NONE" and report.error == ""

    def test_results_are_capped_and_deterministic(self):
        service, _ = memory_service(max_items=2)
        service.remember_run(make_run(BATTERY_REPORT, BATTERY_Q, "proj-A", BATTERY_SOURCES))
        first, _ = service.recall(BATTERY_Q, "proj-A")
        second, _ = service.recall(BATTERY_Q, "proj-A")
        assert len(first) == 2
        assert [h.finding.id for h in first] == [h.finding.id for h in second]
        assert first[0].score >= first[1].score

    def test_provenance_survives_retrieval(self):
        service, _ = self._loaded()
        hits, report = service.recall(BATTERY_Q, "proj-A")
        hit = hits[0]
        assert hit.finding.project_id == "proj-A" and hit.finding.run_id
        assert hit.finding.question == BATTERY_Q
        assert hit.finding.sources and hit.finding.sources[0].url.startswith("https://")
        assert report.items[0]["run_id"] == hit.finding.run_id
        assert report.items[0]["sources"][0]["url"] == hit.finding.sources[0].url


class TestPromptInjection:
    def test_planner_receives_memory_context(self):
        llm = FakeLLM(plans=[make_plan()])
        PlannerAgent(llm, memory_context="- Interface instability is the key barrier.")(
            {"question": BATTERY_Q}
        )
        prompt = str(llm.with_structured_output(ResearchPlan).calls[0])
        assert "Interface instability is the key barrier" in prompt
        assert "PREVIOUS PROJECT FINDINGS" in prompt

    def test_planner_without_memory_is_unchanged(self):
        llm = FakeLLM(plans=[make_plan()])
        PlannerAgent(llm)({"question": BATTERY_Q})
        assert "PREVIOUS PROJECT FINDINGS" not in str(
            llm.with_structured_output(ResearchPlan).calls[0]
        )

    def test_synthesizer_separates_memory_from_citable_sources(self):
        from tests.conftest import make_evidence

        evidence = [make_evidence("https://x.com/1", title="X",
                                  content="Fresh evidence about dry-room costs today.")]
        llm = FakeLLM(synthesis="Report body [1].")
        SynthesizerAgent(llm, memory_context="- Interface instability is the key barrier.")(
            {"question": BATTERY_Q, "evidence": evidence}
        )
        user = llm.invoke_calls[0][1][1]
        memory_part = user.split("PROJECT MEMORY")[1]
        assert "NOT citable" in memory_part
        assert "Interface instability" in memory_part
        # Memory appears AFTER the numbered sources and carries no numbers.
        assert user.index("SOURCE [1]") < user.index("PROJECT MEMORY")
        assert "[1]" not in memory_part.split("\n\n")[-1]

    def test_memory_does_not_corrupt_citation_numbering(self):
        from tests.conftest import make_evidence

        evidence = [make_evidence("https://x.com/1", title="X", content="Fresh evidence one."),
                    make_evidence("https://y.com/2", title="Y", content="Fresh evidence two.")]
        llm = FakeLLM(synthesis="Claim one [1]. Claim two [2].")
        result = SynthesizerAgent(llm, memory_context="- Old finding from memory.")(
            {"question": BATTERY_Q, "evidence": evidence}
        )
        report = result["final_report"]
        assert result["sources_selected"] == 2 and result["sources_cited"] == 2
        assert "https://x.com/1" in report and "https://y.com/2" in report
        assert "Old finding from memory" not in report  # never becomes a source
        assert evaluate_report(report, [e.source for e in evidence]).passed

    def test_memory_block_is_bounded(self):
        hits = [MemoryHit(finding=ProjectFinding(project_id="p", run_id="r", text="x" * 300),
                          score=0.9) for _ in range(10)]
        assert len(format_memory_block(hits, max_chars=600)) <= 650
        assert format_memory_block([]) == ""


class TestServiceIntegration:
    def _container(self, tmp_path):
        llm = FakeLLM(
            plans=[make_plan()],
            critiques=[make_critique(CriticDecision.SYNTHESIZE, score=9)],
            synthesis='{"report": "Interface instability between electrolyte and anode '
                      'still dominates solid-state battery development [1][2]."}',
        )
        search = make_search_fn(default=[
            {"url": "https://a.com/1", "title": "A", "score": 0.9,
             "content": "Dry rooms for sulfide electrolytes remain the key manufacturing cost."},
            {"url": "https://b.com/2", "title": "B", "score": 0.8,
             "content": "Pilot lines report low yields when stacking solid electrolyte layers."},
        ])
        c = make_container(tmp_path, llm=llm, search_fn=search, embed_fn=topic_embed)
        project = Project(name="Battery Technology Research")
        c.projects_repo.save(project)
        return c, project, llm

    def test_run_stores_memory_and_next_run_reuses_it(self, tmp_path):
        c, project, llm = self._container(tmp_path)
        first = c.research_service.create_run(
            "What are the biggest technical barriers for solid-state batteries?",
            mode=RunMode.FAST, project_id=project.id)
        first_final = c.research_service.get_run(first.id)
        assert first_final.status is RunStatus.COMPLETED
        assert first_final.metrics.project_memory_hits == 0  # nothing stored yet
        assert c.findings_repo.list_for_project(project.id)  # now it is

        llm._syntheses = ['{"report": "Manufacturing scalability is now the binding '
                          'constraint for solid-state battery production [1][2]."}']
        llm.queue_structured(ResearchPlan, [make_plan()])
        from src.models.research import Critique

        llm.queue_structured(Critique, [make_critique(CriticDecision.SYNTHESIZE, score=9)])
        second = c.research_service.create_run(BATTERY_Q, mode=RunMode.FAST,
                                               project_id=project.id)
        final = c.research_service.get_run(second.id)
        assert final.status is RunStatus.COMPLETED
        m = final.metrics
        assert m.memory_enabled and m.memory_scope == "PROJECT"
        assert m.project_memory_hits > 0 and m.memory_error == ""
        assert m.memory_items[0]["run_id"] == first.id  # provenance to run 1
        assert m.memory_items[0]["score"] >= m.memory_threshold
        # Fresh research still happened and the report is still grounded.
        assert m.sources_collected > 0 and m.sources_cited > 0
        assert final.evaluation.passed

    def test_memory_off_retrieves_and_injects_nothing(self, tmp_path):
        c, project, llm = self._container(tmp_path)
        c.research_service.create_run("Barriers for solid-state batteries?",
                                      mode=RunMode.FAST, project_id=project.id)
        assert c.findings_repo.list_for_project(project.id)

        llm._syntheses = ['{"report": "Fresh web research alone drives this solid-state '
                          'battery conclusion today [1][2]."}']
        llm.queue_structured(ResearchPlan, [make_plan()])
        from src.models.research import Critique

        llm.queue_structured(Critique, [make_critique(CriticDecision.SYNTHESIZE, score=9)])
        run = c.research_service.create_run(BATTERY_Q, mode=RunMode.FAST,
                                            project_id=project.id, use_memory=False)
        final = c.research_service.get_run(run.id)
        m = final.metrics
        assert m.memory_enabled is False and m.project_memory_hits == 0
        assert m.memory_items == [] and m.memory_scope == "NONE"
        planner_prompt = str(llm.with_structured_output(ResearchPlan).calls[-1])
        assert "PREVIOUS PROJECT FINDINGS" not in planner_prompt
        assert "PROJECT MEMORY" not in llm.invoke_calls[-1][1][1]

    def test_non_project_run_reports_no_scope(self, tmp_path):
        c, _, _ = self._container(tmp_path)
        run = c.research_service.create_run("A global question?", mode=RunMode.FAST)
        metrics = c.research_service.get_run(run.id).metrics
        assert metrics.memory_scope == "NONE" and metrics.project_memory_hits == 0

    def test_backfill_makes_existing_runs_reusable(self, tmp_path):
        c, project, _ = self._container(tmp_path)
        # A completed project run saved directly, as if it predated memory.
        legacy = make_run(BATTERY_REPORT, "Earlier battery research", project.id,
                          BATTERY_SOURCES)
        c.runs_repo.save(legacy)
        assert c.findings_repo.list_for_project(project.id) == []
        assert c.research_service.backfill_project_memory() > 0
        assert c.research_service.backfill_project_memory() == 0  # idempotent
        hits, _ = c.project_memory.recall(BATTERY_Q, project.id)
        assert hits and hits[0].finding.run_id == legacy.id


class TestRealEmbeddingCalibration:
    """Values measured with nomic-embed-text on real Atlas runs (run
    ecf918c1 findings), recorded so a threshold change is a deliberate act."""

    MEASURED = {
        "battery follow-up vs battery findings": 0.832,
        "battery adjacent vs battery findings": 0.778,
        "battery question vs solar findings": 0.581,
        "solar question vs battery findings": 0.496,
        "unrelated question vs battery findings": 0.390,
    }

    def test_threshold_separates_measured_topics(self):
        t = DEFAULT_RELEVANCE_THRESHOLD
        assert self.MEASURED["battery adjacent vs battery findings"] > t
        assert self.MEASURED["battery follow-up vs battery findings"] > t
        assert self.MEASURED["battery question vs solar findings"] < t
        assert self.MEASURED["solar question vs battery findings"] < t
        assert self.MEASURED["unrelated question vs battery findings"] < t

    def test_threshold_has_margin_on_both_sides(self):
        t = DEFAULT_RELEVANCE_THRESHOLD
        assert t - self.MEASURED["battery question vs solar findings"] >= 0.05
        assert self.MEASURED["battery adjacent vs battery findings"] - t >= 0.05
