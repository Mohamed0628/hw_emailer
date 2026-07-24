"""Filtering: keep US internships and new-grad jobs in our target categories.

A job passes only if it is:
1. An internship or new-grad role (and not excluded by seniority/domain rules).
2. Within an allowed season/year when detectable.
3. In a target category (built-in hardware/EE domain aliases supplement the
   configured categories; generic titles need corroborating context).
4. US-located.

As a side effect, ``apply_filters`` annotates each *kept* Job with
``.category``, ``.season``, and ``.year``.  Rejected jobs are never mutated.

Design notes
------------
* All matching happens on a normalized copy of the title (lowercase,
  punctuation folded to spaces, ``&`` -> ``and``, ``co-op`` -> ``coop``,
  ``R&D``/``research and development`` -> ``r and d``); the original title is
  never modified.  ``C++`` survives normalization because ``+`` is preserved.
* Terms match on token boundaries, so ``ai`` never matches ``maintenance``
  and ``board`` never matches ``onboarding``.  A trailing ``*`` on a term
  enables prefix matching on the final token (``schematic*`` matches
  ``schematics``, ``validat*`` matches ``validation``).
* Categories are scored: specific/strong phrases outrank broad ones, weak
  generic terms (``verification``, ``product development``, ``r and d``...)
  only count when hardware/domain context exists in the title, company, or
  job metadata.  Ties break on a deterministic priority list.
* ``explain_pass`` exposes the exact same evaluation used by ``passes`` so
  diagnostics can never disagree with filtering.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Iterable, Optional

from . import config
from .models import Job

# ---------------------------------------------------------------------------
# Text normalization
# ---------------------------------------------------------------------------

_WS_RE = re.compile(r"\s+")
# Keep [a-z0-9+] so meaningful tokens like "c++" survive normalization.
_NON_TOKEN_RE = re.compile(r"[^a-z0-9+]+")

# Phrase-level canonicalization applied after tokenization, so that config
# terms and titles converge on a single spelling.
_PHRASE_CANON: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bco ops\b"), "coops"),
    (re.compile(r"\bco op\b"), "coop"),
    (re.compile(r"\boff cycle\b"), "offcycle"),
    (re.compile(r"\bnew graduate\b"), "new grad"),
    (re.compile(r"\bresearch and development\b"), "r and d"),
)


def _normalize_raw(s: str) -> str:
    """Normalize arbitrary text for matching (uncached core)."""
    s = (s or "").lower()
    s = s.replace("&", " and ")
    s = _NON_TOKEN_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()
    for rx, repl in _PHRASE_CANON:
        s = rx.sub(repl, s)
    return s


@lru_cache(maxsize=4096)
def normalize_text(s: str) -> str:
    """Cached normalization for short strings (titles, terms, locations)."""
    return _normalize_raw(s)


@lru_cache(maxsize=None)
def _norm_term(term: str) -> str:
    """Normalize a match term, preserving a trailing ``*`` prefix marker."""
    term = (term or "").strip()
    star = term.endswith("*")
    normalized = normalize_text(term[:-1] if star else term)
    return normalized + "*" if star and normalized else normalized


@lru_cache(maxsize=256)
def _norm_terms(terms: tuple[str, ...]) -> tuple[str, ...]:
    """Normalize a tuple of configured terms once (config is never mutated)."""
    out = []
    for t in terms:
        n = _norm_term(t)
        if n:
            out.append(n)
    return tuple(out)


# ---------------------------------------------------------------------------
# Phrase-aware matching
# ---------------------------------------------------------------------------

@lru_cache(maxsize=None)
def _term_pattern(term: str) -> re.Pattern[str]:
    """Compile a normalized term into a token-boundary-aware regex.

    Terms match whole tokens (``ee`` will not match ``engineering``); a
    trailing ``*`` allows the final token to be a prefix (``validat*``
    matches ``validation``).
    """
    prefix = term.endswith("*")
    core = term[:-1] if prefix else term
    pattern = r"(?<!\S)" + re.escape(core)
    pattern += r"\S*" if prefix else r"(?!\S)"
    return re.compile(pattern)


def _match_terms(text: str, terms: Iterable[str]) -> tuple[str, ...]:
    """Return the normalized terms that match ``text``."""
    return tuple(t for t in terms if t and _term_pattern(t).search(text))


def _contains_any(text: str, terms: Iterable[str]) -> bool:
    """Return True when any normalized term matches the text."""
    return any(t and _term_pattern(t).search(text) for t in terms)


def _lc(s: str) -> str:
    """Return a lowercase string, safely handling empty values."""
    return (s or "").lower()


def _tokens(term: str) -> int:
    """Number of tokens in a term (used for specificity scoring)."""
    return term.rstrip("*").count(" ") + 1


# ---------------------------------------------------------------------------
# Built-in vocabularies
# ---------------------------------------------------------------------------

# Signals that establish "this title is in hardware/EE territory", enabling
# generic weak terms like "verification" or "product development".
_HARDWARE_CONTEXT: tuple[str, ...] = (
    "electrical", "electronic*", "electro", "electromechanical", "hardware",
    "embedded", "firmware", "pcb", "circuit*", "mechatronic*", "robot*",
    "semiconductor*", "silicon", "fpga*", "asic*", "analog", "mixed signal",
    "rf", "avionics", "instrumentation", "medical device*",
    "power electronics", "controls", "plc", "motor*", "battery", "hil",
    "hardware in the loop", "lab",
)

# Canonical built-in categories.  "strong" terms are sufficient on their
# own; "weak" terms are too generic and only count when context exists.
_BUILTIN_CATEGORIES: dict[str, dict[str, tuple[str, ...]]] = {
    "pcb_hardware": {
        "strong": (
            "pcb", "printed circuit board*", "circuit board*", "board design",
            "board layout", "pcb layout", "schematic*", "hardware design",
            "electronics design", "circuit design", "electrical design",
            "analog hardware", "digital hardware", "mixed signal",
            "signal integrity", "power integrity", "board bring up",
            "board validation", "prototype electronics",
            "electronic design automation", "eda", "altium", "kicad",
            "orcad", "allegro", "mentor graphics", "electroacoustic*",
        ),
        "weak": ("bring up", "npi", "pads", "layout"),
    },
    "embedded_firmware": {
        "strong": (
            "embedded", "firmware", "device software", "bare metal", "rtos",
            "real time system*", "microcontroller*", "mcu", "bsp",
            "board support package", "bootloader*", "device driver*",
            "kernel driver*", "stm32", "esp32", "nrf*", "arm cortex",
            "low level software", "motor control firmware", "fpga firmware",
        ),
        "weak": ("real time", "low level", "nordic"),
    },
    "medtech_hardware": {
        "strong": (
            "medical device*", "medtech", "implantable*", "wearable*",
            "diagnostic device*", "surgical robot*", "neurotech*",
            "bioelectronic*", "catheter*", "design assurance",
            "electronics development", "hardware development",
        ),
        "weak": (
            "product development", "r and d", "systems engineering",
            "systems integration", "verification", "validation",
            "design verification", "design validation", "reliability",
            "sustaining engineering", "diagnostic*", "instrumentation",
        ),
    },
    "automotive": {
        "strong": (
            "automotive", "vehicle electronics", "vehicle system*",
            "vehicle integration", "electrical architecture",
            "e e architecture", "ecu*", "electronic control unit*",
            "body electronics", "powertrain*", "propulsion",
            "battery management", "bms", "charging system*", "harness*",
            "wire harness*", "wiring system*", "electrical distribution",
            "adas", "autonomous vehicle*", "embedded controls",
        ),
        "weak": ("vehicle*", "functional safety", "test and validation"),
    },
    "robotics_controls": {
        "strong": (
            "robot*", "mechatronic*", "electromechanical", "control system*",
            "motion control*", "motor control*", "servo*", "actuator*",
            "actuation", "manipulator*", "industrial automation", "plc",
            "scada", "hmi", "machine control*", "autonomous system*",
            "hardware integration",
        ),
        "weak": ("controls", "automation", "systems integration",
                 "commissioning"),
    },
    "power_electronics": {
        "strong": (
            "power electronics", "motor drive*", "electric drive*",
            "inverter*", "converter*", "power conversion", "power suppl*",
            "battery system*", "energy storage", "power distribution",
            "protection and control*", "industrial control*",
            "control panel*", "panel design", "instrumentation",
            "power system*", "electrical system*",
        ),
        "weak": ("field service", "commissioning", "applications engineering",
                 "power", "battery", "relay*"),
    },
    "semiconductor": {
        "strong": (
            "semiconductor*", "asic*", "fpga*", "rtl", "digital design",
            "analog design", "analog", "mixed signal design",
            "physical design", "silicon", "post silicon", "pre silicon",
            "tapeout", "package design",
        ),
        "weak": (
            "design verification", "verification", "validation",
            "characterization", "applications engineering",
            "field applications*", "product engineering", "test engineering",
            "lab validation",
        ),
    },
    "aerospace": {
        "strong": (
            "avionics", "flight control*", "flight test*", "gnc",
            "guidance navigation*", "spacecraft*", "satellite*", "payload*",
            "aerospace electrical", "telemetry", "hardware in the loop",
            "hil", "flight software", "electrical integration",
        ),
        "weak": ("aerospace", "mission system*", "test system*"),
    },
    "electrical": {
        "strong": (
            "electrical engineer*", "electrical", "electronics",
            "hardware engineer*", "hardware", "hardware test*",
            "hardware validation",
        ),
        "weak": ("test engineer*",),
    },
}

# Deterministic tie-break order (most specific domains first).
_BUILTIN_PRIORITY: tuple[str, ...] = (
    "pcb_hardware", "embedded_firmware", "medtech_hardware", "automotive",
    "robotics_controls", "power_electronics", "semiconductor", "aerospace",
    "electrical",
)

# Map configured category names (e.g. "pcb", "medical") onto built-in
# canonical categories so their alias vocabularies apply automatically.
_CONFIGURED_NAME_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("pcb", "circuit", "board"), "pcb_hardware"),
    (("embedded", "firmware"), "embedded_firmware"),
    (("med", "bio", "health"), "medtech_hardware"),
    (("auto", "vehicle", "ev"), "automotive"),
    (("robot", "mechatronic", "control"), "robotics_controls"),
    (("power", "energy", "drive"), "power_electronics"),
    (("semi", "silicon", "chip", "asic", "fpga", "vlsi"), "semiconductor"),
    (("aero", "avionic", "space", "defense"), "aerospace"),
    (("electric", "ee", "hardware"), "electrical"),
)

# --- Role-type vocabularies ------------------------------------------------

_BUILTIN_INTERNSHIP_TERMS: tuple[str, ...] = (
    "intern", "interns", "internship", "internships", "coop", "coops",
    "student engineer*", "engineering student*",
)
# "summer associate" only counts when the title is technical.
_CONDITIONAL_INTERNSHIP_TERMS: tuple[str, ...] = ("summer associate*",)

_BUILTIN_NEW_GRAD_TERMS: tuple[str, ...] = (
    "new grad", "recent graduate*", "early career", "entry level",
    "university graduate*", "campus hire*", "rotational engineer*",
    "rotational program", "development program engineer*",
    "engineering development program", "graduate engineer*",
)

# "associate"/"junior" only count as new-grad next to a technical title.
_ASSOCIATE_MARKERS: tuple[str, ...] = ("associate", "junior", "jr")
_TECH_ENGINEER_PHRASES: tuple[str, ...] = (
    "hardware engineer*", "electrical engineer*", "firmware engineer*",
    "electronics engineer*", "embedded engineer*", "controls engineer*",
    "test engineer*", "systems engineer*", "robotics engineer*",
    "mechatronics engineer*", "power engineer*", "design engineer*",
    "validation engineer*", "verification engineer*",
    "applications engineer*",
)

# --- Exclusion groups (contextual allow rules, not one blunt list) ---------

_SENIORITY_EXCLUDES: tuple[str, ...] = (
    "senior", "sr", "staff", "principal", "lead", "manager*", "director*",
    "architect", "architects", "distinguished", "fellow", "chief", "vp",
    "vice president", "head", "supervisor*", "expert",
)

# Match Engineer II/III/IV/V/2..9 (Engineer I is handled separately).
_ENGINEER_LEVEL_2PLUS_RE = re.compile(
    r"\bengineer\s+(?:level\s+)?(?:ii|iii|iv|v|vi|[2-9])\b"
)

# Match entry-level Engineer I titles without accidentally matching
# Engineer II, Engineer III, or Engineer IV.
#
# Accepted examples:
#   Electrical Engineer I
#   Hardware Engineer 1
#   Firmware Engineer Level I
#   Controls Engineer Level 1
_ENGINEER_I_RE = re.compile(
    r"\bengineer\s+(?:level\s+)?(?:1|i)\b(?!\s*i\b)",
    re.IGNORECASE,
)

# Trades / non-engineering roles: always rejected.
_NON_ENGINEER_EXCLUDES: tuple[str, ...] = (
    "technician*", "mechanic", "mechanics", "machinist*", "welder*",
)

# Business / corporate functions: always rejected.
_BUSINESS_EXCLUDES: tuple[str, ...] = (
    "product manager*", "product management", "project manager*",
    "project management", "program manager*", "program management",
    "business*", "sales*", "marketing*", "finance*", "financial*",
    "accounting", "accountant*", "human resources", "hr", "recruiter*",
    "recruiting", "recruitment", "talent*", "legal", "attorney*",
    "paralegal*", "counsel", "supply chain", "procurement", "sourcing",
    "logistics", "customer success", "customer support", "communications",
    "brand*", "merchandis*",
)

# Other engineering / science disciplines: rejected unless an EE signal
# co-occurs (so "Electro-Mechanical Intern" survives "mechanical").
_OTHER_ENG_EXCLUDES: tuple[str, ...] = (
    "civil", "structural", "geotechnical", "environmental", "chemical*",
    "chemistry", "clinical*", "biolog*", "microbiolog*", "wet lab",
    "pharmaceutic*", "pharmacy", "pharmacist*", "nursing", "nurse*",
    "physician*", "industrial design*", "graphic*", "ux", "ui",
    "mechanical",
)
_OTHER_ENG_ALLOWS: tuple[str, ...] = (
    "electrical", "electronic*", "electro", "electromechanical",
    "mechatronic*", "controls", "embedded", "firmware", "instrumentation",
    "hardware", "avionics", "power electronics", "robot*",
)

# Software / IT / data roles: rejected unless embedded/low-level/hardware
# indicators are present ("Embedded Software Intern" must pass).
_SOFTWARE_EXCLUDES: tuple[str, ...] = (
    "software", "frontend", "front end", "backend", "back end",
    "full stack", "fullstack", "web", "mobile developer*", "mobile app*",
    "mobile engineer*", "ios", "android", "cloud", "devops",
    "site reliability", "sre", "data science*", "data scientist*",
    "data engineer*", "data analyst*", "analytics", "machine learning",
    "deep learning", "ml", "ai", "artificial intelligence",
    "computer vision", "perception", "nlp", "cybersecurity", "security",
    "information technology", "it", "network administrat*", "help desk",
    "database*",
)
_SOFTWARE_ALLOWS: tuple[str, ...] = (
    "embedded", "firmware", "device software", "bsp",
    "board support package", "device driver*", "driver development",
    "kernel*", "rtos", "bare metal", "low level", "real time", "controls",
    "hardware", "fpga*", "asic*", "silicon", "accelerator*",
    "mechatronic*", "hil", "hardware in the loop", "avionics",
    "flight software",
)

# Small built-in company -> category context map.  This does NOT auto-pass a
# job; it only supplies domain context so generic titles ("R&D Intern") can
# classify.  Prefer `company_aliases` configuration for anything beyond this.
_BUILTIN_COMPANY_CONTEXT: dict[str, str] = {
    "medtronic": "medtech_hardware",
    "boston scientific": "medtech_hardware",
    "abbott": "medtech_hardware",
    "stryker": "medtech_hardware",
    "texas instruments": "semiconductor",
    "analog devices": "semiconductor",
}

_FULLTIME_VARIANTS = {"full-time", "full time", "fulltime"}

_YEAR_RE = re.compile(r"\b(20\d{2})\b")

# Map detection keywords (searched in normalized text) to canonical labels.
_SEASON_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("summer", "summer"),
    ("spring", "spring"),
    ("autumn", "fall"),
    ("fall", "fall"),
    ("winter", "winter"),
    ("offcycle", "offcycle"),
)


# ---------------------------------------------------------------------------
# Season / year detection
# ---------------------------------------------------------------------------

def _metadata_texts(job: Job) -> tuple[str, ...]:
    """Optional department/team strings, safely fetched."""
    return tuple(
        s for s in (
            getattr(job, "department", None),
            getattr(job, "team", None),
        ) if s
    )


def _find_season(text: str) -> Optional[str]:
    norm = normalize_text(text)
    for keyword, canonical in _SEASON_KEYWORDS:
        if _term_pattern(keyword).search(norm):
            return canonical
    return None


def detect_season(job: Job) -> Optional[str]:
    """Detect and normalize a job's season from its fields or title."""
    if job.season:
        return _find_season(job.season) or normalize_text(job.season)

    for text in (job.title or "", *_metadata_texts(job)):
        season = _find_season(text)
        if season:
            return season

    return None


