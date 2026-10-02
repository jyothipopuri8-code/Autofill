"""Phase 40 audit: every route, headers, limits, files, logs and the extension's declared permissions."""

import json
import logging
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from autofill_agent.config import Settings
from autofill_agent.main import create_app
from tests.conftest import EXT_ORIGIN
from tests.helpers import SAMPLE_RESUME, make_pdf

ROOT = Path(__file__).resolve().parents[2]


def _fill_path(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "1", path)


def test_every_api_route_requires_the_token(client):
    checked = 0
    for path, methods in client.app.openapi()["paths"].items():
        if not path.startswith("/api/") or path == "/api/v1/health":
            continue
        for method in methods:
            if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                continue
            r = client.request(method.upper(), _fill_path(path))
            assert r.status_code == 401, f"{method.upper()} {path} answered {r.status_code} without a token"
            checked += 1
    assert checked >= 40  # the audit actually walked the API, not an empty list


def test_wrong_and_malformed_tokens_are_rejected(client):
    for value in ("Bearer wrong", "Bearer ", "Basic abc", "bearer", "Token abc"):
        assert client.get("/api/v1/status", headers={"Authorization": value}).status_code == 401


def test_only_health_is_public_and_it_reveals_nothing_personal(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200 and set(r.json()) <= {"status", "version"}


def test_security_headers_on_api_and_ui(client, auth):
    for path in ("/api/v1/health", "/ui/", "/ui/app.js"):
        h = client.get(path).headers
        assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY"
        assert h["referrer-policy"] == "no-referrer" and h["cache-control"] == "no-store"
        assert h["cross-origin-resource-policy"] == "same-origin"
        assert "frame-ancestors 'none'" in h["content-security-policy"]


def test_dns_rebinding_host_headers_are_refused(client):
    assert client.get("/api/v1/health", headers={"Host": "evil.example"}).status_code == 400
    assert client.get("/api/v1/health", headers={"Host": "127.0.0.1.evil.example"}).status_code == 400


def test_cors_preflight_only_for_the_extension(client):
    ok = client.options("/api/v1/status", headers={"Origin": EXT_ORIGIN, "Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "authorization"})
    assert ok.headers.get("access-control-allow-origin") == EXT_ORIGIN
    bad = client.options("/api/v1/status", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert bad.status_code == 403 and "access-control-allow-origin" not in bad.headers


def test_oversized_bodies_are_refused_before_processing(client, auth):
    big = json.dumps({"fields": [], "pad": "x" * (9 * 1024 * 1024)})
    r = client.post("/api/v1/sessions/1/analyze", headers={**auth, "Content-Type": "application/json"}, content=big)
    assert r.status_code == 413
    r = client.post("/api/v1/resumes", headers=auth, files={"file": ("big.pdf", b"%PDF-1.4" + b"0" * (12 * 1024 * 1024))})
    assert r.status_code == 413


def test_unhandled_errors_do_not_leak_internals(settings):
    app = create_app(settings)

    @app.get("/api/v1/boom")
    def boom():  # pragma: no cover - raises on purpose
        raise RuntimeError("secret path /home/jane/.config/token and SELECT * FROM profile")

    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/api/v1/boom")
        assert r.status_code == 500 and r.json() == {"detail": "Internal error"}
        assert "secret" not in r.text and "SELECT" not in r.text


def test_static_ui_cannot_be_used_to_read_other_files(client):
    for p in ("/ui/../config.py", "/ui/%2e%2e/config.py", "/ui/..%2fmain.py", "/ui/../../../etc/passwd"):
        r = client.get(p)
        assert r.status_code in (400, 404) and "FastAPI" not in r.text and "root:" not in r.text


def test_api_docs_are_off_by_default(client):
    for p in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(p).status_code == 404


# --- files and storage ---------------------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_secrets_and_data_are_owner_only(client, auth, settings):
    client.post("/api/v1/resumes", headers=auth, files={"file": ("r.pdf", make_pdf(SAMPLE_RESUME))})
    logging.getLogger("autofill_agent").info("hello")
    for path, want in [(settings.data_dir, 0o700), (settings.resume_dir, 0o700), (settings.log_dir, 0o700), (settings.token_path, 0o600),
                       (settings.database_path, 0o600), (settings.log_dir / "agent.log", 0o600), *[(p, 0o600) for p in settings.resume_dir.glob("*")]]:
        assert stat.S_IMODE(os.stat(path).st_mode) == want, path


@pytest.mark.parametrize("name", ["../../evil.pdf", "..\\..\\evil.pdf", "a\x00b.pdf", "/etc/passwd.pdf", "x" * 400 + ".pdf"])
def test_hostile_upload_names_never_reach_the_filesystem(client, auth, settings, name):
    r = client.post("/api/v1/resumes", headers=auth, files={"file": (name, make_pdf(SAMPLE_RESUME))})
    assert r.status_code in (201, 400, 422)
    stored = [p.name for p in settings.resume_dir.glob("*")]
    assert all(re.fullmatch(r"[0-9a-f]{64}\.(pdf|docx)", n) for n in stored), stored
    assert not (settings.data_dir.parent / "evil.pdf").exists()


@pytest.mark.parametrize("payload", [b"", b"MZ\x90\x00" + b"0" * 2000, b"PK\x03\x04" + b"0" * 100, b"<html><script>alert(1)</script></html>"])
def test_files_that_are_not_resumes_are_rejected_at_upload(client, auth, payload):
    r = client.post("/api/v1/resumes", headers=auth, files={"file": ("r.pdf", payload)})
    assert r.status_code in (400, 415, 422), r.text


@pytest.mark.parametrize("payload", [b"%PDF-1.4\n" + b"\x00" * 50, b"%PDF-1.7\n1 0 obj<<>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF"])
def test_a_broken_pdf_fails_cleanly_when_parsed(client, auth, payload):
    r = client.post("/api/v1/resumes", headers=auth, files={"file": ("r.pdf", payload)})
    assert r.status_code == 201
    parsed = client.post(f"/api/v1/resumes/{r.json()['id']}/parse", headers=auth)
    assert parsed.status_code in (200, 400, 422) and parsed.status_code != 500, parsed.text


def test_logs_never_contain_personal_values_or_tokens(client, auth, settings):
    client.patch("/api/v1/profile", headers=auth, json={"first_name": "Zephyrine", "email": "zephyrine.q@secret-mail.example", "phone": "(555) 867-5309"})
    r = client.post("/api/v1/resumes", headers=auth, files={"file": ("r.pdf", make_pdf(["Zephyrine Q", "zephyrine.q@secret-mail.example", "(555) 867-5309"] + SAMPLE_RESUME))}).json()
    client.post(f"/api/v1/resumes/{r['id']}/parse", headers=auth)
    client.get("/api/v1/profile", headers={"Authorization": "Bearer definitely-wrong-token-value"})
    for h in logging.getLogger("autofill_agent").handlers:
        h.flush()
    log = (settings.log_dir / "agent.log").read_text()
    for secret in ("zephyrine.q@secret-mail.example", "867-5309", client.app.state.install_token, "definitely-wrong-token-value"):
        assert secret not in log, f"{secret!r} leaked into the log"


def test_token_rotation_replaces_the_token(tmp_path):
    env = {**os.environ, "AUTOFILL_DATA_DIR": str(tmp_path / "d"), "PYTHONPATH": str(ROOT / "backend")}
    run = lambda *a: subprocess.run([sys.executable, "-m", "autofill_agent", "token", *a], env=env, capture_output=True, text=True, check=True).stdout.strip()
    first = run()
    assert run() == first and len(first) >= 32
    rotated = run("--rotate")
    assert rotated != first and run() == rotated
    assert stat.S_IMODE(os.stat(tmp_path / "d" / "install_token").st_mode) == 0o600 or sys.platform == "win32"


# --- extension declaration -----------------------------------------------------------


def test_extension_manifest_asks_for_the_minimum():
    m = json.loads((ROOT / "extension" / "manifest.base.json").read_text())
    assert m["manifest_version"] == 3
    assert set(m["permissions"]) <= {"storage", "scripting", "activeTab"}
    assert m["host_permissions"] == ["http://127.0.0.1:8765/*"], "only the local agent may be accessed without asking"
    assert set(m["optional_host_permissions"]) <= {"https://*/*", "http://*/*"}
    for banned in ("tabs", "cookies", "history", "webRequest", "webRequestBlocking", "downloads", "nativeMessaging", "management",
                   "debugger", "clipboardRead", "clipboardWrite", "bookmarks", "topSites", "identity", "<all_urls>", "declarativeNetRequest"):
        assert banned not in m["permissions"] and banned not in m["host_permissions"], banned
    assert "content_scripts" not in m, "pages must opt in per site; nothing runs everywhere"
    assert "externally_connectable" not in m and "web_accessible_resources" not in m
    csp = m["content_security_policy"]["extension_pages"]
    assert "script-src 'self'" in csp and "unsafe-eval" not in csp and "unsafe-inline" not in csp
