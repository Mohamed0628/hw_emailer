from src.job_hydration import hydrate_job
from src.models import Job


def test_greenhouse_uses_public_api(monkeypatch):
    job = Job(company="X", title="RF Engineer",
              url="https://job-boards.greenhouse.io/x/jobs/123", source="alert-history")
    seen = {}
    def fake(url, timeout):
        seen["url"] = url
        return {"id": 123, "content": "<p>RF PCB antenna design</p>",
                "absolute_url": job.url, "location": {"name": "MN"}}, 200
    monkeypatch.setattr("src.job_hydration._json_get", fake)
    result = hydrate_job(job)
    assert result.status == "verified"
    assert "boards-api.greenhouse.io/v1/boards/x/jobs/123" in seen["url"]
    assert result.job.ats == "greenhouse"
    assert "antenna" in result.job.description


def test_lever_uses_specific_public_posting(monkeypatch):
    job = Job(company="X", title="EE I", url="https://jobs.lever.co/x/abc")
    seen = {}
    def fake(url, timeout):
        seen["url"] = url
        return {"id": "abc", "text": "EE I", "descriptionPlain": "PCB power electronics",
                "hostedUrl": job.url, "applyUrl": job.url + "/apply",
                "categories": {"location": "Minneapolis"}}, 200
    monkeypatch.setattr("src.job_hydration._json_get", fake)
    result = hydrate_job(job)
    assert result.status == "verified"
    assert "api.lever.co/v0/postings/x/abc" in seen["url"]
    assert "power electronics" in result.job.description


def test_ashby_matches_public_board_job(monkeypatch):
    job = Job(company="X", title="Analog Engineer",
              url="https://jobs.ashbyhq.com/x/1234")
    def fake(url, timeout):
        return {"jobs": [{"title": "Analog Engineer", "location": "MN",
                          "jobUrl": job.url, "applyUrl": job.url + "/application",
                          "descriptionPlain": "analog mixed signal PCB"}]}, 200
    monkeypatch.setattr("src.job_hydration._json_get", fake)
    result = hydrate_job(job)
    assert result.status == "verified"
    assert result.job.ats == "ashby"
    assert "mixed signal" in result.job.description


def test_workday_is_never_fetched(monkeypatch):
    job = Job(company="X", title="EE I", url="https://x.wd1.myworkdayjobs.com/jobs/job/a/EE-I_R1")
    monkeypatch.setattr("src.job_hydration._json_get",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not fetch")))
    result = hydrate_job(job)
    assert result.status == "manual"


def test_temporary_failure_does_not_mark_job_closed(monkeypatch):
    job = Job(company="X", title="EE I", url="https://jobs.lever.co/x/abc")
    monkeypatch.setattr("src.job_hydration._json_get", lambda *a, **k: (None, 0))
    result = hydrate_job(job)
    assert result.status == "temporary_failure"
    assert result.job.active


def test_404_is_closed(monkeypatch):
    job = Job(company="X", title="EE I", url="https://jobs.lever.co/x/abc")
    monkeypatch.setattr("src.job_hydration._json_get", lambda *a, **k: (None, 404))
    result = hydrate_job(job)
    assert result.status == "closed"
    assert not result.job.active


def test_unknown_host_is_manual_not_fake_closed():
    job = Job(company="X", title="EE I", url="https://example.com/jobs/1")
    result = hydrate_job(job)
    assert result.status == "manual"
    assert result.job.active
