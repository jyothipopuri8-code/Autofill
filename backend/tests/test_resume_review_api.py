import copy

from autofill_agent.db.models import Resume
from tests.helpers import SAMPLE_RESUME, make_docx, make_pdf

BASE = "/api/v1/resumes"


def upload(client, auth, name="r.pdf", data=None):
    data = data if data is not None else make_pdf(SAMPLE_RESUME)
    r = client.post(BASE, headers=auth, files={"file": (name, data)})
    assert r.status_code == 201, r.text
    return r.json()


def test_requires_token(client, auth):
    rid = upload(client, auth)["id"]
    for method, path in [("post", "parse"), ("get", "data"), ("put", "verified-data"), ("post", "verify")]:
        assert getattr(client, method)(f"{BASE}/{rid}/{path}").status_code == 401


def test_parse_then_data(client, auth):
    r = upload(client, auth)
    assert r["status"] == "UPLOADED"
    d = client.post(f"{BASE}/{r['id']}/parse", headers=auth).json()
    assert d["status"] == "PARSED" and d["verified"] is False and d["verified_data"] is None
    assert d["parsed_data"]["contact"]["email"] == "jane.doe@example.com"
    assert d["effective_data"] == d["parsed_data"]
    assert client.get(f"{BASE}/{r['id']}", headers=auth).json()["parsed_at"] is not None


def test_parse_docx(client, auth):
    r = upload(client, auth, "r.docx", make_docx(SAMPLE_RESUME))
    d = client.post(f"{BASE}/{r['id']}/parse", headers=auth).json()
    assert d["parsed_data"]["experience"][0]["company"] == "CrowdStrike"


def test_parse_unreadable_and_missing(client, auth):
    r = upload(client, auth, "scan.pdf", make_pdf([]))
    resp = client.post(f"{BASE}/{r['id']}/parse", headers=auth)
    assert resp.status_code == 422 and "No selectable text" in resp.json()["detail"]
    assert client.get(f"{BASE}/{r['id']}/data", headers=auth).json()["parsed_data"] is None
    assert client.post(f"{BASE}/999/parse", headers=auth).status_code == 404


def test_parse_refuses_tampered_file(client, auth):
    r = upload(client, auth)
    (client.app.state.settings.resume_dir / f"{r['sha256']}.pdf").write_bytes(make_pdf(["Someone Else"]))
    resp = client.post(f"{BASE}/{r['id']}/parse", headers=auth)
    assert resp.status_code == 409 and "SHA-256" in resp.json()["detail"]


def test_verify_requires_data(client, auth):
    r = upload(client, auth)
    assert client.post(f"{BASE}/{r['id']}/verify", headers=auth).status_code == 409


def test_verify_parse_as_is(client, auth):
    r = upload(client, auth)
    client.post(f"{BASE}/{r['id']}/parse", headers=auth)
    d = client.post(f"{BASE}/{r['id']}/verify", headers=auth).json()
    assert d["verified"] is True and d["status"] == "VERIFIED"
    assert "warnings" not in d["verified_data"] and d["verified_data"]["contact"]["last_name"] == "Doe"
    assert client.get(f"{BASE}/{r['id']}", headers=auth).json()["verified_at"] is not None


def test_corrections_win_and_editing_unverifies(client, auth):
    r = upload(client, auth)
    parsed = client.post(f"{BASE}/{r['id']}/parse", headers=auth).json()["parsed_data"]
    fixed = copy.deepcopy(parsed)
    fixed.pop("warnings")
    fixed["contact"]["phone"] = "555-222-2222"
    fixed["experience"][0]["title"] = "Staff Security Engineer"
    d = client.put(f"{BASE}/{r['id']}/verified-data", headers=auth, json=fixed).json()
    assert d["status"] == "PARSED" and d["effective_data"]["contact"]["phone"] == "555-222-2222"
    assert d["parsed_data"]["contact"]["phone"] == "(555) 123-4567"  # raw parse untouched

    assert client.post(f"{BASE}/{r['id']}/verify", headers=auth).json()["status"] == "VERIFIED"
    fixed["summary"] = "Edited after verification"
    d = client.put(f"{BASE}/{r['id']}/verified-data", headers=auth, json=fixed).json()
    assert d["status"] == "PARSED" and d["verified"] is False


def test_reparse_keeps_corrections_but_unverifies(client, auth):
    r = upload(client, auth)
    client.post(f"{BASE}/{r['id']}/parse", headers=auth)
    client.post(f"{BASE}/{r['id']}/verify", headers=auth)
    d = client.post(f"{BASE}/{r['id']}/parse", headers=auth).json()
    assert d["status"] == "PARSED" and d["verified_data"] is not None


def test_corrections_validated(client, auth):
    rid = upload(client, auth)["id"]
    url = f"{BASE}/{rid}/verified-data"
    bad = [
        {"contact": {"email": "nope"}},
        {"contact": {"linkedin_url": "javascript:x"}},
        {"experience": [{"start_date": "01/2020"}]},
        {"experience": [{"start_date": "2020-13"}]},
        {"experience": [{"current": True, "end_date": "2021-01"}]},
        {"education": [{"graduation_date": "May 2020"}]},
        {"surprise": 1},
        {"skills": [""]},
    ]
    for payload in bad:
        assert client.put(url, headers=auth, json=payload).status_code == 422, payload
    ok = {"contact": {"email": ""}, "experience": [{"title": "Eng", "start_date": "2020-01", "end_date": "2021"}], "skills": ["Go"]}
    d = client.put(url, headers=auth, json=ok).json()
    assert d["verified_data"]["contact"]["email"] is None and d["status"] == "UPLOADED"


def test_manual_entry_without_parse_can_be_verified(client, auth):
    rid = upload(client, auth, "scan.pdf", make_pdf([]))["id"]
    client.put(f"{BASE}/{rid}/verified-data", headers=auth, json={"contact": {"full_name": "Sam Lee"}})
    d = client.post(f"{BASE}/{rid}/verify", headers=auth).json()
    assert d["verified"] and d["effective_data"]["contact"]["full_name"] == "Sam Lee"


def test_archived_resume_data_still_readable(client, auth):
    rid = upload(client, auth)["id"]
    client.post(f"{BASE}/{rid}/parse", headers=auth)
    client.post(f"{BASE}/{rid}/archive", headers=auth)
    assert client.get(f"{BASE}/{rid}/data", headers=auth).json()["parsed_data"] is not None