def detect_year(job: Job) -> Optional[int]:
    """Detect a four-digit year from the job, title, or metadata."""
    if job.year:
        return job.year

    for text in (job.title or "", *_metadata_texts(job)):
        match = _YEAR_RE.search(text)
        if match:
            return int(match.group(1))

    return None


# ---------------------------------------------------------------------------
# Exclusion logic
# ---------------------------------------------------------------------------

def _excluded(norm_title: str) -> Optional[tuple[str, tuple[str, ...]]]:
    """Return (reason, matched_terms) when the title should be rejected.

    Exclusions are grouped, and the "other engineering" and "software"
    groups honor contextual allow terms so that e.g. Embedded Software
    Intern or Electro-Mechanical Intern are not rejected.
    """
    hits = _match_terms(norm_title, _SENIORITY_EXCLUDES)
    if hits or _ENGINEER_LEVEL_2PLUS_RE.search(norm_title):
        return ("seniority", hits or ("engineer level >= 2",))

    hits = _match_terms(norm_title, _NON_ENGINEER_EXCLUDES)
    if hits:
        return ("non_engineering_role", hits)

    hits = _match_terms(norm_title, _BUSINESS_EXCLUDES)
    if hits:
        return ("business_role", hits)

    hits = _match_terms(norm_title, _OTHER_ENG_EXCLUDES)
    if hits and not _contains_any(norm_title, _OTHER_ENG_ALLOWS):
        return ("other_discipline", hits)

    hits = _match_terms(norm_title, _SOFTWARE_EXCLUDES)
    if hits and not _contains_any(norm_title, _SOFTWARE_ALLOWS):
        return ("software_role", hits)

    return None


