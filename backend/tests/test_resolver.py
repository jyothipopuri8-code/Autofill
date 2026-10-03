from datetime import date

import pytest

from autofill_agent.db.enums import AnswerSource, FieldOwnership, FieldStatus
from autofill_agent.engine.descriptor import FieldDescriptor
from autofill_agent.engine.resolver import (
    ApprovedEntry, Context, LibraryEntry, ResumeInfo, resolve_field,
)

RESUME = {
    "contact": {"full_name": "Jane Q. Doe", "first_name": "Jane", "last_name": "Doe", "email": "jane.doe@example.com",
                "phone": "(555) 123-4567", "location": "Austin, TX"},
    "skills": ["Python", "Splunk", "SIEM", "CyberArk"],
    "experience": [
        {"title": "Senior Security Engineer", "company": "CrowdStrike", "location": "Austin, TX", "start_date": "2021-01",
         "end_date": None, "current": True, "description": "Built SIEM detection pipelines in Splunk\nLed incident response"},
        {"title": "Security Analyst", "company": "Acme Corp", "location": "Dallas, TX", "start_date": "2018-06", "end_date": "2020-12",
         "current": False, "description": "Triaged SIEM alerts"},
    ],
    "education": [{"school": "UT Austin", "degree": "Bachelor of Science", "field_of_study": "Computer Science",
                   "start_date": None, "graduation_date": "2018-05", "expected_graduation_date": None}],
    "certifications": [{"name": "CISSP", "number": None, "issued_date": "2020", "expiration_date": None}],
    "languages": [{"language": "English", "proficiency": "Native"}],
}


def ctx(**kw):
    base = dict(
        profile={"first_name": "Jane", "last_name": "Doe", "email": "jane.doe@example.com", "phone": "(555) 123-4567",
                 "city": "Austin", "state": "TX", "country": "United States", "linkedin_url": "https://linkedin.com/in/janedoe",
                 "authorized_to_work_us": True, "require_sponsorship_now": False, "require_sponsorship_future": False,
                 "available_start_date": date(2026, 11, 2)},
        work_auth_verified=True,
        resume=ResumeInfo(RESUME, verified=True, sha256="a" * 64, filename="Jane.pdf"),
        job={"company": "CrowdStrike", "title": "Security Engineer"},
        today=date(2026, 10, 1),
    )
    base.update(kw)
    return Context(**base)


def fd(**kw):
    kw.setdefault("key", "k")
    kw.setdefault("kind", "text")
    return FieldDescriptor(**kw)


def test_profile_field_is_ready_and_labelled():
    r = resolve_field(fd(label="First Name", required=True), ctx())
    assert (r.value, r.source, r.action, r.band, r.status) == ("Jane", AnswerSource.PROFILE, "fill", "READY", FieldStatus.PENDING)
    assert r.confidence >= 95


def test_weak_signal_drops_to_review():
    r = resolve_field(fd(placeholder="First name"), ctx())
    assert r.value == "Jane" and r.band == "REVIEW" and r.action == "review" and r.status is FieldStatus.NEEDS_REVIEW


def test_user_override_wins_over_profile_and_resume():
    r = resolve_field(fd(label="Phone"), ctx(overrides={"contact.phone": "555-999-0000"}))
    assert r.value == "555-999-0000" and r.source is AnswerSource.USER_CURRENT


def test_conflict_between_profile_and_resume_blocks_fill():
    c = ctx()
    c.resume.data = {**RESUME, "contact": {**RESUME["contact"], "phone": "555-222-2222"}}
    r = resolve_field(fd(label="Phone Number"), c)
    assert r.action == "conflict" and r.value is None
    assert r.conflict == {"canonical_field": "contact.phone", "profile_value": "(555) 123-4567", "resume_value": "555-222-2222"}
    # formatting differences alone are not a conflict
    c.resume.data = {**RESUME, "contact": {**RESUME["contact"], "phone": "555.123.4567"}}
    assert resolve_field(fd(label="Phone Number"), c).action == "fill"
    # once the user chose, it is no longer a conflict
    c.resume.data = {**RESUME, "contact": {**RESUME["contact"], "phone": "555-222-2222"}}
    c.overrides["contact.phone"] = "555-222-2222"
    r = resolve_field(fd(label="Phone Number"), c)
    assert r.action == "fill" and r.value == "555-222-2222"


