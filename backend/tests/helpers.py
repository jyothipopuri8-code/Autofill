"""Build tiny but valid PDF and DOCX resumes for tests."""

from __future__ import annotations

import io
import zipfile
from xml.sax.saxutils import escape


def make_pdf(lines: list[str]) -> bytes:
    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    pages = [lines[i : i + 50] for i in range(0, max(len(lines), 1), 50)]
    objs: list[bytes] = []
    n_pages = len(pages)
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(n_pages))
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode())
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    for i, page in enumerate(pages):
        ops = ["BT", "/F1 11 Tf"]
        y = 760
        for line in page:
            ops.append(f"1 0 0 1 50 {y} Tm ({esc(line)}) Tj")
            y -= 14
        ops.append("ET")
        stream = "\n".join(ops).encode("cp1252", "replace")
        objs.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {5 + 2 * i} 0 R "
            f"/Resources << /Font << /F1 3 0 R >> >> >>".encode()
        )
        objs.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n".encode() + b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def make_docx(lines: list[str]) -> bytes:
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    paras = "".join(f'<w:p><w:r><w:t xml:space="preserve">{escape(line)}</w:t></w:r></w:p>' for line in lines)
    doc = f'<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="{ns}"><w:body>{paras}</w:body></w:document>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("word/document.xml", doc)
    return buf.getvalue()


SAMPLE_RESUME = [
    "Jane Q. Doe",
    "Austin, TX | jane.doe@example.com | (555) 123-4567",
    "linkedin.com/in/janedoe | github.com/janedoe",
    "",
    "SUMMARY",
    "Security engineer with 6 years of experience in detection and response.",
    "",
    "SKILLS",
    "Languages: Python, Go",
    "Tools: Splunk, AWS, Incident Response, SIEM",
    "",
    "EXPERIENCE",
    "Senior Security Engineer | CrowdStrike | Austin, TX",
    "Jan 2021 - Present",
    "• Built detection pipelines",
    "• Led incident response",
    "Security Analyst | Acme Corp | Dallas, TX",
    "06/2018 - 12/2020",
    "• Triaged alerts",
    "",
    "EDUCATION",
    "University of Texas at Austin",
    "Bachelor of Science in Computer Science, May 2018",
    "",
    "CERTIFICATIONS",
    "CISSP (Issued 2020)",
    "AWS Certified Security - Specialty, 2022",
    "",
    "LANGUAGES",
    "English (Native), Spanish (Professional), French",
]
