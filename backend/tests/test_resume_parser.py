import pytest

from autofill_agent.resume_parser import ResumeParseError, extract_text, parse_resume_file, parse_text
from autofill_agent.resume_schema import ResumeData
from tests.helpers import SAMPLE_RESUME, make_docx, make_pdf


@pytest.fixture(params=["pdf", "docx"])
def parsed(request, tmp_path):
    path = tmp_path / f"r.{request.param}"
    path.write_bytes(make_pdf(SAMPLE_RESUME) if request.param == "pdf" else make_docx(SAMPLE_RESUME))
    return parse_resume_file(path)


def test_contact(parsed):
    c = parsed.contact
    assert (c.full_name, c.first_name, c.last_name) == ("Jane Q. Doe", "Jane", "Doe")
    assert c.email == "jane.doe@example.com" and c.phone == "(555) 123-4567"
    assert c.location == "Austin, TX"
    assert c.linkedin_url == "https://linkedin.com/in/janedoe" and c.github_url == "https://github.com/janedoe"


def test_summary_and_skills(parsed):
    assert parsed.summary.startswith("Security engineer")
    assert parsed.skills == ["Python", "Go", "Splunk", "AWS", "Incident Response", "SIEM"]


def test_experience(parsed):
    cur, old = parsed.experience
    assert (cur.title, cur.company, cur.location) == ("Senior Security Engineer", "CrowdStrike", "Austin, TX")
    assert cur.start_date == "2021-01" and cur.end_date is None and cur.current is True
    assert cur.description == "Built detection pipelines\nLed incident response"
    assert (old.title, old.company) == ("Security Analyst", "Acme Corp")
    assert (old.start_date, old.end_date, old.current) == ("2018-06", "2020-12", False)


def test_education_certs_languages(parsed):
    edu = parsed.education[0]
    assert (edu.school, edu.degree, edu.field_of_study, edu.graduation_date) == (
        "University of Texas at Austin", "Bachelor of Science", "Computer Science", "2018-05")
    names = [(c.name, c.issued_date, c.number) for c in parsed.certifications]
    assert names == [("CISSP", "2020", None), ("AWS Certified Security - Specialty", "2022", None)]
    assert [(x.language, x.proficiency) for x in parsed.languages] == [
        ("English", "Native"), ("Spanish", "Professional"), ("French", None)]
    assert parsed.warnings == []


def test_output_is_valid_resume_data(parsed):
    data = parsed.model_dump(mode="json")
    data.pop("warnings")
    ResumeData.model_validate(data)


def test_never_invents_missing_facts():
    p = parse_text("Sam Lee\nsam@example.com\n\nCERTIFICATIONS\nSecurity+\n\nLANGUAGES\nGerman")
    assert p.certifications[0].number is None and p.certifications[0].issued_date is None
    assert p.languages[0].proficiency is None
    assert p.experience == [] and p.education == []
    assert "No phone number found." in p.warnings and "No experience section found." in p.warnings


def test_explicit_certificate_number_and_expiry():
    p = parse_text("A B\n\nCERTIFICATIONS\n• AWS Solutions Architect - Credential ID: ABC12345, Expires Mar 2027")
    c = p.certifications[0]
    assert c.number == "ABC12345" and c.expiration_date == "2027-03" and c.name == "AWS Solutions Architect"


def test_expected_graduation_and_year_only():
    p = parse_text("A B\n\nEDUCATION\nState University\nMaster of Science in Data Science, Expected May 2027\nCommunity College\nAssociate degree, 2015")
    a, b = p.education
    assert a.expected_graduation_date == "2027-05" and a.graduation_date is None and a.field_of_study == "Data Science"
    assert b.school == "Community College" and b.graduation_date == "2015"


def test_single_line_experience_headers_and_numeric_dates():
    text = "A B\n\nWORK EXPERIENCE\nDevOps Engineer, Initech, Remote  03/2019 - 05/2022\n- Ran CI\nSupport Technician at Hooli (2016 - 2019)\nFixed laptops."
    first, second = parse_text(text).experience
    assert (first.title, first.company, first.location) == ("DevOps Engineer", "Initech", "Remote")
    assert (first.start_date, first.end_date) == ("2019-03", "2022-05") and first.description == "Ran CI"
    assert (second.title, second.company, second.start_date, second.end_date) == ("Support Technician", "Hooli", "2016", "2019")


def test_unreadable_dates_are_flagged_not_guessed():
    p = parse_text("A B\n\nEXPERIENCE\nEngineer at Acme\n• did things")
    assert p.experience == [] and any("no dated positions" in w for w in p.warnings)


def test_image_only_pdf_rejected(tmp_path):
    f = tmp_path / "scan.pdf"
    f.write_bytes(make_pdf([]))
    with pytest.raises(ResumeParseError, match="No selectable text"):
        extract_text(f)


def test_corrupt_files_rejected(tmp_path):
    bad_pdf = tmp_path / "x.pdf"
    bad_pdf.write_bytes(b"%PDF-1.4\ngarbage")
    with pytest.raises(ResumeParseError):
        extract_text(bad_pdf)
    bad_docx = tmp_path / "x.docx"
    bad_docx.write_bytes(b"PK\x03\x04 nope")
    with pytest.raises(ResumeParseError):
        extract_text(bad_docx)


def test_docx_xml_entity_bomb_rejected(tmp_path):
    import io
    import zipfile

    bomb = (
        '<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;">]>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>&b;</w:t></w:r></w:p></w:body></w:document>'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", bomb)
    f = tmp_path / "bomb.docx"
    f.write_bytes(buf.getvalue())
    with pytest.raises(ResumeParseError):
        extract_text(f)