def test_work_authorization_needs_verification_and_maps_options():
    q = dict(label="Are you legally authorized to work in the United States?", kind="radio_group", options=[{"label": "Yes"}, {"label": "No"}])
    r = resolve_field(fd(**q), ctx())
    assert r.option["label"] == "Yes" and r.band == "READY"
    r = resolve_field(fd(**q), ctx(work_auth_verified=False))
    assert r.action == "ask" and r.value is None and "verified" in r.reason
    sp = dict(label="Will you now or in the future require sponsorship?", kind="select", options=[{"label": "Yes"}, {"label": "No"}])
    assert resolve_field(fd(**sp), ctx()).option["label"] == "No"
    c = ctx()
    c.profile["require_sponsorship_future"] = True
    assert resolve_field(fd(**sp), c).option["label"] == "Yes"
    c.profile["require_sponsorship_now"] = None
    c.profile["require_sponsorship_future"] = False
    assert resolve_field(fd(**sp), c).action == "ask"  # one unknown, other False: cannot say


def test_sensitive_policies():
    q = dict(label="Gender", kind="select", options=[{"label": "Male"}, {"label": "Female"}, {"label": "Decline to self-identify"}])
    r = resolve_field(fd(**q), ctx())
    assert r.action == "ask" and r.sensitive and "ASK_ME" in r.reason
    r = resolve_field(fd(**q), ctx(sensitive={"sensitive.gender": ("NEVER_FILL", None)}))
    assert r.action == "skip" and r.status is FieldStatus.SKIPPED
    r = resolve_field(fd(**q), ctx(sensitive={"sensitive.gender": ("AUTOFILL", "Female")}))
    assert r.option["label"] == "Female" and r.sensitive
    r = resolve_field(fd(**q), ctx(sensitive={"sensitive.gender": ("AUTOFILL", "Attack helicopter")}))
    assert r.action == "ask" and r.value is None
    assert resolve_field(fd(label="Sexual orientation"), ctx()).action == "ask"


def test_password_legal_captcha_and_files_are_never_filled():
    assert resolve_field(fd(kind="password", label="Password"), ctx()).status is FieldStatus.SKIPPED
    r = resolve_field(fd(kind="checkbox", label="I agree to the Privacy Policy", required=True), ctx())
    assert r.action == "user_action" and r.status is FieldStatus.USER_ACTION_REQUIRED and r.value is None
    assert resolve_field(fd(kind="captcha"), ctx()).status is FieldStatus.USER_ACTION_REQUIRED
    assert resolve_field(fd(kind="file", label="Cover letter"), ctx()).action == "user_action"
    assert resolve_field(fd(kind="file", label="Transcript"), ctx()).action == "user_action"


def test_resume_attachment_and_mismatch_block():
    r = resolve_field(fd(kind="file", label="Resume/CV"), ctx())
    assert r.action == "attach" and r.value == "Jane.pdf"
    blocked = ctx(resume_blocked="Selected resume differs from the one this application started with")
    r = resolve_field(fd(kind="file", label="Resume/CV"), blocked)
    assert r.action == "user_action" and "differs" in r.reason
    r = resolve_field(fd(label="Company", section={"name": "experience", "index": 0}), blocked)
    assert r.action == "user_action"
    # profile-only fields are not affected by the resume mismatch
    assert resolve_field(fd(label="First Name"), blocked).action == "fill"


