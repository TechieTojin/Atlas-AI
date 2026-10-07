"""Comparison Synthesis V2.1: each section must mean what its heading says.

V2 made the model return structured data instead of prose, which removed the
narration. Inspecting a real V2 comparison then exposed the next layer of
problems, all of them semantic rather than structural:

* an "Agreement" attributed to Run 1 alone,
* a conclusion asserting a primary obstacle the Agreements never established,
* a source carrying that conclusion shown as "(collected, not cited)",
* an Overview made of run metadata ("identical completion dates and templates").

These tests pin the rules that make those outputs impossible.
"""

from __future__ import annotations

import pytest

from src.agents.synthesizer import render_sources_section
from src.models.research import Source
from src.services.comparison_service import build_comparison_sources, overlap_stats
from src.services.comparison_synthesis import (
    ComparisonError,
    ComparisonPoint,
    ComparisonSynthesis,
    Conclusion,
    Contradiction,
    ContradictionPosition,
    UniqueEvidencePoint,
    build_evidence_block,
    build_registry,
    cited_numbers,
    conclusion_citations,
    render_comparison,
    validate_synthesis,
)
from src.services.comparison_synthesis import _looks_like_instructions


class FakeRun:
    """Just enough of a ResearchRun for registry and rendering."""

    def __init__(self, run_id: str, sources: list[Source], evidence=()) -> None:
        self.id = run_id
        self.selected_sources = sources
        self.evidence = list(evidence)


def source(url: str, title: str = "T") -> Source:
    return Source(title=title, url=url, domain=url.split("/")[2])


SHARED = "https://shared.test/a"
ONLY1 = "https://one.test/b"
ONLY2 = "https://two.test/c"


def two_runs() -> list[FakeRun]:
    """Source 1 is shared; source 2 belongs to run 1 and source 3 to run 2."""
    return [
        FakeRun("run-1", [source(SHARED, "Shared"), source(ONLY1, "One")]),
        FakeRun("run-2", [source(SHARED + "/", "Shared"), source(ONLY2, "Two")]),
    ]


def agreement(**kw) -> ComparisonPoint:
    return ComparisonPoint(**{
        "id": "A1",
        "text": "Both runs find the barrier is cost.",
        "runs": [1, 2],
        "citations": [1],
        **kw,
    })


def unique(**kw) -> UniqueEvidencePoint:
    return UniqueEvidencePoint(**{
        "id": "U1",
        "run": 1,
        "text": "Run 1 alone found a pilot line.",
        "citations": [2],
        **kw,
    })


def valid(**overrides) -> ComparisonSynthesis:
    base = dict(
        overview="The runs converge on cost as the barrier and differ on timelines.",
        agreements=[agreement()],
        contradictions=[],
        unique_evidence=[unique()],
        conclusion=Conclusion(
            text="Cost is the shared barrier.", based_on=["A1", "U1"]
        ),
    )
    base.update(overrides)
    return ComparisonSynthesis(**base)


def checked(synthesis: ComparisonSynthesis) -> ComparisonSynthesis:
    return validate_synthesis(synthesis, build_registry(two_runs()))


def render(synthesis: ComparisonSynthesis, title="Comparison: Test") -> str:
    runs = two_runs()
    registry = build_registry(runs)
    return render_comparison(
        validate_synthesis(synthesis, registry), registry, runs, title,
        render_sources_section,
    )


# -- the canonical source registry (unchanged in V2.1) ------------------------


