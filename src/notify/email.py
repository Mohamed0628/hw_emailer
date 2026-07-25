"""Email digest via Gmail SMTP."""

from __future__ import annotations

import logging
import re
import smtplib
import ssl
from email.message import EmailMessage
from html import escape

from ..models import Job

log = logging.getLogger(__name__)

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465

_CATEGORY_LABELS = {
    "silicon": "Silicon / Chip Design",
    "hardware": "Hardware / Electrical",
    "medtech_hardware": "Medtech Engineering",
    "firmware": "Firmware / Embedded",
    "other": "Other",
}


def is_faang(company: str, terms: list[str]) -> bool:
    """Token-based match so apple hits Apple Inc but not Snapple."""
    tokens = set(re.findall(r"[a-z0-9]+", (company or "").lower()))
    return any(term in tokens for term in terms)


def faang_jobs(jobs: list[Job], terms: list[str]) -> list[Job]:
    terms = [term.lower() for term in (terms or [])]
    if not terms:
        return []
    return [job for job in jobs if is_faang(job.company, terms)]


def group_by_category(
    jobs: list[Job],
    order: list[str],
) -> list[tuple[str, list[Job]]]:
    buckets: dict[str, list[Job]] = {}
    for job in jobs:
        buckets.setdefault(job.category or "other", []).append(job)
    ordered_keys = [category for category in order if category in buckets]
    ordered_keys += [category for category in buckets if category not in order]
    return [(category, buckets[category]) for category in ordered_keys]


def _counts_summary(grouped: list[tuple[str, list[Job]]]) -> str:
    parts = []
    for category, jobs in grouped:
        label = _CATEGORY_LABELS.get(category, category)
        parts.append(f"{len(jobs)} {label}")
    return ", ".join(parts)


def build_subject(
    jobs: list[Job],
    grouped,
    prefix: str,
    faang: list[Job] | None = None,
) -> str:
    priority_a = [job for job in jobs if job.priority == "A"]
    if priority_a:
        names = ", ".join(sorted({job.company for job in priority_a}))
        return f"Priority A job alert - {names} ({len(jobs)} new opportunities)"
    if faang:
        names = ", ".join(sorted({job.company for job in faang}))
        return f"FAANG job out now - {names} ({len(jobs)} new opportunities)"
    return f"{prefix} {len(jobs)} new opportunities - {_counts_summary(grouped)}"


def _priority_banner(jobs: list[Job]) -> str:
    priority_jobs = [job for job in jobs if job.priority == "A"]
    if not priority_jobs:
        return ""

    items = []
    for job in sorted(
        priority_jobs,
        key=lambda item: (item.company.lower(), item.title.lower()),
    ):
        location = escape(job.location_str) if job.location_str else ""
        signal = escape(job.hiring_signal or "High-priority match")
        items.append(
            "<li style='margin:5px 0'>"
            f"<a href='{escape(job.url)}' style='color:#991b1b;font-weight:700;"
            f"text-decoration:none'>{escape(job.title)}</a>"
            f"<span style='color:#7f1d1d'> - {escape(job.company)}</span>"
            + (
                f"<span style='color:#777;font-size:12px'> | {location}</span>"
                if location
                else ""
            )
            + f"<br><span style='color:#7f1d1d;font-size:12px'>{signal}</span>"
            + "</li>"
        )
    return (
        "<div style='background:#fff7ed;border:2px solid #c2410c;border-radius:8px;"
        "padding:14px 16px;margin:14px 0'>"
        "<div style='font:700 17px system-ui,sans-serif;color:#9a3412;margin-bottom:6px'>"
        "Priority A roles - review immediately</div>"
        f"<ul style='margin:0;padding-left:20px;font:14px system-ui,sans-serif'>"
        f"{''.join(items)}</ul></div>"
    )


def _faang_banner(faang: list[Job] | None) -> str:
    if not faang:
        return ""

    items = []
    for job in sorted(
        faang,
        key=lambda item: (item.company.lower(), item.title.lower()),
    ):
        location = escape(job.location_str) if job.location_str else ""
        items.append(
            "<li style='margin:4px 0'>"
            f"<a href='{escape(job.url)}' style='color:#b91c1c;font-weight:700;"
            f"text-decoration:none'>{escape(job.title)}</a>"
            f"<span style='color:#7f1d1d'> - {escape(job.company)}</span>"
            + (
                f"<span style='color:#777;font-size:12px'> | {location}</span>"
                if location
                else ""
            )
            + "</li>"
        )
    return (
        "<div style='background:#fff1f0;border:2px solid #e11d48;border-radius:8px;"
        "padding:14px 16px;margin:14px 0'>"
        "<div style='font:700 17px system-ui,sans-serif;color:#b91c1c;margin-bottom:6px'>"
        "FAANG roles just posted</div>"
        f"<ul style='margin:0;padding-left:20px;font:14px system-ui,sans-serif'>"
        f"{''.join(items)}</ul></div>"
    )


