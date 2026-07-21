"""FUTURE: auto-apply module (scaffolded, not yet implemented).

The contract here lets a later project add real form-filling without changing
the collection/notification pipeline. Nothing in this package is invoked by the
daily run today.

Design intent for the eventual implementation:
  * Human-in-the-loop by default — prepare a filled application, let the user
    review, then submit. This keeps it within site ToS and avoids account bans.
  * Browser automation (Playwright) per ATS, since Greenhouse/Lever/Ashby render
    application forms client-side.
  * Screening-question answers come from the stored ApplicantProfile.
"""
