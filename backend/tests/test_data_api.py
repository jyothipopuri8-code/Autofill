from tests.helpers import SAMPLE_RESUME, make_pdf
from tests.test_sessions_api import F, S, create, upload_resume


def seed(client, auth):
    client.patch("/api/v1/profile", headers=auth, json={"first_name": "Jane", "last_name": "Doe", "email": "jane@example.com"})
    client.put("/api/v1/answers/desired_salary", headers=auth, json={"category": "compensation", "value": "150000", "policy": "AUTOFILL"})
    resume = upload_resume(client, auth)
    sid = create(client, auth).json()["id"]
    client.post(f"{S}/{sid}/analyze", headers=auth, json={"page_index": 0, "fields": [F("why", "Why do you want to work here?", kind="textarea", required=True)]})
    client.post(f"{S}/{sid}/answers", headers=auth, json={"page_index": 0, "field_key": "why", "value": "I like the mission.", "remember": True})
    return resume, sid


def test_requires_token(client):
    for method, path in [("get", "/api/v1/memory"), ("delete", "/api/v1/memory/1"), ("get", "/api/v1/data/export"), ("post", "/api/v1/data/delete")]:
        assert getattr(client, method)(path).status_code == 401, path


def test_memory_can_be_listed_and_forgotten(client, auth):
    seed(client, auth)
    mem = client.get("/api/v1/memory", headers=auth).json()
    assert len(mem) == 1 and mem[0]["answer"] == "I like the mission." and "work here" in mem[0]["question"]
    assert client.delete(f"/api/v1/memory/{mem[0]['id']}", headers=auth).status_code == 204
    assert client.get("/api/v1/memory", headers=auth).json() == []
    assert client.delete("/api/v1/memory/999", headers=auth).status_code == 404


def test_export_contains_data_but_not_files_or_paths(client, auth, settings):
    resume, _ = seed(client, auth)
    r = client.get("/api/v1/data/export", headers=auth)
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"] and r.headers["cache-control"] == "no-store"
    body = r.json()
    assert body["profile"]["first_name"] == "Jane" and body["answer_library"][0]["key"] == "desired_salary"
    assert body["applications"][0]["company"] == "CrowdStrike" and body["resumes"][0]["sha256"] == resume["sha256"]
    assert str(settings.data_dir) not in r.text


def test_delete_needs_the_exact_phrase_and_a_known_scope(client, auth):
    seed(client, auth)
    assert client.post("/api/v1/data/delete", headers=auth, json={"scope": "all", "confirm": "yes"}).status_code == 422
    assert client.post("/api/v1/data/delete", headers=auth, json={"scope": "everything", "confirm": "DELETE MY DATA"}).status_code == 422
    assert client.get("/api/v1/profile", headers=auth).json()["first_name"] == "Jane"


def test_delete_scopes(client, auth):
    seed(client, auth)
    r = client.post("/api/v1/data/delete", headers=auth, json={"scope": "memory", "confirm": "DELETE MY DATA"})
    assert r.json()["deleted"]["remembered_answers"] == 1
    assert client.get("/api/v1/applications", headers=auth).json() != []
    r = client.post("/api/v1/data/delete", headers=auth, json={"scope": "applications", "confirm": "DELETE MY DATA"})
    assert r.json()["deleted"]["applications"] == 1
    assert client.get("/api/v1/applications", headers=auth).json() == [] and client.get(S, headers=auth).json() == []
    assert client.get("/api/v1/profile", headers=auth).json()["first_name"] == "Jane"


def test_delete_all_removes_everything_including_files_but_keeps_the_token(client, auth, settings):
    resume, _ = seed(client, auth)
    assert list(settings.resume_dir.glob("*"))
    r = client.post("/api/v1/data/delete", headers=auth, json={"scope": "all", "confirm": "DELETE MY DATA"})
    assert r.status_code == 200 and r.json()["files_removed"] == 1
    assert list(settings.resume_dir.glob("*")) == []
    assert client.get("/api/v1/resumes", headers=auth).json() == []
    assert client.get("/api/v1/answers", headers=auth).json() == []
    assert client.get("/api/v1/profile", headers=auth).json().get("first_name") is None
    assert client.get("/api/v1/status", headers=auth).status_code == 200  # the agent itself keeps working
    # and a fresh start works
    upload_resume(client, auth, name="New.pdf", lines=SAMPLE_RESUME + ["extra line"])
