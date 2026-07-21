"""Generic, label-driven form filling.

ATS application forms differ in markup but share field *semantics* (first name,
email, resume upload, ...). Matching on visible label / placeholder / attribute
text is far more portable than per-site CSS ids, and the review step is the
safety net for anything this misses. Every locator op is wrapped — a fill engine
must never crash the run.
"""

from __future__ import annotations

import logging
import re

from ..models import ApplicantProfile

log = logging.getLogger(__name__)


# Phrases that mean the posting is closed / not taking applications. Matched
# case-insensitively against the page text.
_CLOSED_PHRASES = (
    "no longer accepting",
    "no longer available",
    "not accepting applications",
    "isn't hiring for this role",
    "is not hiring for this role",
    "not hiring for this role",
    "this position has been filled",
    "this role has been filled",
    "applications are closed",
    "posting is closed",
    "job is closed",
    "this job is no longer",
    "position is no longer",
    "we are no longer considering",
    # expired / removed postings (Greenhouse, Lever, etc.)
    "job you requested was not found",
    "job you requested",
    "job not found",
    "posting not found",
    "position not found",
    "could not find the job",
    "couldn't find the job",
    "page not found",
    "404",
)


def text_looks_closed(text: str) -> bool:
    # Check only the top of the page — a long job description that happens to
    # contain "404" deep in the body shouldn't trip it.
    head = (text or "").lower()[:1200]
    return any(p in head for p in _CLOSED_PHRASES)


def looks_closed(page) -> bool:
    try:
        return text_looks_closed(page.inner_text("body") or "")
    except Exception:  # noqa: BLE001
        return False


def _name_parts(full_name: str) -> tuple[str, str]:
    parts = (full_name or "").split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def _specs(profile: ApplicantProfile) -> list[dict]:
    first, last = _name_parts(profile.full_name)
    raw = [
        (r"first name|given name", "first", first),
        (r"last name|family name|surname", "last", last),
        (r"^name$|full name|your name|legal name", "name", profile.full_name),
        (r"e-?mail", "email", profile.email),
        (r"phone|mobile|telephone", "phone", profile.phone),
        (r"linkedin", "linkedin", profile.linkedin),
        (r"github", "github", profile.github),
        (r"portfolio|website|personal site", "url", profile.website),
        (r"school|university|college|institution", "school", profile.school),
        (r"gpa", "gpa", profile.gpa),
        (r"location|city|where are you", "location", profile.current_location),
    ]
    return [
        {"label": lbl, "attr": attr, "value": val}
        for (lbl, attr, val) in raw
        if val
    ]


def _find_input(page, label_re: str, attr: str):
    # 1) associated <label>
    try:
        loc = page.get_by_label(re.compile(label_re, re.I))
        if loc.count() >= 1 and loc.first.is_visible():
            return loc.first
    except Exception:  # noqa: BLE001
        pass
    # 2) placeholder text
    try:
        loc = page.get_by_placeholder(re.compile(label_re, re.I))
        if loc.count() >= 1 and loc.first.is_visible():
            return loc.first
    except Exception:  # noqa: BLE001
        pass
    # 3) name / id attribute substring
    sel = (
        f"input[name*='{attr}' i], input[id*='{attr}' i], "
        f"input[aria-label*='{attr}' i]"
    )
    try:
        loc = page.locator(sel)
        if loc.count() >= 1 and loc.first.is_visible():
            return loc.first
    except Exception:  # noqa: BLE001
        pass
    return None


def fill_text_fields(page, profile: ApplicantProfile) -> list[str]:
    filled: list[str] = []
    for spec in _specs(profile):
        el = _find_input(page, spec["label"], spec["attr"])
        if el is None:
            continue
        try:
            if (el.input_value() or "").strip():
                continue  # already populated
            el.fill(spec["value"])
            filled.append(spec["attr"])
        except Exception:  # noqa: BLE001
            continue
    return filled


def upload_resume(page, resume_path: str) -> bool:
    try:
        inputs = page.locator("input[type='file']")
        count = inputs.count()
    except Exception:  # noqa: BLE001
        count = 0
    if not count:
        return False
    # Prefer a file input that looks resume/cv related; else the first one.
    target = None
    for i in range(count):
        el = inputs.nth(i)
        try:
            ident = " ".join(
                (el.get_attribute(a) or "")
                for a in ("name", "id", "aria-label")
            ).lower()
        except Exception:  # noqa: BLE001
            ident = ""
        if any(k in ident for k in ("resume", "cv", "attach")):
            target = el
            break
    target = target or inputs.first
    try:
        target.set_input_files(resume_path)  # works even on hidden inputs
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("resume upload failed: %s", exc)
        return False


def fill_cover_letter(page, text: str) -> bool:
    if not text:
        return False
    try:
        loc = page.get_by_label(re.compile(r"cover letter|why .*interest", re.I))
        if loc.count() >= 1 and loc.first.is_visible():
            loc.first.fill(text)
            return True
    except Exception:  # noqa: BLE001
        pass
    # Fallback: a lone textarea on the page is often the free-text / cover field.
    try:
        tas = page.locator("textarea")
        if tas.count() == 1 and tas.first.is_visible():
            if not (tas.first.input_value() or "").strip():
                tas.first.fill(text)
                return True
    except Exception:  # noqa: BLE001
        pass
    return False


def _describe(el) -> str:
    for attr in ("aria-label", "name", "id", "placeholder"):
        try:
            v = el.get_attribute(attr)
            if v:
                return v
        except Exception:  # noqa: BLE001
            continue
    return "<unlabeled field>"


def find_unfilled_required(page) -> list[str]:
    """Visible required fields still empty — the signal for a 'hard' form."""
    out: list[str] = []
    sel = (
        "input[required], textarea[required], select[required], "
        "[aria-required='true']"
    )
    try:
        loc = page.locator(sel)
        count = min(loc.count(), 80)
    except Exception:  # noqa: BLE001
        return out
    for i in range(count):
        el = loc.nth(i)
        try:
            if not el.is_visible():
                continue
            typ = (el.get_attribute("type") or "").lower()
            if typ in ("hidden", "submit", "button"):
                continue
            if typ in ("checkbox", "radio"):
                val = "x" if el.is_checked() else ""
            else:
                val = el.input_value()
            if (val or "").strip() == "":
                desc = _describe(el)
                if desc not in out:
                    out.append(desc)
        except Exception:  # noqa: BLE001
            continue
    return out


def find_submit_button(page):
    import re as _re

    name_re = _re.compile(r"submit application|submit|apply now|send application", _re.I)
    try:
        loc = page.get_by_role("button", name=name_re)
        if loc.count() >= 1 and loc.first.is_visible():
            return loc.first
    except Exception:  # noqa: BLE001
        pass
    for sel in ("input[type='submit']", "button[type='submit']"):
        try:
            loc = page.locator(sel)
            if loc.count() >= 1 and loc.first.is_visible():
                return loc.first
        except Exception:  # noqa: BLE001
            continue
    return None
