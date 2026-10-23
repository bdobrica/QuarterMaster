from uuid import UUID

import pytest


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"name": "Demo"},
        {"mission": "Help"},
        {"name": " ", "mission": "Help"},
        {"name": "Demo", "mission": "\n"},
        {"name": 123, "mission": "Help"},
        {"name": "Demo", "mission": None},
        {"name": "x" * 121, "mission": "Help"},
        {"name": "Demo", "mission": "x" * 4001},
        {"name": "Demo", "mission": "Help", "unexpected": "field"},
        {"name": "Demo", "mission": "Help", "schema_version": "unknown/v2"},
    ],
)
def test_invalid_projects_leave_database_unchanged(client, payload):
    assert client.post("/api/projects", json=payload).status_code == 422
    assert client.get("/api/projects").json() == []


def test_validation_does_not_reflect_sensitive_inputs(client):
    response = client.post("/api/projects", json={"secret": "sensitive-fixture"})
    assert response.status_code == 422
    assert "sensitive-fixture" not in response.text


def test_ids_are_unique_and_values_are_normalized(client, project_fixture):
    project_fixture["name"] = "  Workshop  "
    first = client.post("/api/projects", json=project_fixture).json()
    second = client.post("/api/projects", json=project_fixture).json()
    assert first["id"] != second["id"]
    assert UUID(first["id"])
    assert first["name"] == "Workshop"
    assert first["schema_version"] == "quartermaster.project/v1"
    assert first["created_at"].endswith("Z")


def test_untrusted_text_is_escaped_and_stored_as_data(client):
    draft = {"name": "<script>alert(1)</script>", "mission": "'); DROP TABLE projects; --"}
    assert client.post("/api/projects", json=draft).status_code == 201
    assert client.get("/api/projects").json()[0]["mission"] == draft["mission"]
    html = client.get("/").text
    assert draft["name"] not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


@pytest.mark.parametrize("route", ["/api/projects", "/projects"])
def test_foreign_origin_is_rejected(client, project_fixture, route):
    response = client.post(route, json=project_fixture, headers={"Origin": "https://evil.test"})
    assert response.status_code == 403
    assert client.get("/api/projects").json() == []


def test_form_requires_origin_and_json_api_rejects_form_content(client, project_fixture):
    assert client.post("/projects", data=project_fixture).status_code == 403
    assert client.post("/api/projects", data=project_fixture).status_code == 422
    assert client.get("/api/projects").json() == []


def test_htmx_creates_project_and_returns_fragment(client, project_fixture):
    response = client.post(
        "/projects",
        data=project_fixture,
        headers={"Origin": "http://testserver", "HX-Request": "true"},
    )
    assert response.status_code == 200
    assert 'id="projects"' in response.text
    assert project_fixture["name"] in response.text
    assert "<html" not in response.text
    assert len(client.get("/api/projects").json()) == 1


def test_form_works_without_javascript(client, project_fixture):
    response = client.post(
        "/projects",
        data=project_fixture,
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert project_fixture["name"] in client.get("/").text


def test_invalid_form_explains_how_to_correct_it(client):
    response = client.post(
        "/projects", data={"name": "  "}, headers={"Origin": "http://testserver"}
    )
    assert response.status_code == 422
    assert "Enter a name" in response.text
    assert client.get("/api/projects").json() == []
