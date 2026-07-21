"""Apply-tool logic that doesn't need a browser."""

from src.apply import applog as applog_mod
from src.apply import fields
from src.apply.ashby import AshbyApplicator
from src.apply.greenhouse import GreenhouseApplicator
from src.apply.lever import LeverApplicator
from src.apply.registry import get_applicator
from src.models import Job


# --- closed-posting detection ------------------------------------------------

def test_closed_detects_notion_message():
    assert fields.text_looks_closed("Notion isn't hiring for this role right now.")


def test_closed_detects_common_phrases():
    assert fields.text_looks_closed("This job is no longer accepting applications.")
    assert fields.text_looks_closed("This position has been filled.")
    assert fields.text_looks_closed("Page not found")


def test_closed_detects_greenhouse_not_found():
    assert fields.text_looks_closed(
        "Job not found. The job you requested was not found."
    )


def test_open_job_not_flagged_closed():
    body = (
        "Software Engineer Intern. Notion is the connected workspace where better, "
        "faster work happens. Apply below. First name, last name, email, resume."
    )
    assert not fields.text_looks_closed(body)


# --- application URL derivation ---------------------------------------------

def test_lever_apply_url():
    j = Job(company="Palantir", title="SWE Intern", url="https://jobs.lever.co/palantir/abc", ats="lever")
    assert LeverApplicator().application_url(j).endswith("/abc/apply")


def test_ashby_apply_url():
    j = Job(company="Notion", title="SWE Intern", url="https://jobs.ashbyhq.com/notion/abc", ats="ashby")
    assert AshbyApplicator().application_url(j).endswith("/abc/application")


def test_greenhouse_apply_url_is_job_url():
    j = Job(company="Stripe", title="SWE Intern", url="https://job-boards.greenhouse.io/stripe/jobs/1", ats="greenhouse")
    assert GreenhouseApplicator().application_url(j) == j.url


def test_registry_picks_by_ats():
    assert get_applicator(Job(company="X", title="t", url="u", ats="ashby")).ats == "ashby"
    assert get_applicator(Job(company="X", title="t", url="u", ats="workday")) is None


# --- is_done: never re-apply to handled jobs ---------------------------------

def test_is_done_terminal_statuses():
    for status in ("submitted", "reviewed", "skipped", "closed"):
        applog = {"j1": {"status": status}}
        assert applog_mod.is_done("j1", applog) is True


def test_is_done_failed_skipped_by_default_but_retryable():
    applog = {"j1": {"status": "failed"}}
    assert applog_mod.is_done("j1", applog) is True              # default: don't re-show
    assert applog_mod.is_done("j1", applog, retry_failed=True) is False  # opt-in retry


def test_is_done_unknown_or_prepared_not_done():
    assert applog_mod.is_done("missing", {}) is False
    assert applog_mod.is_done("j1", {"j1": {"status": "prepared"}}) is False


# --- CSV mirror --------------------------------------------------------------

def test_save_writes_csv_in_sync(tmp_path, monkeypatch):
    import csv as _csv

    monkeypatch.setattr(applog_mod, "APPLOG_PATH", tmp_path / "applications.json")
    monkeypatch.setattr(applog_mod, "APPLOG_CSV", tmp_path / "applications.csv")

    applog = {}
    j = Job(company="Stripe", title="SWE Intern", url="https://x/stripe", ats="greenhouse")
    applog_mod.record(applog, j, "submitted", "auto")
    applog_mod.save(applog)

    assert (tmp_path / "applications.json").exists()
    assert (tmp_path / "applications.csv").exists()

    with (tmp_path / "applications.csv").open(newline="") as fh:
        rows = list(_csv.DictReader(fh))
    assert len(rows) == 1
    assert rows[0]["company"] == "Stripe"
    assert rows[0]["status"] == "submitted"
    assert rows[0]["url"] == "https://x/stripe"
