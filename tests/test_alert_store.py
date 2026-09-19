from src.alert_store import jobs_from_seen_state, load_alert_jobs, merge_alert_jobs, save_alert_jobs
from src.models import Job


def test_alert_store_roundtrip(tmp_path):
    path = tmp_path / "alerts.json"
    job = Job(company="Acme", title="RF Engineer", url="https://jobs.lever.co/acme/abc",
              description="RF hardware", source="lever")
    save_alert_jobs(path, [job])
    loaded = load_alert_jobs(path)
    assert len(loaded) == 1
    assert loaded[0].company == "Acme"
    assert loaded[0].description == "RF hardware"


def test_merge_alert_jobs_deduplicates_and_keeps_richer_record():
    old = Job(company="Acme", title="RF Engineer", url="https://jobs.lever.co/acme/abc")
    new = Job(company="Acme", title="RF Engineer", url="https://jobs.lever.co/acme/abc?utm_source=email",
              description="Design RF hardware", ats="lever")
    merged = merge_alert_jobs([old], [new])
    assert len(merged) == 1
    assert merged[0].description == "Design RF hardware"
    assert merged[0].ats == "lever"


def test_seen_state_backfills_legacy_email_alerts():
    state = {
        "old": {
            "company": "Legacy Co",
            "title": "Electrical Engineer I",
            "url": "https://example.com/jobs/123",
            "requisition_id": "123",
            "first_seen": "2026-09-01",
        }
    }
    jobs = jobs_from_seen_state(state)
    assert len(jobs) == 1
    assert jobs[0].company == "Legacy Co"
    assert jobs[0].source == "alert-history"
    assert jobs[0].requisition_id == "123"