def test_experience_sections_and_dates():
    sec = lambda i: {"name": "experience", "index": i}
    assert resolve_field(fd(label="Job Title", section=sec(0)), ctx()).value == "Senior Security Engineer"
    assert resolve_field(fd(label="Company", section=sec(1)), ctx()).value == "Acme Corp"
    r = resolve_field(fd(label="Start Date", placeholder="MM/YYYY", section=sec(1)), ctx())
    assert r.value == "06/2018" and r.parts == {"year": 2018, "month": 6, "day": None} and r.band == "READY"
    r = resolve_field(fd(label="Start Date", section=sec(1)), ctx())  # format unknown -> guessed, needs review
    assert r.value == "06/2018" and r.band == "REVIEW" and "guessed" in r.reason
    assert resolve_field(fd(label="End Date", section=sec(0)), ctx()).action == "skip"  # current job
    assert resolve_field(fd(label="End Date", placeholder="MM/YYYY", section=sec(1)), ctx()).value == "12/2020"
    assert resolve_field(fd(label="I currently work here", kind="checkbox", section=sec(0)), ctx()).checked is True
    assert resolve_field(fd(label="I currently work here", kind="checkbox", section=sec(1)), ctx()).checked is False
    r = resolve_field(fd(label="Company", section=sec(5)), ctx())
    assert r.action == "skip" and "no experience entry #6" in r.reason


def test_unverified_resume_lowers_confidence():
    c = ctx(resume=ResumeInfo(RESUME, verified=False, sha256="a" * 64, filename="Jane.pdf"))
    r = resolve_field(fd(label="Job Title", section={"name": "experience", "index": 0}), c)
    assert r.band == "REVIEW" and r.value == "Senior Security Engineer"


def test_education_certifications_languages():
    assert resolve_field(fd(label="School", section={"name": "education", "index": 0}), ctx()).value == "UT Austin"
    d = fd(label="Degree", kind="select", section={"name": "education", "index": 0},
           options=[{"label": "Associate's"}, {"label": "Bachelor's Degree"}, {"label": "Master's"}])
    assert resolve_field(d, ctx()).option["label"] == "Bachelor's Degree"
    r = resolve_field(fd(label="Graduation Date", placeholder="MM/YYYY", section={"name": "education", "index": 0}), ctx())
    assert r.value == "05/2018"
    r = resolve_field(fd(label="Credential ID", section={"name": "certification", "index": 0}), ctx())
    assert r.action == "ask" and r.value is None  # never fabricated
    r = resolve_field(fd(label="Issued", placeholder="MM/YYYY", section={"name": "certification", "index": 0}), ctx())
    assert r.action == "ask"  # only a year on the resume; month would be invented
    assert resolve_field(fd(label="Proficiency", section={"name": "language", "index": 0}), ctx()).value == "Native"


def test_derived_fields():
    assert resolve_field(fd(label="Current company"), ctx()).value == "CrowdStrike"
    assert resolve_field(fd(label="Current title"), ctx()).value == "Senior Security Engineer"
    r = resolve_field(fd(label="Total years of professional experience"), ctx())
    assert r.value == "8" and r.source is AnswerSource.CALCULATED and r.band == "REVIEW"  # 2018-06 -> 2026-10 minus nothing: 8y4m
    assert resolve_field(fd(label="Highest level of education"), ctx()).value == "Bachelor of Science"


