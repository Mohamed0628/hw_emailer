"""Per-job cover letter generation via Google Gemini 2.5 Flash.

Degrades gracefully: if the `google-genai` package isn't installed or no API key
(GEMINI_API_KEY / GOOGLE_API_KEY) is set, returns None and the apply flow
proceeds without a cover letter.
"""

from __future__ import annotations

import logging
import os
import re
import time

from ..models import ApplicantProfile, Job

log = logging.getLogger(__name__)

MODEL = "gemini-2.5-flash"

SYSTEM = (
    "You write concise, specific cover letters for hardware / electrical / embedded internship "
    "applications. Rules: 200-280 words; 3 short paragraphs; professional but "
    "human (no buzzword salad); ground every claim in the candidate's provided "
    "background — never invent experience, employers, or metrics; tie the "
    "candidate's actual skills to this specific role and company; no greeting "
    "placeholders like [Hiring Manager] and no sign-off block (the form handles "
    "the name). Output only the letter body text."
)


def _prompt(job: Job, profile: ApplicantProfile) -> str:
    bg = profile.summary or "(no summary provided)"
    return (
        f"Company: {job.company}\n"
        f"Role: {job.title}\n"
        f"Location: {job.location_str or 'N/A'}\n\n"
        f"Candidate: {profile.full_name}\n"
        f"School: {profile.school or 'N/A'}\n"
        f"Graduation: {profile.graduation_date or 'N/A'}\n"
        f"Background and skills: {bg}\n\n"
        "Write the cover letter body now."
    )


def generate_cover_letter(job: Job, profile: ApplicantProfile) -> str | None:
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        log.info("cover letter skipped: GEMINI_API_KEY not set")
        return None
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        log.info("cover letter skipped: google-genai package not installed")
        return None

    cfg = types.GenerateContentConfig(
        system_instruction=SYSTEM,
        max_output_tokens=1024,
        temperature=0.7,
        # Cover letters don't need reasoning; disabling thinking keeps it
        # fast/cheap and avoids the token budget being eaten by thinking.
        thinking_config=types.ThinkingConfig(thinking_budget=0),
    )
    client = genai.Client(api_key=key)
    last_exc = None
    for attempt in range(3):  # retry transient 503/overload
        try:
            resp = client.models.generate_content(
                model=MODEL, contents=_prompt(job, profile), config=cfg
            )
            text = (resp.text or "").strip()
            return text or None
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            msg = str(exc).lower()
            transient = any(
                s in msg for s in ("503", "unavailable", "overloaded", "429", "resource_exhausted", "rate")
            )
            if transient and attempt < 2:
                # Honor the server's suggested retry delay (free tier = 5 req/min),
                # capped so we don't stall the run too long.
                m = re.search(r"retry in ([\d.]+)s", msg) or re.search(
                    r"retrydelay['\"]?:?\s*['\"]?([\d.]+)s", msg
                )
                wait = min((float(m.group(1)) if m else 2 * (attempt + 1)) + 1, 55)
                log.info("cover letter rate-limited; waiting %.0fs then retrying", wait)
                time.sleep(wait)
                continue
            break
    log.warning("cover letter generation failed for %s: %s", job.company, last_exc)
    return None