def _hard_excludes(role_cfg: dict) -> tuple[str, ...]:
    """Return normalized configured exclusions (minus full-time variants)."""
    raw = tuple(
        term for term in role_cfg.get("exclude_terms", ())
        if _lc(term) not in _FULLTIME_VARIANTS
    )
    return _norm_terms(raw)


def _technical_signal(norm_title: str) -> bool:
    """True when the title carries any hardware/EE domain signal."""
    if _contains_any(norm_title, _HARDWARE_CONTEXT):
        return True
    return any(
        _contains_any(norm_title, spec["strong"])
        for spec in _BUILTIN_CATEGORIES.values()
    )


# ---------------------------------------------------------------------------
# Role-type detection
# ---------------------------------------------------------------------------

def is_internship(title_lc: str, role_cfg: dict) -> bool:
    """Return True if the title looks like a relevant internship.

    Built-in variants (intern, co-op, student engineer, ...) supplement the
    configured ``internship_terms``.  Seniority terms, configured excludes,
    and built-in domain excludes (HR, marketing, plain software, ...) reject
    the title; contextual allow rules keep embedded/firmware roles.
    """
    norm = normalize_text(title_lc)

    terms = _norm_terms(tuple(role_cfg.get("internship_terms", ())))
    matched = (
        _contains_any(norm, _BUILTIN_INTERNSHIP_TERMS)
        or _contains_any(norm, terms)
        or (
            _contains_any(norm, _CONDITIONAL_INTERNSHIP_TERMS)
            and _technical_signal(norm)
        )
    )
    if not matched:
        return False

    if _contains_any(norm, _hard_excludes(role_cfg)):
        return False

    return _excluded(norm) is None


