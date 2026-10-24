"""Research integrity: claim extraction, citation verification, contradiction
detection, quality scoring and their persistence.

These tests pin the *documented contract* of the deterministic verifier, so a
future change to the thresholds has to be deliberate.
"""

from __future__ import annotations

import pytest

from src.models.integrity import (
    ClaimRecord,
    ClaimVerification,
    ConfidenceBand,
    Contradiction,
    ContradictionType,
    QualityComponent,
    QualityScore,
    VerificationStatus,
)
from src.models.research import Evidence, Source, SourceQuality
from src.models.runs import EvaluationResult
from src.persistence.db import Database
from src.persistence.integrity import IntegrityRepository
from src.services.integrity_service import (
    IntegrityService,
    detect_contradiction,
    verify_claim_text,
)


def src(url: str, domain: str = "", quality: SourceQuality | None = None) -> Source:
    return Source(title=url, url=url, domain=domain or url, kind="web", quality=quality)


def ev(source: Source, content: str, relevance: float | None = 0.8) -> Evidence:
    return Evidence(source=source, content=content, relevance_score=relevance)


class FakeRun:
    """Minimal stand-in exposing only what IntegrityService reads."""

    def __init__(self, report, sources, evidence, coverage=1.0, run_id="run-1", project_id=None):
        self.id = run_id
        self.project_id = project_id
        self.final_report = report
        self.selected_sources = sources
        self.evidence = evidence
        self.evaluation = EvaluationResult(citation_coverage=coverage)


@pytest.fixture()
def db() -> Database:
    return Database(":memory:")


@pytest.fixture()
def repo(db: Database) -> IntegrityRepository:
    return IntegrityRepository(db)


@pytest.fixture()
def service(repo: IntegrityRepository) -> IntegrityService:
    return IntegrityService(repo)


