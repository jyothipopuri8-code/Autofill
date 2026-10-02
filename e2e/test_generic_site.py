import re

import pytest

pytestmark = pytest.mark.e2e


def values(page):
    return page.evaluate("""() => Object.fromEntries(['fn','ln','em','ph','li','city','state','country','py','why','gender','start','pw'].map(id => [id, document.getElementById(id).value]))""")


def test_start_scan_fill_and_safety_rules(session, agent):
    s = session("generic.html")
    s.start()
    s.wait_ready()
    page = s.page

    # Safe mode: nothing is filled until the user clicks Fill.
    assert values(page)["ln"] == ""
    # The user types first; the agent must never overwrite it.
    page.fill("#fn", "Janet")
    s.shot("generic-before-fill")
    s.click("Rescan page")
    s.wait_ready()
    s.click("Fill")
    s.wait_filled()

    v = values(page)
    assert v["fn"] == "Janet", "user-typed value was overwritten"
    assert v["ln"] == "Doe" and v["em"] == "jane.doe@example.com"
    assert re.sub(r"\D", "", v["ph"]) == "5551234567"
    assert v["li"] == "https://linkedin.com/in/janedoe"
    assert v["city"] == "Austin" and v["state"] == "TX" and v["country"] == "United States"
    assert page.evaluate("document.getElementById('resume').files[0]?.name") == "Jane.pdf"
    assert page.evaluate("document.getElementById('resume').files[0]?.size") == len(agent.api("GET", f"/api/v1/sessions/{agent.api('GET', '/api/v1/sessions').json()[0]['id']}/resume-file").content)
    assert page.is_checked("input[name=auth][value=yes]") and page.is_checked("input[name=sponsor][value=no]")

    s.shot("generic-after-fill")

    # What must stay with the human.
    assert v["pw"] == "" and v["why"] == "" and v["gender"] == ""
    assert not page.is_checked("#agree")
    assert page.evaluate("document.getElementById('cover').files.length") == 0
    assert page.evaluate("window.__submitClicks") == 0

    # The needs-attention list names the open items.
    text = s.panel_text()
    assert "Why do you want to work at Acme Corp?" in text
    assert "CAPTCHA" in text

    # A web page cannot reach the agent with its own origin or without the token.
    assert page.evaluate("window.__probe") in ("blocked", 401, 403)

    # Undo reverts only what the agent wrote.
    s.click("Undo last fill")
    page.wait_for_function("document.getElementById('ln').value === ''")
    assert page.input_value("#fn") == "Janet"
    assert page.evaluate("document.getElementById('resume').files.length") == 0


def start_and_fill(s):
    s.start()
    s.wait_ready()
    s.click("Fill")
    s.wait_filled()


def test_custom_question_answer_goes_to_the_page_and_is_remembered(session, agent):
    s = session("generic.html")
    start_and_fill(s)
    card = s.page.locator("[data-autofill-agent] .card", has_text="Why do you want to work at Acme Corp?")
    card.locator("textarea").fill("I admire how Acme treats security as a product feature.")
    card.locator("input[type=checkbox]").check()
    card.get_by_text("Use for this application").click()
    s.page.wait_for_function("document.getElementById('why').value.startsWith('I admire')")
    assert s.page.evaluate("window.__submitClicks") == 0

    # A second Acme role with the same question gets the remembered answer, shown for review rather than typed in silently.
    s2 = session("generic_b.html")
    start_and_fill(s2)
    card2 = s2.page.locator("[data-autofill-agent] .card", has_text="Why do you want to work at Acme Corp?")
    assert "I admire how Acme" in card2.inner_text()
    assert s2.page.input_value("#why") == ""


def test_profile_and_resume_conflict_requires_a_choice(session, agent):
    agent.api("PATCH", "/api/v1/profile", json={"email": "jane@home.example"})
    s = session("generic.html")
    start_and_fill(s)
    assert s.page.input_value("#em") == ""  # neither value is used until the user decides
    card = s.page.locator("[data-autofill-agent] .card", has_text="Email")
    assert "jane@home.example" in card.inner_text() and "jane.doe@example.com" in card.inner_text()
    card.get_by_text("Use profile").click()
    s.page.wait_for_function("document.getElementById('em').value === 'jane@home.example'")


