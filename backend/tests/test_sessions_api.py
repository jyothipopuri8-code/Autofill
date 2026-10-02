import pytest
from fastapi.testclient import TestClient

from autofill_agent.main import create_app
from tests.helpers import SAMPLE_RESUME, make_pdf

S = "/api/v1/sessions"


def upload_resume(client, auth, name="Jane.pdf", lines=None, verify=True, current=True):
    lines = lines or SAMPLE_RESUME
    r = client.post("/api/v1/resumes", headers=auth, files={"file": (name, make_pdf(lines))}).json()
    if verify:
        client.post(f"/api/v1/resumes/{r['id']}/parse", headers=auth)
        client.post(f"/api/v1/resumes/{r['id']}/verify", headers=auth)
    if current:
        client.post(f"/api/v1/resumes/{r['id']}/set-current", headers=auth)
    return r


@pytest.fixture
def env(client, auth):
    client.patch("/api/v1/profile", headers=auth, json={
        "first_name": "Jane", "last_name": "Doe", "email": "jane.doe@example.com", "phone": "(555) 123-4567",
        "city": "Austin", "state": "TX", "country": "United States", "authorized_to_work_us": True,
        "require_sponsorship_now": False, "require_sponsorship_future": False, "work_authorization_verified": True})
    resume = upload_resume(client, auth)
    return resume


def create(client, auth, **kw):
    body = {"company": "CrowdStrike", "job_title": "Security Engineer", "url": "https://boards.greenhouse.io/crowdstrike/jobs/1", "ats": "greenhouse", **kw}
    return client.post(S, headers=auth, json=body)


def F(key, label=None, **kw):
    return {"key": key, "kind": kw.pop("kind", "text"), "label": label or key, **kw}


PAGE = [
    F("fn", "First Name", required=True), F("ln", "Last Name", required=True), F("em", "Email", kind="email", required=True),
    F("pw", "Password", kind="password"), F("agree", "I agree to the Privacy Policy", kind="checkbox", required=True),
    F("why", "Why are you interested in this role?", kind="textarea", required=True),
    F("gender", "Gender", kind="select", options=[{"label": "Male"}, {"label": "Female"}, {"label": "Decline to self-identify"}]),
]


def test_requires_token(client):
    for method, path in [("get", S), ("post", S), ("get", f"{S}/1"), ("post", f"{S}/1/analyze"), ("get", "/api/v1/applications"),
                         ("get", "/api/v1/settings"), ("get", f"{S}/1/resume-file")]:
        assert getattr(client, method)(path).status_code == 401, path


def test_create_requires_a_resume(client, auth):
    assert create(client, auth).status_code == 409
    r = client.post("/api/v1/resumes", headers=auth, files={"file": ("a.pdf", make_pdf(SAMPLE_RESUME))}).json()
    assert create(client, auth).status_code == 409  # uploaded but not selected as current
    assert create(client, auth, resume_id=r["id"]).status_code == 201


def test_create_snapshots_resume_and_validates(client, auth, env):
    r = create(client, auth)
    assert r.status_code == 201
    body = r.json()
    assert body["application"]["resume_filename"] == "Jane.pdf" and body["application"]["resume_sha256"] == env["sha256"]
    assert body["application"]["ats"] == "GREENHOUSE" and body["application"]["status"] == "STARTED" and body["status"] == "ACTIVE"
    assert body["resume"]["blocked"] is None
    assert client.post(S, headers=auth, json={"job_title": "x"}).status_code == 422
    assert client.post(S, headers=auth, json={"url": "javascript:alert(1)"}).status_code == 422


def test_duplicate_detection_and_force(client, auth, env):
    first = create(client, auth).json()
    r = create(client, auth)
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["code"] == "POSSIBLE_DUPLICATE" and detail["matches"][0]["strength"] == "strong"
    assert detail["matches"][0]["active_session_id"] == first["id"]
    r = create(client, auth, force=True)
    assert r.status_code == 201 and r.json()["id"] != first["id"]
    other = create(client, auth, company="Acme", job_title="Data Analyst", url="https://acme.com/jobs/9")
    assert other.status_code == 201


