import json
import re

import pytest

pytestmark = pytest.mark.e2e


def real_errors(page):
    """Console noise that is not just the browser logging an expected 4xx (we send invalid input on purpose)."""
    return [e for e in page.errors if "Failed to load resource" not in e]


def test_profile_and_sensitive_settings_are_saved_through_the_dashboard(dash, agent):
    dash.click("#tabs button[data-tab=profile]")
    dash.wait_for_selector("#profile-form [data-f=first_name]")
    assert dash.input_value("[data-f=first_name]") == "Jane"  # seeded profile is shown
    dash.fill("[data-f=first_name]", "Janet")
    dash.fill("[data-f=city]", "Dallas")
    dash.select_option("[data-f=willing_to_relocate]", "true")
    dash.fill("[data-f=available_start_date]", "2026-12-01")
    dash.fill("[data-f=middle_name]", "")
    dash.click("#profile-save")
    dash.wait_for_selector("#profile-msg.ok")
    p = agent.api("GET", "/api/v1/profile").json()
    assert p["first_name"] == "Janet" and p["city"] == "Dallas" and p["willing_to_relocate"] is True and p["available_start_date"] == "2026-12-01"

    dash.fill("[data-f=email]", "not-an-email")
    dash.click("#profile-save")
    dash.wait_for_selector("#profile-msg.err")
    assert "email" in dash.inner_text("#profile-msg").lower()

    # Sensitive answers default to "ask me"; "always answer" needs an explicit value.
    row = dash.locator("#sensitive-list li", has_text="Veteran status")
    assert row.locator("select").input_value() == "ASK_ME"
    row.locator("select").select_option("AUTOFILL")
    row.locator("input[type=text]").fill("I decline to self-identify")
    row.get_by_text("Save").click()
    dash.wait_for_selector("#sensitive-msg.ok")
    prefs = {x["field"]: x for x in agent.api("GET", "/api/v1/profile/sensitive").json()}
    assert prefs["veteran_status"]["policy"] == "AUTOFILL" and prefs["veteran_status"]["value"] == "I decline to self-identify"
    assert not real_errors(dash), dash.errors


def test_answer_library_and_remembered_answers(dash, agent):
    dash.click("#tabs button[data-tab=answers]")
    dash.fill("#a-key", "desired_salary")
    dash.fill("#a-category", "compensation")
    dash.select_option("#a-policy", "AUTOFILL")
    dash.fill("#a-value", "150000")
    dash.click("#a-save")
    dash.wait_for_selector("#library-list li:has-text('desired_salary')")
    stored = agent.api("GET", "/api/v1/answers/desired_salary").json()
    assert stored["value"] == "150000" and stored["policy"] == "AUTOFILL"
    dash.fill("#a-key", "veteran_status")
    dash.click("#a-save")
    dash.wait_for_selector("#a-msg.err")  # sensitive keys belong under the profile's sensitive settings

    # Seed one remembered answer through a real session, then forget it in the UI.
    sid = agent.api("POST", "/api/v1/sessions", json={"company": "Acme", "job_title": "Engineer", "url": "https://example.com/j/1"}).json()["id"]
    agent.api("POST", f"/api/v1/sessions/{sid}/analyze", json={"page_index": 0, "fields": [{"key": "q", "kind": "textarea", "label": "Why do you want to work here?", "required": True}]})
    agent.api("POST", f"/api/v1/sessions/{sid}/answers", json={"page_index": 0, "field_key": "q", "value": "The mission.", "remember": True})
    dash.click("#tabs button[data-tab=history]")
    dash.click("#tabs button[data-tab=answers]")
    dash.wait_for_selector("#memory-list li:has-text('The mission.')")
    dash.once("dialog", lambda d: d.accept())
    dash.click("#memory-list li >> text=Forget")
    dash.wait_for_selector("#memory-list li:has-text('Nothing remembered yet')")
    assert agent.api("GET", "/api/v1/memory").json() == []
    assert not real_errors(dash), dash.errors


def test_application_history_status_and_details(dash, agent):
    sid = agent.api("POST", "/api/v1/sessions", json={"company": "Initech", "job_title": "Staff Engineer", "url": "https://boards.greenhouse.io/initech/jobs/9", "ats": "greenhouse"}).json()["id"]
    agent.api("POST", f"/api/v1/sessions/{sid}/analyze", json={"page_index": 0, "fields": [{"key": "fn", "kind": "text", "label": "First Name", "required": True}]})
    dash.click("#tabs button[data-tab=history]")
    card = dash.locator("#h-list li", has_text="Initech")
    card.wait_for()
    card.locator("select").select_option("INTERVIEW")
    dash.wait_for_selector("#h-msg.ok")
    app = agent.api("GET", "/api/v1/applications").json()[0]
    assert app["status"] == "INTERVIEW"
    card.get_by_text("Details").click()
    card.locator("dd", has_text=re.compile(r"^Jane$")).wait_for()  # the answer the agent prepared for First Name
    dash.fill("#h-search", "nomatch")
    dash.press("#h-search", "Enter")
    dash.wait_for_selector("#h-list li:has-text('No applications yet')")
    assert not real_errors(dash), dash.errors


def test_settings_mode_export_and_erase(dash, agent, tmp_path):
    dash.click("#tabs button[data-tab=settings]")
    dash.wait_for_selector("#mode-box input[value=STANDARD]")
    assert dash.is_checked("#mode-box input[value=SAFE]")
    dash.check("#mode-box input[value=STANDARD]")
    dash.wait_for_selector("#mode-msg.ok")
    assert agent.api("GET", "/api/v1/settings").json()["mode"] == "STANDARD"

    with dash.expect_download() as dl:
        dash.click("#export")
    path = tmp_path / "export.json"
    dl.value.save_as(path)
    data = json.loads(path.read_text())
    assert data["profile"]["first_name"] == "Jane" and data["resumes"][0]["filename"] == "Jane.pdf"

    # Erasing needs the phrase typed by the user.
    dash.select_option("#erase-scope", "all")
    dash.once("dialog", lambda d: d.accept())
    dash.fill("#erase-confirm", "yes please")
    dash.click("#erase")
    dash.wait_for_selector("#erase-msg.err")
    assert agent.api("GET", "/api/v1/profile").json()["first_name"] == "Jane"
    dash.once("dialog", lambda d: d.accept())
    dash.fill("#erase-confirm", "DELETE MY DATA")
    dash.click("#erase")
    dash.wait_for_selector("#erase-msg.ok")
    assert agent.api("GET", "/api/v1/resumes").json() == []
    assert not real_errors(dash), dash.errors