def test_a_different_current_resume_blocks_resume_fields_until_chosen(session, agent):
    s = session("generic.html")
    s.start()
    s.wait_ready()
    other = agent.upload_resume("Other.pdf", lines=["Jane Q. Doe", "Austin, TX | jane.doe@example.com", "SUMMARY", "A different resume."], current=True)  # becomes the current resume after the session started
    s.click("Rescan page")
    s.page.locator("[data-autofill-agent] >> text=Choose a resume").wait_for()
    s.click("Fill")
    s.wait_filled()
    assert s.page.evaluate("document.getElementById('resume').files.length") == 0, "resume attached while blocked"
    s.page.locator("[data-autofill-agent] button", has_text="Keep Jane.pdf").click()
    s.page.locator("[data-autofill-agent] >> text=Choose a resume").wait_for(state="detached")
    s.click("Fill")
    s.page.wait_for_function("document.getElementById('resume').files.length === 1")
    assert s.page.evaluate("document.getElementById('resume').files[0].name") == "Jane.pdf"


def test_standard_mode_fills_ready_fields_by_itself_but_not_sensitive_ones(session, agent):
    agent.api("PUT", "/api/v1/settings", json={"mode": "STANDARD"})
    agent.api("PUT", "/api/v1/profile/sensitive/gender", json={"policy": "ALWAYS_ANSWER", "value": "Decline to self-identify"})
    s = session("generic.html")
    s.start()
    s.wait_filled()
    assert s.page.input_value("#ln") == "Doe"
    assert s.page.input_value("#gender") == "", "sensitive answers are never auto-filled"
    assert s.page.evaluate("window.__submitClicks") == 0


def test_manual_assist_never_fills_until_asked(session, agent):
    agent.api("PUT", "/api/v1/settings", json={"mode": "MANUAL_ASSIST"})
    s = session("generic.html")
    s.start()
    s.wait_ready()
    assert s.page.locator("[data-autofill-agent] button", has_text=re.compile(r"^Fill \d+ ready")).count() == 0
    assert s.page.input_value("#ln") == ""
    s.page.locator("[data-autofill-agent] summary", has_text="Ready to fill").click()
    s.page.locator("[data-autofill-agent] li", has_text="Last Name").get_by_text("Insert").click()
    s.page.wait_for_function("document.getElementById('ln').value === 'Doe'")
    assert s.page.input_value("#em") == ""


def test_duplicate_application_is_flagged(session, agent):
    first = session("generic.html")
    first.start()
    first.wait_ready()
    second = session("generic.html")
    second.start()
    second.page.locator("[data-autofill-agent] >> text=Possible duplicate application").wait_for()
    second.page.locator("[data-autofill-agent] button", has_text="Continue earlier session").click()
    second.wait_ready()
    assert len(agent.api("GET", "/api/v1/sessions").json()) == 1


def test_reload_resumes_the_same_session(session, agent):
    s = session("generic.html")
    s.start()
    s.wait_ready()
    s.page.reload()
    s.wait_ready()
    assert len(agent.api("GET", "/api/v1/sessions").json()) == 1


def test_agent_going_away_is_reported_clearly(session, agent):
    s = session("generic.html")
    s.start()
    s.wait_ready()
    agent.stop()
    s.click("Rescan page")
    s.page.locator("[data-autofill-agent] >> text=Cannot reach the agent").wait_for()
    assert s.page.input_value("#ln") == ""


def test_final_review_is_not_ready_while_required_answers_are_missing(session, agent):
    s = session("generic.html")
    start_and_fill(s)
    s.click("Final review checklist")
    box = s.page.locator("[data-autofill-agent] .banner", has_text="NOT READY")
    box.wait_for()
    text = box.inner_text()
    assert "Required fields completed" in text and "Legal actions completed by you" in text
    assert s.page.evaluate("window.__submitClicks") == 0

    # The user submits on their own; the agent only asks whether it went through.
    s.page.click("#submit")
    s.page.locator("[data-autofill-agent] >> text=Did the application go through?").wait_for(timeout=10000)
    s.click("Yes, mark it submitted")
    s.page.locator("[data-autofill-agent] >> text=Marked as submitted").wait_for()
    app = agent.api("GET", "/api/v1/applications").json()
    items = app["items"] if isinstance(app, dict) else app
    assert items[0]["status"] == "SUBMITTED"
    assert s.page.evaluate("window.__submitClicks") == 1  # exactly the user's own click