def test_custom_questions_are_grounded():
    r = resolve_field(fd(label="How many years of SIEM experience do you have?", kind="textarea"), ctx())
    assert r.value == "8" and r.source is AnswerSource.CALCULATED and r.action in ("review", "confirm")
    r = resolve_field(fd(label="How many years of CyberArk experience do you have?"), ctx())
    assert r.action == "ask" and r.value is None and "no dated role" in r.reason
    r = resolve_field(fd(label="How many years of Kubernetes experience do you have?"), ctx())
    assert r.action == "ask" and "Cannot verify from current resume" in r.reason
    r = resolve_field(fd(label="Describe your Splunk experience", kind="textarea"), ctx())
    assert "Built SIEM detection pipelines in Splunk" in r.value and r.action == "confirm" and r.source is AnswerSource.RESUME
    r = resolve_field(fd(label="Describe your Rust experience", kind="textarea"), ctx())
    assert r.action == "ask" and r.value is None
    r = resolve_field(fd(label="Do you have experience with Splunk?", kind="radio_group", options=[{"label": "Yes"}, {"label": "No"}]), ctx())
    assert r.option["label"] == "Yes" and r.action in ("review", "confirm")
    r = resolve_field(fd(label="Do you have experience with Terraform?", kind="radio_group", options=[{"label": "Yes"}, {"label": "No"}]), ctx())
    assert r.action == "ask" and r.option is None  # absence from the resume is not a "No"
    r = resolve_field(fd(label="Why are you interested in this role?", kind="textarea", required=True), ctx())
    assert r.action == "ask" and r.status is FieldStatus.MISSING_REQUIRED


def test_overlapping_roles_are_counted_once():
    c = ctx()
    c.resume.data = {**RESUME, "experience": [
        {"title": "Eng", "company": "A", "start_date": "2019-01", "end_date": "2021-01", "current": False, "description": "Used Go"},
        {"title": "Eng", "company": "B", "start_date": "2020-01", "end_date": "2022-01", "current": False, "description": "Used Go"}]}
    assert resolve_field(fd(label="How many years of Go experience do you have?"), c).value == "3"


def test_question_memory_rules():
    from autofill_agent.engine.custom_questions import question_hash

    q = "What is your preferred pronoun usage at work?"
    h = question_hash(q)
    entry = ApprovedEntry(question_hash=h, canonical_field=None, answer="she/her")
    r = resolve_field(fd(label=q), ctx(approved=[entry]))
    assert r.value == "she/her" and r.source is AnswerSource.APPROVED_ANSWER and r.reason == "Previously approved answer"
    # equivalent wording maps to the same meaning
    assert resolve_field(fd(label="What pronoun usage do you prefer at work"), ctx(approved=[entry])).value == "she/her"
    # resume-dependent memory is dropped when the resume changes
    dep = ApprovedEntry(question_hash=h, canonical_field=None, answer="x", resume_sha256="b" * 64, depends_on_resume=True)
    assert resolve_field(fd(label=q), ctx(approved=[dep])).action == "ask"
    # job-specific memory only for the same company
    scoped = ApprovedEntry(question_hash=h, canonical_field=None, answer="y", company="Initech")
    assert resolve_field(fd(label=q), ctx(approved=[scoped])).action == "ask"
    assert resolve_field(fd(label=q), ctx(approved=[scoped], job={"company": "Initech"})).value == "y"
    # profile-dependent memory is dropped when the profile changed
    prof = ApprovedEntry(question_hash=h, canonical_field=None, answer="z", profile_version="v1", depends_on_profile=True)
    assert resolve_field(fd(label=q), ctx(approved=[prof], profile_version="v2")).action == "ask"
    assert resolve_field(fd(label=q), ctx(approved=[prof], profile_version="v1")).value == "z"
    # an explicit answer for this application replaces memory
    r = resolve_field(fd(label=q), ctx(approved=[entry], overrides={f"q:{h}": "they/them"}))
    assert r.value == "they/them" and r.source is AnswerSource.USER_CURRENT


def test_library_policies():
    lib = lambda **kw: ctx(library={"desired_salary": LibraryEntry(**kw)})
    q = fd(label="Desired salary")
    r = resolve_field(q, lib(value="150000", policy="AUTOFILL", verified=True))
    assert r.value == "150000" and r.band == "READY"
    r = resolve_field(q, lib(value="150000", policy="AUTOFILL", verified=False))
    assert r.value == "150000" and r.band == "REVIEW"
    r = resolve_field(q, lib(value="150000", policy="ASK_ME"))
    assert r.action == "ask" and r.suggestion == "150000" and r.value is None
    assert resolve_field(q, lib(value="150000", policy="NEVER_FILL")).action == "skip"
    assert resolve_field(q, ctx()).action == "ask"


