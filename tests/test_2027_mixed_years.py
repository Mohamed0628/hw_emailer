"""Regression tests for postings that name both 2026 and 2027."""

from src.consumer_2027_filters import detect_2027_cohort
from src.models import Job
from src.sources.github_lists import _parse_table_row

_SOURCE = "githublist:speedyapply-2027-new-grad-usa"


def test_feed_keeps_mixed_year_title_when_2027_is_included():
    row = (
        "| Example Electronics | Hardware Engineer, 2026 or 2027 Start | "
        "Austin, TX | $95K | [Apply](https://example.com/mixed-year) | 1d |"
    )
    job = _parse_table_row(
        row,
        _SOURCE,
        default_year=2027,
        role_type="new_grad",
        reject_explicit_other_years=True,
    )

    assert job is not None
    assert job.year == 2027


def test_cohort_detection_prefers_latest_title_year():
    job = Job(
        company="Oura",
        title="Hardware Engineer, 2026 or 2027 Start",
        url="https://example.com/job",
        locations=["Austin, TX"],
    )

    assert detect_2027_cohort(job) == 2027
