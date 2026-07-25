"""Tests for description-aware early-career filtering."""

from __future__ import annotations

from src.models import Job
from src.smart_filters import explain_pass, passes, workday_search_terms


def make_job(
    title: str,
    description: str = "",
    company: str = "Example Medical",
    location: str = "Minneapolis, MN",
) -> Job:
    return Job(
        company=company,
        title=title,
        url="https://example.com/job",
        locations=[location],
        description=description,
    )


def test_unnumbered_engineer_passes_with_zero_to_two_year_requirement():
    job = make_job(
        "Electrical Engineer",
        "Bachelor's degree in Electrical Engineering and 0-2 years of experience.",
    )
    assert passes(job)
    assert job.role_type == "new_grad"
    assert job.entry_level_score >= 5


def test_engineer_ii_passes_only_when_bachelors_path_is_zero_to_two():
    eligible = make_job(
        "R&D Engineer II",
        "Bachelor's degree with 0-2 years of relevant experience.",
        company="Medtronic",
    )
    assert passes(eligible), explain_pass(eligible)
    assert "Engineer II verified at 0-2 years" in eligible.entry_level_evidence

    ineligible = make_job(
        "R&D Engineer II",
        "Bachelor's degree with 3-6 years of experience or "
        "Master's degree with 0-3 years of experience.",
        company="Medtronic",
    )
    assert not passes(ineligible)
    info = explain_pass(ineligible)
    assert "bachelor's path requires 3+ years" == info["rejection_reason"]


def test_engineer_i_is_rejected_when_description_requires_experience():
    job = make_job(
        "Electrical Engineer I",
        "Bachelor's degree and a minimum of 4 years of professional experience.",
    )
    assert not passes(job)


def test_senior_title_is_never_rescued_by_description():
    job = make_job(
        "Senior Electrical Engineer",
        "Bachelor's degree and 0 years of experience.",
    )
    assert not passes(job)


def test_minnesota_medtech_alias_supplies_category_and_priority():
    job = make_job(
        "R&D Engineer",
        "Bachelor's degree and no previous experience required. "
        "Work under close supervision on medical device verification.",
        company="Minnetronix Medical",
    )
    assert passes(job), explain_pass(job)
    assert job.category == "medtech_hardware"
    assert job.priority == "A"
    assert job.hiring_signal


def test_existing_internship_behavior_is_preserved():
    job = make_job("Embedded Firmware Intern", "")
    assert passes(job)
    assert job.role_type == "internship"


def test_medtronic_workday_queries_include_full_time_titles():
    terms = workday_search_terms("Medtronic")
    assert "intern" in terms
    assert "engineer i" in terms
    assert "engineer ii" in terms
    assert "electrical engineer" in terms