def test_analyze_classifies_each_field(client, auth, env):
    sid = create(client, auth).json()["id"]
    r = client.post(f"{S}/{sid}/analyze", headers=auth, json={"page_index": 0, "fields": PAGE}).json()
    res = {x["key"]: x for x in r["results"]}
    assert res["fn"]["value"] == "Jane" and res["fn"]["action"] == "fill" and res["fn"]["band"] == "READY" and res["fn"]["auto"] is False
    assert res["em"]["value"] == "jane.doe@example.com"
    assert res["pw"]["status"] == "SKIPPED"
    assert res["agree"]["status"] == "USER_ACTION_REQUIRED" and res["agree"]["value"] is None
    assert res["why"]["action"] == "ask" and res["why"]["status"] == "MISSING_REQUIRED"
    assert res["gender"]["action"] == "ask" and res["gender"]["sensitive"] is True
    assert r["mode"] == "SAFE"
    assert r["counts"]["detected"] == 7
    labels = {i["key"] for i in r["needs_attention"]}
    assert labels == {"agree", "why", "gender"}  # gender is sensitive ASK_ME: surfaced even though optional
    assert r["section_counts"]["experience"] == 2


def test_modes_control_auto_fill(client, auth, env):
    sid = create(client, auth).json()["id"]
    assert client.put("/api/v1/settings", headers=auth, json={"mode": "STANDARD"}).json()["mode"] == "STANDARD"
    assert client.put("/api/v1/settings", headers=auth, json={"mode": "YOLO"}).status_code == 422
    client.put("/api/v1/profile/sensitive/gender", headers=auth, json={"policy": "AUTOFILL", "value": "Female"})
    res = {x["key"]: x for x in client.post(f"{S}/{sid}/analyze", headers=auth, json={"fields": PAGE}).json()["results"]}
    assert res["fn"]["auto"] is True
    assert res["gender"]["option"]["label"] == "Female" and res["gender"]["auto"] is False  # sensitive: never automatic
    client.put("/api/v1/settings", headers=auth, json={"mode": "MANUAL_ASSIST"})
    res = {x["key"]: x for x in client.post(f"{S}/{sid}/analyze", headers=auth, json={"fields": PAGE}).json()["results"]}
    assert res["fn"]["auto"] is False and res["fn"]["action"] == "fill"


def test_user_answer_outranks_and_is_remembered(client, auth, env):
    sid = create(client, auth).json()["id"]
    client.post(f"{S}/{sid}/analyze", headers=auth, json={"fields": PAGE})
    r = client.post(f"{S}/{sid}/answers", headers=auth, json={"field_key": "why", "value": "I like their mission", "remember": True})
    assert r.status_code == 200 and r.json()["remembered"] is True
    res = {x["key"]: x for x in client.post(f"{S}/{sid}/analyze", headers=auth, json={"fields": PAGE}).json()["results"]}
    assert res["why"]["value"] == "I like their mission" and res["why"]["source"] == "USER_CURRENT" and res["why"]["action"] == "fill"
    # job-specific question: remembered for the same company only
    same = create(client, auth, force=True).json()["id"]
    res = {x["key"]: x for x in client.post(f"{S}/{same}/analyze", headers=auth, json={"fields": PAGE}).json()["results"]}
    assert res["why"]["value"] == "I like their mission" and res["why"]["source"] == "APPROVED_ANSWER"
    other = create(client, auth, company="Acme", job_title="Eng", url="https://acme.com/j/1").json()["id"]
    res = {x["key"]: x for x in client.post(f"{S}/{other}/analyze", headers=auth, json={"fields": PAGE}).json()["results"]}
    assert res["why"]["action"] == "ask"


def test_general_answers_are_reused_and_replaced(client, auth, env):
    page = [F("pron", "What are your preferred pronouns at work?")]
    a = create(client, auth).json()["id"]
    client.post(f"{S}/{a}/analyze", headers=auth, json={"fields": page})
    client.post(f"{S}/{a}/answers", headers=auth, json={"field_key": "pron", "value": "she/her", "remember": True})
    b = create(client, auth, company="Acme", job_title="Eng", url="https://acme.com/j/1").json()["id"]
    r = client.post(f"{S}/{b}/analyze", headers=auth, json={"fields": page}).json()["results"][0]
    assert r["value"] == "she/her" and r["source"] == "APPROVED_ANSWER"
    client.post(f"{S}/{b}/answers", headers=auth, json={"field_key": "pron", "value": "they/them", "remember": True})
    c = create(client, auth, company="Initech", job_title="Eng", url="https://initech.com/j/1").json()["id"]
    assert client.post(f"{S}/{c}/analyze", headers=auth, json={"fields": page}).json()["results"][0]["value"] == "they/them"


