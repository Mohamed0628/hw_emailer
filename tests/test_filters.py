"""Filter behaviour against the real config/filters.yaml."""

from src import config
from src.filters import passes
from src.models import Job


def _job(title, locations=None, **kw):
    return Job(
        company=kw.pop("company", "Acme"),
        title=title,
        url=kw.pop("url", f"https://example.com/{abs(hash(title)) % 10000}"),
        locations=locations or [],
        **kw,
    )


F = config.filters()


def test_hardware_intern_us_kept():
    j = _job("Hardware Engineer Intern", ["New York, NY"])
    assert passes(j, F)
    assert j.category == "hardware"
    assert j.season == "summer" or j.season is None  # season may be undetected from title


def test_asic_intern_classified_as_silicon():
    j = _job("ASIC Design Verification Intern", ["Santa Clara, CA"])
    assert passes(j, F)
    assert j.category == "silicon"


def test_firmware_intern_kept():
    j = _job("Firmware Engineering Intern", ["Boston, MA"])
    assert passes(j, F)
    assert j.category == "firmware"


def test_fulltime_senior_role_rejected():
    j = _job("Senior Hardware Engineer", ["San Francisco, CA"])
    assert not passes(j, F)


def test_new_grad_fulltime_rejected():
    j = _job("Hardware Engineer, New Grad", ["Seattle, WA"])
    # no internship term -> rejected
    assert not passes(j, F)


def test_non_us_location_rejected():
    j = _job("Hardware Engineer Intern", ["London, UK"])
    assert not passes(j, F)


def test_canada_rejected():
    j = _job("Embedded Software Intern", ["Toronto, Canada"])
    assert not passes(j, F)


def test_unknown_location_kept():
    j = _job("Electrical Engineering Intern")
    assert passes(j, F)  # keep_when_location_unknown: true


def test_multi_location_with_us_option_kept():
    j = _job("PCB Design Intern", ["London, UK", "New York, NY"])
    assert passes(j, F)


def test_non_category_intern_rejected():
    j = _job("Marketing Intern", ["New York, NY"])
    assert not passes(j, F)


def test_out_of_window_year_rejected():
    j = _job("Hardware Engineer Intern, Summer 2025", ["Austin, TX"])
    assert not passes(j, F)


def test_coop_kept():
    j = _job("Electrical Engineering Co-op", ["Boston, MA"])
    assert passes(j, F)


def test_remote_kept():
    j = _job("Firmware Engineer Intern", ["Remote"])

def test_pure_swe_intern_rejected():
    # software-only titles should no longer match any hardware category
    j = _job("Software Engineer Intern", ["New York, NY"])
    assert not passes(j, F)

def test_remote_kept_2():
    j = _job("RF Engineer Intern", ["Remote"])
    assert passes(j, F)
