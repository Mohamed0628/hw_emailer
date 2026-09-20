"""Agentic browser application runner for AUTO_ELIGIBLE.

hw_emailer remains responsible for discovery, filtering, resume selection, policy,
deduplication, and audit logging. This module only drives the already-selected
application in a real browser using browser-use.
"""
from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, Field

from ..identity import detect_ats
from ..models import ApplicantProfile, Job
from .policy import settings


class AgentPrerequisiteError(RuntimeError):
    """Agentic apply cannot start because a local dependency/config is missing."""


class AgentSubmissionUnknown(RuntimeError):
    """The agent started browser actions but did not leave a trustworthy outcome."""


class MissingQuestion(BaseModel):
    question: str
    options: list[str] = Field(default_factory=list)


class BrowserApplyResult(BaseModel):
    submitted: bool = False
    confirmation: str = ""
    missing_questions: list[MissingQuestion] = Field(default_factory=list)
    captcha_or_login: bool = False
    notes: str = ""


@dataclass
class AgentOutcome:
    status: str
    reason: str
    learned_answers: dict[str, str | bool] = field(default_factory=dict)


def enabled() -> bool:
    cfg = settings().get("agentic_browser") or {}
    return bool(cfg.get("enabled", True))


def _agent_settings() -> dict:
    return settings().get("agentic_browser") or {}