class TestSourceRegistry:
    def test_one_url_reached_by_both_runs_is_a_single_shared_source(self):
        registry = build_registry(two_runs())

        assert registry.count == 3
        assert registry.runs_for(1) == [1, 2]
        assert len(registry.shared()) == 1

    def test_unique_counts_are_per_run(self):
        registry = build_registry(two_runs())

        assert [e.number for e in registry.unique_to(1)] == [2]
        assert [e.number for e in registry.unique_to(2)] == [3]

    def test_overlap_stats_come_from_the_same_registry(self):
        runs = two_runs()
        registry = build_registry(runs)

        stats = registry.overlap_stats(runs)

        assert stats["total_sources"] == registry.count
        assert stats["shared_sources"] == len(registry.shared())
        assert stats["unique_per_run"]["run-1"] == len(registry.unique_to(1))

    def test_legacy_helpers_delegate_to_the_registry(self):
        runs = two_runs()
        sources = build_comparison_sources(runs)

        assert len(sources) == build_registry(runs).count
        assert overlap_stats(runs, sources) == build_registry(runs).overlap_stats(runs)
        assert sources[0].run_ids == ["run-1", "run-2"]

    def test_source_ownership_is_stated_in_the_prompt(self):
        runs = two_runs()
        for index, run in enumerate(runs):
            run.evidence = [
                type("E", (), {"source": s, "content": f"evidence {index}"})()
                for s in run.selected_sources
            ]

        block = build_evidence_block(
            build_registry(runs), runs, lambda ev, n: list(ev)[:n], 8, 600
        )

        assert "SOURCE 1\nRUNS: 1, 2" in block
        assert "SOURCE 2\nRUNS: 1" in block
        assert "SOURCE 3\nRUNS: 2" in block


# -- 1. agreements must actually be agreements --------------------------------


class TestAgreementSemantics:
    def test_an_agreement_backed_by_both_runs_is_accepted(self):
        assert checked(valid()).agreements[0].runs == [1, 2]

    def test_a_shared_source_can_support_both_runs(self):
        """Source 1 was genuinely collected by both, so one citation suffices."""
        result = checked(valid(agreements=[agreement(runs=[1, 2], citations=[1])]))

        assert result.agreements[0].citations == [1]

    def test_an_agreement_attributed_only_to_run_1_is_rejected(self):
        """The exact defect seen in the real V2 output."""
        with pytest.raises(ComparisonError, match="only run 1"):
            checked(valid(agreements=[agreement(runs=[1], citations=[2])]))

    def test_an_agreement_attributed_only_to_run_2_is_rejected(self):
        with pytest.raises(ComparisonError, match="only run 2"):
            checked(valid(agreements=[agreement(runs=[2], citations=[3])]))

    def test_an_agreement_citing_only_one_runs_evidence_is_rejected(self):
        """Claims both runs agree, but only run 1's evidence is cited."""
        with pytest.raises(ComparisonError, match="run 2 agrees"):
            checked(valid(agreements=[agreement(runs=[1, 2], citations=[2])]))

    def test_evidence_from_each_run_separately_is_accepted(self):
        result = checked(valid(agreements=[agreement(runs=[1, 2], citations=[2, 3])]))

        assert result.agreements[0].citations == [2, 3]

    def test_a_missing_run_list_is_read_off_the_evidence(self):
        result = checked(valid(agreements=[agreement(runs=[], citations=[2, 3])]))

        assert result.agreements[0].runs == [1, 2]

    def test_a_single_run_finding_cannot_sneak_in_via_a_missing_run_list(self):
        with pytest.raises(ComparisonError, match="only run 1"):
            checked(valid(agreements=[agreement(runs=[], citations=[2])]))

    def test_the_rendered_agreement_names_the_participating_runs(self):
        report = render(valid())

        assert "- Run 1 and Run 2: Both runs find the barrier is cost. [1]" in report

    def test_no_agreements_is_stated_rather_than_implied(self):
        report = render(valid(agreements=[], conclusion=Conclusion(
            text="Only run 1 contributed.", based_on=["U1"])))

        assert "No finding was supported by more than one" in report


# -- 2. contradictions must have two grounded sides ---------------------------


def contradiction(**kw) -> Contradiction:
    return Contradiction(**{
        "id": "C1",
        "topic": "Timeline to mass production",
        "positions": [
            ContradictionPosition(
                runs=[1], text="Run 1 puts it before 2027.", citations=[2]
            ),
            ContradictionPosition(
                runs=[2], text="Run 2 puts it after 2030.", citations=[3]
            ),
        ],
        **kw,
    })


