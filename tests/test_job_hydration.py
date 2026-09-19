import io
from urllib.error import HTTPError

from src.job_hydration import hydrate_job
from src.models import Job


class Headers:
    def get_content_charset(self):
        return "utf-8"


class Response:
    headers = Headers()
    def __init__(self, url, body):
        self.url, self.body = url, body
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def geturl(self): return self.url
    def read(self, n): return self.body[:n]


def test_hydrates_verified_greenhouse(monkeypatch):
    job = Job(company="X", title="RF Engineer", url="https://job-boards.greenhouse.io/x/jobs/123",
              source="alert-history")
    monkeypatch.setattr("src.job_hydration.urlopen",
                        lambda req, timeout: Response(job.url, b"<html>RF PCB antenna design</html>"))
    result = hydrate_job(job)
    assert result.status == "verified"
    assert result.job.ats == "greenhouse"
    assert "antenna" in result.job.description


def test_workday_is_never_hydrated(monkeypatch):
    job = Job(company="X", title="EE I", url="https://x.wd1.myworkdayjobs.com/jobs/job/a/EE-I_R1")
    monkeypatch.setattr("src.job_hydration.urlopen",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not fetch")))
    result = hydrate_job(job)
    assert result.status == "manual"


def test_unknown_host_fails_closed():
    job = Job(company="X", title="EE I", url="https://example.com/jobs/1")
    result = hydrate_job(job)
    assert result.status == "blocked"
    assert not result.job.active


def test_404_is_closed(monkeypatch):
    job = Job(company="X", title="EE I", url="https://jobs.lever.co/x/abc")
    def fail(req, timeout):
        raise HTTPError(job.url, 404, "not found", {}, io.BytesIO())
    monkeypatch.setattr("src.job_hydration.urlopen", fail)
    result = hydrate_job(job)
    assert result.status == "closed"
    assert not result.job.active