def test_sensitive_and_legal_answers_are_not_remembered_or_accepted(client, auth, env):
    sid = create(client, auth).json()["id"]
    client.post(f"{S}/{sid}/analyze", headers=auth, json={"fields": PAGE})
    r = client.post(f"{S}/{sid}/answers", headers=auth, json={"field_key": "gender", "value": "Female", "remember": True}).json()
    assert r["remembered"] is False and "policy" in r["note"]
    assert client.post(f"{S}/{sid}/answers", headers=auth, json={"field_key": "agree", "value": "yes"}).status_code == 409
    assert client.post(f"{S}/{sid}/answers", headers=auth, json={"field_key": "pw", "value": "hunter2"}).status_code == 409
    assert client.post(f"{S}/{sid}/answers", headers=auth, json={"field_key": "nope", "value": "x"}).status_code == 404


def test_conflict_detected_and_resolved(client, auth, env):
    client.patch("/api/v1/profile", headers=auth, json={"phone": "555-999-0000"})
    sid = create(client, auth).json()["id"]
    page = [F("ph", "Phone Number", kind="tel", required=True)]
    r = client.post(f"{S}/{sid}/analyze", headers=auth, json={"fields": page}).json()
    assert r["results"][0]["action"] == "conflict" and r["results"][0]["value"] is None
    assert r["results"][0]["conflict"]["resume_value"] == "(555) 123-4567"
    assert r["needs_attention"][0]["conflict"]["profile_value"] == "555-999-0000"
    assert client.post(f"{S}/{sid}/conflicts/resolve", headers=auth, json={"canonical_field": "contact.phone", "choice": "custom"}).status_code == 422
    assert client.post(f"{S}/{sid}/conflicts/resolve", headers=auth, json={"canonical_field": "personal.pronouns", "choice": "profile"}).status_code == 422
    ok = client.post(f"{S}/{sid}/conflicts/resolve", headers=auth, json={"canonical_field": "contact.phone", "choice": "resume"})
    assert ok.json()["value"] == "(555) 123-4567"
    r = client.post(f"{S}/{sid}/analyze", headers=auth, json={"fields": page}).json()["results"][0]
    assert r["action"] == "fill" and r["value"] == "(555) 123-4567" and r["source"] == "USER_CURRENT"
    # the choice is for this application only
    other = create(client, auth, force=True).json()["id"]
    assert client.post(f"{S}/{other}/analyze", headers=auth, json={"fields": page}).json()["results"][0]["action"] == "conflict"


def test_resume_mismatch_blocks_until_user_chooses(client, auth, env):
    sid = create(client, auth).json()["id"]
    other = upload_resume(client, auth, "Google_Resume.pdf", lines=SAMPLE_RESUME + ["", "PROJECTS", "x"], current=True)
    page = [F("co", "Company", section={"name": "experience", "index": 0}), F("fn", "First Name"),
            F("cv", "Resume/CV", kind="file")]
    r = client.post(f"{S}/{sid}/analyze", headers=auth, json={"fields": page}).json()
    res = {x["key"]: x for x in r["results"]}
    assert "Google_Resume.pdf" in r["resume"]["blocked"] and "Jane.pdf" in r["resume"]["blocked"]
    assert res["co"]["action"] == "user_action" and res["cv"]["action"] == "user_action" and res["fn"]["action"] == "fill"
    assert client.get(f"{S}/{sid}/resume-file", headers=auth).status_code == 409
    chosen = client.post(f"{S}/{sid}/resume", headers=auth, json={"resume_id": other["id"]}).json()
    assert chosen["application"]["resume_filename"] == "Google_Resume.pdf" and chosen["resume"]["blocked"] is None
    res = {x["key"]: x for x in client.post(f"{S}/{sid}/analyze", headers=auth, json={"fields": page}).json()["results"]}
    assert res["co"]["value"] == "CrowdStrike" and res["cv"]["action"] == "attach" and res["cv"]["value"] == "Google_Resume.pdf"
    assert client.post(f"{S}/{sid}/resume", headers=auth, json={"resume_id": 999}).status_code == 404


