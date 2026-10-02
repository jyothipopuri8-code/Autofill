import pytest

from autofill_agent.engine.dates import date_parts, format_date, infer_format, months_between
from autofill_agent.engine.descriptor import FieldDescriptor, Option
from autofill_agent.engine.options import match_option


def O(*labels):
    return [Option(value=l.lower(), label=l) for l in labels]


@pytest.mark.parametrize("iso,fmt,expected", [
    ("2021-01", "MM/YYYY", "01/2021"), ("2021-01", "MMMM YYYY", "January 2021"), ("2021-09", "MMM YYYY", "Sep 2021"),
    ("2021-01-15", "MM/DD/YYYY", "01/15/2021"), ("2021-01-15", "DD/MM/YYYY", "15/01/2021"), ("2021-01", "YYYY-MM", "2021-01"),
    ("2021", "YYYY", "2021"), ("2021-03", "M/YYYY", "3/2021"), ("2021-03", None, "2021-03"),
])
def test_format_date(iso, fmt, expected):
    assert format_date(iso, fmt) == expected


def test_missing_components_are_never_invented():
    assert format_date("2021", "MM/YYYY") is None
    assert format_date("2021-05", "MM/DD/YYYY") is None
    assert format_date("garbage", "MM/YYYY") is None
    assert format_date("2021-13", "MM/YYYY") is None


def test_date_parts_and_months():
    assert date_parts("2021-05") == {"year": 2021, "month": 5, "day": None}
    assert months_between("2018-06", "2020-12") == 30 and months_between("2020", "2022") == 24


def test_infer_format():
    mk = lambda **kw: FieldDescriptor(key="k", **kw)
    assert infer_format(mk(input_type="date")) == "YYYY-MM-DD"
    assert infer_format(mk(input_type="month")) == "YYYY-MM"
    assert infer_format(mk(placeholder="MM/YYYY")) == "MM/YYYY"
    assert infer_format(mk(placeholder="mm/dd/yyyy")) == "MM/DD/YYYY"
    assert infer_format(mk(placeholder="Month, Year")) == "MMMM YYYY"
    assert infer_format(mk(date_format="MMM YYYY")) == "MMM YYYY"
    assert infer_format(mk(placeholder="Your answer")) is None


def test_exact_and_placeholder_skipping():
    m = match_option("Austin", O("Select...", "Austin", "Dallas"))
    assert m.option.label == "Austin" and m.factor == 1.0
    assert match_option("Reno", O("Select...", "Austin")).option is None


def test_yes_no_variants():
    opts = O("Select", "Yes, I am authorized to work in the US", "No, I am not authorized")
    assert match_option("Yes", opts, "work_auth.authorized_to_work").option.label.startswith("Yes")
    assert match_option("No", opts, "work_auth.authorized_to_work").option.label.startswith("No")
    ambiguous = O("Yes, US citizen", "Yes, visa holder", "No")
    assert match_option("Yes", ambiguous).option is None


def test_state_and_country_synonyms():
    assert match_option("TX", O("Texas", "Utah"), "location.state").option.label == "Texas"
    assert match_option("Texas", O("TX", "UT"), "location.state").option.label == "TX"
    assert match_option("United States", O("USA", "Canada"), "location.country").option.label == "USA"
    assert match_option("US", O("United States of America", "Canada"), "location.country").option.label == "United States of America"


def test_sensitive_options():
    g = O("Male", "Female", "Non-binary", "Decline to self-identify")
    assert match_option("Female", g, "sensitive.gender").option.label == "Female"
    assert match_option("Prefer not to say", g, "sensitive.gender").option.label == "Decline to self-identify"
    assert match_option("woman", g, "sensitive.gender").option.label == "Female"
    assert match_option("Attack helicopter", g, "sensitive.gender").option is None


def test_degree_levels_and_months_and_phone_codes():
    d = O("High School", "Bachelor's Degree", "Master's Degree", "PhD")
    assert match_option("Bachelor of Science", d, "education.degree").option.label == "Bachelor's Degree"
    assert match_option("MBA", d, "education.degree").option.label == "Master's Degree"
    months = O("January", "February", "March")
    assert match_option("02", months).option.label == "February"
    assert match_option("+1", O("United States (+1)", "India (+91)"), "contact.phone_country_code").option.label == "United States (+1)"
    assert match_option("mobile", O("Home", "Mobile", "Work"), "contact.phone_device_type").option.label == "Mobile"


def test_word_containment_requires_uniqueness():
    assert match_option("LinkedIn", O("Job board", "LinkedIn posting", "Friend")).option.label == "LinkedIn posting"
    assert match_option("Job", O("Job board", "Job fair")).option is None