class TestContradictionSemantics:
    def test_two_grounded_opposing_sides_are_accepted(self):
        result = checked(valid(
            contradictions=[contradiction()],
            conclusion=Conclusion(text="They disagree on timing.", based_on=["C1"]),
        ))

        assert len(result.contradictions[0].positions) == 2

    def test_a_one_sided_contradiction_is_rejected(self):
        one_sided = contradiction(positions=[ContradictionPosition(
            runs=[1], text="Run 1 says 2027.", citations=[2]
        )])

        with pytest.raises(ComparisonError, match="at least two opposing positions"):
            checked(valid(contradictions=[one_sided],
                          conclusion=Conclusion(text="x", based_on=["C1"])))

    def test_both_sides_held_by_the_same_run_is_rejected(self):
        same_run = contradiction(positions=[
            ContradictionPosition(runs=[1], text="A.", citations=[2]),
            ContradictionPosition(runs=[1], text="B.", citations=[2]),
        ])

        with pytest.raises(ComparisonError, match="between different runs"):
            checked(valid(contradictions=[same_run],
                          conclusion=Conclusion(text="x", based_on=["C1"])))

    def test_a_side_citing_the_wrong_runs_evidence_is_rejected(self):
        wrong = contradiction(positions=[
            ContradictionPosition(runs=[1], text="A.", citations=[3]),  # run 2's source
            ContradictionPosition(runs=[2], text="B.", citations=[3]),
        ])

        with pytest.raises(ComparisonError, match="attributed to run 1"):
            checked(valid(contradictions=[wrong],
                          conclusion=Conclusion(text="x", based_on=["C1"])))

    def test_a_side_with_no_evidence_is_rejected(self):
        unsupported = contradiction(positions=[
            ContradictionPosition(runs=[1], text="A.", citations=[2]),
            ContradictionPosition(runs=[2], text="B.", citations=[]),
        ])

        with pytest.raises(ComparisonError, match="cites no sources"):
            checked(valid(contradictions=[unsupported],
                          conclusion=Conclusion(text="x", based_on=["C1"])))

    def test_no_contradiction_is_stated_plainly_not_invented(self):
        report = render(valid(contradictions=[]))

        assert "No direct contradiction was identified" in report

    def test_both_sides_render_under_the_topic(self):
        report = render(valid(
            contradictions=[contradiction()],
            conclusion=Conclusion(text="They disagree.", based_on=["C1"]),
        ))

        assert "- **Timeline to mass production**" in report
        assert "  - Run 1: Run 1 puts it before 2027. [2]" in report
        assert "  - Run 2: Run 2 puts it after 2030. [3]" in report


# -- 3. unique evidence must actually be unique --------------------------------


class TestUniqueEvidenceSemantics:
    def test_a_source_only_that_run_collected_is_accepted(self):
        assert checked(valid()).unique_evidence[0].run == 1

    def test_citing_another_runs_source_is_rejected(self):
        with pytest.raises(ComparisonError, match="did not collect it"):
            checked(valid(unique_evidence=[unique(run=1, citations=[3])]))

    def test_citing_a_shared_source_is_not_unique(self):
        with pytest.raises(ComparisonError, match="not unique"):
            checked(valid(unique_evidence=[unique(run=1, citations=[1])]))

    def test_an_unknown_run_is_rejected(self):
        with pytest.raises(ComparisonError, match="run 5"):
            checked(valid(unique_evidence=[unique(run=5, citations=[2])]))

    def test_absent_unique_evidence_is_stated_rather_than_fabricated(self):
        report = render(valid(unique_evidence=[], conclusion=Conclusion(
            text="They agree on cost.", based_on=["A1"])))

        assert "Neither run contributed evidence the other did not also reach." in report


# -- 4. the conclusion must be grounded in the validated body ------------------


