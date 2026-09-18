"""Only load an explicitly reviewed, job-specific letter. No automatic LLM claims."""
from pathlib import Path
from .. import config
from ..identity import canonical_url


def generate_cover_letter(job, profile):
    path = profile.approved_cover_letters.get(canonical_url(job.url))
    if not path:
        return None
    return (config.ROOT / Path(path)).read_text(encoding='utf-8')
