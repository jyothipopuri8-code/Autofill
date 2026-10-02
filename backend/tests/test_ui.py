from tests.conftest import EXT_ORIGIN


def test_ui_served_with_strict_csp(client):
    r = client.get("/ui/")
    assert r.status_code == 200 and "Autofill Agent" in r.text
    csp = r.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "unsafe-inline" not in csp and "unsafe-eval" not in csp
    assert "frame-ancestors 'none'" in csp
    for asset in ("app.js", "style.css"):
        assert client.get(f"/ui/{asset}").status_code == 200


def test_ui_contains_no_inline_script_or_innerhtml(client):
    assert "<script>" not in client.get("/ui/").text
    js = client.get("/ui/app.js").text
    assert "innerHTML" not in js and "eval(" not in js


def test_api_keeps_locked_down_csp(client):
    assert client.get("/api/v1/health").headers["content-security-policy"].startswith("default-src 'none'")


def test_ui_ships_no_personal_data_and_needs_token_for_api(client):
    assert client.get("/api/v1/resumes").status_code == 401


def test_agents_own_origin_allowed_but_other_sites_not(client, auth):
    own = "http://127.0.0.1:8765"
    assert client.get("/api/v1/status", headers={**auth, "Origin": own}).status_code == 200
    assert client.get("/api/v1/status", headers={**auth, "Origin": "http://127.0.0.1:9999"}).status_code == 403
    assert client.get("/api/v1/status", headers={**auth, "Origin": "https://evil.example"}).status_code == 403
    assert client.get("/api/v1/status", headers={**auth, "Origin": EXT_ORIGIN}).status_code == 200
