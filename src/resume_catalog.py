"""Private, matching-only evidence for discovery runtimes without resume PDFs.

Export only after the normal five-file hash/review checks. Never use this catalog
for uploads or application answers. No contact details or resume prose are exported.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from .resumes import Resume, load_resumes
from .signals import vocabulary

SECRET_NAME = "RESUME_MATCHING_CATALOG_JSON"


def vocabulary_hash() -> str:
    encoded = json.dumps(vocabulary(), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def export_catalog(resumes: list[Resume]) -> str:
    payload = {
        "version": 1,
        "vocabulary_sha256": vocabulary_hash(),
        "resumes": [{"id": r.id, "sha256": r.sha256, "terms": sorted(r.terms),
                     "project_terms": sorted(r.project_terms)} for r in resumes],
    }
    encoded = json.dumps(payload, indent=2) + "\n"
    load_catalog(encoded)  # Validate before creating a reusable secret.
    return encoded


def load_catalog(encoded: str) -> list[Resume]:
    try:
        data = json.loads(encoded)
        if (data["version"] != 1 or data["vocabulary_sha256"] != vocabulary_hash()
                or len(data["resumes"]) != 5):
            raise ValueError()
        allowed = {t for terms in vocabulary()["domains"].values() for t in terms}
        allowed.update(vocabulary()["supporting_embedded"])
        resumes = []
        for row in data["resumes"]:
            if (not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", row["id"])
                    or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"])):
                raise ValueError()
            if not isinstance(row["terms"], list) or not isinstance(row["project_terms"], list):
                raise ValueError()
            terms, projects = frozenset(row["terms"]), frozenset(row["project_terms"])
            if not terms or not terms <= allowed or not projects <= terms:
                raise ValueError()
            resumes.append(Resume(row["id"], "", row["sha256"], "", {}, terms, projects))
        if len({r.id for r in resumes}) != 5 or len({r.sha256 for r in resumes}) != 5:
            raise ValueError()
        return resumes
    except (KeyError, TypeError, ValueError):
        # Do not echo private secret content into workflow logs.
        raise ValueError("Invalid or outdated private resume matching catalog; regenerate it from the five reviewed files") from None


def main(argv=None) -> int:
    from .apply.profile import load_profile
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--output", type=Path, default=Path("data/candidate_matching_catalog.json"))
    args = parser.parse_args(argv)
    catalog = export_catalog(load_resumes(load_profile(args.profile)))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(catalog, encoding="utf-8")
    args.output.chmod(0o600)
    print(f"Private matching catalog written to {args.output}; set GitHub Actions secret {SECRET_NAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