def _api_key() -> str:
    key = os.getenv("BROWSER_AGENT_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not key:
        raise AgentPrerequisiteError(
            "Agentic browser needs OPENAI_API_KEY (or BROWSER_AGENT_API_KEY) in this shell."
        )
    return key


def _imports():
    try:
        from browser_use import Agent, BrowserProfile, BrowserSession, ChatOpenAI
    except ImportError as exc:
        raise AgentPrerequisiteError(
            "browser-use is not installed; run: python -m pip install -r requirements-apply.txt"
        ) from exc
    return Agent, BrowserProfile, BrowserSession, ChatOpenAI


def _allowed_domains(job: Job) -> list[str]:
    url = job.application_url or job.url
    host = (urlsplit(url).hostname or "").lower()
    ats = detect_ats(url)
    if ats == "lever":
        return ["https://jobs.lever.co", "https://*.lever.co"]
    if ats == "greenhouse":
        return [
            "https://job-boards.greenhouse.io",
            "https://boards.greenhouse.io",
            "https://*.greenhouse.io",
        ]
    if ats == "ashby":
        return ["https://jobs.ashbyhq.com", "https://*.ashbyhq.com"]
    return [f"https://{host}"] if host else []


def _non_demographic_answers(values: dict[str, str | bool]) -> dict[str, str | bool]:
    """Do not send voluntary demographic answers to the browser LLM."""
    blocked = ("race", "ethnicity", "gender", "sex", "veteran", "disability")
    return {
        key: value
        for key, value in values.items()
        if not any(word in key.casefold() for word in blocked)
    }


def _profile_payload(profile: ApplicantProfile) -> dict:
    return {
        "full_name": profile.full_name,
        "email": profile.email,
        "phone": profile.phone,
        "school": profile.school,
        "graduation_date": profile.graduation_date,
        "gpa": profile.gpa,
        "current_location": profile.current_location,
        "work_authorization": profile.work_authorization,
        "requires_sponsorship": profile.requires_sponsorship,
        "linkedin": profile.linkedin,
        "github": profile.github,
        "website": profile.website,
        "summary": profile.summary,
        "available_start_date": profile.available_start_date,
        "common_answers": _non_demographic_answers(profile.common_answers),
        "confirmed_answers": _non_demographic_answers(profile.confirmed_answers),
    }


def _task(job: Job, profile: ApplicantProfile, resume_path: str, *, continuation: bool = False) -> str:
    verb = "Continue" if continuation else "Apply"
    return f"""
{verb} the single job application below on behalf of the candidate.

JOB
Company: {job.company}
Title: {job.title}
Exact application URL: {job.application_url or job.url}
Job ID: {job.job_id}

RESUME
Upload exactly this file and no other resume:
{resume_path}

VERIFIED CANDIDATE DATA
{json.dumps(_profile_payload(profile), ensure_ascii=False, indent=2)}

RULES
1. Work only on this exact requisition. Do not search for or apply to any other job.
2. Complete the application and SUBMIT it when every required answer is supported by
   the verified candidate data above.
3. Never invent employment history, education, dates, skills, citizenship, work
   authorization, sponsorship, salary expectations, legal attestations, addresses,
   demographic answers, or any other candidate fact.
4. Exact confirmed_answers override generic/common answers.
5. Leave voluntary demographic/self-identification/EEOC questions blank. If a
   demographic field is required, report it in missing_questions instead of guessing.
6. Optional marketing/source/referral questions may be left blank when the verified
   data does not contain an answer.
7. If a required or consequential question cannot be answered from the verified data,
   DO NOT GUESS and DO NOT SUBMIT. Return its exact visible question text and visible
   options in missing_questions.
8. If a CAPTCHA, login wall, or 2FA challenge is actually visible, stop and set
   captcha_or_login=true. Do not attempt to bypass it.
9. Set submitted=true only after clicking the final submit control AND observing a new,
   explicit confirmation that this application was received/submitted.
10. If submission did not happen, submitted must be false and notes should say why.
""".strip()


def _extract(history) -> BrowserApplyResult:
    try:
        out = getattr(history, "structured_output", None)
    except Exception:
        out = None
    if isinstance(out, BrowserApplyResult):
        return out
    if isinstance(out, dict):
        try:
            return BrowserApplyResult(**out)
        except Exception:
            pass
    try:
        model_output = history.model_output()
    except Exception:
        model_output = None
    if isinstance(model_output, BrowserApplyResult):
        return model_output
    final = ""
    try:
        final = str(history.final_result() or "")
    except Exception:
        final = ""
    return BrowserApplyResult(
        submitted=False,
        notes=("Agent returned no valid structured result. " + final[:500]).strip(),
    )


def _ask_missing(questions: list[MissingQuestion]) -> dict[str, str | bool]:
    learned: dict[str, str | bool] = {}
    seen: set[str] = set()
    for item in questions:
        question = " ".join((item.question or "").split())
        if not question or question.casefold() in seen:
            continue
        seen.add(question.casefold())
        options = [" ".join(str(o).split()) for o in item.options if str(o).strip()]

        print("\nApplication needs one factual answer:")
        print("  " + question)
        if options:
            for i, option in enumerate(options, 1):
                print(f"    {i}. {option}")
            raw = input(
                "Choose a number or type the exact option (blank = stop this application): "
            ).strip()
            if not raw:
                continue
            try:
                idx = int(raw) - 1
            except ValueError:
                idx = -1
            if 0 <= idx < len(options):
                learned[question] = options[idx]
                continue
            exact = [o for o in options if o.casefold() == raw.casefold()]
            if len(exact) == 1:
                learned[question] = exact[0]
            else:
                print("  Answer not recognized; leaving this application paused.")
            continue

        raw = input("Enter the exact truthful answer (blank = stop this application): ").strip()
        if raw:
            learned[question] = raw
    return learned


async def _close_session(session) -> None:
    for name in ("close", "kill"):
        fn = getattr(session, name, None)
        if callable(fn):
            try:
                result = fn()
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                pass
            return


async def _run(job: Job, profile: ApplicantProfile, resume_path: str) -> AgentOutcome:
    Agent, BrowserProfile, BrowserSession, ChatOpenAI = _imports()
    key = _api_key()
    cfg = _agent_settings()
    model = os.getenv("BROWSER_AGENT_MODEL") or str(cfg.get("model") or "gpt-4o")
    max_steps = int(cfg.get("max_steps", 45))
    max_interventions = int(cfg.get("max_interventions", 3))

    llm_kwargs = {"model": model, "api_key": key}
    base_url = os.getenv("BROWSER_AGENT_BASE_URL")
    if base_url:
        llm_kwargs["base_url"] = base_url
    llm = ChatOpenAI(**llm_kwargs)

    browser_kwargs = {
        "headless": False,
        "keep_alive": True,
        "allowed_domains": _allowed_domains(job),
    }
    user_data_dir = os.getenv("BROWSER_AGENT_USER_DATA_DIR")
    if user_data_dir:
        browser_kwargs["user_data_dir"] = user_data_dir
    browser_profile = BrowserProfile(**browser_kwargs)
    session = BrowserSession(browser_profile=browser_profile)

    learned: dict[str, str | bool] = {}
    current = profile
    continuation = False
    started = False
    try:
        for _ in range(max_interventions + 1):
            agent = Agent(
                task=_task(job, current, resume_path, continuation=continuation),
                llm=llm,
                browser_session=session,
                output_model_schema=BrowserApplyResult,
                max_failures=3,
                extend_system_message=(
                    "You are an application execution agent. Accuracy is more important than "
                    "completion. Never fabricate candidate data. Submit only this exact job."
                ),
            )
            started = True
            history = await agent.run(max_steps=max_steps)
            result = _extract(history)

            if result.submitted:
                confirmation = result.confirmation.strip() or result.notes.strip()
                return AgentOutcome(
                    "submitted",
                    confirmation or "agent observed explicit application submission confirmation",
                    learned,
                )

            if result.captcha_or_login:
                answer = await asyncio.to_thread(
                    input,
                    f"\n{job.company}: solve the visible CAPTCHA/login/2FA in the browser, "
                    "then press Enter to continue (type skip to stop): ",
                )
                if answer.strip().casefold() == "skip":
                    return AgentOutcome(
                        "needs_input",
                        "human challenge not completed",
                        learned,
                    )
                continuation = True
                continue

            if result.missing_questions:
                updates = await asyncio.to_thread(_ask_missing, result.missing_questions)
                if not updates:
                    return AgentOutcome(
                        "needs_input",
                        result.notes.strip() or "required factual answers are still missing",
                        learned,
                    )
                learned.update(updates)
                current = current.model_copy(update={
                    "confirmed_answers": {**current.confirmed_answers, **learned}
                })
                continuation = True
                continue

            return AgentOutcome(
                "needs_input",
                result.notes.strip() or "agent stopped without confirmed submission",
                learned,
            )

        return AgentOutcome(
            "needs_input",
            "agent exceeded the configured human-intervention limit",
            learned,
        )
    except AgentPrerequisiteError:
        raise
    except Exception as exc:
        if started:
            raise AgentSubmissionUnknown(
                f"agent/browser interrupted after live actions began: {type(exc).__name__}: {exc}"
            ) from exc
        raise AgentPrerequisiteError(
            f"agent/browser could not start: {type(exc).__name__}: {exc}"
        ) from exc
    finally:
        await _close_session(session)


def require_ready(resume_path: str | Path) -> None:
    """Validate local agent prerequisites without opening a browser."""
    path = Path(resume_path)
    if not path.exists():
        raise AgentPrerequisiteError(f"selected resume file not found: {path}")
    _api_key()
    _imports()


def apply(job: Job, profile: ApplicantProfile, resume_path: str | Path) -> AgentOutcome:
    path = Path(resume_path)
    require_ready(path)
    return asyncio.run(_run(job, profile, str(path.resolve())))
