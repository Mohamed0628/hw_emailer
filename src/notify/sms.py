"""SMS nudge via Twilio."""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def send_sms(body: str, secrets: dict[str, str]) -> bool:
    """Send an SMS. Returns True if sent, False if skipped (missing creds/lib)."""
    sid = secrets.get("TWILIO_ACCOUNT_SID")
    token = secrets.get("TWILIO_AUTH_TOKEN")
    from_ = secrets.get("TWILIO_FROM")
    to = secrets.get("SMS_TO")
    if not (sid and token and from_ and to):
        log.warning(
            "sms skipped: TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_FROM / SMS_TO not all set"
        )
        return False

    try:
        from twilio.rest import Client  # imported lazily so the lib is optional
    except ImportError:
        log.warning("sms skipped: twilio package not installed")
        return False

    try:
        client = Client(sid, token)
        client.messages.create(body=body, from_=from_, to=to)
        log.info("sms sent to %s", to)
        return True
    except Exception as exc:  # noqa: BLE001
        log.error("sms send failed: %s", exc)
        return False


def build_body(count: int, template: str) -> str:
    try:
        return template.format(n=count)
    except (KeyError, IndexError):
        return f"{count} new internships today. Check your email."
