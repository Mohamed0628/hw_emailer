"""Tests for 2027-start consumer-electronics and hardware opportunities."""

from __future__ import annotations

from src.consumer_2027_filters import apply_filters, detect_2027_cohort
from src.models import Job
from src.sources.github_lists import _parse_table_row, build_sources

_TRUSTED_SOURCE = "githublist:speedyapply-2027-new-grad-usa"


def make_job(
    company: str,
    title: str,
    description: str = "",
    *,
    source: str = "greenhouse:test",
    year: int | None = None,
    role_type: str | None = None,
) -> Job:
    return Job(
        company=company,
        title=title,
        url="https://example.com/job",
        locations=["San Francisco, CA"],
        source=source,
        description=description,
        year=year,
        role_type=role_type,
    )


def test_readme_parser_finds_markdown_apply_link_before_last_column():
    row = (
        "| Oura | Hardware Engineer | San Francisco, CA | $105K-$135K | "
        "[Apply](https://example.com/oura-hardware) | 1d |"
    )
    job = _parse_table_row(
        row,
        _TRUSTED_SOURCE,
        default_year=2027,
        role_type="new_grad",
        reject_explicit_other_years=True,
    )

    assert job is not None
    assert job.url == "https://example.com/oura-hardware"
    assert job.year == 2027
    assert job.role_type == "new_grad"


def test_readme_parser_handles_live_html_company_and_apply_links():
    row = (
        '| <a href="https://www.oura.com"><strong>Oura</strong></a> | '
        "Hardware Engineer | San Francisco, CA | $105K-$135K | "
        '<a href="https://example.com/oura-hardware"><img src="apply.png" '
        'alt="Apply" width="70"/></a> | 1d |'
    )
    job = _parse_table_row(
        row,
        _TRUSTED_SOURCE,
        default_year=2027,
        role_type="new_grad",
        reject_explicit_other_years=True,
    )

    assert job is not None
    assert job.company == "Oura"
    assert job.url == "https://example.com/oura-hardware"
    assert job.year == 2027


def test_2027_feed_rejects_explicit_2026_title():
    row = (
        "| Example Electronics | Hardware Engineer, 2026 Start | Austin, TX | "
        "$95K | [Apply](https://example.com/2026-role) | 1d |"
    )
    job = _parse_table_row(
        row,
        _TRUSTED_SOURCE,
        default_year=2027,
        role_type="new_grad",
        reject_explicit_other_years=True,
    )

    assert job is None


def test_target_company_role_uses_2027_start_language_in_description():
    job = make_job(
        "Oura",
        "Hardware Design Engineer",
        "Bachelor's degree in electrical engineering. Candidates graduating in "
        "May 2027 must be available to start in July 2027. Design PCB electronics "
        "for wearable consumer products.",
    )

    assert detect_2027_cohort(job) == 2027
    assert apply_filters([job]) == [job]
    assert job.year == 2027
    assert job.role_type == "new_grad"
    assert job.priority == "A"
    assert "2027 start or graduation cohort" in job.entry_level_evidence


def test_2027_cohort_does_not_override_hard_experience_requirement():
    job = make_job(
        "Oura",
        "Hardware Design Engineer",
        "Candidates graduating in 2027 are welcome to apply. Bachelor's degree "
        "and a minimum of 4 years of professional hardware-design experience required.",
    )

    assert apply_filters([job]) == []


def test_trusted_2027_feed_can_rescue_non_catalog_hardware_company():
    job = make_job(
        "Example Consumer Electronics",
        "Hardware Engineer",
        source=_TRUSTED_SOURCE,
        year=2027,
        role_type="new_grad",
    )

    assert apply_filters([job]) == [job]
    assert job.year == 2027
    assert job.priority == "A"
    assert "trusted 2027 US new-grad feed" in job.entry_level_evidence


def test_non_catalog_company_is_not_rescued_only_from_description_year():
    job = make_job(
        "Unrelated Industrial Company",
        "Hardware Engineer",
        "The selected candidate will graduate in 2027 and start in August 2027.",
    )

    assert apply_filters([job]) == []


def test_existing_2026_hardware_internship_still_passes():
    job = make_job(
        "Example Electronics",
        "Hardware Engineering Intern, Summer 2026",
    )

    assert apply_filters([job]) == [job]
    assert job.year == 2026
    assert job.role_type == "internship"


def test_2027_new_grad_source_is_configured():
    sources = build_sources()
    source = next(item for item in sources if item.name == _TRUSTED_SOURCE)

    assert source.default_year == 2027
    assert source.role_type == "new_grad"
    assert source.reject_explicit_other_years is True