class TestConclusionGrounding:
    def test_a_conclusion_referencing_real_points_is_accepted(self):
        assert checked(valid()).conclusion.based_on == ["A1", "U1"]

    def test_a_stale_reference_is_dropped_when_real_ones_remain(self):
        """An id naming no point adds no citation and removes no claim, so it is
        dropped rather than failing a comparison that is otherwise sound. The
        real model does this: it referenced "C1" having returned no
        contradictions."""
        result = checked(valid(conclusion=Conclusion(
            text="Cost is the barrier.", based_on=["A1", "C1"]
        )))

        assert result.conclusion.based_on == ["A1"]
        # The dropped id contributes nothing to the citations either.
        assert conclusion_citations(result) == [1]

    def test_a_conclusion_referencing_only_nonexistent_points_is_rejected(self):
        """Dropping every reference would leave the conclusion ungrounded."""
        with pytest.raises(ComparisonError, match="does not reference any"):
            checked(valid(conclusion=Conclusion(text="x", based_on=["C1", "C2"])))

    def test_a_conclusion_grounded_in_nothing_is_rejected(self):
        """The real V2 failure: a new primary finding appearing only at the end."""
        with pytest.raises(ComparisonError, match="does not reference any"):
            checked(valid(conclusion=Conclusion(
                text="Interfacial stability is the primary obstacle across both runs.",
                based_on=[],
            )))

    def test_an_unsupported_claim_cannot_acquire_citations_of_its_own(self):
        """Conclusion citations are derived from referenced points, never invented."""
        result = checked(valid(conclusion=Conclusion(text="Cost.", based_on=["A1"])))

        assert conclusion_citations(result) == [1]

    def test_conclusion_citations_follow_the_referenced_points(self):
        result = checked(valid(conclusion=Conclusion(
            text="Cost and the pilot line.", based_on=["A1", "U1"]
        )))

        assert conclusion_citations(result) == [1, 2]

    def test_a_missing_conclusion_is_rejected(self):
        with pytest.raises(ComparisonError, match="no conclusion"):
            checked(valid(conclusion=Conclusion(text="   ", based_on=["A1"])))

    def test_the_rendered_conclusion_carries_its_derived_citations(self):
        report = render(valid())
        conclusion = report.split("## Conclusion")[1].split("##")[0]

        assert "Cost is the shared barrier. [1][2]" in conclusion


# -- 5. the overview must be substantive ---------------------------------------


class TestOverviewSemantics:
    @pytest.mark.parametrize("metadata", [
        "Both runs asked the same question with identical templates.",
        "The runs share the same completion date and the same mode.",
        "Both runs were completed on the same date, so they are comparable.",
    ])
    def test_a_metadata_overview_is_rejected(self, metadata):
        with pytest.raises(ComparisonError, match="how the runs were set up"):
            checked(valid(overview=metadata))

    def test_an_overview_about_findings_is_accepted(self):
        result = checked(valid(
            overview="Both runs converge on cost, but Run 2 adds manufacturing evidence."
        ))

        assert "converge on cost" in result.overview

    def test_the_prompt_forbids_metadata_overviews(self):
        from src.prompts.research import COMPARISON_SYSTEM

        lowered = COMPARISON_SYSTEM.lower()
        assert "never mention dates, templates, modes" in lowered
        assert "how the runs findings relate" in lowered


# -- 6/7. cited vs collected ---------------------------------------------------


class TestCitedSources:
    def test_a_source_behind_the_conclusion_counts_as_cited(self):
        """The real defect: source 5 carried the conclusion yet read
        "(collected, not cited)"."""
        result = checked(valid())

        assert conclusion_citations(result) <= sorted(cited_numbers(result))
        assert 1 in cited_numbers(result) and 2 in cited_numbers(result)

    def test_an_unused_source_stays_marked_collected_not_cited(self):
        report = render(valid(unique_evidence=[], conclusion=Conclusion(
            text="They agree on cost.", based_on=["A1"])))

        # Source 1 carries the only point; 2 and 3 are unused.
        assert "(collected, not cited)" in report
        lines = [line for line in report.splitlines() if line.startswith("1. ")]
        assert lines and "collected, not cited" not in lines[0]

    def test_every_rendered_citation_appears_in_the_sources_list(self):
        report = render(valid())
        body, sources = report.split("## Sources")

        import re

        for number in {int(n) for n in re.findall(r"\[(\d+)\]", body)}:
            assert f"\n{number}. " in sources


