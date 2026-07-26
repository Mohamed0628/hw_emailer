"""Ensure new consumer-hardware companies receive the 2027 cohort path."""

from __future__ import annotations

from src.consumer_2027_filters import _target_companies, apply_filters
from src.filters import normalize_text
from src.models import Job


def test_new_catalog_company_is_in_2027_target_set():
    _target_companies.cache_clear()
    assert normalize_text("SharkNinja") in _target_companies()
    assert normalize_text("GoPro") in _target_companies()


def test_new_catalog_role_can_use_description_based_2027_start():
    job = Job(
        company="SharkNinja",
        title="Electrical Engineer",
        url="https://example.com/sharkninja-2027",
        locations=["Needham, MA"],
        description=(
            "Bachelor's degree in electrical engineering. Candidates graduating in "
            "May 2027 must be available to start in July 2027. Support schematic "
            "capture, PCB design, embedded firmware, and consumer product validation."
        ),
    )

    assert apply_filters([job]) == [job]
    assert job.year == 2027
    assert job.role_type == "new_grad"
    assert job.priority == "A"
