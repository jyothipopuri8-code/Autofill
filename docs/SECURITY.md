# Security model

The agent holds personal data (contact details, work authorization, resumes). The design goal is that this data
is reachable only by you, on your own computer, and only does what you can see it do. This page lists what is
enforced, where, and which test proves it. Anything not listed here is not a guarantee.

## What is protected, and from whom

| Threat | Defence | Enforced by |
|---|---|---|
| A website reads your data from the local agent | Agent binds to `127.0.0.1` only (refuses other hosts at startup); every endpoint except `/health` needs the install token; requests carrying an unregistered `Origin` get 403; CORS is limited to the extension's origin | `test_every_api_route_requires_the_token`, `test_cors_preflight_only_for_the_extension` |
| DNS rebinding (a hostile domain that resolves to 127.0.0.1) | `Host` header allow-list | `test_dns_rebinding_host_headers_are_refused` |
| A website talks to the agent through the extension | The page-side script has no network access to the agent. All calls go through the extension's service worker, which accepts only an explicit allow-list of endpoints from the page-side script (no profile, answers, resume data, history, settings writes, deletes or exports) | `extension/test/allowlist.test.mjs` |
| A website reads or clicks the Autofill panel | Closed shadow root; panel text is always inserted as text, never HTML; panel buttons ignore script-made (untrusted) clicks | `e2e/test_hostile_page.py` |
| The agent fills more than you intended | Safe mode (default) fills nothing until you click *Fill*; Standard fills only ready, non-sensitive fields; Manual assist inserts one field per click. Sensitive and uncertain fields are never bulk-filled in any mode | design, `e2e/test_generic_site.py` |
| Honeypot fields (invisible fields used to catch bots) | Fields a person cannot see (hidden, zero opacity, clipped, off-screen, 1px) are never scanned or filled | `e2e/test_hostile_page.py` |
| Data left in the browser | The token lives in `chrome.storage.local` (extension-private); session state in `chrome.storage.session` (cleared when the browser closes); no profile data is stored in the extension | design |
| Another local user reads the data | Data folder `0700`; database, token, resumes and logs `0600` (on Windows, the per-user `%LOCALAPPDATA%` ACL) | `test_secrets_and_data_are_owner_only` |
| Personal data in logs | Emails, phone numbers, SSNs and tokens are redacted from every log line; log files are private | `test_logs_never_contain_personal_values_or_tokens` |
| Malicious uploads | Resume uploads are content-checked (PDF/DOCX only), size-limited, stored under their SHA-256 (the client's filename never touches the filesystem), and parsed in-process with `defusedxml`; a broken file fails cleanly | `test_hostile_upload_names_never_reach_the_filesystem`, `test_files_that_are_not_resumes_are_rejected_at_upload`, `test_a_broken_pdf_fails_cleanly_when_parsed` |
| Oversized requests | JSON bodies capped at 8 MB, uploads at the resume limit plus 1 MB; refused before processing | `test_oversized_bodies_are_refused_before_processing` |
| Information leaks through errors or docs | Unhandled errors return a generic 500; API docs are off unless `AUTOFILL_DEVELOPER_MODE=true` | `test_unhandled_errors_do_not_leak_internals`, `test_api_docs_are_off_by_default` |
| The review page reading other files | Static serving is confined to the UI folder | `test_static_ui_cannot_be_used_to_read_other_files` |
| Stolen or leaked token | `python -m autofill_agent token --rotate` replaces it (browsers must be re-paired) | `test_token_rotation_replaces_the_token` |

Response headers on everything: strict `Content-Security-Policy` (the review page allows only its own scripts and styles; the API allows nothing),
`X-Content-Type-Options: nosniff`, `Cache-Control: no-store`, `Referrer-Policy: no-referrer`,
`Cross-Origin-Resource-Policy` and `Cross-Origin-Opener-Policy: same-origin`, restrictive `Permissions-Policy`
(`test_security_headers_on_api_and_ui`).

## Extension permissions

Fixed in the manifest (`test_extension_manifest_asks_for_the_minimum`):

- `storage`, `scripting`, `activeTab`.
- Host access to `http://127.0.0.1:8765/*` only (the agent).
- Access to a job site is **optional** and requested per site, from the popup, when you choose to use the agent there. There are no
  static content scripts, so the extension does not run on any site you have not approved.

## The agent never does these things

- Submit an application. A submit click by you is observed so the agent can ask whether it went through; it is never performed by the agent.
- Accept legal or consent statements, sign, or fill passwords, security answers or CAPTCHAs.
- Fill a field it is not sure about. Uncertain questions go to a "needs your attention" list.
- Overwrite what you typed (ownership tracking uses trusted input events only).
- Invent facts. Answers come from your verified profile and resume; the optional local AI is off by default, only sees your verified resume and the job description, and a draft that introduces facts not present in them is rejected and always needs your review.

## Prompt injection

Everything on a job page is untrusted input, including question text and job descriptions. The deterministic mapping layer does not
interpret page text as instructions. The optional AI drafting path (off by default) treats page text as data, never gets tool access,
only produces a draft for you to review, and is checked against your resume for invented facts.

## Known limits (be aware)

- The install token is a bearer secret. Anyone who can read your user's data folder, or run code as you, can read it. The defence against
  that is your operating system account, not this software.
- Another program running as you on the same computer can call the agent if it has the token. It cannot get it from a web page.
- The agent protects data at rest only through OS file permissions. The database is not encrypted; use full-disk encryption (BitLocker / FileVault / LUKS).
- A browser extension with "all sites" access is a powerful thing. Review the permissions at `chrome://extensions` and only enable sites you use.
- Windows file permissions and the packaged executable have not been tested on a real Windows machine yet. See [WINDOWS.md](WINDOWS.md).

## Reporting a problem

Open a private security advisory on the GitHub repository rather than a public issue, and do not include real personal data in reports.