def test_start_date_formats():
    assert resolve_field(fd(label="Available start date", kind="date", input_type="date"), ctx()).value == "2026-11-02"
    assert resolve_field(fd(label="Available start date", placeholder="MM/DD/YYYY"), ctx()).value == "11/02/2026"


def test_location_and_phone_helpers():
    assert resolve_field(fd(label="Location"), ctx()).value == "Austin, TX"
    r = resolve_field(fd(label="State", kind="select", options=[{"label": "Select..."}, {"label": "Texas"}, {"label": "Utah"}]), ctx())
    assert r.option["label"] == "Texas"
    r = resolve_field(fd(label="Phone", kind="tel", maxlength=10), ctx())
    assert r.value == "5551234567"
    assert resolve_field(fd(label="Phone", kind="tel", maxlength=7), ctx()).action == "ask"


def test_ownership_protection():
    for own in (FieldOwnership.USER_FILLED, FieldOwnership.USER_MODIFIED_AGENT_VALUE):
        r = resolve_field(fd(label="First Name", current_value="Janet", ownership=own), ctx())
        assert r.action == "keep" and r.value == "Janet"
    r = resolve_field(fd(label="First Name", current_value="Jane", ownership=FieldOwnership.AGENT_FILLED), ctx())
    assert r.action == "keep"
    # a differing site default is surfaced, not silently overwritten
    r = resolve_field(fd(label="Country", current_value="Canada", ownership=FieldOwnership.SITE_DEFAULT), ctx())
    assert r.action == "review" and r.reason == "Site default differs from your answer"
    r = resolve_field(fd(label="Country", current_value="United States", ownership=FieldOwnership.SITE_DEFAULT), ctx())
    assert r.action == "keep"


def test_unmatched_option_never_forced():
    r = resolve_field(fd(label="State", kind="select", options=[{"label": "Ontario"}, {"label": "Quebec"}]), ctx())
    assert r.action == "ask" and r.value is None and "None of the options match" in r.reason
    r = resolve_field(fd(label="Optional note"), ctx())
    assert r.status is FieldStatus.OPTIONAL_EMPTY


MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]


def test_month_and_year_dropdowns_use_the_date_parts():
    sec = {"name": "experience", "index": 0}
    month = resolve_field(fd(label="Start date month", kind="select", section=sec, options=[{"label": "Month"}, *({"label": m} for m in MONTHS)]), ctx())
    assert month.option["label"] == "January" and month.action in ("fill", "review")
    year = resolve_field(fd(label="Start date year", kind="select", section=sec, options=[{"label": "Year"}, *({"label": str(y)} for y in range(2015, 2027))]), ctx())
    assert year.option["label"] == "2021"
    combined = resolve_field(fd(label="Start date", kind="custom_select", section=sec, options=[{"label": f"{m} {y}"} for y in (2020, 2021) for m in MONTHS]), ctx())
    assert combined.option["label"] == "January 2021"
    numeric = resolve_field(fd(label="Start date month", kind="select", section={"name": "experience", "index": 1}, options=[{"label": str(i), "value": f"{i:02d}"} for i in range(1, 13)]), ctx())
    assert numeric.option["label"] == "6"


def test_month_dropdown_never_invents_a_missing_month():
    from autofill_agent.engine.options import match_date_option
    from autofill_agent.engine.descriptor import Option

    opts = [Option(label=m, value=m.lower()) for m in MONTHS]
    m = match_date_option("2021", opts)
    assert m.option is None and "month" in (m.note or "")
    assert match_date_option("2021-09", opts).option.label == "September"
    assert match_date_option("2021-09", [Option(label=str(y), value=str(y)) for y in (2020, 2021)]).option.label == "2021"


# --- found by checking the real Deepgram application (Ashby) -------------------------------------------------------

