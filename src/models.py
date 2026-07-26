"""Core data models."""

from __future__ import annotations

import hashlib
import re
from typing import Optional

from pydantic import BaseModel, Field

Category = str


def normalize_title(title: str) -> str:
    """Lowercase + collapse whitespace, for stable IDs and matching."""
    return re.sub(r"\s+", " ", (title or "").strip().lower())


class Job(BaseModel):
    """A normalized job posting from any source."""

    company: str
    title: str
    url: str
    locations: list[str] = Field(default_factory=list)
    source: str = ""
    ats: Optional[str] = None

    # Filled in by the filter step.
    category: Optional[Category] = None
    season: Optional[str] = None
    year: Optional[int] = None
    role_type: Optional[str] = None
    entry_level_score: int = 0
    entry_level_evidence: list[str] = Field(default_factory=list)
    priority: Optional[str] = None
    hiring_signal: Optional[str] = None

    # Career outcome scoring. These values answer whether the role develops
    # PCB, embedded, firmware, RF, controls, robotics, power, silicon, or
    # hands-on electrical engineering skills rather than generic PM work.
    career_fit_score: int = 0
    career_fit_band: Optional[str] = None
    hardware_skill_score: int = 0
    resume_growth_score: int = 0
    career_alignment_score: int = 0
    company_quality_score: int = 0
    location_fit_score: int = 0
    career_fit_evidence: list[str] = Field(default_factory=list)

    # Optional metadata when the source provides it.
    posted_date: Optional[str] = None
    sponsorship: Optional[str] = None
    active: bool = True
    description: Optional[str] = None
    department: Optional[str] = None
    team: Optional[str] = None
    employment_type: Optional[str] = None

    @property
    def location_str(self) -> str:
        return " | ".join(self.locations) if self.locations else ""

    @property
    def job_id(self) -> str:
        """Stable id used for dedup. Based on company + normalized title + url."""
        basis = f"{self.company.strip().lower()}|{normalize_title(self.title)}|{self.url.strip()}"
        return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


class ApplicantProfile(BaseModel):
    """Stored applicant info for the future auto-apply module."""

    full_name: str = ""
    email: str = ""
    phone: str = ""
    school: str = ""
    graduation_date: str = ""
    gpa: str = ""
    current_location: str = ""
    work_authorization: str = ""
    requires_sponsorship: Optional[bool] = None
    linkedin: str = ""
    github: str = ""
    website: str = ""
    resume_path: str = ""
    summary: str = ""
    common_answers: dict[str, str] = Field(default_factory=dict)

    @property
    def is_configured(self) -> bool:
        """Minimum needed to attempt an application."""
        return bool(self.full_name and self.email and self.resume_path)
