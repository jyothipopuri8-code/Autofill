"""Safe storage of uploaded resume files.

Files are stored content-addressed (``<sha256>.<ext>``) inside the resume
directory, so the user-supplied filename never influences the path on disk.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

CHUNK = 1024 * 1024
MAX_UNCOMPRESSED_DOCX = 100 * 1024 * 1024

ALLOWED = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


class ResumeUploadError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass
class StoredFile:
    path: Path
    sha256: str
    size: int
    mime_type: str
    ext: str


def sanitize_filename(name: str | None) -> str:
    """Display-safe filename: no directories, control characters or odd symbols."""
    name = unicodedata.normalize("NFKC", name or "")
    name = re.split(r"[\\/]", name)[-1]
    name = "".join(c for c in name if c.isprintable())
    name = re.sub(r"[^\w.\- ()]", "_", name).strip(" .")
    if len(name) > 255:
        stem, dot, ext = name.rpartition(".")
        name = (stem[: 255 - len(ext) - 1] + dot + ext) if dot else name[:255]
    return name


def _check_content(path: Path, ext: str) -> None:
    if ext == ".pdf":
        with open(path, "rb") as f:
            if f.read(5) != b"%PDF-":
                raise ResumeUploadError(415, "File content is not a PDF")
        return
    try:
        if not zipfile.is_zipfile(path):
            raise ResumeUploadError(415, "File content is not a DOCX document")
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
            if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                raise ResumeUploadError(415, "File content is not a DOCX document")
            if sum(i.file_size for i in z.infolist()) > MAX_UNCOMPRESSED_DOCX:
                raise ResumeUploadError(413, "Document expands to an unreasonable size")
    except zipfile.BadZipFile:
        raise ResumeUploadError(415, "File content is not a DOCX document") from None


def save_upload(src: BinaryIO, filename: str, resume_dir: Path, max_bytes: int) -> StoredFile:
    """Stream ``src`` to disk, enforcing type and size, and move it to its content-addressed name.

    The returned path is final; the caller must delete it if the database insert fails
    (unless the file already existed, see ``existed``).
    """
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED:
        raise ResumeUploadError(415, "Only PDF and DOCX resumes are supported")

    tmp = resume_dir / f".upload-{secrets.token_hex(8)}"
    digest = hashlib.sha256()
    size = 0
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as out:
            while chunk := src.read(CHUNK):
                size += len(chunk)
                if size > max_bytes:
                    raise ResumeUploadError(413, f"Resume exceeds the {max_bytes // (1024 * 1024)} MB limit")
                digest.update(chunk)
                out.write(chunk)
        if size == 0:
            raise ResumeUploadError(400, "Uploaded file is empty")
        _check_content(tmp, ext)
        sha = digest.hexdigest()
        final = resume_dir / f"{sha}{ext}"
        os.replace(tmp, final)
        return StoredFile(final, sha, size, ALLOWED[ext], ext)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def sha256_of(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()
