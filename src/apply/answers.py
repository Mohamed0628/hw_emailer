"""Exact, evidence-backed form answers. Unknown is never converted into No."""
from __future__ import annotations
import re
from dataclasses import dataclass
from ..models import ApplicantProfile


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold().strip().rstrip("* :?"))


@dataclass
class Answer:
    known: bool
    value: str | bool | None = None
    reason: str = "unconfigured question"


DEMOGRAPHIC_FIELDS = {
    "gender": "gender", "gender identity": "gender", "sex": "gender",
    "race": "race", "race ethnicity": "race", "race/ethnicity": "race",
    "veteran status": "veteran", "protected veteran status": "veteran",
    "disability status": "disability", "disability": "disability",
}
DEMOGRAPHIC_OPTIONS = {
    "male": {"male"},
    "black": {"black", "black or african american", "black / african american", "black/african american"},
    "not_veteran": {"not a veteran", "i am not a veteran", "i am not a protected veteran", "not a protected veteran"},
    # A current disability answer does not assert no prior disability history.
    "not_disabled": {"not disabled", "i do not have a disability", "no, i do not have a disability"},
}


def resolve(label: str, profile: ApplicantProfile, options: list[str] | None = None,
            voluntary: bool = False) -> Answer:
    key = normalize(label)
    confirmed = {normalize(k): v for k, v in {**profile.common_answers, **profile.confirmed_answers}.items()}
    if key in confirmed:
        value = confirmed[key]
        if options:
            matches = [o for o in options if normalize(o) == normalize(str(value))]
            return Answer(True, matches[0], "exact confirmed answer") if len(matches) == 1 else Answer(False, reason="confirmed answer has no unique option")
        return Answer(True, value, "exact confirmed answer")
    if key in DEMOGRAPHIC_FIELDS:
        if not voluntary:
            return Answer(False, reason="demographic field not clearly voluntary")
        value = profile.demographics.get(DEMOGRAPHIC_FIELDS[key])
        allowed = DEMOGRAPHIC_OPTIONS.get(value or "", set())
        matches = [o for o in options or [] if normalize(o) in allowed]
        return Answer(True, matches[0], "configured voluntary demographic") if len(matches) == 1 else Answer(False, reason="demographic option not an exact supported match")
    first, _, last = profile.full_name.partition(" ")
    values = {
        "first name": first, "given name": first, "last name": last, "family name": last,
        "full name": profile.full_name, "name": profile.full_name,
        "email": profile.email, "email address": profile.email, "e-mail": profile.email,
        "phone": profile.phone, "phone number": profile.phone, "mobile phone": profile.phone,
        "linkedin": profile.linkedin, "linkedin profile": profile.linkedin, "linkedin url": profile.linkedin,
        "github": profile.github, "github url": profile.github,
        "website": profile.website, "portfolio": profile.website,
        "school": profile.school, "university": profile.school,
        "current location": profile.current_location, "current city": profile.current_location,
        "gpa": profile.gpa,
    }
    value = values.get(key)
    if not value:
        return Answer(False)
    if options:
        matches = [o for o in options if normalize(o) == normalize(value)]
        return Answer(True, matches[0], "candidate field") if len(matches) == 1 else Answer(False, reason="candidate value not present in options")
    return Answer(True, value, "candidate field")
