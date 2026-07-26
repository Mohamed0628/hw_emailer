from src import career_fit
from src.models import Job


def job(title: str, category: str, description: str = "", company: str = "Example", location: str = "Austin, TX") -> Job:
    return Job(
        company=company,
        title=title,
        url="https://example.com/job",
        locations=[location],
        category=category,
        description=description,
    )


def test_direct_hardware_title_passes_without_description():
    result = career_fit.evaluate(job("Embedded Firmware Engineer I", "embedded_firmware"))
    assert result.passed
    assert result.score >= 70


def test_pcb_design_role_is_high_value():
    result = career_fit.evaluate(
        job(
            "Electrical Hardware Intern, PCB Design",
            "pcb_board_design",
            "Create schematics, perform PCB layout in Altium, and complete board bring-up with an oscilloscope.",
        )
    )
    assert result.passed
    assert result.score >= 80


def test_project_engineer_is_always_rejected():
    result = career_fit.evaluate(
        job(
            "Project Engineer Intern",
            "general_electrical",
            "Track project schedules, budgets, subcontractors, and construction progress.",
        )
    )
    assert not result.passed
    assert result.score == 0


def test_generic_quality_engineer_is_rejected():
    result = career_fit.evaluate(
        job(
            "Quality Engineer I",
            "medtech_hardware",
            "Own CAPA, complaint investigations, document control, and regulatory compliance.",
            company="Abbott",
            location="Minnetonka, MN",
        )
    )
    assert not result.passed


def test_quality_engineer_with_real_electronics_can_pass():
    result = career_fit.evaluate(
        job(
            "Design Quality Engineer I",
            "medtech_hardware",
            "Perform PCB schematic reviews, circuit failure analysis, oscilloscope testing, and embedded hardware validation.",
            company="Medtronic",
            location="Minneapolis, MN",
        )
    )
    assert result.passed


def test_process_engineer_without_hardware_proof_is_rejected():
    result = career_fit.evaluate(
        job(
            "Process Engineer II",
            "manufacturing_npi",
            "Improve production throughput, lean metrics, and manufacturing workflows.",
            company="Medtronic",
            location="Brooklyn Center, MN",
        )
    )
    assert not result.passed


def test_pcba_manufacturing_role_can_pass():
    result = career_fit.evaluate(
        job(
            "Manufacturing Engineer, PCBA",
            "manufacturing_npi",
            "Own PCBA manufacturing, SMT process development, schematic review, board rework, and electrical test fixtures.",
            company="SpaceX",
        )
    )
    assert result.passed


def test_famous_company_does_not_rescue_software_role():
    result = career_fit.evaluate(
        job(
            "Site Reliability Engineer, Kubernetes Platform",
            "avionics_space",
            "Operate Kubernetes clusters, cloud infrastructure, and backend services.",
            company="SpaceX",
        )
    )
    assert not result.passed


def test_minnesota_location_is_only_a_small_bonus():
    result = career_fit.evaluate(
        job(
            "Manufacturing Engineer",
            "manufacturing_npi",
            "Production scheduling and continuous improvement.",
            company="Abbott",
            location="Minnetonka, MN",
        )
    )
    assert not result.passed
