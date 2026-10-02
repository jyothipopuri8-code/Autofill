# Real-site validation checklist (Phase 43)

The automated tests use mock pages that imitate Greenhouse, Lever, Workday, Ashby, iCIMS and SmartRecruiters markup. **They do not replace
trying real sites**, which change their markup, add bot protection and behave differently in ways a mock cannot show. This checklist is
for you to run on your own computer, with your own data, **without submitting anything**. Record the results in the table at the bottom.

## Ground rules

- Use a real job you would actually consider, but stop before the final Submit button on every test. You can still close the tab afterwards.
- Safe mode first. Move to Standard only after Safe mode behaved correctly on that site.
- If the agent does anything on the "must never" list below, stop, note the site, field and what you saw, and report it.

## Before you start

- [ ] Agent running (`/api/v1/health` shows `ok`), extension paired, resume uploaded and **verified** at `/ui/`.
- [ ] Profile has your name, email, phone, location, links and your work-authorization answers (or left blank on purpose).
- [ ] You approved the site's access from the extension popup.

## Per site: do each step and tick it

1. [ ] **Detect.** Open the application page. Start the agent. The job title and company shown in the panel are correct.
2. [ ] **Scan.** The field count looks about right. Anything obvious missed (a field on the page that is not in the panel's counts)?
3. [ ] **Fill (Safe mode).** Click *Fill*. Name, email, phone, location and links are correct. Nothing was typed before you clicked.
4. [ ] **Resume.** The resume file is attached once, and it is the one you expect (check the file name shown by the site).
5. [ ] **Dropdowns and radios.** Country, state, work authorization, sponsorship, degree: right option chosen, or left for you with a reason.
6. [ ] **Your typing wins.** Type a different value in a filled field, click *Rescan* then *Fill* again. Your value stays.
7. [ ] **Undo.** *Undo last fill* removes only what the agent wrote.
8. [ ] **Needs attention.** Custom questions, essay boxes, EEO/demographic questions, CAPTCHA and legal checkboxes are listed for you, not filled.
9. [ ] **Repeating sections** (work experience, education): the right number of entries, dates correct, no invented dates or employers.
10. [ ] **Multi-page.** Click the site's *Next*. The panel says it is checking the next page, then shows that page's fields.
11. [ ] **Final review.** The checklist is accurate: it says NOT READY while required fields are empty, and READY only when they are all complete.
12. [ ] **Stop.** Close the tab without submitting. Reopen the job later: the panel offers to continue the saved session.
13. [ ] **History.** `/ui/` shows the application as In progress, not Submitted.

## Must never happen

- A submit/apply button is clicked by the agent.
- A password, security answer, CAPTCHA, signature or "I agree" box is filled or ticked.
- A value is invented (a date, an employer, a salary, a degree, a skills claim not in your resume).
- A value you typed is overwritten.
- A field you cannot see on the page is filled.
- Anything about your data appears in a request to a domain other than the agent (check DevTools > Network if you want to confirm).

## Sites to try

Pick at least one posting per system you expect to use. Mark N/A where you have no job to test.

| Site / ATS | Example URL pattern | Date tested | Result (pass / issues) | Notes |
|---|---|---|---|---|
| Greenhouse | `boards.greenhouse.io/...`, `job-boards.greenhouse.io/...` | | | |
| Lever | `jobs.lever.co/.../apply` | | | |
| Workday | `*.myworkdayjobs.com/...` | | | |
| Ashby | `jobs.ashbyhq.com/...` | | | |
| iCIMS | `*.icims.com/jobs/...` | | | |
| SmartRecruiters | `jobs.smartrecruiters.com/...` | | | |
| A company's own careers page (generic form) | | | | |
| A site with an embedded ATS in an iframe | | | | |

## Reporting an issue

For each failure: the site name and URL (no personal data in screenshots), the field label as shown on the page, what you expected,
what happened, and the agent log lines around that time (`%LOCALAPPDATA%\AutofillAgent\logs` on Windows; redacted of personal values).
Sites that block extensions, require login first, or load the form in a cross-origin iframe are known limits and are reported in the panel rather than worked around.
