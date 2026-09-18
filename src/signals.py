"""One configurable hardware vocabulary for scoring and resume comparisons."""
from functools import lru_cache
from . import config
from .filters import normalize_text, _norm_term, _term_pattern


@lru_cache(maxsize=1)
def vocabulary() -> dict:
    return config._load_yaml("job_preferences.yaml")


def hits(text: str, terms: list[str]) -> list[str]:
    normalized = normalize_text(text)
    return [t for t in terms if _term_pattern(_norm_term(t)).search(normalized)]


def features(text: str) -> dict[str, list[str]]:
    return {domain: hits(text, terms) for domain, terms in vocabulary()["domains"].items()}


def is_minnesota(location: str) -> bool:
    # City names in other states must not earn the MN bonus (Plymouth, MA).
    import re
    if re.search(r"\bMN\b|\bMinnesota\b", location, re.I):
        return True
    if re.search(r",\s*[A-Z]{2}\b", location):
        return False
    return bool(hits(location, ["minneapolis", "saint paul", "st paul", "twin cities"]))