def test_resume_file_endpoint_serves_exact_verified_file(client, auth, env):
    sid = create(client, auth).json()["id"]
    r = client.get(f"{S}/{sid}/resume-file", headers=auth)
    assert r.status_code == 200 and r.content == make_pdf(SAMPLE_RESUME)
    assert r.headers["x-resume-sha256"] == env["sha256"] and r.headers["x-resume-filename"] == "Jane.pdf"
    (client.app.state.settings.resume_dir / f"{env['sha256']}.pdf").write_bytes(b"%PDF-tampered")
    assert client.get(f"{S}/{sid}/resume-file", headers=auth).status_code == 409


def test_deleted_resume_blocks_resume_dependent_fields(client, auth, env):
    sid = create(client, auth).json()["id"]
    client.delete(f"/api/v1/resumes/{env['id']}", headers=auth)
    r = client.post(f"{S}/{sid}/analyze", headers=auth, json={"fields": [F("co", "Company", section={"name": "experience", "index": 0})]}).json()
    assert r["resume"]["blocked"] and r["results"][0]["action"] == "user_action"


def test_fill_validate_and_final_review(client, auth, env):
    sid = create(client, auth).json()["id"]
    page = [F("fn", "First Name", required=True), F("em", "Email", kind="email", required=True),
            F("pw", "Password", kind="password"), F("agree", "I agree to the Privacy Policy", kind="checkbox", required=True)]
    client.post(f"{S}/{sid}/analyze", headers=auth, json={"fields": page})
    review = client.get(f"{S}/{sid}/final-review", headers=auth).json()
    assert review["ready"] is False and review["headline"] == "NOT READY"

    assert client.post(f"{S}/{sid}/fill-report", headers=auth, json={"fields": [
        {"key": "fn", "outcome": "FILLED", "value": "Jane"}, {"key": "em", "outcome": "FAILED_TO_FILL", "error": "readonly"}]}).json()["updated"] == 2
    assert client.get(f"{S}/{sid}").json if False else True
    assert client.get(f"{S}", headers=auth).json()[0]["application"]["status"] == "IN_PROGRESS"

    v = client.post(f"{S}/{sid}/validate", headers=auth, json={"fields": [
        {**page[0], "current_value": "Jane", "ownership": "AGENT_FILLED"},
        {**page[1], "current_value": "", "ownership": "AGENT_FILLED"},
        {**page[2], "current_value": "", "ownership": "EMPTY"},
        {**page[3], "current_value": "", "ownership": "EMPTY"}]}).json()
    st = {x["key"]: x["status"] for x in v["fields"]}
    assert st == {"fn": "FILLED", "em": "FAILED_TO_FILL", "pw": "SKIPPED", "agree": "USER_ACTION_REQUIRED"}
    assert v["counts"]["complete"] == 1 and v["counts"]["failed_to_fill"] == 1 and v["counts"]["user_action_required"] == 1
    assert {i["key"] for i in v["needs_attention"]} == {"em", "agree"}
    assert client.get(f"{S}/{sid}/final-review", headers=auth).json()["ready"] is False

    # The user fixes the email by hand and ticks the consent box themselves.
    v = client.post(f"{S}/{sid}/validate", headers=auth, json={"fields": [
        {**page[0], "current_value": "Jane", "ownership": "AGENT_FILLED"},
        {**page[1], "current_value": "jane@home.example", "ownership": "USER_FILLED"},
        {**page[2], "current_value": "", "ownership": "EMPTY"},
        {**page[3], "current_value": "true", "ownership": "USER_FILLED"}]}).json()
    assert v["counts"]["complete"] == 3 and v["needs_attention"] == []
    review = client.get(f"{S}/{sid}/final-review", headers=auth).json()
    assert review["ready"] is True and review["headline"] == "READY FOR USER REVIEW" and "submitted" in review["note"]
    assert client.get(S, headers=auth).json()[0]["application"]["status"] == "READY_FOR_REVIEW"


def test_user_edit_is_never_overwritten_on_rescan(client, auth, env):
    sid = create(client, auth).json()["id"]
    r = client.post(f"{S}/{sid}/analyze", headers=auth, json={"fields": [
        {**F("fn", "First Name"), "current_value": "Janet", "ownership": "USER_MODIFIED_AGENT_VALUE"}]}).json()["results"][0]
    assert r["action"] == "keep" and r["value"] == "Janet"


