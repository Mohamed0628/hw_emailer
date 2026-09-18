"""Deterministic comparison against every reviewed resume, tied to file hashes."""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, asdict
from pathlib import Path

from . import config
from .models import ApplicantProfile, Job
from .signals import features, hits, vocabulary


@dataclass(frozen=True)
class Resume:
    id: str
    path: str
    sha256: str
    text: str
    sections: dict[str, str]

    @property
    def terms(self) -> set[str]:
        technical = {t for values in features(self.text).values() for t in values}
        return technical | set(hits(self.text, vocabulary()["supporting_embedded"]))


def extract_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        from pypdf import PdfReader
        return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
    if path.suffix.lower() in {".txt", ".md"}:
        return path.read_text(encoding="utf-8")
    raise ValueError("Resume must be PDF or text: " + path.name)


def sections(text: str) -> dict[str, str]:
    parts = re.split(r"(?im)^\s*(Education|Experience|Club Experience|Projects|Skills)\s*$", text)
    result = {"header": parts[0]}
    for i in range(1, len(parts), 2):
        result[parts[i].strip().lower()] = parts[i + 1].strip()
    return result


def load_resumes(profile: ApplicantProfile, root: Path | None = None) -> list[Resume]:
    root = root or config.ROOT
    if len(profile.resumes) != 5:
        raise ValueError("Configure all five reviewed resumes before selecting or applying")
    resumes = []
    for spec in profile.resumes:
        if spec.get("reviewed") is not True:
            raise ValueError("Every resume must be reviewed; no filename-based assumptions")
        path = (root / spec["path"]).resolve()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != spec.get("sha256"):
            raise ValueError("Resume changed since review: " + str(spec.get("id")))
        text = extract_text(path)
        if len(text.strip()) < 100:
            raise ValueError("Resume text unavailable; review OCR first: " + path.name)
        resumes.append(Resume(spec["id"], str(path), digest, text, sections(text)))
    if len({r.id for r in resumes}) != 5 or len({r.sha256 for r in resumes}) != 5:
        raise ValueError("Five distinct resume IDs and files are required")
    return resumes


@dataclass
class ResumeMatch:
    selected_resume: str
    resume_fit_score: int
    evidence: list[str]
    alternative_resume: str
    reason: str
    confident: bool
    rankings: list[dict]
    missing_terms: list[str]
    sha256: str

    def to_dict(self) -> dict:
        return asdict(self)


def match_job(job: Job, resumes: list[Resume]) -> ResumeMatch:
    if len(resumes) != 5:
        raise ValueError("Compare all five resumes")
    job_text = job.title + "\n" + (job.description or "")
    required, preferred = [], []
    # Section-aware keyword weights; absence of headings is handled as ordinary JD text.
    chunks = re.split(r"(?i)(preferred qualifications|nice to have|requirements|required qualifications|responsibilities)", job_text)
    for i in range(1, len(chunks), 2):
        (preferred if 'preferred' in chunks[i].lower() or 'nice' in chunks[i].lower() else required).append(chunks[i+1])
    all_terms = {t for values in features(job_text).values() for t in values}
    all_terms |= set(hits(job_text, vocabulary()["supporting_embedded"]))
    title_terms = {t for values in features(job.title).values() for t in values}
    required_terms = {t for values in features("\n".join(required)).values() for t in values}
    preferred_terms = {t for values in features("\n".join(preferred)).values() for t in values}
    sets = {r.id: r.terms for r in resumes}
    weights = {}
    for term in all_terms:
        idf = 1 + math.log(6 / (1 + sum(term in v for v in sets.values())))
        weights[term] = idf * (3 if term in title_terms else 2 if term in required_terms else 0.6 if term in preferred_terms else 1)
    total = sum(weights.values())
    rankings = []
    for resume in resumes:
        matched = sorted(all_terms & sets[resume.id])
        score = round(100 * sum(weights[t] for t in matched) / total) if total else 0
        project_terms = {t for v in features(resume.sections.get("projects", "")).values() for t in v}
        project_hits = sorted(set(matched) & project_terms)
        rankings.append({"id": resume.id, "score": score, "matched_terms": matched,
                         "project_evidence": project_hits,
                         "missing_terms": sorted(all_terms - sets[resume.id])})
    rankings.sort(key=lambda r: (-r["score"], -len(r["project_evidence"]), r["id"]))
    best, alternative = rankings[:2]
    margin = best["score"] - alternative["score"]
    policy = config._load_yaml("application_policy.yaml")
    confident = (best["score"] >= policy.get("minimum_resume_fit", 55)
                 and margin >= policy.get("minimum_resume_margin", 5) and len(best["matched_terms"]) >= 3)
    selected = next(r for r in resumes if r.id == best["id"])
    return ResumeMatch(best["id"], best["score"], best["matched_terms"], alternative["id"],
                       f"Weighted technical coverage {best['score']}%; margin {margin} points; compared all five resumes. "
                       "Coverage is not proof of meeting every qualification.", confident, rankings,
                       best["missing_terms"], selected.sha256)


def annotate(job: Job, resumes: list[Resume]) -> ResumeMatch:
    result = match_job(job, resumes)
    job.selected_resume = result.selected_resume
    job.resume_fit_score = result.resume_fit_score
    job.resume_match = result.to_dict()
    return result