def is_engineer_i(title_lc: str) -> bool:
    """Return True for Engineer I / Engineer 1 / Level 1 Engineer titles.

    The regex deliberately avoids matching higher levels such as
    Engineer II, Engineer III, or Engineer IV.
    """
    return bool(_ENGINEER_I_RE.search(normalize_text(title_lc)))


def _is_associate_new_grad(norm_title: str) -> bool:
    """Associate/Junior only counts next to a technical engineering title."""
    return (
        _contains_any(norm_title, _ASSOCIATE_MARKERS)
        and _contains_any(norm_title, _TECH_ENGINEER_PHRASES)
    )


def is_new_grad(title_lc: str, role_cfg: dict) -> bool:
    """Return True if the title looks like a new-grad / early-career role."""
    norm = normalize_text(title_lc)

    terms = _norm_terms(tuple(role_cfg.get("new_grad_terms", ())))
    matched = (
        _contains_any(norm, _BUILTIN_NEW_GRAD_TERMS)
        or _contains_any(norm, terms)
        or is_engineer_i(norm)
        or _is_associate_new_grad(norm)
    )
    if not matched:
        return False

    if _contains_any(norm, _hard_excludes(role_cfg)):
        return False

    return _excluded(norm) is None


# ---------------------------------------------------------------------------
# Category classification
# ---------------------------------------------------------------------------

