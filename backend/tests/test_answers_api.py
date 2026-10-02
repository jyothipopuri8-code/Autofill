BASE = "/api/v1/answers"


def put(client, auth, key, **body):
    payload = {"category": "compensation", **body}
    return client.put(f"{BASE}/{key}", headers=auth, json=payload)


def test_requires_token(client):
    assert client.get(BASE).status_code == 401
    assert client.put(f"{BASE}/desired_salary", json={"category": "x"}).status_code == 401


def test_create_update_get_list_delete(client, auth):
    r = put(client, auth, "desired_salary", value="150000", policy="AUTOFILL", verification="VERIFIED", notes="USD")
    assert r.status_code == 200
    body = r.json()
    assert body["key"] == "desired_salary" and body["verification"] == "VERIFIED" and body["policy"] == "AUTOFILL"

    r = put(client, auth, "desired_salary", value="160000", policy="ASK_ME")
    assert r.json()["value"] == "160000" and r.json()["verification"] == "UNVERIFIED"
    assert len(client.get(BASE, headers=auth).json()) == 1

    put(client, auth, "travel_percentage", category="preferences", value="25")
    assert [a["key"] for a in client.get(BASE, headers=auth, params={"category": "preferences"}).json()] == ["travel_percentage"]
    assert client.get(f"{BASE}/travel_percentage", headers=auth).json()["value"] == "25"

    assert client.delete(f"{BASE}/travel_percentage", headers=auth).status_code == 204
    assert client.get(f"{BASE}/travel_percentage", headers=auth).status_code == 404
    assert client.delete(f"{BASE}/travel_percentage", headers=auth).status_code == 404


def test_rules(client, auth):
    assert put(client, auth, "desired_salary", policy="AUTOFILL").status_code == 422
    assert put(client, auth, "desired_salary", verification="VERIFIED").status_code == 422
    assert put(client, auth, "desired_salary", value="1", extra="x").status_code == 422
    assert put(client, auth, "Bad-Key", value="1").status_code == 422
    assert put(client, auth, "gender", value="x").status_code == 422  # sensitive fields live elsewhere
    assert put(client, auth, "veteran_status", value="x").status_code == 422
    assert client.get(BASE, headers=auth).json() == []


def test_standard_keys(client, auth):
    keys = client.get(f"{BASE}/standard-keys", headers=auth).json()
    assert keys["desired_salary"] == "compensation"
