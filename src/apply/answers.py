"""Exact, evidence-backed form answers. Unknown is never converted into No."""
from __future__ import annotations
import re
from dataclasses import dataclass
from ..models import ApplicantProfile


def normalize(value: str) -> str:
    text = (value or "").casefold().strip()
    # ATSs use several visual required markers, including Lever's heavy asterisk.
    text = re.sub(r"[\\*✱＊]+", "", text)
    return re.sub(r"\\s+", " ", text).strip(" :?")


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
_US_STATE_CODES = {
    "al","ak","az","ar","ca","co","ct","de","fl","ga","hi","id","il","in","ia","ks","ky","la",
    "me","md","ma","mi","mn","ms","mo","mt","ne","nv","nh","nj","nm","ny","nc","nd","oh","ok",
    "or","pa","ri","sc","sd","tn","tx","ut","vt","va","wa","wv","wi","wy","dc",
}
_US_STATE_NAMES = {
    "alabama","alaska","arizona","arkansas","california","colorado","connecticut","delaware",
    "florida","georgia","hawaii","idaho","illinois","indiana","iowa","kansas","kentucky",
    "louisiana","maine","maryland","massachusetts","michigan","minnesota","mississippi",
    "missouri","montana","nebraska","nevada","new hampshire","new jersey","new mexico",
    "new york","north carolina","north dakota","ohio","oklahoma","oregon","pennsylvania",
    "rhode island","south carolina","south dakota","tennessee","texas","utah","vermont",
    "virginia","washington","west virginia","wisconsin","wyoming","district of columbia",
}


def _location_parts(value: str) -> tuple[str, str]:
    """Return (city, country) only when the configured location proves the country."""
    text = (value or "").strip()
    if not text:
        return "", ""
    pieces = [p.strip() for p in text.split(",") if p.strip()]
    city = pieces[0] if pieces else text
    low = text.casefold()
    country = ""
    if re.search(r"\b(?:united states|usa|u\.s\.a?\.?|us)\b", low):
        country = "United States"
    else:
        tokens = {p.casefold().strip(".") for p in pieces[1:]}
        if tokens & _US_STATE_CODES or tokens & _US_STATE_NAMES:
            country = "United States"
    return city, country


DEMOGRAPHIC_OPTIONS = {
    "male": {"male"},
    "black": {"black", "black or african american", "black / african american", "black/african american"},
    "not_veteran": {"not a veteran", "i am not a veteran", "i am not a protected veteran", "not a protected veteran"},
    # A current disability answer does not assert no prior disability history.
    "not_disabled": {"not disabled", "i do not have a disability", "no, i do not have a disability"},
}


def _date_parts(value: str) -> tuple[str, str]:
    """Return (month name, year) from explicit profile date text when possible."""
    text = (value or "").strip()
    if not text:
        return "", ""
    months = {
        "01": "January", "02": "February", "03": "March", "04": "April",
        "05": "May", "06": "June", "07": "July", "08": "August",
        "09": "September", "10": "October", "11": "November", "12": "December",
    }
    iso = re.fullmatch(r"(\d{4})-(\d{2})(?:-\d{2})?", text)
    if iso:
        return months.get(iso.group(2), ""), iso.group(1)
    year = re.search(r"\b(20\d{2})\b", text)
    month = next((name for name in months.values() if re.search(r"\b" + name + r"\b", text, re.I)), "")
    return month, year.group(1) if year else ""


def _exact_option(value: str, options: list[str] | None, reason: str) -> Answer:
    if not options:
        return Answer(True, value, reason)
    matches = [o for o in options if normalize(o) == normalize(value)]
    return Answer(True, matches[0], reason) if len(matches) == 1 else Answer(False, reason="candidate value not present as a unique option")


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
    grad_month, grad_year = _date_parts(profile.graduation_date)
    current_city, current_country = _location_parts(profile.current_location)
    values = {
        "first name": first, "given name": first, "last name": last, "family name": last,
        "full name": profile.full_name, "name": profile.full_name,
        "email": profile.email, "email address": profile.email, "e-mail": profile.email,
        "phone": profile.phone, "phone number": profile.phone, "mobile phone": profile.phone,
        "linkedin": profile.linkedin, "linkedin profile": profile.linkedin, "linkedin url": profile.linkedin,
        "github": profile.github, "github url": profile.github,
        "website": profile.website, "portfolio": profile.website,
        "school": profile.school, "university": profile.school,
        "current location": profile.current_location, "current city": current_city,
        "location (city)": current_city, "location city": current_city,
        "city": current_city, "country": current_country, "country/region": current_country,
        "country or region": current_country,
        "gpa": profile.gpa, "current gpa": profile.gpa, "cumulative gpa": profile.gpa,
        "what is your current gpa": profile.gpa, "please enter your cumulative gpa": profile.gpa,
        "graduation date": profile.graduation_date,
        "anticipated graduation date": profile.graduation_date,
        "expected graduation date": profile.graduation_date,
        "graduation year": grad_year, "end date year": grad_year,
        "what year do you intend to complete your degree": grad_year,
        "what year will you graduate": grad_year,
        "end date month": grad_month,
        "earliest available start date": profile.available_start_date or "",
        "what is your earliest available start date": profile.available_start_date or "",
    }

    sponsorship_keys = {
        "will you now or in the future require sponsorship for employment in the us",
        "will you now or in the future require visa sponsorship",
        "will you, at any point, require employer sponsorship to work in the united states",
        "will you require immigration sponsorship to begin working for imc examples of sponsorship would include (but is not limited to) f-1 opt, h-1b, h-4 ead, l-1, l-2, tn, o-1, j-1, e-1/e-2, and e-3",
        "will you require immigration sponsorship in the future to continue working for imc examples of sponsorship would include (but is not limited to) f-1 opt, h-1b, h-4 ead, l-1, l-2, tn, o-1, j-1, e-1/e-2, and e-3",
    }
    if key in sponsorship_keys and profile.requires_sponsorship is not None:
        return _exact_option("Yes" if profile.requires_sponsorship else "No", options, "configured sponsorship answer")

    value = values.get(key)
    if not value:
        return Answer(False)
    return _exact_option(str(value), options, "candidate field")