def _builtin_for_configured(name: str) -> Optional[str]:
    """Map a configured category name onto a built-in canonical category."""
    if name in _BUILTIN_CATEGORIES:
        return name
    norm = normalize_text(name).replace(" ", "_")
    for hints, builtin in _CONFIGURED_NAME_HINTS:
        if any(hint in norm for hint in hints):
            return builtin
    return None


def _freeze_categories(categories_cfg: dict) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Turn the categories config into a hashable key without mutating it."""
    return tuple(
        (name, tuple(terms or ()))
        for name, terms in (categories_cfg or {}).items()
    )


@lru_cache(maxsize=32)
def _compiled_categories(
    cfg_key: tuple[tuple[str, tuple[str, ...]], ...],
) -> tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...]:
    """Return (name, strong_terms, weak_terms) triples for classification.

    Configured categories keep their names; their terms are treated as
    strong and supplemented (never replaced) by the vocabulary of the
    built-in category their name maps onto.  With no configured
    categories, the built-in canonical set is used directly.
    """
    if not cfg_key:
        return tuple(
            (name, spec["strong"], spec["weak"])
            for name, spec in _BUILTIN_CATEGORIES.items()
        )

    out = []
    for name, terms in cfg_key:
        strong = list(_norm_terms(terms))
        weak: tuple[str, ...] = ()
        builtin = _builtin_for_configured(name)
        if builtin:
            spec = _BUILTIN_CATEGORIES[builtin]
            strong.extend(t for t in spec["strong"] if t not in strong)
            weak = spec["weak"]
        out.append((name, tuple(strong), weak))
    return tuple(out)


@lru_cache(maxsize=16)
def _priority_index(
    priority_key: tuple[str, ...],
    names: tuple[str, ...],
) -> dict[str, int]:
    """Deterministic rank per category (configured priority wins)."""
    order: list[str] = []
    for name in priority_key:
        if name in names and name not in order:
            order.append(name)
    # Then built-in priority, mapped through configured names.
    for builtin in _BUILTIN_PRIORITY:
        for name in names:
            if name in order:
                continue
            if name == builtin or _builtin_for_configured(name) == builtin:
                order.append(name)
    # Anything left keeps its configuration order.
    for name in names:
        if name not in order:
            order.append(name)
    return {name: i for i, name in enumerate(order)}


def _score_categories(
    norm_text: str,
    cat_defs: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...],
    priority: dict[str, int],
    has_context: bool,
    strong_only: bool = False,
) -> tuple[Optional[str], tuple[str, ...]]:
    """Score all categories against text; return the best (name, matches).

    Strong matches score 10 + 2 * tokens, weak matches 3 + tokens; weak
    terms only count when context exists (a strong match anywhere, a
    hardware context term, company/industry context, or metadata).  Ties
    break on the deterministic priority order, never dict insertion order.
    """
    strong_hits = {
        name: _match_terms(norm_text, strong)
        for name, strong, _ in cat_defs
    }
    context = (
        has_context
        or any(strong_hits.values())
        or _contains_any(norm_text, _HARDWARE_CONTEXT)
    )

    best_name: Optional[str] = None
    best_matches: tuple[str, ...] = ()
    best_key: tuple[int, int] = (0, 0)

    for name, _, weak in cat_defs:
        s_hits = strong_hits[name]
        w_hits = () if strong_only or not context else _match_terms(norm_text, weak)
        score = sum(10 + 2 * _tokens(t) for t in s_hits)
        score += sum(3 + _tokens(t) for t in w_hits)
        if score <= 0:
            continue
        key = (score, -priority.get(name, len(priority)))
        if key > best_key:
            best_key = key
            best_name = name
            best_matches = s_hits + w_hits

    return best_name, best_matches


def classify_category(
    title_lc: str,
    categories_cfg: dict,
) -> Optional[str]:
    """Classify a job title into the best-scoring configured category.

    Title-only classification (kept for backward compatibility); ``passes``
    uses an internal company- and metadata-aware classifier built on the
    same scoring.
    """
    cat_defs = _compiled_categories(_freeze_categories(categories_cfg))
    names = tuple(name for name, _, _ in cat_defs)
    priority = _priority_index((), names)
    name, _ = _score_categories(
        normalize_text(title_lc), cat_defs, priority, has_context=False
    )
    return name


def _job_company(job: Job) -> str:
    """Best-effort normalized company name."""
    company = (
        getattr(job, "company", None)
        or getattr(job, "company_name", None)
        or getattr(job, "employer", None)
        or ""
    )
    return normalize_text(str(company))


def _resolve_category_name(name: str, names: tuple[str, ...]) -> str:
    """Map an alias/built-in category onto a configured name when possible."""
    if not name or name in names:
        return name
    builtin = _builtin_for_configured(name) or name
    for configured in names:
        if _builtin_for_configured(configured) == builtin:
            return configured
    return name


def _company_alias(
    job: Job,
    f: dict,
) -> tuple[Optional[dict], Optional[str]]:
    """Return (alias_cfg, builtin_context_category) for the job's company."""
    norm_company = _job_company(job)
    if not norm_company:
        return None, None

    alias_cfg = None
    for key, spec in (f.get("company_aliases") or {}).items():
        norm_key = _norm_term(str(key))
        if norm_key and _term_pattern(norm_key).search(norm_company):
            alias_cfg = spec or {}
            break

    builtin_ctx = None
    for key, category in _BUILTIN_COMPANY_CONTEXT.items():
        if _term_pattern(key).search(norm_company):
            builtin_ctx = category
            break

    return alias_cfg, builtin_ctx