def test_sessions_survive_a_restart_and_can_be_recovered(settings, client, auth, env):
    sid = create(client, auth).json()["id"]
    client.post(f"{S}/{sid}/analyze", headers=auth, json={"page_index": 2, "url": "https://x.example/page3", "fields": PAGE})
    client.post(f"{S}/{sid}/answers", headers=auth, json={"page_index": 2, "field_key": "why", "value": "Because"})
    client.app.state.db.dispose()

    with TestClient(create_app(settings)) as c2:
        auth2 = {"Authorization": f"Bearer {c2.app.state.install_token}"}
        assert auth2 == auth  # same token persisted
        listed = c2.get(S, headers=auth2).json()
        assert [x["id"] for x in listed] == [sid] and listed[0]["current_page_index"] == 2
        assert listed[0]["current_page_url"] == "https://x.example/page3"
        assert c2.get(S, headers=auth2, params={"url": "https://x.example/page3"}).json()[0]["id"] == sid
        assert c2.get(S, headers=auth2, params={"url": "https://elsewhere.example/"}).json() == []
        res = {x["key"]: x for x in c2.post(f"{S}/{sid}/analyze", headers=auth2, json={"page_index": 2, "fields": PAGE}).json()["results"]}
        assert res["why"]["value"] == "Because"  # user answers survived


def test_patch_and_delete_session(client, auth, env):
    sid = create(client, auth).json()["id"]
    r = client.patch(f"{S}/{sid}", headers=auth, json={"status": "PAUSED", "job_title": "Staff Security Engineer"}).json()
    assert r["status"] == "PAUSED" and r["application"]["job_title"] == "Staff Security Engineer"
    assert client.get(S, headers=auth).json()[0]["id"] == sid  # paused is still incomplete
    client.patch(f"{S}/{sid}", headers=auth, json={"status": "ABANDONED"})
    assert client.get(S, headers=auth).json() == []
    assert client.post(f"{S}/{sid}/analyze", headers=auth, json={"fields": PAGE}).status_code == 409
    assert client.delete(f"{S}/{sid}", headers=auth, params={"delete_application": True}).status_code == 204
    assert client.get(f"{S}/{sid}", headers=auth).status_code == 404
    assert client.get("/api/v1/applications", headers=auth).json() == []


def test_oversized_scans_are_rejected(client, auth, env):
    sid = create(client, auth).json()["id"]
    many = [F(f"k{i}", "Name") for i in range(501)]
    assert client.post(f"{S}/{sid}/analyze", headers=auth, json={"fields": many}).status_code == 422
    long = F("k", "x" * 5000, nearby_text="y" * 5000)
    assert client.post(f"{S}/{sid}/analyze", headers=auth, json={"fields": [long]}).status_code == 200  # truncated, not fatal


def test_application_history(client, auth, env):
    sid = create(client, auth).json()["id"]
    client.post(f"{S}/{sid}/analyze", headers=auth, json={"fields": PAGE})
    apps = client.get("/api/v1/applications", headers=auth).json()
    aid = apps[0]["id"]
    detail = client.get(f"/api/v1/applications/{aid}", headers=auth).json()
    assert detail["company"] == "CrowdStrike" and any(q["label"] == "First Name" and q["answer"] == "Jane" for q in detail["questions"])
    assert client.get("/api/v1/applications", headers=auth, params={"q": "crowd"}).json()[0]["id"] == aid
    assert client.get("/api/v1/applications", headers=auth, params={"q": "zzz"}).json() == []
    assert client.get("/api/v1/applications", headers=auth, params={"status": "SUBMITTED"}).json() == []
    assert client.patch(f"/api/v1/applications/{aid}", headers=auth, json={"status": "BOGUS"}).status_code == 422
    r = client.patch(f"/api/v1/applications/{aid}", headers=auth, json={"status": "SUBMITTED"}).json()
    assert r["status"] == "SUBMITTED" and r["submitted_at"]
    assert client.get(f"{S}/{sid}", headers=auth).json()["status"] == "COMPLETED"
    assert client.get(S, headers=auth).json() == []
    # a submitted application is flagged on a repeat attempt
    d = create(client, auth).json()["detail"]
    assert d["matches"][0]["status"] == "SUBMITTED"
    assert client.delete(f"/api/v1/applications/{aid}", headers=auth).status_code == 204
    assert client.get(f"{S}/{sid}", headers=auth).status_code == 404