YN = [{"value": "Yes", "label": "Yes"}, {"value": "No", "label": "No"}]


def test_site_resume_autofill_uploader_is_not_the_resume_field():
    widget = resolve_field(fd(kind="file", label="Autofill from resume", nearby_text="Upload your resume here to autofill key application fields."), ctx(), "ASHBY")
    assert widget.action == "skip" and "resume field" in widget.reason.lower()
    real = resolve_field(fd(kind="file", label="Resume", required=True), ctx(), "ASHBY")
    assert real.action == "attach"


def test_preferred_first_name_is_suggested_not_filled_and_preferred_last_name_is_left_alone():
    r = resolve_field(fd(label="Preferred First Name", required=True), ctx())
    assert r.action == "ask" and r.suggestion == "Jane" and r.value is None
    saved = resolve_field(fd(label="Preferred First Name", required=True), ctx(profile={**ctx().profile, "preferred_name": "Janie"}))
    assert saved.action == "fill" and saved.value == "Janie"
    last = resolve_field(fd(label="Preferred Last Name (if applicable)"), ctx())
    assert last.action == "ask" and last.value is None  # optional, so it is not even listed for the person


COUNTRY_Q = "Are you legally authorized to work in the country where this role is located?"
SPONSOR_Q = "Will you now or in the future require visa sponsorship to work in the country where this role is located?"


@pytest.mark.parametrize("location,filled", [
    ("USA - Remote", True), ("United States", True), ("Austin, TX", True), ("Remote, US", True), ("New York, NY (Hybrid)", True),
    ("Berlin, Germany", False), ("London, UK", False), ("Toronto, Canada", False), ("Remote", False), (None, False), ("", False),
    ("Santa Fe, New Mexico", False),  # a state name alone does not say which country; ask rather than guess
])
def test_country_of_the_role_is_answered_only_when_the_role_is_known_to_be_in_the_us(location, filled):
    for q, expected in ((COUNTRY_Q, "Yes"), (SPONSOR_Q, "No")):
        r = resolve_field(fd(kind="radio_group", label=q, required=True, options=YN), ctx(job={"company": "Deepgram", "title": "SE", "location": location}), "ASHBY")
        if filled:
            assert r.option["label"] == expected and r.action in ("fill", "review"), (location, q)
        else:
            assert r.action == "ask" and r.option is None, (location, q)


@pytest.mark.parametrize("q,expected_filled", [
    ("Are you legally authorized to work in the United States?", True),
    ("Are you authorized to work in the US?", True),
    ("Are you legally authorized to work in Canada?", False),
    ("Are you authorized to work in the UK or the EU?", False),
    ("Are you authorized to work in the United States or Canada?", False),
    ("Are you legally authorized to work in New Mexico, United States?", True),
])
def test_named_country_in_a_work_authorization_question(q, expected_filled):
    r = resolve_field(fd(kind="radio_group", label=q, options=YN), ctx(job={"location": "Berlin, Germany"}))
    assert (r.option is not None) is expected_filled, q


def test_home_location_typeahead_matches_city_and_state_in_place_results():
    places = [{"value": p, "label": p} for p in ["Austin, Minnesota, United States", "Austin, Texas, United States", "Austin, Arkansas, United States"]]
    r = resolve_field(fd(kind="custom_select", label="Home Location", required=True, options=places), ctx(), "ASHBY")
    assert r.option["label"] == "Austin, Texas, United States" and r.action in ("fill", "review")
    # Without the options the answer is the profile's "City, ST", typed into the search box.
    bare = resolve_field(fd(kind="custom_select", label="Home Location", required=True), ctx(), "ASHBY")
    assert bare.value == "Austin, TX"
    # A result list with no Texas entry is never guessed between.
    wrong = resolve_field(fd(kind="custom_select", label="Home Location", options=[p for p in places if "Texas" not in p["label"]]), ctx(), "ASHBY")
    assert wrong.action == "ask"
