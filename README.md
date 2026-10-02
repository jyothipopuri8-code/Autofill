# Local Job Application Autofill Agent

A privacy-focused assistant that fills repetitive job-application fields from locally stored, verified data. It never submits an application; the applicant always reviews and submits.

See the design doc in the project thread for the full spec and 43-phase roadmap.

## Layout

```
backend/     FastAPI localhost agent (Python 3.11+), SQLite storage
extension/   Chrome/Edge Manifest V3 extension (TypeScript), Phase 10+
docs/        Notes and decisions
```

## Status

| Phase | Scope | State |
|---|---|---|
| 1 | Repo structure, tooling | done |
| 2 | FastAPI backend, 127.0.0.1 binding, health, config, logging, token auth | done |
| 3 | SQLite models: profile, sensitive prefs, resume, library/approved answers, application, session, session answers | done |
| 4 | Profile manager API (`/api/v1/profile`, sensitive-field policies) | done |
| 5 | Answer library API (`/api/v1/answers`) | done |
| 6 | Resume manager API (`/api/v1/resumes`: upload, SHA-256, select, archive, integrity check, delete) | done |
| 7 | Resume parser: PDF/DOCX text extraction and structured extraction (contact, summary, skills, experience, education, certifications, languages) | done |
| 8 | Resume verification: correction/verify API and a local review page at `/ui/` | done |
| 9 | Application sessions: isolated, persisted, recoverable after restart | done |
| 12-15 | Field normalization, mapping engine, conflict detection, confidence | done (backend) |
| 28 | Date engine (per-site date formats) | done |
| 31 | Manual question queue (`/sessions/{id}/attention`) | done (backend) |
| 33 | Question memory (approved answers with reuse rules) | done |
| 34 | Custom question engine (grounded in the resume) | done |
| 35 | Optional local AI (Ollama, off by default, grounding check) | done |
| 38-39 | Application history and duplicate detection | done |

## Run the backend

```bash
cd backend
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
python -m autofill_agent          # listens on 127.0.0.1:8765
pytest
```

Data (database, resumes, logs, install token) lives in `~/.local/share/autofill-agent` (Windows: `%LOCALAPPDATA%\AutofillAgent`). Override with `AUTOFILL_DATA_DIR`.

## API (all endpoints except `/health` need `Authorization: Bearer <install token>`)

| Endpoint | Purpose |
|---|---|
| `GET/PATCH/DELETE /api/v1/profile` | Fixed profile; PATCH changes only the fields sent, `""`/`null` clears a field |
| `GET /api/v1/profile/sensitive`, `PUT .../sensitive/{field}` | AUTOFILL / ASK_ME / NEVER_FILL per sensitive field (default ASK_ME) |
| `GET/PUT/DELETE /api/v1/answers/{key}`, `GET /api/v1/answers` | Reusable answers with policy and verification status |
| `POST /api/v1/resumes` (multipart `file`) | Upload PDF/DOCX (10 MB max, content-checked, stored as `<sha256>.<ext>`) |
| `GET /api/v1/resumes`, `/current`, `/{id}` | List, current, detail (no on-disk paths exposed) |
| `POST /api/v1/resumes/{id}/set-current\|archive\|unarchive` | Select / archive |
| `GET /api/v1/resumes/{id}/integrity` | Confirm the file exists and still matches its SHA-256 |
| `POST /api/v1/resumes/{id}/parse` | Extract structured data; refuses if the stored file is missing or no longer matches its hash |
| `GET /api/v1/resumes/{id}/data` | Raw parse, your corrections, and the `effective_data` to use |
| `PUT /api/v1/resumes/{id}/verified-data` | Save corrections (draft); editing a verified resume un-verifies it |
| `POST /api/v1/resumes/{id}/verify` | Confirm the data is accurate (uses corrections, else the parse as-is) |
| `DELETE /api/v1/resumes/{id}` | Remove record and file; application history keeps its filename/hash snapshot |

### Sessions, answers and history

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/sessions` | Start an application session (409 `POSSIBLE_DUPLICATE` with matches unless `force`) |
| `GET /api/v1/sessions[?status=&url=]` | Incomplete sessions for recovery |
| `POST /api/v1/sessions/{id}/analyze` | Send detected fields for a page; get per-field answer, source, confidence, action |
| `POST /api/v1/sessions/{id}/answers` | Your answer for this application (optionally remembered) |
| `POST /api/v1/sessions/{id}/conflicts/resolve` | Choose profile, resume or a custom value when they disagree |
| `POST /api/v1/sessions/{id}/resume` | Explicitly choose the resume after a mismatch |
| `GET /api/v1/sessions/{id}/resume-file` | The exact verified resume (hash-checked) for attaching |
| `POST /api/v1/sessions/{id}/fill-report`, `/validate` | Report fills; classify every field after filling |
| `GET /api/v1/sessions/{id}/attention`, `/final-review` | "Needs your attention" queue; final completeness check |
| `GET/PATCH/DELETE /api/v1/applications` | History; only you set final statuses |
| `GET/PUT /api/v1/settings` | Operating mode: SAFE (default), STANDARD, MANUAL_ASSIST |

Answer priority per field: your answer for this application, verified profile/library, the session's tailored resume, a previously approved answer, a deterministic calculation, an optional grounded AI draft, then ask you. Passwords, legal acknowledgements, signatures, CAPTCHAs and non-resume uploads are never filled.

Optional local AI: set `AUTOFILL_OLLAMA_ENABLED=true` (and `AUTOFILL_OLLAMA_MODEL`) to draft free-text answers with a local Ollama server. Drafts only use your verified resume and the job description, are rejected if they introduce facts that are not in them, and always need your review.

## Review page

With the agent running, open <http://127.0.0.1:8765/ui/>, paste the installation token (the file `install_token` in the data folder; the path is printed at startup), upload a resume, click **Parse**, correct anything wrong and click **Verify**. The page is plain HTML/JS served by the agent with a strict CSP (own files only, no inline script), builds the DOM with `textContent`, and keeps the token in the tab's session storage only.

## Parser notes

Parsing is deterministic and offline (pypdf for PDF, defusedxml for DOCX). It is a best guess: anything it cannot read is left empty with a warning, never invented (for example certification numbers, language proficiency, or undated positions). Scanned/image-only PDFs are rejected because there is no OCR. Dates are normalized to `YYYY-MM` (or `YYYY` when only a year is given).

## Security foundations in place

- Host is validated to be exactly `127.0.0.1`; other values refuse to start.
- Random install token (0600 file), required as `Authorization: Bearer` on every endpoint except `/api/v1/health`.
- Requests with a non-registered `Origin` get 403; CORS only for `AUTOFILL_ALLOWED_ORIGINS` (extension origins only); `Host` allow-list against DNS rebinding.
- Strict response headers (CSP, nosniff, no-store); API docs disabled unless `AUTOFILL_DEVELOPER_MODE=true`.
- Log redaction of emails, phones, SSNs and tokens.

## Data-model notes

- Work authorization and sensitive fields are nullable: `NULL` means "ask the user", never a guess. Sensitive fields default to policy `ASK_ME`.
- Resumes are identified by SHA-256; at most one is `is_current`. Applications snapshot resume filename and hash so history survives resume deletion.
- Session answers keep source, confidence, status and ownership state, with a unique row per field per page.