def _classify_job(
    job: Job,
    f: dict,
    norm_title: str,
) -> tuple[Optional[str], tuple[str, ...]]:
    """Company- and metadata-aware classification used by ``passes``.

    Signal order: configured company aliases, then the title (strongest),
    then department/team, then description (strong terms only) — so a long
    description cannot overwhelm a clearly unrelated title.
    """
    categories_cfg = f.get("categories", {}) or {}
    cat_defs = _compiled_categories(_freeze_categories(categories_cfg))
    names = tuple(name for name, _, _ in cat_defs)
    priority_cfg = tuple(f.get("category_priority", ()) or ())
    priority = _priority_index(priority_cfg, names)

    alias_cfg, builtin_ctx = _company_alias(job, f)

    # 1. Configured company aliases override/supplement built-in rules.
    if alias_cfg:
        include = _norm_terms(tuple(alias_cfg.get("include_terms", ())))
        matched = _match_terms(norm_title, include)
        if matched:
            name = _resolve_category_name(
                str(alias_cfg.get("category", "")), names
            )
            if name:
                return name, matched

    company_context = bool(alias_cfg) or bool(builtin_ctx)

    # Department/team can supply context for generic titles.
    meta_norm = tuple(normalize_text(t) for t in _metadata_texts(job))
    meta_context = any(
        _contains_any(m, _HARDWARE_CONTEXT) for m in meta_norm
    )

    # 2. Title is the strongest signal.
    name, matched = _score_categories(
        norm_title, cat_defs, priority,
        has_context=company_context or meta_context,
    )
    if name:
        return name, matched

    # 3. Department / team (full scoring).
    for m in meta_norm:
        name, matched = _score_categories(
            m, cat_defs, priority, has_context=company_context
        )
        if name:
            return name, matched

    # 4. Description: strong terms only, and only for otherwise-generic
    #    titles that already look like target roles.
    description = getattr(job, "description", None) or ""
    if description:
        desc_norm = _normalize_raw(str(description)[:1500])
        name, matched = _score_categories(
            desc_norm, cat_defs, priority,
            has_context=False, strong_only=True,
        )
        if name:
            return name, matched

    # 5. Company industry context alone can rescue a generic technical
    #    title (e.g. "R&D Intern" at a known medtech company).
    if builtin_ctx and not alias_cfg:
        name = _resolve_category_name(builtin_ctx, names)
        weak_terms = _BUILTIN_CATEGORIES[builtin_ctx]["weak"]
        matched = _match_terms(norm_title, weak_terms)
        if matched:
            return name, matched

    return None, ()


