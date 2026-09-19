"""Defense/clearance jobs must remain manual-only."""
from src.apply.defense_gate import is_defense_or_clearance_job
from src.models import Job


def test_known_defense_company_is_manual():
    assert is_defense_or_clearance_job(
        Job(company="Lockheed Martin", title="Electrical Engineer", url="https://example.com/job")
    )


def test_clearance_language_is_manual():
    assert is_defense_or_clearance_job(Job(
        company="Example Aerospace",
        title="RF Engineer",
        url="https://example.com/job",
        description="Candidate must be eligible to obtain a Secret security clearance.",
    ))


def test_dod_or_itar_language_is_manual():
    assert is_defense_or_clearance_job(Job(
        company="Example Systems",
        title="Hardware Engineer",
        url="https://example.com/job",
        description="Hardware development for DoD programs subject to ITAR requirements.",
    ))


def test_normal_hardware_job_is_not_blocked():
    assert not is_defense_or_clearance_job(Job(
        company="Example Medical",
        title="Electrical Engineer",
        url="https://example.com/job",
        description="Design mixed-signal PCBs for medical devices.",
    ))
