import pytest

from autofill_agent.engine.descriptor import FieldDescriptor
from autofill_agent.engine.matching import classify


def fd(**kw):
    kw.setdefault("key", "k")
    kw.setdefault("kind", "text")
    return FieldDescriptor(**kw)


@pytest.mark.parametrize("label", ["First Name", "Legal First Name", "Given Name", "Candidate First Name", "first name *"])
def test_first_name_labels(label):
    m = classify(fd(label=label))
    assert m.canonical == "personal.first_name" and m.score >= 0.9


@pytest.mark.parametrize("name", ["fname", "first_name", "firstName", "candidate[firstName]"])
def test_first_name_attributes(name):
    m = classify(fd(name=name))
    assert m.canonical == "personal.first_name" and m.score >= 0.84


def test_autocomplete_and_input_type_are_strong():
    assert classify(fd(autocomplete="given-name")).score >= 0.99
    m = classify(fd(kind="email", input_type="email"))
    assert m.canonical == "contact.email" and m.score >= 0.97
    assert classify(fd(kind="tel", input_type="tel", label="Mobile")).canonical == "contact.phone"


@pytest.mark.parametrize("label,canonical", [
    ("Last Name", "personal.last_name"), ("Surname", "personal.last_name"),
    ("Email Address", "contact.email"), ("Phone Number", "contact.phone"),
    ("LinkedIn Profile", "contact.linkedin"), ("GitHub", "contact.github"),
    ("City", "location.city"), ("State / Province", "location.state"), ("Country", "location.country"),
    ("ZIP Code", "location.postal_code"), ("Street Address", "location.address_line1"),
    ("Full name", "personal.full_name"), ("Name", "personal.full_name"),
    ("Phone Extension", "contact.phone_extension"), ("Country Code", "contact.phone_country_code"),
    ("Phone Device Type", "contact.phone_device_type"),
    ("Desired salary", "preferences.desired_salary"), ("When can you start?", "preferences.start_date"),
    ("How did you hear about us?", "preferences.referral_source"),
    ("Are you willing to relocate?", "preferences.relocate"),
    ("Do you have an active security clearance?", "preferences.security_clearance"),
    ("Gender", "sensitive.gender"), ("Race", "sensitive.race"), ("Veteran Status", "sensitive.veteran_status"),
    ("Disability Status", "sensitive.disability_status"), ("Are you Hispanic/Latino?", "sensitive.hispanic_latino"),
    ("Upload your resume/CV", "resume.file"),
])
def test_label_to_canonical(label, canonical):
    kind = "file" if "resume" in label.lower() else "text"
    assert classify(fd(label=label, kind=kind)).canonical == canonical


def test_work_authorization_variants():
    q = lambda label: classify(fd(label=label, kind="radio_group")).canonical
    assert q("Are you authorized to work in the United States?") == "work_auth.authorized_to_work"
    assert q("Are you legally authorized to work in the US?") == "work_auth.authorized_to_work"
    assert q("Will you require sponsorship?") == "work_auth.sponsorship_now"
    assert q("Will you now or in the future require sponsorship?") == "work_auth.sponsorship_any"
    assert q("Will you require sponsorship in the future?") == "work_auth.sponsorship_future"
    assert q("Will you require H-1B sponsorship?") == "work_auth.sponsorship_any"


def test_state_is_not_confused_with_united_states():
    m = classify(fd(label="Are you authorized to work in the United States?", kind="select"))
    assert m.canonical == "work_auth.authorized_to_work"


def test_sectioned_fields_only_match_inside_their_section():
    exp = {"name": "experience", "index": 0}
    assert classify(fd(label="Company", section=exp)).canonical == "experience.company"
    assert classify(fd(label="Title", section=exp)).canonical == "experience.title"
    assert classify(fd(label="Start Date", section=exp)).canonical == "experience.start_date"
    assert classify(fd(label="Start Date", section={"name": "education", "index": 0})).canonical == "education.start_date"
    assert classify(fd(label="School", section={"name": "education", "index": 1})).canonical == "education.school"
    assert classify(fd(label="Company")).canonical is None  # outside any section: not guessed
    assert classify(fd(label="Current company")).canonical == "calc.current_company"
    assert classify(fd(label="Credential ID", section={"name": "certification", "index": 0})).canonical == "certification.number"


def test_password_legal_and_captcha():
    assert classify(fd(kind="password", label="Create password")).canonical == "security.password"
    assert classify(fd(input_type="password", label="x")).canonical == "security.password"
    assert classify(fd(kind="captcha")).canonical == "security.captcha"
    for label in ["I agree to the Privacy Policy", "I certify that the information is accurate", "I consent to the processing of my data",
                  "I have read and accept the Terms and Conditions"]:
        assert classify(fd(label=label, kind="checkbox")).canonical == "legal.consent", label
    assert classify(fd(label="Electronic signature")).canonical == "legal.signature"


def test_unknown_questions_stay_unmapped():
    assert classify(fd(label="Why are you interested in this role?", kind="textarea")).canonical is None
    assert classify(fd(label="Describe your AWS experience", kind="textarea")).canonical is None


def test_incompatible_kind_lowers_score():
    good = classify(fd(label="Email", kind="text")).score
    bad = classify(fd(label="Email", kind="checkbox")).score
    assert bad < good


def test_ats_alias_boosts_known_structures():
    m = classify(fd(name="eeo[gender]", kind="select"), ats="LEVER")
    assert m.canonical == "sensitive.gender" and "ats_alias" in m.signals and m.score >= 0.97
    m = classify(fd(name="_systemfield_name"), ats="ASHBY")
    assert m.canonical == "personal.full_name"
    m = classify(fd(name="legalNameSection_firstName", id="input-3"), ats="WORKDAY")
    assert m.canonical == "personal.first_name"


def test_does_not_treat_other_name_fields_as_person_name():
    assert classify(fd(label="Company name")).canonical != "personal.full_name"
    assert classify(fd(label="School name")).canonical != "personal.full_name"
    assert classify(fd(label="Reference name")).canonical != "personal.full_name"


def test_documents_and_legal_fields_match_even_when_the_page_puts_them_inside_a_section():
    from autofill_agent.engine.descriptor import FieldDescriptor
    from autofill_agent.engine.matching import classify

    sec = {"name": "education", "index": 0}
    assert classify(FieldDescriptor(key="k", kind="file", label="Resume/CV", section=sec)).canonical == "resume.file"
    assert classify(FieldDescriptor(key="k", kind="checkbox", label="I agree to the Privacy Policy and Terms", section=sec)).canonical.startswith("legal.")
    # ordinary profile fields do not leak into sections
    assert classify(FieldDescriptor(key="k", kind="text", label="Email address", section=sec)).canonical is None
