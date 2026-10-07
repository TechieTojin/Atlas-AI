"""FastAPI endpoint tests, including SSE streaming and uploads (no network)."""

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.models.runs import RunStatus
from tests.conftest import FakeLLM, make_critique, make_plan
from src.models.research import CriticDecision
from tests.conftest_v2 import make_container


@pytest.fixture
def client(tmp_path):
    container = make_container(tmp_path)
    app = create_app(container)
    with TestClient(app) as test_client:
        test_client.container = container
        yield test_client


class TestHealth:
    def test_health(self, client):
        response = client.get("/api/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["database"] == "ok"


class TestRunsApi:
    def test_create_and_get_run(self, client):
        response = client.post("/api/runs", json={"query": "What is X?", "mode": "FAST"})
        assert response.status_code == 201
        run_id = response.json()["id"]

        detail = client.get(f"/api/runs/{run_id}").json()
        assert detail["status"] == "COMPLETED"
        assert detail["mode"] == "FAST"
        assert "Findings [1] and [2]." in detail["final_report"]
        assert len(detail["sources"]) == 2
        assert detail["sources"][0]["url"] == "https://a.com/1"
        assert detail["evidence"]
        assert detail["metrics"]["sources_cited"] == 2

    def test_list_runs_pagination(self, client):
        for i in range(3):
            client.post("/api/runs", json={"query": f"query number {i}"})
        body = client.get("/api/runs?limit=2").json()
        assert body["total"] == 3
        assert len(body["runs"]) == 2

    def test_get_missing_run_404(self, client):
        assert client.get("/api/runs/does-not-exist").status_code == 404

    def test_delete_run(self, client):
        run_id = client.post("/api/runs", json={"query": "q"}).json()["id"]
        assert client.delete(f"/api/runs/{run_id}").status_code == 204
        assert client.get(f"/api/runs/{run_id}").status_code == 404

    def test_invalid_body_422(self, client):
        assert client.post("/api/runs", json={"query": ""}).status_code == 422
        assert client.post("/api/runs", json={}).status_code == 422

    def test_metrics_endpoint(self, client):
        run_id = client.post("/api/runs", json={"query": "q"}).json()["id"]
        body = client.get(f"/api/runs/{run_id}/metrics").json()
        assert body["metrics"]["sources_collected"] == 2
        assert body["evaluation"]["passed"] is True

    def test_export_markdown(self, client):
        run_id = client.post("/api/runs", json={"query": "exportable"}).json()["id"]
        response = client.get(f"/api/runs/{run_id}/export")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/markdown")
        assert "attachment" in response.headers["content-disposition"]
        assert "# Atlas Research Report" in response.text

    def test_export_incomplete_409(self, client):
        run_id = client.post(
            "/api/runs", json={"query": "q", "approval_required": True}
        ).json()["id"]
        assert client.get(f"/api/runs/{run_id}/export").status_code == 409


class TestApprovalApi:
    def test_approve_flow(self, client):
        run_id = client.post(
            "/api/runs", json={"query": "q", "approval_required": True}
        ).json()["id"]
        detail = client.get(f"/api/runs/{run_id}").json()
        assert detail["status"] == "AWAITING_APPROVAL"
        assert detail["plan"]["subquestions"]

        response = client.post(f"/api/runs/{run_id}/plan/approve")
        assert response.status_code == 200
        assert client.get(f"/api/runs/{run_id}").json()["status"] == "COMPLETED"

    def test_edit_flow_and_validation(self, client):
        run_id = client.post(
            "/api/runs", json={"query": "q", "approval_required": True}
        ).json()["id"]
        bad = client.post(
            f"/api/runs/{run_id}/plan/edit", json={"search_queries": ["", " "]}
        )
        assert bad.status_code == 422
        good = client.post(
            f"/api/runs/{run_id}/plan/edit", json={"search_queries": ["new query"]}
        )
        assert good.status_code == 200
        assert good.json()["plan"]["search_queries"] == ["new query"]

    def test_approve_completed_run_409(self, client):
        run_id = client.post("/api/runs", json={"query": "q"}).json()["id"]
        assert client.post(f"/api/runs/{run_id}/plan/approve").status_code == 409

    def test_cancel_awaiting_run(self, client):
        run_id = client.post(
            "/api/runs", json={"query": "q", "approval_required": True}
        ).json()["id"]
        response = client.post(f"/api/runs/{run_id}/cancel")
        assert response.status_code == 200
        assert response.json()["status"] == "CANCELLED"


class TestSse:
    def test_event_stream_replays_and_terminates(self, client):
        run_id = client.post("/api/runs", json={"query": "q"}).json()["id"]
        with client.stream("GET", f"/api/runs/{run_id}/events") as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            body = "".join(response.iter_text())
        assert "event: RUN_STARTED" in body
        assert "event: PLAN_CREATED" in body
        assert "event: RUN_COMPLETED" in body
        assert body.index("RUN_STARTED") < body.index("RUN_COMPLETED")
        assert "data: {" in body
        assert "<think>" not in body

    def test_stream_unknown_run_404(self, client):
        assert client.get("/api/runs/missing/events").status_code == 404


class TestDocumentsApi:
    def test_upload_list_get_delete(self, client):
        response = client.post(
            "/api/documents",
            files={"file": ("notes.txt", b"useful research text " * 30, "text/plain")},
        )
        assert response.status_code == 201
        doc = response.json()
        assert doc["status"] == "READY"
        assert doc["chunk_count"] >= 1

        listing = client.get("/api/documents").json()
        assert len(listing["documents"]) == 1

        assert client.get(f"/api/documents/{doc['id']}").status_code == 200
        assert client.delete(f"/api/documents/{doc['id']}").status_code == 204
        assert client.get(f"/api/documents/{doc['id']}").status_code == 404

    def test_upload_invalid_type_400(self, client):
        response = client.post(
            "/api/documents",
            files={"file": ("evil.exe", b"MZ", "application/octet-stream")},
        )
        assert response.status_code == 400
        assert "Unsupported" in response.json()["detail"]

    def test_run_with_documents_scope(self, client):
        doc = client.post(
            "/api/documents",
            files={"file": ("ctx.txt", b"domain specific knowledge " * 30, "text/plain")},
        ).json()
        response = client.post(
            "/api/runs",
            json={
                "query": "q",
                "source_scope": "WEB_AND_DOCUMENTS",
                "document_ids": [doc["id"]],
            },
        )
        assert response.status_code == 201
        detail = client.get(f"/api/runs/{response.json()['id']}").json()
        assert detail["status"] == "COMPLETED"
        assert detail["metrics"]["document_chunks_retrieved"] > 0

    def test_documents_scope_without_ids_422(self, client):
        response = client.post(
            "/api/runs", json={"query": "q", "source_scope": "DOCUMENTS"}
        )
        assert response.status_code == 422
