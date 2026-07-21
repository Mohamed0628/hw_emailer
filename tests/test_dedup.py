"""Dedup / state behaviour."""

from datetime import date

from src import dedup
from src.models import Job


def _job(company, title, url):
    return Job(company=company, title=title, url=url)


def test_new_jobs_excludes_seen():
    j1 = _job("Acme", "SWE Intern", "https://a.com/1")
    j2 = _job("Beta", "Quant Intern", "https://b.com/2")
    state = {j1.job_id: {"first_seen": "2026-06-01"}}
    out = dedup.new_jobs([j1, j2], state)
    assert out == [j2]


def test_new_jobs_dedups_within_batch():
    j1 = _job("Acme", "SWE Intern", "https://a.com/1")
    dup = _job("Acme", "SWE Intern", "https://a.com/1")  # same id
    out = dedup.new_jobs([j1, dup], {})
    assert len(out) == 1


def test_update_state_adds_entries():
    j = _job("Acme", "SWE Intern", "https://a.com/1")
    state: dict = {}
    dedup.update_state(state, [j], today=date(2026, 6, 22))
    assert j.job_id in state
    assert state[j.job_id]["first_seen"] == "2026-06-22"
    assert state[j.job_id]["company"] == "Acme"


def test_prune_removes_old_entries():
    state = {
        "old": {"first_seen": "2025-01-01"},
        "recent": {"first_seen": "2026-06-20"},
    }
    kept = dedup.prune(state, max_age_days=120, today=date(2026, 6, 22))
    assert "recent" in kept
    assert "old" not in kept


def test_prune_noop_when_disabled():
    state = {"old": {"first_seen": "2000-01-01"}}
    kept = dedup.prune(state, max_age_days=0, today=date(2026, 6, 22))
    assert kept == state


def test_job_id_stable_and_case_insensitive():
    a = _job("Acme", "SWE Intern", "https://a.com/1")
    b = _job("acme", "swe  intern", "https://a.com/1")  # case + extra space
    assert a.job_id == b.job_id
