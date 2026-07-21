"""Load the applicant profile for the (future) auto-apply module."""

from __future__ import annotations

from pathlib import Path

import yaml

from .. import config
from ..models import ApplicantProfile

PROFILE_PATH = config.CONFIG_DIR / "profile.yaml"  # gitignored when it holds real data


def load_profile(path: Path | None = None) -> ApplicantProfile:
    path = path or PROFILE_PATH
    if not path.exists():
        return ApplicantProfile()
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return ApplicantProfile(**data)
