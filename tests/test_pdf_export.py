"""Feature 8: PDF export."""

from src.export.pdf import render_run_pdf, safe_pdf_filename
from src.models.research import CriticDecision
from src.models.runs import ResearchRun, RunStatus, utcnow
from tests.conftest import FakeLLM, make_critique, make_plan
from tests.conftest_v2 import make_container


def completed_run(report: str) -> ResearchRun:
    run = ResearchRun(query="Why thermal runaway?", status=RunStatus.COMPLETED)
    run.started_at = utcnow()
    run.completed_at = utcnow()
    run.final_report = report
    run.metrics.total_ms = 12_000
    run.metrics.sources_selected = 2
    run.metrics.sources_cited = 2
    run.metrics.citation_coverage = 1.0
    run.metrics.source_quality_tiers = {"high": 1, "low": 1}
    return run


def pdf_text_contains(pdf_bytes: bytes, needle: str) -> bool:
    """Extract text from the generated PDF and search it."""
    import io

    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf_bytes))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    return needle in text


REPORT = """\
## Summary

Thermal runaway cascades [1]. See [details](https://a.com/1) for more [2].

- Separator failure matters [1].
- Costs are falling.

| Metric | Value |
| --- | --- |
| Peak temp | 800C |

## Sources

1. [A](https://a.com/1)
2. [B](https://b.com/2)
"""


class TestPdfRendering:
    def test_valid_pdf_with_content(self):
        pdf = render_run_pdf(completed_run(REPORT))
        assert pdf[:5] == b"%PDF-"
        assert len(pdf) > 1500
        assert pdf_text_contains(pdf, "Why thermal runaway?")
        assert pdf_text_contains(pdf, "Thermal runaway cascades [1]")
        assert pdf_text_contains(pdf, "https://a.com/1")  # sources listed
        assert pdf_text_contains(pdf, "Run Metrics")
        assert pdf_text_contains(pdf, "Citation coverage: 100%")

    def test_links_flattened_and_table_rendered(self):
        pdf = render_run_pdf(completed_run(REPORT))
        assert pdf_text_contains(pdf, "details (https://a.com/1)")
        assert pdf_text_contains(pdf, "Peak temp")

    def test_unicode_handled(self):
        report = "## Résumé\n\nTempérature ≥ 150 °C déclenche l'emballement [1].\n\n## Sources\n\n1. x"
        pdf = render_run_pdf(completed_run(report))
        assert pdf[:5] == b"%PDF-"
        assert pdf_text_contains(pdf, "150")

    def test_long_report_paginates(self):
        report = "## Long\n\n" + ("A sentence of filler content here [1]. " * 600)
        pdf = render_run_pdf(completed_run(report))
        import io
        from pypdf import PdfReader

        assert len(PdfReader(io.BytesIO(pdf)).pages) > 1

    def test_malicious_html_treated_as_text(self):
        report = (
            "## X\n\n<script>alert(1)</script> and "
            "<img src=x onerror=steal()> [1].\n\n## Sources\n\n1. x"
        )
        pdf = render_run_pdf(completed_run(report))
        # Rendered as literal text; no HTML interpretation path exists.
        assert pdf_text_contains(pdf, "<script>alert(1)</script>")

    def test_safe_filename(self):
        run = completed_run(REPORT)
        run.query = 'Weird/\\name: "quotes" <tags>?'
        name = safe_pdf_filename(run)
        assert name.endswith(".pdf")
        assert all(ch not in name for ch in '/\\:"<>?')


class TestPdfApi:
    def _client(self, tmp_path):
        from fastapi.testclient import TestClient
        from src.api.app import create_app

        llm = FakeLLM(
            plans=[make_plan()],
            critiques=[make_critique(CriticDecision.SYNTHESIZE, score=9)],
            synthesis="Body [1][2].",
        )
        c = make_container(tmp_path, llm=llm)
        return TestClient(create_app(c))

    def test_pdf_endpoint(self, tmp_path):
        with self._client(tmp_path) as client:
            run_id = client.post("/api/runs", json={"query": "q"}).json()["id"]
            response = client.get(f"/api/runs/{run_id}/export?format=pdf")
            assert response.status_code == 200
            assert response.headers["content-type"] == "application/pdf"
            assert "attachment" in response.headers["content-disposition"]
            assert response.content[:5] == b"%PDF-"

    def test_markdown_still_works(self, tmp_path):
        with self._client(tmp_path) as client:
            run_id = client.post("/api/runs", json={"query": "q"}).json()["id"]
            assert client.get(
                f"/api/runs/{run_id}/export?format=markdown"
            ).status_code == 200

    def test_unknown_format_400(self, tmp_path):
        with self._client(tmp_path) as client:
            run_id = client.post("/api/runs", json={"query": "q"}).json()["id"]
            assert client.get(
                f"/api/runs/{run_id}/export?format=docx"
            ).status_code == 400

    def test_incomplete_run_409_and_missing_404(self, tmp_path):
        with self._client(tmp_path) as client:
            pending = client.post(
                "/api/runs", json={"query": "q", "approval_required": True}
            ).json()["id"]
            assert client.get(
                f"/api/runs/{pending}/export?format=pdf"
            ).status_code == 409
            assert client.get(
                "/api/runs/missing/export?format=pdf"
            ).status_code == 404