# ---------------------------------------------------------------------------
# Location
# ---------------------------------------------------------------------------

_US_STATE_ABBRS = frozenset(
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN "
    "MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA "
    "WA WV WI WY DC PR".split()
)
_CA_PROVINCE_ABBRS = frozenset(
    "BC ON QC AB MB SK NS NB NL PE YT NT NU".split()
)

_US_STATE_NAMES: tuple[str, ...] = (
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana",
    "maine", "maryland", "massachusetts", "michigan", "minnesota",
    "mississippi", "missouri", "montana", "nebraska", "nevada",
    "new hampshire", "new jersey", "new mexico", "new york",
    "north carolina", "north dakota", "ohio", "oklahoma", "oregon",
    "pennsylvania", "rhode island", "south carolina", "south dakota",
    "tennessee", "texas", "utah", "vermont", "virginia", "washington",
    "west virginia", "wisconsin", "wyoming", "district of columbia",
    "washington dc", "puerto rico",
)

_BUILTIN_US_TERMS: tuple[str, ...] = (
    "united states", "usa", "u s", "us remote", "remote us",
) + _US_STATE_NAMES

_BUILTIN_NON_US_TERMS: tuple[str, ...] = (
    "canada", "canadian", "mexico", "united kingdom", "uk", "england",
    "scotland", "wales", "ireland", "germany", "france", "netherlands",
    "spain", "italy", "poland", "sweden", "switzerland", "austria",
    "belgium", "denmark", "norway", "finland", "portugal", "czech*",
    "hungary", "romania", "india", "china", "japan", "korea", "singapore",
    "malaysia", "taiwan", "vietnam", "philippines", "thailand",
    "indonesia", "australia", "new zealand", "brazil", "argentina",
    "colombia", "chile", "costa rica", "israel", "turkey",
    "united arab emirates", "saudi arabia", "egypt", "south africa",
    "nigeria", "kenya", "europe", "emea", "apac", "latam",
    "toronto", "vancouver", "montreal", "ottawa", "calgary", "london",
    "bangalore", "bengaluru", "hyderabad", "munich", "berlin", "paris",
    "dublin", "tel aviv", "shanghai", "beijing", "tokyo", "sydney",
)

# Uppercase indicators read from the ORIGINAL location string, so that
# state abbreviations aren't lowercased away ("IN", "OR", "ME", "CA")
# and can't be confused with ordinary words.
_UPPER_US_RE = re.compile(r"(?<![A-Za-z])(?:U\.?S\.?A?\.?|US)(?![A-Za-z])")
_UPPER_ABBR_RE = re.compile(r"(?<![A-Za-z])([A-Z]{2})(?![A-Za-z])")
_COMMA_ABBR_RE = re.compile(r",\s*([A-Z]{2})(?![A-Za-z])")


@lru_cache(maxsize=8)
def _loc_regex(terms: tuple[str, ...]) -> Optional[re.Pattern[str]]:
    """Compile lowercase location terms into one alternation.

    This prevents short location terms from matching inside longer words.
    For example, ", ca" can match "San Jose, CA" without matching "Canada".
    """
    if not terms:
        return None
    pattern = "(?:" + "|".join(re.escape(t) for t in terms) + ")(?![a-z])"
    return re.compile(pattern)


def _loc_match(text: str, terms: Iterable[str]) -> bool:
    """Return True when the location text matches a configured term."""
    rx = _loc_regex(tuple(terms))
    return bool(rx.search(text)) if rx else False


def _builtin_location_signals(original: str) -> tuple[bool, bool]:
    """Return (has_us, has_non_us) using built-in heuristics.

    Comma-state patterns and standalone uppercase abbreviations are read
    from the original string; country/city/state names from the
    normalized string.  US and Canadian abbreviation sets are disjoint,
    so ", CA" reads as California while ", ON" reads as Ontario.
    """
    has_us = False
    has_non_us = False

    if _UPPER_US_RE.search(original):
        has_us = True

    for rx in (_COMMA_ABBR_RE, _UPPER_ABBR_RE):
        for match in rx.finditer(original):
            abbr = match.group(1)
            if abbr in _US_STATE_ABBRS:
                has_us = True
            elif abbr in _CA_PROVINCE_ABBRS:
                has_non_us = True

    norm = normalize_text(original)
    if _contains_any(norm, _BUILTIN_US_TERMS):
        has_us = True
    if _contains_any(norm, _BUILTIN_NON_US_TERMS):
        has_non_us = True

    return has_us, has_non_us


