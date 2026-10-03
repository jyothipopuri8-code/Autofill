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


def test_lever_like_page_uses_a_single_full_name_field(session, agent):
    s = session("lever.html")
    fill_all(s)
    page = s.page
    app = agent.api("GET", "/api/v1/sessions").json()[0]["application"]
    assert app["ats"] == "LEVER" and "Application Security Engineer" in app["job_title"]
    assert page.input_value("#name") == "Jane Doe" and page.input_value("#email") == "jane.doe@example.com"
    assert page.input_value("#linkedin") == "https://linkedin.com/in/janedoe"
    assert page.evaluate("document.getElementById('resume').files[0]?.name") == "Jane.pdf"
    assert page.input_value("#q1") == ""
    assert page.evaluate("window.__submitClicks") == 0


def test_repeatable_sections_experience_education_certifications_languages(session, agent):
    s = session("sections.html")
    s.start()
    s.wait_ready()
    page = s.page
    banner = s.panel_text()
    assert "Your resume has 2 work experience entries; this page shows 1" in banner
    assert "Your resume has 2 certification entries; this page shows 1" in banner
    assert "Your resume has 3 language entries; this page shows 1" in banner
    assert "Your resume has 1 education" not in banner  # one entry on the resume, one on the page

    for name, n in (("work experience", 2), ("certification", 2), ("language", 3)):
        before = page.locator(".entry").count()
        s.page.locator("[data-autofill-agent] .banner", has_text=f"Your resume has {n} {name}").get_by_text("Add").click()
        page.wait_for_function("(b) => document.querySelectorAll('.entry').length > b", arg=before)
        s.page.locator("[data-autofill-agent] .wrap[data-phase='ready']").wait_for()
    s.click("Rescan page")
    s.wait_ready()
    s.click("Fill")
    s.wait_filled()

    v = lambda i: page.input_value(f"#{i}")
    assert (v("jt1"), v("co1"), v("sd1")) == ("Senior Security Engineer", "CrowdStrike", "01/2021")
    assert v("ed1") == "", "an ongoing job has no end date"
    assert page.is_checked("#cur1") and not page.is_checked("#cur2")
    assert (v("jt2"), v("co2"), v("sd2"), v("ed2")) == ("Security Analyst", "Acme Corp", "06/2018", "12/2020")
    assert "Triaged alerts" in v("ds2")
    assert v("sc1") == "University of Texas at Austin" and page.input_value("#dg1") == "Bachelor's Degree" and v("gd1") == "05/2018"
    assert v("cn1") == "CISSP" and v("cn2") == "AWS Certified Security - Specialty"
    assert v("ci1") == "" and v("ci2") == "", "a certification year without a month is never turned into a made-up date"
    assert [v("ln_1"), v("ln_2"), v("ln_3")] == ["English", "Spanish", "French"]
    assert [page.input_value("#lp1"), page.input_value("#lp2")] == ["Native", "Professional"] and page.input_value("#lp3") == ""
    assert page.evaluate("document.getElementById('resume').files[0]?.name") == "Jane.pdf"
    assert page.evaluate("window.__submitClicks") == 0


def test_ashby_like_page_yes_no_buttons_and_single_name_field(session, agent):
    s = session("ashby.html")
    fill_all(s)
    page = s.page
    app = agent.api("GET", "/api/v1/sessions").json()[0]["application"]
    assert app["ats"] == "ASHBY" and "Senior Security Engineer" in app["job_title"]
    assert page.input_value("#_systemfield_name") == "Jane Doe"
    assert page.input_value("#_systemfield_email") == "jane.doe@example.com"
    assert page.evaluate("document.getElementById('_systemfield_resume').files[0]?.name") == "Jane.pdf"
    assert page.input_value("#linkedin") == "https://linkedin.com/in/janedoe"
    # Buttons that act as Yes / No: the two work-authorization questions are answered from the profile,
    # the optional relocation question is not something the profile knows, so it is left alone, and the
    # required free-text question is listed for the person.
    answers = page.evaluate("window.__answers()")
    assert answers["q-auth"] == "Yes" and answers["q-sponsor"] == "No" and answers["q-relocate"] is None
    assert "Why do you want to work at Dendrite?" in s.panel_text()
    assert page.input_value("#why") == ""
    assert page.evaluate("window.__submitClicks") == 0


def test_ashby_like_yes_no_choice_made_by_the_person_is_kept(session, agent):
    s = session("ashby.html")
    s.start()
    s.wait_ready()
    s.page.locator("#q-auth button", has_text="No").click()  # a real click by the person
    s.click("Rescan page")
    s.wait_ready()
    s.click("Fill")
    s.wait_filled()
    assert s.page.evaluate("window.__answers()")["q-auth"] == "No"


def test_smartrecruiters_like_web_components_in_open_shadow_roots(session, agent):
    s = session("smartrecruiters.html")
    fill_all(s)
    page = s.page
    app = agent.api("GET", "/api/v1/sessions").json()[0]["application"]
    assert app["ats"] == "SMARTRECRUITERS" and "Staff Platform Engineer" in app["job_title"]
    vals = page.evaluate("""() => Object.fromEntries(['first', 'last', 'email', 'phone', 'country', 'auth', 'why'].map(id => [id, document.getElementById(id).value]))""")
    assert vals["first"] == "Jane" and vals["last"] == "Doe" and vals["email"] == "jane.doe@example.com"
    assert vals["phone"].replace("-", "").replace("(", "").replace(")", "").replace(" ", "") == "5551234567"
    assert vals["country"] == "US", "the select inside the component's shadow root was not set"
    assert vals["auth"] == "yes", "the radio choice never reached the component"
    assert page.evaluate("document.getElementById('resume').fileName") == "Jane.pdf"
    assert vals["why"] == ""
    assert "Why do you want to work at Contoso Labs?" in s.panel_text()
    assert page.evaluate("window.__submitClicks") == 0


def test_icims_like_classic_table_layout(session, agent):
    s = session("icims.html")
    fill_all(s)
    page = s.page
    app = agent.api("GET", "/api/v1/sessions").json()[0]["application"]
    assert app["ats"] == "ICIMS" and "Data Platform Engineer" in app["job_title"]
    q = lambda name: page.input_value(f"[name='PersonProfileFields.{name}']")
    assert q("FirstName") == "Jane" and q("LastName") == "Doe" and q("Email") == "jane.doe@example.com"
    assert q("AddressCity") == "Austin"
    assert q("AddressState") == "TX-0", "state option values are site specific; the label must decide"
    assert page.is_checked("#auth_yes") and not page.is_checked("#auth_no")
    assert page.evaluate("document.getElementById('resume_1').files[0]?.name") == "Jane.pdf"
    assert page.input_value("[name=q_comp]") == "", "salary expectations must be left for the person"
    assert page.evaluate("window.__submitClicks") == 0
