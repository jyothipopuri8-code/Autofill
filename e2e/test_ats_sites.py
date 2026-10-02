import re

import pytest

pytestmark = pytest.mark.e2e


def fill_all(s):
    s.start()
    s.wait_ready()
    s.click("Fill")
    s.wait_filled()


def test_greenhouse_like_page_is_detected_and_custom_dropdowns_are_filled(session, agent):
    s = session("greenhouse.html")
    fill_all(s)
    page = s.page
    app = agent.api("GET", "/api/v1/sessions").json()[0]["application"]
    assert app["ats"] == "GREENHOUSE" and app["company"] == "Initech" and "Staff Security Engineer" in app["job_title"]
    assert page.input_value("#first_name") == "Jane" and page.input_value("#email") == "jane.doe@example.com"
    assert page.evaluate("document.getElementById('resume').files[0]?.name") == "Jane.pdf"
    # react-select style dropdown: the choice is rendered next to the input, not stored in it.
    assert page.locator("#sel-auth [data-singlevalue]").inner_text() == "Yes"
    assert page.evaluate("window.__submitClicks") == 0


def test_a_dropdown_without_a_literal_match_is_read_then_matched_by_the_agent(session, agent):
    # The resume says "Bachelor of Science"; the dropdown only offers "Bachelor's Degree". The filler reads the
    # real list, hands it to the agent, and the agent maps it (never a guess made in the page).
    s = session("greenhouse.html")
    fill_all(s)
    assert s.page.locator("#sel-edu [data-singlevalue]").inner_text() == "Bachelor's Degree"
    assert "Nothing needs your attention" in s.panel_text()


WORKDAY_FILLED = """() => ({
  fn: document.getElementById('fn')?.value, ln: document.getElementById('ln')?.value,
  em: document.getElementById('em')?.value, ph: document.getElementById('ph')?.value,
  country: document.getElementById('country')?.textContent.trim(),
})"""


def click_next(page, s, n):
    page.click("#next")  # the user's own click: the agent never presses Next
    s.wait_page(n)


def test_workday_like_multi_step_application(session, agent):
    s = session("workday.html")
    fill_all(s)
    page = s.page
    v = page.evaluate(WORKDAY_FILLED)
    assert (v["fn"], v["ln"], v["em"]) == ("Jane", "Doe", "jane.doe@example.com")
    assert re.sub(r"\D", "", v["ph"]) == "5551234567"
    assert v["country"] == "United States of America"
    assert page.evaluate("window.__nextClicks") == 0, "the agent must never advance the application"

    # Next page of the same application, same URL: the panel notices the new step by itself.
    click_next(page, s, 1)
    s.page.locator("[data-autofill-agent] >> text=Add 1 more").wait_for(timeout=20000)
    assert "Your resume has 2 work experience entries; this page shows 1" in s.panel_text()
    s.click("Add 1 more")
    page.wait_for_selector("[data-automation-id='workExperience-2']")
    s.page.locator("[data-autofill-agent] .chips").wait_for()
    s.click("Fill")
    s.wait_filled()
    titles = page.evaluate("[...document.querySelectorAll('[data-automation-id=jobTitle]')].map(e => e.value)")
    assert titles == ["Senior Security Engineer", "Security Analyst"]
    assert page.input_value("#from1") == "01/2021" and page.input_value("#from2") == "06/2018"
    assert page.input_value("#to2") == "12/2020"
    assert page.input_value("#co2") == "Acme Corp"
    assert page.evaluate("document.getElementById('resume').files[0]?.name") == "Jane.pdf"
    assert page.evaluate("window.__nextClicks") == 1  # only the user's click

    # Third step: radio, salary question (needs the user) and a sensitive dropdown (left alone).
    click_next(page, s, 2)
    s.click("Fill")
    s.wait_filled()
    assert page.is_checked("input[name=auth][value=Yes]")
    assert page.input_value("#sal") == "" and page.input_value("#vet") == ""

    # Review step: only optional questions are blank, so the checklist is green, and it never claims submission.
    page.click("#next")  # the review step has no fields, so the panel stays on the same page number
    page.wait_for_selector("text=Check everything, then submit")
    s.click("Final review checklist")
    box = s.page.locator("[data-autofill-agent] .banner", has_text="READY FOR USER REVIEW")
    box.wait_for()
    assert "does not mean the application has been submitted" in box.inner_text()
    assert page.evaluate("window.__submitClicks") == 0


def test_multi_page_application_keeps_its_session_across_real_navigations(session, agent):
    s = session("multipage_1.html")
    fill_all(s)
    page = s.page
    assert page.input_value("#fn") == "Jane" and page.input_value("#em") == "jane.doe@example.com"
    page.click("#next")  # a real navigation to step 2
    page.wait_for_url(re.compile("multipage_2"))
    s.wait_ready()
    sessions = agent.api("GET", "/api/v1/sessions").json()
    assert len(sessions) == 1 and sessions[0]["current_page_index"] >= 0
    s.click("Fill")
    s.wait_filled()
    assert re.sub(r"\D", "", page.input_value("#ph")) == "5551234567" and page.input_value("#city") == "Austin"
    assert page.input_value("#why") == ""
    assert page.evaluate("window.__submitClicks") == 0
