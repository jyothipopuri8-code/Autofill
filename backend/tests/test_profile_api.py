def test_requires_token(client):
    assert client.get("/api/v1/profile").status_code == 401
    assert client.patch("/api/v1/profile", json={"first_name": "A"}).status_code == 401
    assert client.get("/api/v1/profile/sensitive").status_code == 401


def test_empty_profile_has_unknown_work_authorization(client, auth):
    p = client.get("/api/v1/profile", headers=auth).json()
    assert p["first_name"] is None
    assert p["authorized_to_work_us"] is None
    assert p["require_sponsorship_now"] is None
    assert p["work_authorization_verified"] is False


def test_partial_update_and_clear(client, auth):
    r = client.patch("/api/v1/profile", headers=auth, json={"first_name": " Jane ", "email": "jane@example.com", "city": "Austin"})
    assert r.status_code == 200 and r.json()["first_name"] == "Jane"
    r = client.patch("/api/v1/profile", headers=auth, json={"city": ""})
    body = r.json()
    assert body["city"] is None and body["first_name"] == "Jane" and body["email"] == "jane@example.com"
    assert client.get("/api/v1/profile", headers=auth).json()["first_name"] == "Jane"


def test_explicit_false_is_kept_distinct_from_unknown(client, auth):
    body = client.patch("/api/v1/profile", headers=auth, json={"require_sponsorship_now": False}).json()
    assert body["require_sponsorship_now"] is False
    assert body["authorized_to_work_us"] is None


def test_validation(client, auth):
    bad = [
        {"email": "not-an-email"},
        {"phone": "abc"},
        {"linkedin_url": "javascript:alert(1)"},
        {"linkedin_url": "linkedin.com/in/x"},
        {"phone_device_type": "fax"},
        {"phone_country_code": "one"},
        {"first_name": "x" * 101},
        {"unknown_field": "x"},
        {"available_start_date": "tomorrow"},
    ]
    for payload in bad:
        assert client.patch("/api/v1/profile", headers=auth, json=payload).status_code == 422, payload
    ok = {"linkedin_url": "https://linkedin.com/in/jane", "phone": "+1 (555) 123-4567", "phone_device_type": "Mobile",
          "phone_country_code": "+1", "available_start_date": "2026-11-01", "postal_code": "78701"}
    r = client.patch("/api/v1/profile", headers=auth, json=ok)
    assert r.status_code == 200 and r.json()["phone_device_type"] == "mobile"
    assert r.json()["available_start_date"] == "2026-11-01"


def test_sensitive_defaults_to_ask_me(client, auth):
    prefs = client.get("/api/v1/profile/sensitive", headers=auth).json()
    assert {p["field"] for p in prefs} == {
        "gender", "race", "ethnicity", "hispanic_latino", "disability_status", "medical_accommodation", "veteran_status"}
    assert all(p["policy"] == "ASK_ME" and p["value"] is None for p in prefs)


def test_sensitive_policy_rules(client, auth):
    url = "/api/v1/profile/sensitive/gender"
    assert client.put(url, headers=auth, json={"policy": "AUTOFILL"}).status_code == 422
    assert client.put(url, headers=auth, json={"policy": "NEVER_FILL", "value": "x"}).status_code == 422
    assert client.put(url, headers=auth, json={"policy": "ASK_ME", "value": "x"}).status_code == 422
    assert client.put("/api/v1/profile/sensitive/hobby", headers=auth, json={"policy": "ASK_ME"}).status_code == 422

    r = client.put(url, headers=auth, json={"policy": "AUTOFILL", "value": "Female"})
    assert r.status_code == 200 and r.json()["value"] == "Female"
    r = client.put(url, headers=auth, json={"policy": "NEVER_FILL"})
    assert r.json()["policy"] == "NEVER_FILL" and r.json()["value"] is None
    prefs = {p["field"]: p for p in client.get("/api/v1/profile/sensitive", headers=auth).json()}
    assert prefs["gender"]["policy"] == "NEVER_FILL" and prefs["race"]["policy"] == "ASK_ME"


def test_delete_profile_clears_everything(client, auth):
    client.patch("/api/v1/profile", headers=auth, json={"first_name": "Jane"})
    client.put("/api/v1/profile/sensitive/race", headers=auth, json={"policy": "NEVER_FILL"})
    assert client.delete("/api/v1/profile", headers=auth).status_code == 204
    assert client.get("/api/v1/profile", headers=auth).json()["first_name"] is None
    prefs = client.get("/api/v1/profile/sensitive", headers=auth).json()
    assert all(p["policy"] == "ASK_ME" for p in prefs)
