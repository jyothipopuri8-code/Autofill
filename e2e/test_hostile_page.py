import pytest

pytestmark = pytest.mark.e2e

HONEYPOTS = ["hp1", "hp2", "hp3", "hp4", "hp5"]


def test_honeypots_stay_empty_and_markup_in_labels_is_only_text(session, agent):
    s = session("hostile.html")
    s.start()
    s.wait_ready()
    page = s.page

    # A page script cannot press the panel's buttons: synthetic clicks are not user input.
    page.evaluate("""() => {
        const host = document.querySelector('[data-autofill-agent]');
        const btn = Array.from(host.shadowRoot.querySelectorAll('button')).find(b => b.textContent.startsWith('Fill'));
        btn.click();
        btn.dispatchEvent(new MouseEvent('click', {bubbles: true, composed: true}));
    }""")
    page.wait_for_timeout(1500)
    assert page.input_value("#fn") == "" and page.input_value("#em") == "", "a script-made click filled the form"

    s.click("Fill")
    s.wait_filled()
    assert page.input_value("#fn") == "Jane" and page.input_value("#ln") == "Doe"
    assert page.input_value("#em") == "jane.doe@example.com"

    # Fields a person cannot see are never filled, never listed, whatever they are labelled.
    for hp in HONEYPOTS:
        assert page.input_value(f"#{hp}") == "", f"honeypot #{hp} was filled"

    # The page's label text reaches the panel as text. Nothing in it ran.
    assert page.evaluate("window.__pwned") is None
    text = s.panel_text()
    assert "<img" in text and "<b>bold</b>" in text, "label markup should be shown literally"
    assert page.evaluate("document.querySelector('[data-autofill-agent]').shadowRoot.querySelectorAll('img').length") == 0
    assert page.evaluate("window.__submitClicks") == 0
    s.shot("hostile-after-fill")
