import hashlib
from pathlib import Path

from fastapi.testclient import TestClient

from quartermaster.app import create_app


def test_fixture_project_and_files_survive_application_restart(settings, project_fixture):
    with TestClient(create_app(settings)) as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        assert "No projects yet" in client.get("/").text
        response = client.post("/api/projects", json=project_fixture)
        assert response.status_code == 201
        project = response.json()
        marker = settings.artifact_root / "smoke.txt"
        marker.write_text("synthetic persistence fixture")
    with TestClient(create_app(settings)) as restarted:
        assert restarted.get("/healthz").status_code == 200
        assert restarted.get("/api/projects").json() == [project]
        assert project_fixture["name"] in restarted.get("/").text
        assert marker.read_text() == "synthetic persistence fixture"


def test_ui_assets_are_local_and_vendored_htmx_has_expected_hash(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "https://" not in response.text
    assert "/static/vendor/htmx.min.js" in response.text
    assert client.get("/static/app.css").status_code == 200
    script = client.get("/static/vendor/htmx.min.js")
    assert script.status_code == 200
    assert hashlib.sha256(script.content).hexdigest() == (
        "d6fdc75f204e6bdefa99b69bf1e6d4ac69b8a364f77929f45c13476b4000f717"
    )
    assert (Path("quartermaster/ui/static/vendor") / "HTMX-LICENSE.txt").is_file()
