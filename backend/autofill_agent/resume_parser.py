"""Deterministic resume text extraction and structuring (doc §5 step 3).

The extraction is heuristic and deliberately conservative: anything that can't be
read with reasonable confidence is left empty (never invented) and the user
corrects it in the verification step. Nothing here makes network calls.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

from defusedxml import ElementTree as SafeET
from pypdf import PdfReader
from pypdf.errors import PyPdfError

from autofill_agent.resume_schema import (
    Certification,
    Contact,
    Education,
    Experience,
    Language,
    ParsedResume,
)

MAX_PDF_PAGES = 30
MAX_TEXT_CHARS = 200_000


class ResumeParseError(Exception):
    """The file could not be turned into text (corrupt, encrypted, or image-only)."""


# --- Text extraction ---------------------------------------------------------


def extract_text(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".pdf":
        text = _pdf_text(path)
    elif ext == ".docx":
        text = _docx_text(path)
    else:
        raise ResumeParseError("Only PDF and DOCX resumes can be parsed")
    text = text[:MAX_TEXT_CHARS]
    if not text.strip():
        raise ResumeParseError(
            "No selectable text was found. Scanned or image-only resumes are not supported (no OCR); "
            "export a text-based PDF or DOCX instead."
        )
    return text


def _pdf_text(path: Path) -> str:
    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted and not reader.decrypt(""):
            raise ResumeParseError("This PDF is password-protected")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise ResumeParseError(f"PDF has more than {MAX_PDF_PAGES} pages")
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except ResumeParseError:
        raise
    except (PyPdfError, ValueError, KeyError, OSError, RecursionError) as e:
        raise ResumeParseError(f"Could not read this PDF ({type(e).__name__})") from None


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _docx_text(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as z:
            root = SafeET.fromstring(z.read("word/document.xml"))
    except (zipfile.BadZipFile, KeyError, SafeET.ParseError, ValueError, OSError) as e:
        raise ResumeParseError(f"Could not read this DOCX ({type(e).__name__})") from None
    except Exception as e:  # defusedxml raises its own errors for entity bombs / external entities
        raise ResumeParseError(f"Could not read this DOCX ({type(e).__name__})") from None

    lines: list[str] = []
    for para in root.iter(f"{_W}p"):
        parts: list[str] = []
        for el in para.iter():
            if el.tag == f"{_W}t" and el.text:
                parts.append(el.text)
            elif el.tag == f"{_W}tab":
                parts.append("\t")
            elif el.tag in (f"{_W}br", f"{_W}cr"):
                parts.append("\n")
        lines.append("".join(parts))
    return "\n".join(lines)


# --- Patterns ----------------------------------------------------------------

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
_PHONE = re.compile(r"(?<!\d)(?:\+?\d{1,3}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)")
_LINKEDIN = re.compile(r"(?:https?://)?(?:www\.)?linkedin\.com/in/[\w\-%]+/?", re.I)
_GITHUB = re.compile(r"(?:https?://)?(?:www\.)?github\.com/[\w\-]+/?", re.I)
_URL = re.compile(r"(?:https?://|www\.)[^\s|,;]+", re.I)
_CITY_ST = re.compile(r"^[A-Z][A-Za-z.'\- ]+,\s*[A-Z]{2}$")
_TRAILING_CITY_ST = re.compile(r",\s*[A-Z][A-Za-z.'\-]+(?:\s[A-Z][A-Za-z.'\-]+)*,\s*[A-Z]{2}$")

_MONTHS = {m: i + 1 for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split())}
_MONTH = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?"
_DATE = rf"(?:{_MONTH}\s+\d{{4}}|\d{{1,2}}/\d{{4}}|\d{{4}})"
_RANGE = re.compile(
    rf"(?P<start>{_DATE})\s*(?:-|–|—|to)\s*(?P<end>{_DATE}|Present|Current|Now|Ongoing)\b", re.I
)
_SINGLE_DATE = re.compile(_DATE, re.I)

_BULLET = re.compile(r"^\s*(?:[•●▪■◦·]\s*|[-–—*]\s+)")

_SECTIONS: dict[str, set[str]] = {
    "summary": {"summary", "professional summary", "profile", "professional profile", "objective", "career objective", "about me", "about"},
    "skills": {"skills", "technical skills", "core competencies", "key skills", "skills & tools", "skills and tools", "technologies"},
    "experience": {"experience", "work experience", "professional experience", "employment history", "work history", "employment", "relevant experience"},
    "education": {"education", "education & training", "education and training", "academic background"},
    "certifications": {"certifications", "certificates", "licenses & certifications", "certifications & licenses", "licenses", "certifications and licenses"},
    "languages": {"languages", "language skills"},
    "other": {"projects", "publications", "awards", "honors", "volunteer experience", "volunteering", "interests", "references", "activities", "patents"},
}
_HEADING_TO_SECTION = {h: s for s, hs in _SECTIONS.items() for h in hs}

_TITLE_WORDS = re.compile(
    r"\b(engineer|developer|analyst|manager|director|architect|administrator|consultant|specialist|intern|"
    r"scientist|lead|officer|coordinator|technician|associate|designer|programmer|vp|president|head|"
    r"researcher|assistant|supervisor|representative)\b",
    re.I,
)
_SCHOOL_WORDS = re.compile(r"\b(university|college|institute|school|academy|polytechnic)\b", re.I)
_DEGREE = re.compile(
    r"(?:Bachelor|Master|Associate|Doctor)(?:'s)?(?:\s+of\s+(?:Science|Arts|Engineering|Fine Arts|Business Administration|Philosophy|Technology)|\s+degree)?"
    r"|\bMBA\b|\bPh\.?D\.?|\b[BM]\.?\s?(?:S|A|Eng)\.?c?\.?(?=[\s,.:]|$)",
    re.I,
)
_NAME = re.compile(r"^[A-Za-z][A-Za-z.'\-]+(?:\s+[A-Za-z][A-Za-z.'\-]+){1,3}$")
_NAME_SUFFIX = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv", "phd", "ph.d.", "mba", "cissp"}


# --- Helpers -----------------------------------------------------------------


def _norm_date(token: str) -> str | None:
    t = token.strip().rstrip(".")
    m = re.fullmatch(r"(\d{4})", t)
    if m:
        return t if 1950 <= int(t) <= 2100 else None
    m = re.fullmatch(r"(\d{1,2})/(\d{4})", t)
    if m:
        mo, yr = int(m[1]), int(m[2])
        return f"{yr}-{mo:02d}" if 1 <= mo <= 12 and 1950 <= yr <= 2100 else None
    m = re.fullmatch(r"([A-Za-z]{3,9})\.?\s+(\d{4})", t)
    if m and m[1][:3].lower() in _MONTHS and 1950 <= int(m[2]) <= 2100:
        return f"{m[2]}-{_MONTHS[m[1][:3].lower()]:02d}"
    return None


def _is_bullet(line: str) -> bool:
    return bool(_BULLET.match(line))


def _strip_bullet(line: str) -> str:
    return _BULLET.sub("", line, count=1).strip()


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip(" \t|,;:–—-•·")


def _split_sections(lines: list[str]) -> tuple[list[str], dict[str, list[str]]]:
    header: list[str] = []
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in lines:
        key = re.sub(r"\s+", " ", line.strip().rstrip(":").strip()).lower()
        if key and len(key) <= 40 and key in _HEADING_TO_SECTION:
            current = _HEADING_TO_SECTION[key]
            sections.setdefault(current, [])
            continue
        if current is None:
            header.append(line)
        else:
            sections[current].append(line)
    return header, sections


def _normalize_url(u: str) -> str:
    u = u.strip().rstrip("/.,;")
    return u if u.lower().startswith("http") else "https://" + u


# --- Section parsers ---------------------------------------------------------


def _parse_contact(header: list[str]) -> Contact:
    block = "\n".join(header)
    c = Contact()

    if m := _EMAIL.search(block):
        c.email = m.group(0)
    scrub = _EMAIL.sub(" ", block)
    if m := _LINKEDIN.search(scrub):
        c.linkedin_url = _normalize_url(m.group(0))
    if m := _GITHUB.search(scrub):
        c.github_url = _normalize_url(m.group(0))
    scrub = _GITHUB.sub(" ", _LINKEDIN.sub(" ", scrub))
    for m in _URL.finditer(scrub):
        c.website_url = _normalize_url(m.group(0))
        break
    scrub = _URL.sub(" ", scrub)
    if m := _PHONE.search(scrub):
        c.phone = _clean(m.group(0))
    scrub = _PHONE.sub(" ", scrub)

    for line in header[:6]:
        for piece in re.split(r"[|•·\n]", line):
            piece = _clean(piece)
            if _CITY_ST.match(piece) and c.location is None and piece in scrub:
                c.location = piece

    for line in header[:5]:
        cand = _clean(line)
        if _NAME.match(cand) and not _SCHOOL_WORDS.search(cand) and not _CITY_ST.match(cand):
            c.full_name = cand
            tokens = [t for t in cand.split() if t.lower() not in _NAME_SUFFIX]
            if len(tokens) >= 2:
                c.first_name, c.last_name = tokens[0], tokens[-1]
            break
    return c


def _parse_skills(lines: list[str]) -> list[str]:
    skills: list[str] = []
    seen: set[str] = set()
    for line in lines:
        line = _strip_bullet(line)
        if ":" in line:
            prefix, _, rest = line.partition(":")
            if len(prefix) <= 40 and "," not in prefix:
                line = rest
        for item in re.split(r"[,;•·|\t]", line):
            item = _clean(item)
            if item and len(item) <= 80 and item.lower() not in seen:
                seen.add(item.lower())
                skills.append(item)
    return skills[:300]


def _split_header_pieces(text: str) -> list[str]:
    pieces = [p for p in (_clean(x) for x in re.split(r"\s+[|–—]\s+|\s+-\s+|\s+at\s+|\|", text)) if p]
    if len(pieces) == 1 and "," in pieces[0]:
        parts = [p.strip() for p in pieces[0].split(",") if p.strip()]
        if len(parts) >= 3 and re.fullmatch(r"[A-Z]{2}", parts[-1]):
            pieces = parts[:-2] + [f"{parts[-2]}, {parts[-1]}"]
        else:
            pieces = parts
    return pieces


def _header_to_fields(header_lines: list[str]) -> tuple[str | None, str | None, str | None]:
    pieces: list[str] = []
    for line in header_lines:
        pieces.extend(_split_header_pieces(line))
    title = next((p for p in pieces if _TITLE_WORDS.search(p)), None) or (pieces[0] if pieces else None)
    rest = [p for p in pieces if p != title]
    location = next((p for p in rest if _CITY_ST.match(p) or re.fullmatch(r"(?i)remote|hybrid", p)), None)
    company = next((p for p in rest if p != location), None)
    return title, company, location


def _parse_experience(lines: list[str], warnings: list[str]) -> list[Experience]:
    entries: list[tuple[Experience, list[str]]] = []
    pending: list[str] = []
    cur: tuple[Experience, list[str]] | None = None

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if _is_bullet(line):
            if cur:
                cur[1].extend(pending)
                cur[1].append(_strip_bullet(line))
            pending = []
            continue
        if m := _RANGE.search(line):
            start = _norm_date(m["start"])
            end_raw = m["end"]
            is_current = end_raw.lower() in {"present", "current", "now", "ongoing"}
            end = None if is_current else _norm_date(end_raw)
            remainder = _clean(re.sub(r"[(\[]\s*[)\]]", " ", _RANGE.sub(" ", line)))
            header_lines = pending + ([remainder] if remainder else [])
            title, company, location = _header_to_fields(header_lines)
            exp = Experience(
                title=title, company=company, location=location,
                start_date=start, end_date=end, current=is_current,
            )
            cur = (exp, [])
            entries.append(cur)
            pending = []
        elif cur and not cur[1] and (len(line) > 100 or line.endswith(".")):
            cur[1].append(line)  # paragraph-style description
        else:
            pending = (pending + [line])[-3:]
    if pending and cur:
        cur[1].extend(pending)

    result = []
    for exp, desc in entries:
        exp.description = "\n".join(desc) or None
        result.append(exp)
    if lines and not result:
        warnings.append("Experience section found but no dated positions could be read.")
    return result[:50]


def _parse_education(lines: list[str]) -> list[Education]:
    entries: list[Education] = []
    cur: Education | None = None
    for raw in lines:
        line = _strip_bullet(raw.strip())
        if not line:
            continue
        has_school = bool(_SCHOOL_WORDS.search(line))
        deg = _DEGREE.search(line)
        if cur is None or (has_school and cur.school) or (deg and cur.degree):
            cur = Education()
            entries.append(cur)

        expected = bool(re.search(r"(?i)\b(expected|anticipated)\b", line))
        text = line
        if m := _RANGE.search(text):
            cur.start_date = _norm_date(m["start"])
            end = _norm_date(m["end"]) if m["end"].lower() not in {"present", "current", "now", "ongoing"} else None
            if expected:
                cur.expected_graduation_date = end
            else:
                cur.graduation_date = end
            text = _RANGE.sub(" ", text)
        else:
            dates = [d for d in (_norm_date(x.group(0)) for x in _SINGLE_DATE.finditer(text)) if d]
            if dates:
                if expected:
                    cur.expected_graduation_date = dates[-1]
                else:
                    cur.graduation_date = dates[-1]
            text = _SINGLE_DATE.sub(" ", text)
        text = re.sub(r"(?i)\b(expected|anticipated|graduated|graduation)\b:?", " ", text)

        if deg and not cur.degree:
            cur.degree = _clean(deg.group(0))
            rest = text[text.lower().find(deg.group(0).lower()) + len(deg.group(0)):] if deg.group(0).lower() in text.lower() else ""
            rest = re.sub(r"^\s*(?:in|,|-|–|—|:|\|)\s*", "", rest)
            field = _clean(rest.split("|")[0])
            if field and not _SCHOOL_WORDS.search(field):
                cur.field_of_study = field
            elif _SCHOOL_WORDS.search(rest) and not cur.school:
                cur.school = _clean(_TRAILING_CITY_ST.sub("", _clean(rest)))
        elif has_school and not cur.school:
            cur.school = _clean(_TRAILING_CITY_ST.sub("", _clean(re.split(r"\s+[|–—]\s+", text)[0])))
    return [e for e in entries if e.school or e.degree][:20]


def _parse_certifications(lines: list[str]) -> list[Certification]:
    certs: list[Certification] = []
    for raw in lines:
        line = _strip_bullet(raw.strip())
        if not line:
            continue
        cert = Certification()
        if m := re.search(r"(?i)\b(?:credential\s+)?(?:license\s+|licence\s+|certificate\s+|cert\.?\s+)?(?:id|no\.?|number|#)\s*[:#]?\s*([A-Za-z0-9][A-Za-z0-9\-]{3,})", line):
            cert.number = m.group(1)
            line = line.replace(m.group(0), " ")
        if m := re.search(rf"(?i)\b(?:expires?|expiration|exp\.?|valid (?:through|until))\s*:?\s*({_DATE})", line):
            cert.expiration_date = _norm_date(m.group(1))
            line = line.replace(m.group(0), " ")
        if m := re.search(rf"(?i)\b(?:issued|obtained|earned)\s*:?\s*({_DATE})", line):
            cert.issued_date = _norm_date(m.group(1))
            line = line.replace(m.group(0), " ")
        elif m := re.search(rf"(?:[,\-–—|(]\s*)({_DATE})\s*\)?\s*$", line):
            cert.issued_date = _norm_date(m.group(1))
            line = line[: m.start()]
        name = re.sub(r"\(\s*\)", " ", line)
        cert.name = _clean(name) or None
        if cert.name:
            certs.append(cert)
    return certs[:50]


def _parse_languages(lines: list[str]) -> list[Language]:
    out: list[Language] = []
    for line in lines:
        for piece in re.split(r"[,;•·|\n]", _strip_bullet(line)):
            piece = _clean(piece)
            if not piece:
                continue
            m = re.match(r"^([A-Za-z][A-Za-z \-]{1,38}?)\s*(?:\(([^)]{1,40})\)|[-–—:]\s*(.{1,40}))?$", piece)
            if not m:
                continue
            out.append(Language(language=_clean(m.group(1)), proficiency=_clean(m.group(2) or m.group(3) or "") or None))
    return out[:30]


# --- Entry points ------------------------------------------------------------


def parse_text(text: str) -> ParsedResume:
    lines = [ln.rstrip() for ln in text.replace("\r", "\n").split("\n")]
    header, sections = _split_sections(lines)
    warnings: list[str] = []

    contact = _parse_contact(header)
    if not contact.email:
        warnings.append("No email address found.")
    if not contact.phone:
        warnings.append("No phone number found.")
    if not contact.full_name:
        warnings.append("Could not determine your name.")

    summary_lines = [ln.strip() for ln in sections.get("summary", []) if ln.strip()]
    experience = _parse_experience(sections.get("experience", []), warnings) if "experience" in sections else []
    education = _parse_education(sections.get("education", [])) if "education" in sections else []
    for label, key in (("experience", "experience"), ("education", "education"), ("skills", "skills")):
        if key not in sections:
            warnings.append(f"No {label} section found.")
    for exp in experience:
        if exp.start_date is None or (exp.end_date is None and not exp.current):
            warnings.append(f"Check dates for '{exp.title or exp.company or 'a position'}'.")
        if not exp.title or not exp.company:
            warnings.append(f"Check title/company for the position starting {exp.start_date or 'unknown'}.")

    return ParsedResume(
        contact=contact,
        summary=" ".join(summary_lines) or None,
        skills=_parse_skills(sections.get("skills", [])),
        experience=experience,
        education=education,
        certifications=_parse_certifications(sections.get("certifications", [])),
        languages=_parse_languages(sections.get("languages", [])),
        warnings=warnings,
    )


def parse_resume_file(path: Path) -> ParsedResume:
    return parse_text(extract_text(path))