def build_html(
    grouped: list[tuple[str, list[Job]]],
    total: int,
    faang: list[Job] | None = None,
) -> str:
    all_jobs = [job for _, jobs in grouped for job in jobs]
    rows = [_priority_banner(all_jobs), _faang_banner(faang)]
    rows.append(
        "<p style='font:14px system-ui,sans-serif;color:#444'>"
        f"<b>{total}</b> new internship or early-career posting(s) "
        "matched your filters.</p>"
    )

    for category, jobs in grouped:
        label = _CATEGORY_LABELS.get(category, category)
        rows.append(
            f"<h2 style='font:600 18px system-ui,sans-serif;color:#111;"
            f"margin:24px 0 8px;border-bottom:2px solid #eee;padding-bottom:4px'>"
            f"{escape(label)} ({len(jobs)})</h2>"
        )
        for job in sorted(
            jobs,
            key=lambda item: (
                0 if item.priority == "A" else 1 if item.priority == "B" else 2,
                item.company.lower(),
                item.title.lower(),
            ),
        ):
            location = escape(job.location_str) if job.location_str else "-"
            role = escape((job.role_type or "opportunity").replace("_", " "))
            priority = f"Priority {job.priority} | " if job.priority else ""
            meta_bits = [
                priority + location,
                role,
                job.season,
                str(job.year) if job.year else None,
            ]
            meta = escape(" | ".join(bit for bit in meta_bits if bit))
            evidence = ""
            if job.entry_level_evidence:
                evidence = (
                    "<br><span style='color:#777;font-size:11px'>"
                    + escape("; ".join(job.entry_level_evidence[:3]))
                    + "</span>"
                )
            rows.append(
                "<div style='font:14px system-ui,sans-serif;margin:6px 0;"
                "padding:8px 10px;background:#fafafa;border-radius:6px'>"
                f"<a href='{escape(job.url)}' style='color:#1a56db;font-weight:600;"
                f"text-decoration:none'>{escape(job.title)}</a>"
                f"<span style='color:#666'> - {escape(job.company)}</span><br>"
                f"<span style='color:#888;font-size:12px'>{meta}</span>"
                f"{evidence}</div>"
            )

    headline = "FAANG job out now" if faang else "Hardware and Early-Career Job Digest"
    return (
        "<div style='max-width:680px;margin:0 auto'>"
        "<h1 style='font:700 22px system-ui,sans-serif;color:#111'>"
        f"{escape(headline)}</h1>"
        + "".join(rows)
        + "<p style='font:12px system-ui,sans-serif;color:#aaa;margin-top:32px'>"
        "Generated by hw_emailer. Tune sources and filters in <code>config/</code>."
        "</p></div>"
    )


def build_text(
    grouped: list[tuple[str, list[Job]]],
    total: int,
    faang: list[Job] | None = None,
) -> str:
    lines: list[str] = []
    if faang:
        lines.append("FAANG job out now")
        for job in sorted(
            faang,
            key=lambda item: (item.company.lower(), item.title.lower()),
        ):
            lines.append(f"  {job.title} - {job.company}: {job.url}")
        lines.append("")

    lines.extend([f"{total} new internship or early-career posting(s):", ""])
    for category, jobs in grouped:
        lines.append(
            f"== {_CATEGORY_LABELS.get(category, category)} ({len(jobs)}) =="
        )
        for job in sorted(
            jobs,
            key=lambda item: (
                0 if item.priority == "A" else 1 if item.priority == "B" else 2,
                item.company.lower(),
                item.title.lower(),
            ),
        ):
            location = job.location_str or "-"
            role = (job.role_type or "opportunity").replace("_", " ")
            priority = f"Priority {job.priority} | " if job.priority else ""
            lines.append(
                f"- {priority}{job.title} - {job.company} "
                f"[{location}] [{role}]"
            )
            if job.hiring_signal:
                lines.append(f"  {job.hiring_signal}")
            if job.entry_level_evidence:
                evidence = "; ".join(job.entry_level_evidence[:3])
                lines.append(f"  Evidence: {evidence}")
            lines.append(f"  {job.url}")
        lines.append("")
    return "\n".join(lines)


def send_email(
    jobs: list[Job],
    secrets: dict[str, str],
    email_cfg: dict,
    *,
    subject_override: str | None = None,
    html_override: str | None = None,
    text_override: str | None = None,
) -> bool:
    """Send the digest. Return False if credentials are missing or send fails."""
    user = secrets.get("GMAIL_USER")
    password = secrets.get("GMAIL_APP_PASSWORD")
    to = secrets.get("EMAIL_TO") or user
    if not (user and password and to):
        log.warning("email skipped: Gmail credentials or recipient are missing")
        return False

    order = email_cfg.get(
        "category_order",
        ["silicon", "hardware", "medtech_hardware", "firmware", "other"],
    )
    grouped = group_by_category(jobs, order)
    faang = faang_jobs(jobs, email_cfg.get("faang_companies", []))
    subject = subject_override or build_subject(
        jobs,
        grouped,
        email_cfg.get("subject_prefix", "[Hardware Job Alert]"),
        faang,
    )
    html = html_override or build_html(grouped, len(jobs), faang)
    text = text_override or build_text(grouped, len(jobs), faang)

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = user
    recipients = [address.strip() for address in to.split(",") if address.strip()]
    message["To"] = ", ".join(recipients)
    message.set_content(text)
    message.add_alternative(html, subtype="html")

    context = ssl.create_default_context()
    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context) as server:
            server.login(user, password)
            server.send_message(message, from_addr=user, to_addrs=recipients)
        log.info("email sent to %s (%d jobs)", recipients, len(jobs))
        return True
    except Exception as exc:  # noqa: BLE001
        log.error("email send failed: %s", exc)
        return False
