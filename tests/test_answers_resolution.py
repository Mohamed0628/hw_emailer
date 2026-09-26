from src.apply.answers import resolve
from src.models import ApplicantProfile


def test_graduation_month_and_year_use_explicit_profile_date():
    profile = ApplicantProfile(graduation_date="2027-05-15")
    assert resolve("End date month*", profile, ["May", "June"]).value == "May"
    assert resolve("End date year*", profile, ["2027", "2028"]).value == "2027"


def test_common_gpa_wording_uses_explicit_profile_gpa():
    profile = ApplicantProfile(gpa="3.31")
    answer = resolve("Please enter your cumulative GPA*", profile)
    assert answer.known
    assert answer.value == "3.31"


def test_sponsorship_yes_no_uses_explicit_boolean_only():
    profile = ApplicantProfile(requires_sponsorship=False)
    answer = resolve(
        "Will you now or in the future require visa sponsorship?*",
        profile,
        ["Yes", "No"],
    )
    assert answer.known
    assert answer.value == "No"


def test_sponsorship_remains_unknown_when_not_configured():
    profile = ApplicantProfile(requires_sponsorship=None)
    answer = resolve(
        "Will you now or in the future require visa sponsorship?*",
        profile,
        ["Yes", "No"],
    )
    assert not answer.known
