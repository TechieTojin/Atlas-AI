"""Feature 7: projects / workspaces."""

import pytest

from src.models.workspace import Project
from src.services.research_service import PlanValidationError
from tests.conftest_v2 import make_container


def make_project(c, name="AV Research"):
    project = Project(name=name, description="desc")
    c.projects_repo.save(project)
    return project


class TestProjectCrud:
    def test_create_get_update_list(self, tmp_path):
        c = make_container(tmp_path)
        project = make_project(c)
        loaded = c.projects_repo.get(project.id)
        assert loaded.name == "AV Research"
        loaded.name = "Renamed"
        c.projects_repo.save(loaded)
        assert c.projects_repo.get(project.id).name == "Renamed"
        assert len(c.projects_repo.list()) == 1

    def test_counts(self, tmp_path):
        c = make_container(tmp_path)
        project = make_project(c)
        c.research_service.create_run("q1", project_id=project.id)
        doc = c.document_service.ingest("a.txt", b"text content " * 20)
        c.documents_repo.set_project(doc.id, project.id)
        counts = c.projects_repo.counts(project.id)
        assert counts["runs"] == 1
        assert counts["documents"] == 1

    def test_persistence_across_instances(self, tmp_path):
        path = str(tmp_path / "proj.db")
        c = make_container(tmp_path, db_path=path)
        project = make_project(c)
        c2 = make_container(tmp_path, db_path=path)
        assert c2.projects_repo.get(project.id) is not None


class TestRunAssociation:
    def test_run_created_inside_project(self, tmp_path):
        c = make_container(tmp_path)
        project = make_project(c)
        run = c.research_service.create_run("q", project_id=project.id)
        assert c.research_service.get_run(run.id).project_id == project.id
        rows, total = c.runs_repo.list(project_id=project.id)
        assert total == 1 and rows[0].id == run.id

    def test_unknown_project_rejected(self, tmp_path):
        c = make_container(tmp_path)
        with pytest.raises(PlanValidationError, match="Project not found"):
            c.research_service.create_run("q", project_id="nope")

    def test_isolation_between_projects(self, tmp_path):
        c = make_container(tmp_path)
        p1, p2 = make_project(c, "P1"), make_project(c, "P2")
        c.research_service.create_run("q1", project_id=p1.id)
        c.research_service.create_run("q2", project_id=p2.id)
        rows, total = c.runs_repo.list(project_id=p1.id)
        assert total == 1 and rows[0].query == "q1"

    def test_non_project_runs_remain_valid(self, tmp_path):
        c = make_container(tmp_path)
        run = c.research_service.create_run("global q")
        assert c.research_service.get_run(run.id).project_id == ""
        rows, total = c.runs_repo.list(project_id="")
        assert total == 1


class TestMemoryScoping:
    def test_project_memory_scoped(self, tmp_path):
        c = make_container(tmp_path, search_results_per_query=2)
        project = make_project(c)
        from tests.conftest import make_evidence

        c.memory_service.remember("q", [make_evidence("https://p.com/1")],
                                  project_id=project.id)
        assert c.memory_service.recall("q", 5) == []  # invisible globally
        assert len(c.memory_service.recall("q", 5, project_id=project.id)) == 1


class TestDeletion:
    def test_delete_detaches_without_destroying(self, tmp_path):
        c = make_container(tmp_path)
        project = make_project(c)
        run = c.research_service.create_run("q", project_id=project.id)
        doc = c.document_service.ingest("a.txt", b"text content " * 20)
        c.documents_repo.set_project(doc.id, project.id)
        from tests.conftest import make_evidence

        c.memory_service.remember("q", [make_evidence("https://p.com/1")],
                                  project_id=project.id)

        assert c.projects_repo.delete(project.id) is True
        # Runs and documents survive, detached to global scope.
        survived = c.research_service.get_run(run.id)
        assert survived.final_report  # data intact
        rows, _ = c.runs_repo.list(project_id="")
        assert any(r.id == run.id for r in rows)
        assert c.documents_repo.get(doc.id).project_id == ""
        # Project-scoped memory cache is removed.
        assert c.memory_service.recall("q", 5, project_id=project.id) == []

    def test_delete_missing_project(self, tmp_path):
        c = make_container(tmp_path)
        assert c.projects_repo.delete("nope") is False


class TestProjectApi:
    def test_project_endpoints(self, tmp_path):
        from fastapi.testclient import TestClient
        from src.api.app import create_app

        c = make_container(tmp_path)
        with TestClient(create_app(c)) as client:
            created = client.post(
                "/api/projects", json={"name": "P", "description": "d"}
            )
            assert created.status_code == 201
            pid = created.json()["id"]

            assert client.get("/api/projects").json()["projects"][0]["counts"] == {
                "runs": 0, "documents": 0, "comparisons": 0,
            }
            patched = client.patch(f"/api/projects/{pid}", json={"name": "P2"})
            assert patched.json()["name"] == "P2"

            run = client.post("/api/runs", json={"query": "q", "project_id": pid})
            assert run.status_code == 201
            assert run.json()["project_id"] == pid
            listing = client.get(f"/api/runs?project_id={pid}").json()
            assert listing["total"] == 1

            bad = client.post("/api/runs", json={"query": "q", "project_id": "nope"})
            assert bad.status_code == 422

            doc = client.post(
                "/api/documents",
                files={"file": ("x.txt", b"content words " * 20, "text/plain")},
            ).json()
            assert client.put(
                f"/api/projects/{pid}/documents/{doc['id']}"
            ).status_code == 204
            docs = client.get(f"/api/documents?project_id={pid}").json()["documents"]
            assert docs[0]["project_id"] == pid

            assert client.delete(f"/api/projects/{pid}").status_code == 204
            assert client.get(f"/api/projects/{pid}").status_code == 404
            # Run survived the deletion (detached).
            assert client.get(f"/api/runs/{run.json()['id']}").status_code == 200