# -- rendering and structure ---------------------------------------------------


class TestRendering:
    def test_every_required_section_is_present_in_order(self):
        report = render(valid())

        expected = [
            "# Comparison: Test", "## Overview", "## Agreements",
            "## Contradictions", "## New or Unique Evidence", "## Conclusion",
            "## Source Differences", "## Sources",
        ]
        positions = [report.index(heading) for heading in expected]
        assert positions == sorted(positions)

    def test_source_differences_match_the_registry(self):
        report = render(valid())

        assert "- Combined unique sources: 3" in report
        assert "- Shared across runs: 1" in report
        assert "- Unique to Run 1: 1" in report
        assert "- Unique to Run 2: 1" in report

    def test_sources_section_is_rendered_once_with_real_urls(self):
        report = render(valid())

        assert report.count("## Sources") == 1
        assert SHARED in report and ONLY1 in report and ONLY2 in report

    def test_the_report_opens_with_comparison_content(self):
        report = render(valid())

        for narration in ("We are comparing", "Let me", "We need", "Now we", "I will"):
            assert narration not in report
        assert report.split("## Overview")[1].strip().startswith("The runs converge")

    def test_rendering_is_deterministic(self):
        assert render(valid()) == render(valid())


class TestSchemaShape:
    def test_the_schema_leaves_no_field_for_narration(self):
        assert set(ComparisonSynthesis.model_fields) == {
            "overview", "agreements", "contradictions",
            "unique_evidence", "conclusion",
        }

    def test_the_conclusion_must_declare_what_it_rests_on(self):
        assert set(Conclusion.model_fields) == {"text", "based_on"}

    def test_a_contradiction_is_structurally_two_sided(self):
        assert set(Contradiction.model_fields) == {"id", "topic", "positions"}


# -- the model echoing its own schema back as content -------------------------


class TestInstructionEcho:
    """A real V2.1 run filled every field with that field's own description.

    Structurally it was flawless -- ids, runs, citations and attribution all
    validated -- so only the content could give it away.
    """

    @pytest.mark.parametrize("echo", [
        "2-3 sentences on how the runs FINDINGS relate - where they converge.",
        "One specific sentence about the subject matter",
        "Never mention dates, templates, modes, or that the questions match.",
    ])
    def test_an_echoed_instruction_is_rejected_wherever_it_appears(self, echo):
        with pytest.raises(ComparisonError, match="repeats the instructions"):
            checked(valid(overview=echo))

    def test_an_echoed_agreement_is_rejected(self):
        with pytest.raises(ComparisonError, match="repeats the instructions"):
            checked(valid(agreements=[agreement(
                text="One specific sentence about the subject matter"
            )]))

    def test_an_echoed_conclusion_is_rejected(self):
        with pytest.raises(ComparisonError, match="repeats the instructions"):
            checked(valid(conclusion=Conclusion(
                text="2-3 sentences summarising ONLY what the points above establish.",
                based_on=["A1"],
            )))

    def test_real_findings_are_not_mistaken_for_instructions(self):
        """The guard must not reject legitimate research prose."""
        for text in [
            "Both runs identify interface stability as the main barrier.",
            "Run 2 found a pilot line targeting 2027 operation.",
            "The runs converge on cost but differ on the production timeline.",
        ]:
            assert not _looks_like_instructions(text)

    def test_schema_descriptions_stay_terse(self):
        """Long descriptions end up in the grammar and get echoed back."""
        for model in (ComparisonSynthesis, ComparisonPoint, Conclusion,
                      Contradiction, ContradictionPosition, UniqueEvidencePoint):
            for name, info in model.model_fields.items():
                if info.description:
                    assert len(info.description) <= 24, (
                        f"{model.__name__}.{name} description is long enough to echo"
                    )

    def test_the_guard_tracks_the_schema_automatically(self):
        """Derived from the models, so it cannot drift away from them."""
        for model in (ComparisonSynthesis, ComparisonPoint, Conclusion):
            for info in model.model_fields.values():
                if info.description:
                    assert _looks_like_instructions(info.description)
