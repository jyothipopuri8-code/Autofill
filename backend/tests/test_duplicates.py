from datetime import datetime, timezone

from autofill_agent.db.models import Application
from autofill_agent.duplicates import find_duplicates, norm_company, norm_url, title_similarity


def app(**kw):
    return Application(created_at=datetime.now(timezone.utc), **kw)


def test_normalizers():
    assert norm_company("CrowdStrike, Inc.") == norm_company("crowdstrike") == "crowdstrike"
    assert norm_url("https://www.Example.com/jobs/123/apply?utm_source=x#top") == norm_url("https://example.com/jobs/123")
    assert norm_url("https://boards.greenhouse.io/acme/jobs/1?gh_jid=77&utm=1") == "boards.greenhouse.io/acme/jobs/1?gh_jid=77"
    assert norm_url("https://x.com/job?id=1") != norm_url("https://x.com/job?id=2")
    assert title_similarity("Senior Security Engineer", "Security Engineer") == 1.0
    assert title_similarity("Security Engineer", "Marketing Manager") == 0.0


def test_detects_by_url_job_id_and_title():
    a = app(company="CrowdStrike", job_title="Security Engineer", job_id="R123", job_url="https://x.com/jobs/1")
    b = app(company="Acme", job_title="Data Analyst", job_id="R999", job_url="https://x.com/jobs/2")
    ex = [a, b]
    m = find_duplicates(ex, "Other", "Other", None, "https://www.x.com/jobs/1/apply?utm_source=li")
    assert [(x.application, x.strength) for x in m] == [(a, "strong")]
    m = find_duplicates(ex, "crowdstrike inc", "Whatever", "r123", "https://other.com/1")
    assert m and m[0].reason == "Same company and job ID"
    m = find_duplicates(ex, "CrowdStrike", "Sr. Security Engineer", None, "https://other.com/9")
    assert m and m[0].strength == "likely"
    assert find_duplicates(ex, "CrowdStrike", "Marketing Manager", "Z1", "https://other.com/9") == []
    assert find_duplicates([], "A", "B", "C", "https://d.com") == []
