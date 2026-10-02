import os
import stat
import sys

import pytest
from pydantic import ValidationError

from autofill_agent.config import Settings
from tests.conftest import EXT_ORIGIN


def test_health_is_public(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_status_requires_token(client, auth):
    assert client.get("/api/v1/status").status_code == 401
    assert client.get("/api/v1/status", headers={"Authorization": "Bearer wrong"}).status_code == 401
    r = client.get("/api/v1/status", headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["database"] == "ok" and body["authenticated"] is True


def test_foreign_origin_rejected(client, auth):
    r = client.get("/api/v1/health", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_extension_origin_allowed_with_cors(client):
    r = client.get("/api/v1/health", headers={"Origin": EXT_ORIGIN})
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == EXT_ORIGIN


def test_rebinding_host_rejected(client):
    assert client.get("/api/v1/health", headers={"Host": "evil.example"}).status_code == 400


def test_security_headers(client):
    h = client.get("/api/v1/health").headers
    assert h["x-content-type-options"] == "nosniff" and h["cache-control"] == "no-store"


def test_docs_disabled_by_default(client):
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_token_persisted_and_stable(settings):
    from autofill_agent.main import create_app

    t1 = create_app(settings).state.install_token
    t2 = create_app(settings).state.install_token
    assert t1 == t2 and len(t1) >= 32


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_token_and_data_dir_private(client):
    s = client.app.state.settings
    assert stat.S_IMODE(os.stat(s.token_path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(s.data_dir).st_mode) == 0o700


def test_non_loopback_host_refused(tmp_path):
    for host in ("0.0.0.0", "192.168.1.5", "localhost"):
        with pytest.raises(ValidationError):
            Settings(host=host, data_dir=tmp_path, _env_file=None)


def test_web_origin_not_accepted_in_config(tmp_path):
    with pytest.raises(ValidationError):
        Settings(allowed_origins=["https://example.com"], data_dir=tmp_path, _env_file=None)
