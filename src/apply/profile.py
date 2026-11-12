"""Load the applicant profile and local exact-answer cache."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from .. import config
from ..models import ApplicantProfile

PROFILE_PATH = config.CONFIG_DIR / "candidate.yaml"  # gitignored when it holds real data
RUNTIME_ANSWERS_PATH = config.ROOT / "data" / "candidate_confirmed_answers.json"


def _runtime_answers() -> dict[str, str | bool]:
    if not RUNTIME_ANSWERS_PATH.exists():
        return {}
    try:
        data = json.loads(RUNTIME_ANSWERS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def load_profile(path: Path | None = None) -> ApplicantProfile:
    path = path or PROFILE_PATH
    if not path.exists():
        legacy = config.CONFIG_DIR / "profile.yaml"
        if path == PROFILE_PATH and legacy.exists():
            path = legacy
        else:
            profile = ApplicantProfile()
            cached = _runtime_answers()
            return profile.model_copy(update={"confirmed_answers": cached}) if cached else profile
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    profile = ApplicantProfile(**data)
    cached = _runtime_answers()
    if cached:
        profile = profile.model_copy(update={
            "confirmed_answers": {**cached, **profile.confirmed_answers}
        })
    return profile


def remember_confirmed_answers(
    profile: ApplicantProfile,
    answers: dict[str, str | bool],
) -> ApplicantProfile:
    """Persist exact user-entered answers locally for identical future questions."""
    if not answers:
        return profile
    merged_cache = {**_runtime_answers(), **answers}
    RUNTIME_ANSWERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = RUNTIME_ANSWERS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(merged_cache, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(RUNTIME_ANSWERS_PATH)
    return profile.model_copy(update={
        "confirmed_answers": {**profile.confirmed_answers, **answers}
    })
