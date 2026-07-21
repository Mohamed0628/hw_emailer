"""FAANG-urgent email behaviour."""

from src.models import Job
from src.notify import email as E

FAANG = ["meta", "facebook", "amazon", "apple", "netflix", "google", "alphabet"]


def _job(company, title="SWE Intern", url=None):
    return Job(company=company, title=title, url=url or f"https://x/{company}", category="swe")


def test_is_faang_token_match():
    assert E.is_faang("Apple Inc", FAANG)
    assert E.is_faang("Amazon Robotics", FAANG)
    assert E.is_faang("Google", FAANG)


def test_is_faang_no_false_positive():
    assert not E.is_faang("Snapple", FAANG)      # contains 'apple' as substring only
    assert not E.is_faang("Acme Corp", FAANG)


def test_faang_jobs_filters():
    jobs = [_job("Meta"), _job("Acme"), _job("Netflix")]
    faang = E.faang_jobs(jobs, FAANG)
    assert {j.company for j in faang} == {"Meta", "Netflix"}


def test_subject_urgent_when_faang():
    jobs = [_job("Meta"), _job("Acme")]
    grouped = E.group_by_category(jobs, ["swe"])
    subj = E.build_subject(jobs, grouped, "[Intern Alert]", E.faang_jobs(jobs, FAANG))
    assert "FAANG job out now" in subj
    assert "Meta" in subj


def test_subject_normal_without_faang():
    jobs = [_job("Acme")]
    grouped = E.group_by_category(jobs, ["swe"])
    subj = E.build_subject(jobs, grouped, "[Intern Alert]", [])
    assert subj.startswith("[Intern Alert]")
    assert "FAANG" not in subj


def test_html_headline_and_banner_when_faang():
    jobs = [_job("Amazon")]
    grouped = E.group_by_category(jobs, ["swe"])
    html = E.build_html(grouped, 1, E.faang_jobs(jobs, FAANG))
    assert "FAANG job out now" in html
    assert "FAANG roles just posted" in html
