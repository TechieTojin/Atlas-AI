"""Research memory integration and deterministic evaluation tests."""

from src.evaluation import evaluate_report
from src.models.research import CriticDecision, EvidenceOrigin, Source
from src.models.runs import RunMode
from tests.conftest import FakeLLM, make_critique, make_plan, make_search_fn
from tests.conftest_v2 import WEB_RESULTS, make_container


class TestMemoryReuse:
    def test_second_run_reuses_memory_and_skips_search(self, tmp_path):
        plan = make_plan(n_queries=1)  # single query "av barriers query 0"
        search = make_search_fn(default=WEB_RESULTS[:2])

        def fresh_llm():
            return FakeLLM(
                plans=[make_plan(n_queries=1)],
                critiques=[make_critique(CriticDecision.SYNTHESIZE, score=9)],
            )

        c = make_container(tmp_path, llm=fresh_llm(), search_fn=search,
                           search_results_per_query=2)
        first = c.research_service.create_run("q one")
        assert c.research_service.get_run(first.id).metrics.memory_hits == 0
        first_calls = len(search.calls)

        # New service/LLM, same container DB: memory satisfies the query fully.
        c2 = make_container(tmp_path, llm=fresh_llm(), search_fn=search,
                            search_results_per_query=2)
        # Share the same database for memory continuity.
        c2.research_service._memory = c.memory_service
        second = c2.research_service.create_run("q two")
        final = c2.research_service.get_run(second.id)
        assert final.metrics.memory_hits == 2
        assert len(search.calls) == first_calls  # no new web search
        # Provenance preserved: memory evidence keeps its original web source.
        memory_items = [
            e for e in final.evidence if e.origin is EvidenceOrigin.MEMORY
        ]
        assert memory_items
        assert memory_items[0].source.url.startswith("https://")

    def test_memory_and_fresh_search_deduplicate(self, tmp_path):
        search = make_search_fn(default=WEB_RESULTS)
        llm = FakeLLM(
            plans=[make_plan(n_queries=1)],
            critiques=[make_critique(CriticDecision.SYNTHESIZE, score=9)],
        )
        c = make_container(tmp_path, llm=llm, search_fn=search,
                           search_results_per_query=5)
        # Preload memory with one of the two web results.
        from tests.conftest import make_evidence

        c.memory_service.remember(
            "av barriers query 0", [make_evidence("https://a.com/1", title="A1")]
        )
        run = c.research_service.create_run("q")
        final = c.research_service.get_run(run.id)
        urls = [e.source.normalized_url for e in final.evidence]
        assert len(urls) == len(set(urls))  # no duplicate despite overlap
        assert final.metrics.memory_hits == 1


class TestEvaluation:
    SOURCES = [
        Source(title="A", url="https://a.com/1", domain="a.com"),
        Source(
            title="doc, p. 2",
            url="doc://d1#p2",
            domain="document",
            kind="document",
            document_id="d1",
            filename="doc.pdf",
            page=2,
        ),
    ]

    def test_good_report_passes(self):
        report = "Claim [1]. Doc claim [2].\n\n## Sources\n\n1. x\n2. y"
        result = evaluate_report(report, self.SOURCES)
        assert result.passed
        assert result.citation_coverage == 1.0
        assert result.provenance_valid

    def test_missing_citations_fails(self):
        result = evaluate_report("No cites.\n\n## Sources\n\n1. x", self.SOURCES)
        assert not result.has_citations
        assert not result.passed

    def test_invalid_citation_detected(self):
        report = "Claim [9].\n\n## Sources\n\n1. x"
        result = evaluate_report(report, self.SOURCES)
        assert not result.citations_valid

    def test_reasoning_marker_detected(self):
        report = "</think>Claim [1].\n\n## Sources\n\n1. x"
        result = evaluate_report(report, self.SOURCES)
        assert not result.no_reasoning_markers
        assert not result.passed

    def test_multiple_sources_sections_detected(self):
        report = "Claim [1].\n\n## Sources\n\n1. x\n\n## Sources\n\n1. y"
        assert not evaluate_report(report, self.SOURCES).single_sources_section

    def test_bad_provenance_detected(self):
        bad = [Source(title="X", url="javascript:alert(1)", domain="")]
        result = evaluate_report("C [1].\n\n## Sources\n\n1. x", bad)
        assert not result.provenance_valid


class TestMixedOriginCitations:
    def test_document_sources_render_without_urls(self, tmp_path):
        c = make_container(tmp_path)
        doc = c.document_service.ingest(
            "av_safety.pdf.txt".replace(".pdf", ""),  # plain txt upload
            b"LiDAR degradation in rain is a major technical barrier. " * 15,
        )
        from src.models.runs import SourceScope

        run = c.research_service.create_run(
            "q",
            source_scope=SourceScope.WEB_AND_DOCUMENTS,
            document_ids=[doc.id],
        )
        final = c.research_service.get_run(run.id)
        assert final.status.value == "COMPLETED"
        origins = {e.origin.value for e in final.evidence}
        assert "document" in origins and "web" in origins
        # Document source rendered as [Document: filename] with no doc:// link.
        assert "[Document: av_safety.txt" in final.final_report
        assert "doc://" not in final.final_report.split("## Sources")[1].split("\n")[0]
        assert final.metrics.document_chunks_retrieved > 0
