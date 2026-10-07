"""Feature 4: report templates and regeneration."""

import pytest

from src.models.research import CriticDecision
from src.models.runs import RunStatus
from src.services.research_service import InvalidRunStateError
from src.templates import TemplateError, TemplateId, list_templates, resolve_template
from tests.conftest import FakeLLM, make_critique, make_plan, make_search_fn
from tests.conftest_v2 import WEB_RESULTS, make_container

ALL_STRUCTURED = [t for t in TemplateId if t is not TemplateId.CUSTOM]


class TestTemplateRegistry:
    @pytest.mark.parametrize("template_id", [t.value for t in ALL_STRUCTURED])
    def test_every_template_resolves_with_structure(self, template_id):
        resolved_id, structure = resolve_template(template_id)
        assert resolved_id == template_id
        assert len(structure) > 40

    def test_academic_sections(self):
        _, structure = resolve_template("ACADEMIC")
        for section in ("Abstract", "Background", "Findings", "Limitations"):
            assert section in structure

    def test_case_insensitive_and_default(self):
        assert resolve_template("executive")[0] == "EXECUTIVE"
        assert resolve_template("")[0] == "STANDARD"

    def test_unknown_template_rejected(self):
        with pytest.raises(TemplateError, match="Unknown template"):
            resolve_template("HAIKU")

    def test_custom_requires_instructions(self):
        with pytest.raises(TemplateError, match="requires instructions"):
            resolve_template("CUSTOM", "")

    def test_custom_size_cap(self):
        with pytest.raises(TemplateError, match="exceed"):
            resolve_template("CUSTOM", "x" * 5000)

    def test_custom_instructions_marked_as_preferences_only(self):
        _, structure = resolve_template("CUSTOM", "Use pirate voice sections")
        assert "cannot change citation rules" in structure
        assert "Use pirate voice sections" in structure

    def test_list_templates_includes_all(self):
        ids = {t["id"] for t in list_templates()}
        assert ids == {t.value for t in TemplateId}


class TestTemplateRuns:
    @pytest.mark.parametrize("template_id", ["ACADEMIC", "EXECUTIVE", "COMPARISON"])
    def test_run_with_template_persists_and_keeps_citations(self, tmp_path, template_id):
        llm = FakeLLM(
            plans=[make_plan()],
            critiques=[make_critique(CriticDecision.SYNTHESIZE, score=9)],
            synthesis="## Summary\n\nFinding [1]. Another [2].",
        )
        c = make_container(tmp_path, llm=llm)
        run = c.research_service.create_run("q", template=template_id)
        final = c.research_service.get_run(run.id)
        assert final.status is RunStatus.COMPLETED
        assert final.template == template_id
        assert "[1]" in final.final_report
        assert final.final_report.count("## Sources") == 1
        # Structure instructions reached the synthesis prompt.
        synthesis_calls = [c_ for c_ in llm.invoke_calls]
        assert any("REPORT STRUCTURE" in str(call) for call in synthesis_calls)

    def test_invalid_template_rejected_at_creation(self, tmp_path):
        c = make_container(tmp_path)
        with pytest.raises(TemplateError):
            c.research_service.create_run("q", template="NOT_A_TEMPLATE")

    def test_template_recorded_in_history_listing(self, tmp_path):
        c = make_container(tmp_path)
        c.research_service.create_run("q", template="EXECUTIVE")
        rows, _ = c.runs_repo.list()
        assert rows[0].template == "EXECUTIVE"


class TestRegeneration:
    def _completed(self, tmp_path):
        llm = FakeLLM(
            plans=[make_plan()],
            critiques=[make_critique(CriticDecision.SYNTHESIZE, score=9)],
            synthesis="Original body [1][2].",
        )
        search = make_search_fn(default=WEB_RESULTS)
        c = make_container(tmp_path, llm=llm, search_fn=search)
        run = c.research_service.create_run("q")
        return c, c.research_service.get_run(run.id), search, llm

    def test_regenerates_without_new_research(self, tmp_path):
        c, run, search, llm = self._completed(tmp_path)
        calls_before = len(search.calls)
        llm._syntheses = ["## Abstract\n\nRegenerated body [1]."]
        new_run = c.research_service.regenerate_report(run.id, "ACADEMIC")
        final = c.research_service.get_run(new_run.id)
        assert final.status is RunStatus.COMPLETED
        assert final.template == "ACADEMIC"
        assert final.regenerated_from == run.id  # linked to evidence source
        assert "Regenerated body [1]" in final.final_report
        assert len(search.calls) == calls_before  # NO new web research
        assert len(final.evidence) == len(run.evidence)
        # Citation integrity holds for the regenerated report too.
        assert final.evaluation is not None and final.evaluation.citations_valid

    def test_regeneration_requires_completed_run(self, tmp_path):
        c = make_container(tmp_path)
        run = c.research_service.create_run("q", approval_required=True)
        with pytest.raises(InvalidRunStateError):
            c.research_service.regenerate_report(run.id, "ACADEMIC")

    def test_regeneration_validates_template(self, tmp_path):
        c, run, _, _ = self._completed(tmp_path)
        with pytest.raises(TemplateError):
            c.research_service.regenerate_report(run.id, "BOGUS")

    def test_custom_regeneration(self, tmp_path):
        c, run, _, llm = self._completed(tmp_path)
        llm._syntheses = ["Custom shaped [2]."]
        new_run = c.research_service.regenerate_report(
            run.id, "CUSTOM", "Two short sections please"
        )
        final = c.research_service.get_run(new_run.id)
        assert final.custom_template == "Two short sections please"
        assert final.template == "CUSTOM"
