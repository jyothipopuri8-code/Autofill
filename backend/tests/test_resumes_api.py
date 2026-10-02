import hashlib
import io
import os
import zipfile
from pathlib import Path

BASE = "/api/v1/resumes"
PDF_A = b"%PDF-1.4\n% resume A\n%%EOF\n"
PDF_B = b"%PDF-1.4\n% resume B\n%%EOF\n"


def make_docx(extra: bytes = b"") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", "<w:document/>" + extra.decode())
    return buf.getvalue()


def upload(client, auth, name="Security_Engineer_CrowdStrike.pdf", data=PDF_A, mime="application/pdf"):
    return client.post(BASE, headers=auth, files={"file": (name, data, mime)})


def test_requires_token(client):
    assert client.get(BASE).status_code == 401
    assert client.post(BASE, files={"file": ("a.pdf", PDF_A)}).status_code == 401


def test_upload_pdf_hashes_and_stores(client, auth):
    r = upload(client, auth)
    assert r.status_code == 201
    body = r.json()
    assert body["sha256"] == hashlib.sha256(PDF_A).hexdigest()
    assert body["filename"] == "Security_Engineer_CrowdStrike.pdf"
    assert body["status"] == "UPLOADED" and body["is_current"] is False
    assert "stored_path" not in body
    stored = client.app.state.settings.resume_dir / f"{body['sha256']}.pdf"
    assert stored.read_bytes() == PDF_A
    assert not list(client.app.state.settings.resume_dir.glob(".upload-*"))


def test_upload_docx(client, auth):
    r = upload(client, auth, "r.docx", make_docx())
    assert r.status_code == 201 and r.json()["mime_type"].endswith("wordprocessingml.document")


def test_rejects_bad_uploads(client, auth):
    assert upload(client, auth, "r.exe", b"MZ").status_code == 415
    assert upload(client, auth, "r.pdf", b"not a pdf").status_code == 415
    assert upload(client, auth, "r.docx", b"PK not really").status_code == 415
    assert upload(client, auth, "r.docx", PDF_A).status_code == 415
    assert upload(client, auth, "r.pdf", b"").status_code == 400
    empty_zip = io.BytesIO()
    zipfile.ZipFile(empty_zip, "w").close()
    assert upload(client, auth, "r.docx", empty_zip.getvalue()).status_code == 415
    assert client.get(BASE, headers=auth).json() == []
    assert not any(client.app.state.settings.resume_dir.iterdir())


def test_size_limit(client, auth):
    client.app.state.settings.max_resume_bytes = 2048
    r = upload(client, auth, "big.pdf", b"%PDF-" + b"x" * 5000)
    assert r.status_code == 413
    assert not any(client.app.state.settings.resume_dir.iterdir())


def test_filename_is_sanitized_and_cannot_escape(client, auth):
    r = upload(client, auth, "../../etc/pass<wd>\x00.pdf")
    assert r.status_code == 201
    assert "/" not in r.json()["filename"] and "<" not in r.json()["filename"]
    root = client.app.state.settings.resume_dir
    assert [p.parent for p in root.glob("**/*.pdf")] == [root]


def test_duplicate_content_conflicts(client, auth):
    assert upload(client, auth, "a.pdf").status_code == 201
    r = upload(client, auth, "renamed.pdf")
    assert r.status_code == 409 and "a.pdf" in r.json()["detail"]
    assert len(client.get(BASE, headers=auth).json()) == 1


def test_set_current_switches_and_single_current(client, auth):
    a = upload(client, auth, "a.pdf", PDF_A).json()["id"]
    b = upload(client, auth, "b.pdf", PDF_B).json()["id"]
    assert client.get(f"{BASE}/current", headers=auth).status_code == 404
    assert client.post(f"{BASE}/{a}/set-current", headers=auth).json()["is_current"] is True
    assert client.post(f"{BASE}/{b}/set-current", headers=auth).json()["is_current"] is True
    assert client.get(f"{BASE}/current", headers=auth).json()["id"] == b
    current = [r["id"] for r in client.get(BASE, headers=auth).json() if r["is_current"]]
    assert current == [b]
    assert client.post(f"{BASE}/999/set-current", headers=auth).status_code == 404


def test_archive_unarchive(client, auth):
    a = upload(client, auth).json()["id"]
    client.post(f"{BASE}/{a}/set-current", headers=auth)
    r = client.post(f"{BASE}/{a}/archive", headers=auth).json()
    assert r["archived_at"] is not None and r["is_current"] is False
    assert client.get(BASE, headers=auth).json() == []
    assert len(client.get(BASE, headers=auth, params={"include_archived": True}).json()) == 1
    assert client.post(f"{BASE}/{a}/set-current", headers=auth).status_code == 409
    assert client.post(f"{BASE}/{a}/unarchive", headers=auth).json()["archived_at"] is None
    assert client.post(f"{BASE}/{a}/set-current", headers=auth).status_code == 200


def test_integrity_detects_tampering_and_missing_file(client, auth):
    r = upload(client, auth).json()
    path = client.app.state.settings.resume_dir / f"{r['sha256']}.pdf"
    ok = client.get(f"{BASE}/{r['id']}/integrity", headers=auth).json()
    assert ok["file_exists"] and ok["sha256_matches"]
    path.write_bytes(PDF_B)
    bad = client.get(f"{BASE}/{r['id']}/integrity", headers=auth).json()
    assert bad["file_exists"] and not bad["sha256_matches"] and bad["actual_sha256"] != r["sha256"]
    path.unlink()
    gone = client.get(f"{BASE}/{r['id']}/integrity", headers=auth).json()
    assert not gone["file_exists"] and not gone["sha256_matches"] and gone["actual_sha256"] is None


def test_delete_removes_record_and_file_but_keeps_application_snapshot(client, auth):
    from autofill_agent.db.models import Application

    r = upload(client, auth).json()
    db = client.app.state.db
    with db.session() as s:
        s.add(Application(company="CrowdStrike", resume_id=r["id"], resume_filename=r["filename"], resume_sha256=r["sha256"]))
    assert client.delete(f"{BASE}/{r['id']}", headers=auth).status_code == 204
    assert client.get(f"{BASE}/{r['id']}", headers=auth).status_code == 404
    assert not (client.app.state.settings.resume_dir / f"{r['sha256']}.pdf").exists()
    with db.session() as s:
        app = s.query(Application).one()
        assert app.resume_id is None and app.resume_sha256 == r["sha256"]
    # The same file can be uploaded again after deletion.
    assert upload(client, auth).status_code == 201


def test_resume_files_are_private(client, auth):
    r = upload(client, auth).json()
    path = client.app.state.settings.resume_dir / f"{r['sha256']}.pdf"
    if os.name == "posix":
        assert oct(path.stat().st_mode & 0o777) == "0o600"