def is_us_location(job: Job, loc_cfg: dict) -> bool:
    """Return True if the job has an accepted US location.

    Multi-location postings are kept when at least one US location exists.
    Configured ``us_terms`` / ``non_us_terms`` are respected and
    supplemented by built-in state/country handling.
    """
    if not loc_cfg.get("require_us", True):
        return True

    original = getattr(job, "location_str", "") or ""
    text = _lc(original)

    if not text.strip():
        return bool(loc_cfg.get("keep_when_location_unknown", True))

    us_terms = tuple(_lc(t) for t in loc_cfg.get("us_terms", ()))
    non_us_terms = tuple(_lc(t) for t in loc_cfg.get("non_us_terms", ()))

    builtin_us, builtin_non_us = _builtin_location_signals(original)

    has_us = builtin_us or _loc_match(text, us_terms)
    has_non_us = builtin_non_us or _loc_match(text, non_us_terms)

    # Keep multi-location postings when at least one US option exists.
    if has_us:
        return True

    if has_non_us:
        return False

    return bool(loc_cfg.get("keep_when_location_unknown", True))


# ---------------------------------------------------------------------------
# Evaluation pipeline
# ---------------------------------------------------------------------------

@dataclass
class FilterResult:
    """Outcome of evaluating one job (shared by ``passes``/``explain_pass``)."""

    passed: bool
    role_type: Optional[str] = None
    category: Optional[str] = None
    matched_terms: tuple[str, ...] = ()
    season: Optional[str] = None
    year: Optional[int] = None
    location_passed: Optional[bool] = None
    rejection_reason: Optional[str] = None


def _evaluate(job: Job, f: dict) -> FilterResult:
    """Run the full filter pipeline for one job without mutating it."""
    title_lc = _lc(job.title)
    norm_title = normalize_text(title_lc)
    role_cfg = f.get("role", {})
    loc_cfg = f.get("location", {})

    # 0. Hard exclusions (seniority, business, unrelated disciplines,
    #    plain software) with contextual allow rules.
    excluded = _excluded(norm_title)
    if excluded:
        reason, terms = excluded
        return FilterResult(
            False, matched_terms=terms,
            rejection_reason=f"excluded:{reason}",
        )

    if _contains_any(norm_title, _hard_excludes(role_cfg)):
        return FilterResult(False, rejection_reason="excluded:configured")

    # 1. Internship or new-grad role.
    internship = is_internship(title_lc, role_cfg)
    new_grad = is_new_grad(title_lc, role_cfg)

    allow_internships = role_cfg.get("allow_internships", True)
    allow_new_grad = role_cfg.get("allow_new_grad", False)

    if allow_internships and internship:
        role_type = "internship"
    elif allow_new_grad and new_grad:
        role_type = "new_grad"
    else:
        return FilterResult(False, rejection_reason="role_type")

    # 2. Season window (only reject on a detected conflict).
    season = detect_season(job)
    allowed_seasons = [_lc(s) for s in role_cfg.get("seasons", ())]
    if allowed_seasons and season and season not in allowed_seasons:
        return FilterResult(
            False, role_type=role_type, season=season,
            rejection_reason="season",
        )

    # 3. Year window (only reject on a detected conflict).
    year = detect_year(job)
    allowed_years = role_cfg.get("years", ())
    if allowed_years and year and year not in allowed_years:
        return FilterResult(
            False, role_type=role_type, season=season, year=year,
            rejection_reason="year",
        )

    # 4. Category (company- and metadata-aware).
    category, matched = _classify_job(job, f, norm_title)
    if f.get("require_category", True) and not category:
        return FilterResult(
            False, role_type=role_type, season=season, year=year,
            rejection_reason="category",
        )

    # 5. US location.
    location_passed = is_us_location(job, loc_cfg)
    if not location_passed:
        return FilterResult(
            False, role_type=role_type, category=category,
            matched_terms=matched, season=season, year=year,
            location_passed=False, rejection_reason="location",
        )

    return FilterResult(
        True, role_type=role_type, category=category or "other",
        matched_terms=matched, season=season, year=year,
        location_passed=True,
    )


def passes(job: Job, f: dict) -> bool:
    """Return True if a job should be kept, annotating it only on success.

    Rejected jobs are left untouched so they never carry misleading
    partial annotations.
    """
    result = _evaluate(job, f)

    if result.passed:
        job.season = result.season
        job.year = result.year
        job.category = result.category or "other"

    return result.passed


def explain_pass(job: Job, f: dict) -> dict[str, Any]:
    """Explain how a job would be filtered, using the exact same logic
    as ``passes`` (diagnostics can never disagree with filtering)."""
    result = _evaluate(job, f)
    return {
        "passed": result.passed,
        "role_type": result.role_type,
        "category": result.category,
        "matched_terms": list(result.matched_terms),
        "season": result.season,
        "year": result.year,
        "location_passed": result.location_passed,
        "rejection_reason": result.rejection_reason,
    }


def apply_filters(
    jobs: list[Job],
    f: Optional[dict] = None,
) -> list[Job]:
    """Apply the configured filters to a list of jobs."""
    filters_config = f if f is not None else config.filters()
    return [job for job in jobs if passes(job, filters_config)]
