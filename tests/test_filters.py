"""Edge-case tests for hw_emailer.filters."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.filters import (
    apply_filters,
    classify_category,
    detect_season,
    detect_year,
    explain_pass,
    is_engineer_i,
    is_internship,
    is_new_grad,
    is_us_location,
    normalize_text,
    passes,
)


def make_job(title, location="Minneapolis, MN", company="", season=None,
             year=None, **extra):
    """A lightweight Job stand-in (filters only uses attribute access)."""
    return SimpleNamespace(
        title=title, location_str=location, company=company,
        season=season, year=year, **extra,
    )


def base_filters(**overrides):
    f = {
        "role": {
            "internship_terms": ["intern", "co-op"],
            "new_grad_terms": ["new grad"],
            "exclude_terms": ["senior", "staff", "principal", "full-time"],
            "allow_internships": True,
            "allow_new_grad": True,
            "seasons": [],
            "years": [],
        },
        "categories": {},  # rely on built-in category aliases
        "require_category": True,
        "location": {
            "require_us": True,
            "keep_when_location_unknown": True,
            "us_terms": [],
            "non_us_terms": [],
        },
    }
    f.update(overrides)
    return f


# ---------------------------------------------------------------------------
# Normalization / matching
# ---------------------------------------------------------------------------

def test_normalization_variants():
    assert normalize_text("R&D Engineer") == "r and d engineer"
    assert normalize_text("Research & Development") == "r and d"
    assert normalize_text("Hardware Co-op") == "hardware coop"
    assert normalize_text("New-Grad  Engineer") == "new grad engineer"
    assert "c++" in normalize_text("C++ Developer")


def test_token_boundaries_prevent_false_positives():
    f = base_filters()
    # "ai" must not match inside "maintenance"; "board" not in "onboarding".
    assert passes(make_job("Electrical Maintenance Engineering Intern"), f)
    assert not passes(make_job("Onboarding Program Intern"), f)


# ---------------------------------------------------------------------------
# Titles that should pass
# ---------------------------------------------------------------------------

SHOULD_PASS = [
    "Electrical Engineering Intern",
    "PCB Design Intern",
    "Hardware Design Co-op",
    "Embedded Firmware Intern",
    "Device Software Intern",
    "Product Development Engineering Intern - Medical Devices",
    "R&D Engineering Intern, Implantable Systems",
    "Systems Verification Intern - Surgical Robotics",
    "Design Validation Intern - Electronics",
    "Vehicle Electronics Intern",
    "Powertrain Controls Intern",
    "Electrical Architecture Engineer I",
    "Associate Hardware Engineer",
    "New Grad Firmware Engineer",
    "Robot Hardware Intern",
    "Mechatronics Engineering Intern",
    "Motion Control Intern",
    "Industrial Automation Intern",
    "PLC Controls Engineering Intern",
    "Power Electronics Intern",
    "Motor Drives Intern",
    "Avionics Hardware Intern",
    "Flight Controls Intern",
    "Silicon Validation Intern",
    "Post-Silicon Validation Intern",
    "FPGA Design Intern",
    "Field Applications Engineer I - Analog Semiconductor",
    "Electroacoustic Engineering Intern",
    "Hardware Test Engineering Intern",
    "Board Bring-Up Intern",
    "NPI Hardware Engineering Intern",
]


@pytest.mark.parametrize("title", SHOULD_PASS)
def test_should_pass(title):
    job = make_job(title)
    assert passes(job, base_filters()), explain_pass(job, base_filters())


# ---------------------------------------------------------------------------
# Titles that should fail
# ---------------------------------------------------------------------------

SHOULD_FAIL = [
    "Software Engineering Intern",
    "Backend Engineering Intern",
    "Machine Learning Intern",
    "Data Science Intern",
    "Product Management Intern",
    "Marketing Intern",
    "Finance Intern",
    "Human Resources Intern",
    "Civil Engineering Intern",
    "Chemical Engineering Intern",
    "Clinical Research Intern",
    "Mechanical Engineering Intern",
    "Manufacturing Technician",
    "Senior Electrical Engineer",
    "Staff Firmware Engineer",
    "Principal Hardware Engineer",
    "Electrical Engineer II",
    "Engineering Manager",
    "Field Service Technician",
    "Vehicle Dynamics Mechanical Intern",
    "Product Development Intern - Consumer Marketing",
    "Systems Intern - Information Technology",
    "Validation Intern - Pharmaceutical Chemistry",
    "Applications Engineering Intern - Cloud Software",
]


@pytest.mark.parametrize("title", SHOULD_FAIL)
def test_should_fail(title):
    job = make_job(title)
    assert not passes(job, base_filters()), explain_pass(job, base_filters())


# ---------------------------------------------------------------------------
# Context-dependent generic titles
# ---------------------------------------------------------------------------

GENERIC = [
    "Engineering Intern",
    "R&D Intern",
    "Product Development Intern",
    "Verification Intern",
    "Validation Intern",
]


@pytest.mark.parametrize("title", GENERIC)
def test_generic_titles_fail_without_context(title):
    assert not passes(make_job(title), base_filters())


def test_generic_title_passes_with_company_alias():
    f = base_filters()
    f["company_aliases"] = {
        "medtronic": {
            "category": "medtech_hardware",
            "include_terms": ["product development", "r&d",
                              "design verification"],
        },
    }
    job = make_job("Product Development Intern", company="Medtronic")
    assert passes(job, f)
    assert job.category == "medtech_hardware"

    # Alias only applies to its own company.
    other = make_job("Product Development Intern", company="Acme Corp")
    assert not passes(other, f)


def test_generic_title_passes_with_builtin_company_context():
    # No alias config, but a known medtech employer supplies context.
    job = make_job("R&D Intern", company="Boston Scientific")
    assert passes(job, base_filters())
    assert job.category == "medtech_hardware"


def test_generic_title_passes_with_department_metadata():
    job = make_job("Engineering Intern", department="Embedded Systems")
    assert passes(job, base_filters())


def test_embedded_software_allowed_but_plain_software_rejected():
    f = base_filters()
    assert passes(make_job("Embedded Software Intern"), f)
    assert passes(make_job("Machine Learning Hardware Intern"), f)
    assert not passes(make_job("Robotics Software Intern"), f)
    assert passes(make_job("Robotics Software Intern - Controls"), f)


# ---------------------------------------------------------------------------
# Role-type detection
# ---------------------------------------------------------------------------

def test_engineer_i_levels():
    assert is_engineer_i("electrical engineer i")
    assert is_engineer_i("hardware engineer 1")
    assert is_engineer_i("controls engineer level 1")
    assert not is_engineer_i("electrical engineer ii")
    assert not is_engineer_i("electrical engineer iii")
    assert not is_engineer_i("electrical engineer iv")


def test_engineer_i_not_confused_by_following_word():
    # "Engineer I - Analog" must still register as Engineer I.
    assert is_engineer_i("field applications engineer i analog")


def test_associate_requires_technical_pairing():
    role_cfg = {"new_grad_terms": [], "exclude_terms": []}
    assert is_new_grad("associate hardware engineer", role_cfg)
    assert is_new_grad("junior electrical engineer", role_cfg)
    assert not is_new_grad("summer associate", role_cfg)
    assert not is_new_grad("associate marketing specialist", role_cfg)


def test_summer_associate_needs_technical_context():
    role_cfg = {"internship_terms": [], "exclude_terms": []}
    assert is_internship("hardware summer associate", role_cfg)
    assert not is_internship("investment banking summer associate", role_cfg)


def test_new_grad_gated_by_allow_flag():
    f = base_filters()
    f["role"]["allow_new_grad"] = False
    assert not passes(make_job("Associate Hardware Engineer"), f)


# ---------------------------------------------------------------------------
# Category priority / specificity
# ---------------------------------------------------------------------------

def test_specific_category_wins():
    assert classify_category("pcb design intern", {}) == "pcb_hardware"
    assert (classify_category("embedded firmware intern medical devices", {})
            == "embedded_firmware")
    assert (classify_category("power electronics controls intern", {})
            == "power_electronics")


def test_configured_category_names_are_respected():
    cfg = {
        "pcb": ["pcb", "circuit"],
        "embedded": ["embedded", "firmware"],
        "medical": ["medical device"],
    }
    # Built-in aliases classify into the *configured* names.
    assert classify_category("board layout intern", cfg) == "pcb"
    assert classify_category("rtos firmware intern", cfg) == "embedded"
    assert classify_category("implantable device intern", cfg) == "medical"


def test_configured_priority_breaks_ties():
    f = base_filters()
    f["categories"] = {"embedded": ["embedded"], "medical": ["medical device"]}
    f["category_priority"] = ["medical", "embedded"]
    job = make_job("Embedded Medical Device Intern")
    assert passes(job, f)
    # "medical device" (2 tokens, strong) outscores "embedded" here anyway;
    # the point is that the result is deterministic and configurable.
    assert job.category == "medical"


# ---------------------------------------------------------------------------
# Location handling
# ---------------------------------------------------------------------------

LOC = {"require_us": True, "keep_when_location_unknown": True,
       "us_terms": [], "non_us_terms": []}


@pytest.mark.parametrize("loc,expected", [
    ("San Jose, CA", True),          # CA = California, not Canada
    ("Portland, OR", True),          # OR = Oregon, not the word "or"
    ("Indianapolis, IN", True),      # IN = Indiana, not the word "in"
    ("Remote - US", True),
    ("United States Remote", True),
    ("Washington, DC", True),
    ("Minnesota", True),
    ("Boston, MA / Toronto, ON", True),   # multi-location with a US option
    ("Toronto, ON", False),
    ("Vancouver, BC", False),
    ("Remote - Canada", False),
    ("Remote - Europe", False),
    ("London, United Kingdom", False),
    ("Munich, Germany", False),
    ("Bangalore, India", False),
    ("", True),                      # unknown location kept by default
])
def test_locations(loc, expected):
    job = make_job("Electrical Engineering Intern", location=loc)
    assert is_us_location(job, LOC) is expected


def test_location_unknown_can_be_dropped():
    cfg = dict(LOC, keep_when_location_unknown=False)
    assert not is_us_location(make_job("EE Intern", location=""), cfg)


# ---------------------------------------------------------------------------
# Season / year
# ---------------------------------------------------------------------------

def test_season_normalization():
    assert detect_season(make_job("Autumn 2026 Hardware Intern")) == "fall"
    assert detect_season(make_job("Off-Cycle Electrical Intern")) == "offcycle"
    assert detect_season(make_job("Hardware Intern", season="Summer")) == "summer"


def test_year_detection_and_windows():
    assert detect_year(make_job("Hardware Intern Summer 2027")) == 2027

    f = base_filters()
    f["role"]["seasons"] = ["summer"]
    f["role"]["years"] = [2027]

    assert passes(make_job("Summer 2027 Electrical Engineering Intern"), f)
    assert not passes(make_job("Fall 2027 Electrical Engineering Intern"), f)
    assert not passes(make_job("Summer 2026 Electrical Engineering Intern"), f)
    # Missing season/year must not reject.
    assert passes(make_job("Electrical Engineering Intern"), f)


# ---------------------------------------------------------------------------
# Annotation semantics / explainability
# ---------------------------------------------------------------------------

def test_accepted_jobs_are_annotated():
    job = make_job("Summer 2027 PCB Design Intern")
    kept = apply_filters([job], base_filters())
    assert kept == [job]
    assert job.category == "pcb_hardware"
    assert job.season == "summer"
    assert job.year == 2027


def test_rejected_jobs_are_not_mutated():
    job = SimpleNamespace(title="Marketing Intern", location_str="Boston, MA",
                          company="", season=None, year=None)
    assert not passes(job, base_filters())
    assert not hasattr(job, "category")
    assert job.season is None and job.year is None


def test_explain_pass_matches_passes():
    f = base_filters()
    good = make_job("Embedded Firmware Intern")
    bad = make_job("Marketing Intern")

    info = explain_pass(good, f)
    assert info["passed"] is True
    assert info["role_type"] == "internship"
    assert info["category"] == "embedded_firmware"
    assert info["rejection_reason"] is None

    info = explain_pass(bad, f)
    assert info["passed"] is False
    assert info["rejection_reason"].startswith("excluded:")

    # Same underlying evaluation as passes().
    assert passes(good, f) is True
    assert passes(bad, f) is False


def test_config_is_not_mutated():
    f = base_filters()
    import copy
    snapshot = copy.deepcopy(f)
    passes(make_job("Embedded Firmware Intern"), f)
    passes(make_job("Marketing Intern"), f)
    assert f == snapshot