def _register_run(db: Database, run_id: str) -> None:
    """Insert the minimal runs row the integrity foreign keys require.

    Claims are derived artifacts of a real run; the FK (and its ON DELETE
    CASCADE) is deliberate, so tests create the parent row rather than
    weakening the schema.
    """
    conn = db.connect()
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO runs
                (id, query, title, mode, source_scope, status, approval_required,
                 created_at, updated_at, data)
            VALUES (?, 'q', 't', 'FAST', 'WEB', 'COMPLETED', 0, ?, ?, '{}')
            """,
            (run_id, "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
        )
        conn.commit()
    finally:
        db.release(conn)


@pytest.fixture()
def analyze(db: Database, service: IntegrityService):
    """Register the run, then analyse it — mirrors the production order."""

    def run_analysis(run):
        _register_run(db, run.id)
        return service.analyze_run(run)

    return run_analysis


# -- the deterministic verifier ------------------------------------------------


class TestVerifier:
    def test_claim_whose_substance_is_in_the_passage_is_supported(self):
        verdict = verify_claim_text(
            "Thermal runaway can be initiated by overheating and overcharging [1].",
            ["Thermal runaway is initiated by overheating and by overcharging the cells."],
        )
        assert verdict.status is VerificationStatus.SUPPORTED

    def test_claim_only_partly_present_is_partially_supported(self):
        verdict = verify_claim_text(
            "Manufacturing scalability, encapsulation chemistry and lead toxicity "
            "all remain unresolved commercialization barriers [1].",
            ["Manufacturing scalability remains a commercialization barrier."],
        )
        assert verdict.status is VerificationStatus.PARTIALLY_SUPPORTED

    def test_claim_absent_from_the_passage_is_unsupported(self):
        verdict = verify_claim_text(
            "Perovskite modules achieved commercial rooftop deployment in Japan [1].",
            ["Lithium-ion battery packs fail through internal short circuits and heat transfer."],
        )
        assert verdict.status is VerificationStatus.UNSUPPORTED

    def test_claim_with_no_stored_passage_is_not_verifiable(self):
        verdict = verify_claim_text("Reported efficiency reached 25.7% [1].", [])
        assert verdict.status is VerificationStatus.NOT_VERIFIABLE
        assert verdict.confidence is ConfidenceBand.HIGH
        # An honest unknown must not be reported as a failure.
        assert not verdict.status.is_problem

    def test_citation_presence_alone_never_implies_support(self):
        """The whole point of the engine: a marker is not evidence."""
        verdict = verify_claim_text(
            "Global installed capacity tripled between 2019 and 2023 [1][2].",
            ["Encapsulation layers degrade when exposed to humidity."],
        )
        assert verdict.status is VerificationStatus.UNSUPPORTED

    def test_figures_not_present_in_passage_reduce_support(self):
        verdict = verify_claim_text(
            "Reported power conversion efficiency reached 25.7% in 2023 [1].",
            ["Reported power conversion efficiency reached 18.1% in 2016."],
        )
        assert verdict.status in (
            VerificationStatus.PARTIALLY_SUPPORTED,
            VerificationStatus.CONTRADICTED,
        )

    def test_multiple_citations_are_all_examined(self, analyze, repo):
        s1, s2 = src("https://a.test/1", "a.test"), src("https://b.test/2", "b.test")
        run = FakeRun(
            "## Findings\nCost and stability both remain barriers [1][2].\n",
            [s1, s2],
            [ev(s1, "Cost remains a barrier."), ev(s2, "Stability remains a barrier.")],
        )
        analyze(run)
        claim = repo.claims_for_run(run.id)[0]
        verification = repo.verification_for_claim(claim.id)
        assert verification.checked_citations == [1, 2]

    def test_signals_are_recorded_so_a_verdict_can_be_explained(self):
        verdict = verify_claim_text(
            "Efficiency reached 25.7% [1].", ["Efficiency reached 25.7% in testing."]
        )
        names = {s.name for s in verdict.signals}
        assert {"term_overlap", "numeric_match", "evidence_available"} <= names
        assert verdict.explanation


# -- contradictions -------------------------------------------------------------


class TestContradictions:
    def test_different_wording_about_the_same_fact_is_not_a_contradiction(self):
        assert (
            detect_contradiction(
                "Manufacturing scalability remains the main commercialization barrier.",
                "The principal barrier to commercialization is scaling manufacturing.",
            )
            is None
        )

    def test_unrelated_passages_are_not_a_contradiction(self):
        assert (
            detect_contradiction(
                "Encapsulation reduces moisture ingress in perovskite cells.",
                "Interest rates influence mortgage demand in the housing market.",
            )
            is None
        )

    def test_unrelated_incidental_numbers_do_not_create_a_contradiction(self):
        """Regression: two passages agreeing about the Shockley-Queisser limit
        were flagged because an incidental "5" was compared against "1.34"."""
        assert (
            detect_contradiction(
                "The Shockley-Queisser limit was first calculated in 1961 and is "
                "discussed across 5 reviews of single junction solar cell theory.",
                "The Shockley-Queisser limit, defined in 1961, assumes a band gap "
                "of about 1.34 eV for a single junction solar cell.",
            )
            is None
        )

    def test_shared_years_are_not_outdated_vs_current(self):
        """Both sources dating a result to 1961 agree about the period."""
        hit = detect_contradiction(
            "The limit was calculated in 1961 and revisited in 1992 for solar cells.",
            "The limit was calculated in 1961 for single junction solar cells.",
        )
        assert hit is None or hit[0] is not ContradictionType.OUTDATED_VS_CURRENT

    def test_materially_different_figures_are_mixed_evidence(self):
        hit = detect_contradiction(
            "Reported module efficiency reached 25.7 percent in testing.",
            "Reported module efficiency reached 18.1 percent in testing.",
        )
        assert hit is not None and hit[0] is ContradictionType.MIXED_EVIDENCE

    def test_differing_figures_across_periods_are_outdated_vs_current(self):
        hit = detect_contradiction(
            "In 2016 reported efficiency reached 18.1 percent for the module.",
            "In 2023 reported efficiency reached 25.7 percent for the module.",
        )
        assert hit is not None and hit[0] is ContradictionType.OUTDATED_VS_CURRENT

    def test_opposite_statements_on_shared_topic_are_contextual_disagreement(self):
        hit = detect_contradiction(
            "Encapsulation reliably prevents moisture ingress in perovskite modules.",
            "Encapsulation does not prevent moisture ingress in perovskite modules.",
        )
        assert hit is not None and hit[0] is ContradictionType.CONTEXTUAL_DISAGREEMENT

    def test_contradictions_are_persisted_with_both_excerpts(self, analyze, repo):
        s1, s2 = src("https://a.test/1", "a.test"), src("https://b.test/2", "b.test")
        run = FakeRun(
            "## Efficiency\nReported efficiency is well established [1][2].\n",
            [s1, s2],
            [
                ev(s1, "Reported module efficiency reached 25.7 percent in testing."),
                ev(s2, "Reported module efficiency reached 18.1 percent in testing."),
            ],
        )
        analyze(run)
        found = repo.contradictions_for_run(run.id)
        assert len(found) == 1
        assert found[0].source_a == 1 and found[0].source_b == 2
        assert found[0].excerpt_a and found[0].excerpt_b
        assert found[0].explanation


# -- claims + persistence -------------------------------------------------------


class TestClaimsPersistence:
    def test_only_cited_sentences_become_claims(self, analyze, repo):
        s1 = src("https://a.test/1", "a.test")
        run = FakeRun(
            "## Findings\nThis sentence has no citation.\nThis one does [1].\n",
            [s1],
            [ev(s1, "This one does and is supported by the passage.")],
        )
        analyze(run)
        claims = repo.claims_for_run(run.id)
        assert len(claims) == 1
        assert "[1]" in claims[0].text

    def test_claim_keeps_its_section_and_document_order(self, analyze, repo):
        s1 = src("https://a.test/1", "a.test")
        run = FakeRun(
            "## Alpha\nFirst point [1].\n\n## Beta\nSecond point [1].\n",
            [s1],
            [ev(s1, "First point and second point are both discussed here.")],
        )
        analyze(run)
        claims = repo.claims_for_run(run.id)
        assert [c.section for c in claims] == ["Alpha", "Beta"]
        assert [c.position for c in claims] == [0, 1]

    def test_reanalysis_replaces_derived_rows_without_duplicating(self, analyze, repo):
        s1 = src("https://a.test/1", "a.test")
        run = FakeRun("## F\nA point [1].\n", [s1], [ev(s1, "A point is made here.")])
        analyze(run)
        analyze(run)
        assert len(repo.claims_for_run(run.id)) == 1
        assert len(repo.verifications_for_run(run.id)) == 1

    def test_verification_round_trips_through_the_database(self, analyze, repo):
        s1 = src("https://a.test/1", "a.test")
        run = FakeRun("## F\nA clear point [1].\n", [s1], [ev(s1, "A clear point is made here.")])
        analyze(run)
        claim = repo.claims_for_run(run.id)[0]
        stored = repo.verification_for_claim(claim.id)
        assert stored.run_id == run.id
        assert stored.status in set(VerificationStatus)
        assert stored.signals and stored.signals[0].name

    def test_every_verification_points_at_a_real_claim(self, analyze, repo):
        s1 = src("https://a.test/1", "a.test")
        run = FakeRun(
            "## F\nFirst [1].\nSecond distinct point [1].\n",
            [s1],
            [ev(s1, "First and second distinct point both appear here.")],
        )
        analyze(run)
        claim_ids = {c.id for c in repo.claims_for_run(run.id)}
        assert claim_ids
        for v in repo.verifications_for_run(run.id):
            assert v.claim_id in claim_ids


# -- summary + quality ----------------------------------------------------------


class TestSummaryAndQuality:
    def test_summary_counts_each_status(self, analyze, repo):
        s1 = src("https://a.test/1", "a.test")
        run = FakeRun(
            "## F\nA clear supported point [1].\nAn entirely unrelated assertion about mortgages [1].\n",
            [s1],
            [ev(s1, "A clear supported point is explained in detail here.")],
        )
        summary = analyze(run)
        assert summary.total_claims == 2
        assert summary.supported + summary.partially_supported + summary.unsupported == 2

    def test_support_rate_is_none_when_nothing_was_verifiable(self, analyze):
        s1 = src("https://a.test/1", "a.test")
        # Source present but no stored passage text -> NOT_VERIFIABLE.
        run = FakeRun("## F\nA point [1].\n", [s1], [])
        summary = analyze(run)
        assert summary.not_verifiable == 1
        assert summary.support_rate is None, "never fabricate a percentage"

    def test_quality_marks_uncomputable_dimensions_not_available(self, analyze, repo):
        s1 = src("https://a.test/1", "a.test")
        run = FakeRun("## F\nA point [1].\n", [s1], [ev(s1, "A point is made.", relevance=None)])
        analyze(run)
        score = repo.quality_for_run(run.id)
        by_name = {c.name: c for c in score.components}
        assert by_name["source_authority"].available is False
        assert by_name["source_authority"].value is None
        assert by_name["evidence_relevance"].available is False

    def test_quality_uses_authority_when_the_run_recorded_it(self, analyze, repo):
        s1 = src("https://a.test/1", "a.test", quality=SourceQuality(tier="high", score=90))
        run = FakeRun("## F\nA point [1].\n", [s1], [ev(s1, "A point is made here.")])
        analyze(run)
        by_name = {c.name: c for c in repo.quality_for_run(run.id).components}
        assert by_name["source_authority"].available is True
        assert by_name["source_authority"].value == pytest.approx(0.9)

    def test_overall_renormalises_over_available_components_only(self):
        score = QualityScore(
            run_id="r",
            components=[
                QualityComponent(name="a", available=True, value=1.0, weight=0.5),
                QualityComponent(name="b", available=False, value=None, weight=0.5),
            ],
        )
        # The missing half must not drag the score to 0.5.
        assert score.recompute_overall() == pytest.approx(1.0)

    def test_overall_is_none_when_nothing_could_be_computed(self):
        score = QualityScore(
            run_id="r",
            components=[QualityComponent(name="a", available=False, weight=1.0)],
        )
        assert score.recompute_overall() is None

    def test_quality_is_persisted_with_its_formula_version(self, analyze, repo):
        s1 = src("https://a.test/1", "a.test")
        run = FakeRun("## F\nA point [1].\n", [s1], [ev(s1, "A point is made here.")])
        analyze(run)
        stored = repo.quality_for_run(run.id)
        assert stored.formula_version >= 1
        assert stored.components


# -- robustness -----------------------------------------------------------------


class TestRobustness:
    def test_empty_report_produces_no_claims_and_no_crash(self, analyze, repo):
        run = FakeRun("", [], [])
        summary = analyze(run)
        assert summary.total_claims == 0
        assert repo.quality_for_run(run.id) is not None

    def test_citation_markers_beyond_the_source_count_are_ignored(self, analyze, repo):
        s1 = src("https://a.test/1", "a.test")
        run = FakeRun("## F\nA point [9].\n", [s1], [ev(s1, "A point is made here.")])
        analyze(run)
        # [9] is not a real source, so the sentence is not a verifiable claim.
        assert repo.claims_for_run(run.id) == []

    def test_non_latin_report_still_extracts_and_verifies(self, analyze, repo):
        s1 = src("https://a.test/1", "a.test")
        run = FakeRun(
            "## निष्कर्ष\nसौर सेल दक्षता 25.7 प्रतिशत तक पहुँच गई [1]।\n",
            [s1],
            [ev(s1, "सौर सेल दक्षता 25.7 प्रतिशत तक पहुँच गई थी।")],
        )
        analyze(run)
        claims = repo.claims_for_run(run.id)
        assert len(claims) == 1
        verification = repo.verification_for_claim(claims[0].id)
        assert verification.status is VerificationStatus.SUPPORTED


class TestContradictionPrecision:
    """Guards against the false-positive class found during QA acceptance."""

    def test_agreement_on_a_figure_outweighs_a_mispaired_gap(self):
        """Both sources state 1.34 eV; one also mentions silicon's 1.12 eV.

        Pairing 1.12 against 1.34 looked like a disagreement, but the sources
        plainly agree about the quantity under discussion.
        """
        assert (
            detect_contradiction(
                "The efficiency limit is about 33% for a solar cell with a bandgap of "
                "1.34 eV, whereas crystalline silicon has a bandgap of 1.12 eV.",
                "The maximum efficiency of 33.16% is achieved with a band gap of 1.34 eV.",
            )
            is None
        )

    def test_unitless_numbers_are_never_compared(self):
        assert (
            detect_contradiction(
                "The review covers 5 single junction solar cell architectures in detail.",
                "The analysis covers 10 single junction solar cell architectures in detail.",
            )
            is None
        )

    def test_a_genuine_same_unit_disagreement_is_still_reported(self):
        hit = detect_contradiction(
            "The module reached a certified efficiency of 25.7 percent in testing.",
            "The module reached a certified efficiency of 18.1 percent in testing.",
        )
        assert hit is not None

    def test_shared_figure_blocks_a_polarity_only_flag(self):
        """Regression: "cannot exceed 33%" vs "maximum is 33.16%" agree, but a
        stray negation word raised CONTEXTUAL_DISAGREEMENT."""
        assert (
            detect_contradiction(
                "A single junction solar cell cannot exceed an efficiency of about 33%.",
                "The maximum efficiency of 33.16% is achieved with a band gap of 1.34 eV.",
            )
            is None
        )
