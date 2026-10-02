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

## Run the backend

```bash
cd backend
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
python -m autofill_agent          # listens on 127.0.0.1:8765
pytest
```

Data (database, resumes, logs, install token) lives in `~/.local/share/autofill-agent` (Windows: `%LOCALAPPDATA%\AutofillAgent`). Override with `AUTOFILL_DATA_DIR`.

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
