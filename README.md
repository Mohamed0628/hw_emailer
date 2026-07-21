# hw_intern_emailer

A bot that **runs daily on GitHub Actions** and **emails you** **new US hardware engineering internship openings** (Summer & Spring / off-cycle).
It pulls from community internship aggregators and directly from company career
sites (via their ATS APIs), filters to what you care about, remembers what it has
already shown you, and only alerts on **new** postings.

```
sources (github lists + Greenhouse/Lever/Ashby/Workday)
   → normalize → filter (internship · season · category · US)
   → dedup vs data/seen_jobs.json
   → email digest (Gmail)
   → commit updated state back to the repo
```

> SMS (Twilio) is supported but **off by default** — this is an email-only setup.
> To turn it on later, see "Optional: SMS" below.

## What it tracks
- **Roles:** internships only — Summer & Spring / off-cycle / co-op (configurable).
- **Categories:** software engineering, software development, quant dev, quant
  trading, big tech, unicorns, startups, consulting (tech tracks).
- **Location:** United States (incl. US-remote).

All of this is tunable in `config/` — no code changes needed.

## Layout
```
config/        # all tunables (no code): companies, github lists, filters, settings
src/sources/   # one module per source type (github lists + 4 ATS APIs)
src/filters.py # internship / season / category / US-location rules
src/dedup.py   # seen-jobs state (data/seen_jobs.json)
src/notify/    # email.py (Gmail SMTP) + sms.py (Twilio)
src/apply/     # FUTURE auto-apply scaffold (not yet implemented)
src/main.py    # orchestrator + CLI
.github/workflows/daily.yml  # the daily cron
tests/         # pytest: filters + dedup
```

## Quick start (local)
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# See what it would send today — fetches live sources, no email/SMS, no state write:
python -m src.main --dry-run
```

Add credentials to send for real:
```bash
cp .env.example .env      # then fill in GMAIL_USER / GMAIL_APP_PASSWORD / EMAIL_TO
python -m src.main --test-notify   # sends one sample email to verify creds
python -m src.main                 # full run
```

**First-run tip:** with an empty `data/seen_jobs.json`, the first real run will
email the *entire current backlog* (~hundreds of postings) in one digest. If you'd
rather start clean and only get *new* postings from then on, seed the state once:
```bash
python -m src.main --seed   # marks everything currently open as "seen", sends nothing
```

Run the tests:
```bash
pytest
```

## Credentials
Set these as **GitHub repo Secrets** (Settings → Secrets and variables → Actions),
and/or in a local `.env` (see `.env.example`). With none set, the bot still runs in
`--dry-run` and prints results.

| Secret | What it is |
| --- | --- |
| `GMAIL_USER` | Gmail address to send from |
| `GMAIL_APP_PASSWORD` | 16-char [App Password](https://myaccount.google.com/apppasswords) (needs 2FA on) — **not** your login password |
| `EMAIL_TO` | where the digest goes (comma-separate for multiple) |

That's the whole setup — email is free and needs no other accounts.

## Deploy (private repo + daily cron)
1. Create a **private** GitHub repo and push this project.
2. Add the secrets above.
3. (Optional) Run `python -m src.main --seed` locally once and commit the updated
   `data/seen_jobs.json`, so your first scheduled email is a small delta rather than
   the whole backlog.
4. The workflow `.github/workflows/daily.yml` runs at **13:00 UTC daily** and also
   on-demand from the **Actions tab** (`workflow_dispatch`, with a dry-run toggle).
5. Each run commits the updated `data/seen_jobs.json` back to the repo, so the bot
   remembers what it already sent.

Notes:
- Private-repo Actions get 2,000 free minutes/month; a run is ~1–2 min → effectively free.
- GitHub disables scheduled workflows after **60 days of no repo activity** — the daily
  state commit normally counts, but you can also re-trigger manually to keep it alive.
- Adjust the time by editing the `cron:` line (it's in UTC).

## Populating companies.yaml from the 1,182-company target list

`data/companies_master.csv` holds the full deduplicated target list (sector +
A/B/C priority). The discovery tool probes each company's likely board tokens
against the Greenhouse / Lever / Ashby public APIs and keeps only confirmed
live boards:

```
python -m src.discover --priority A       # start with Priority A (~620 companies)
python -m src.discover                    # rest of the list; Ctrl-C safe, resumes
python -m src.discover --write-config     # merge verified hits into config/companies.yaml
```

Progress checkpoints to `data/discovery_state.json` after every company, and
verified hits land in `data/discovered_companies.yaml` for review. Workday
tenants can't be auto-guessed — for big companies that miss, check whether
their careers URL looks like `<tenant>.wd<N>.myworkdayjobs.com/<site>` and add
it to the `workday:` section by hand. Companies with fully custom career sites
(many large industrials) reach you via the community lists instead. Expect a
large fraction of the list to miss — small manufacturers and non-US industrials
often have no public ATS API at all; that's the list telling you which
companies need a manual careers-page check, not a bug.

## Tuning
- **`config/companies.yaml`** — add companies by ATS + token. Quant firms and
  consulting are seeded here because the community lists skew SWE. Some seed tokens
  are best-effort — run `--dry-run` and disable any that 404 (`enabled: false`).
- **`config/github_lists.yaml`** — the community `listings.json` URLs. These repos
  roll names each cycle (`Summer2026` → `Summer2027`); update the URL when the new
  cycle's repo appears.
- **`config/filters.yaml`** — keywords, allowed seasons/years, and US location terms.
- **`config/settings.yaml`** — digest format, state pruning, suppression.

## Optional: SMS
This is an email-only setup, but an SMS-nudge channel (`src/notify/sms.py`, via
Twilio) ships dormant. To enable it later:
1. In `config/settings.yaml`, set `sms.enabled: true`.
2. Uncomment `twilio>=8` in `requirements.txt` and reinstall.
3. Add `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM`, `SMS_TO` (E.164)
   as secrets / `.env` values, and uncomment them in `.github/workflows/daily.yml`.

It sends a short "N new internships today" text alongside the email digest. Twilio
costs a few cents per message.

## Auto-apply (local) — implemented
`src/apply/` is a working local tool that applies to the jobs the bot finds:
opens each Greenhouse / Lever / Ashby application form in a real browser, fills
your details, generates a tailored cover letter via Gemini 2.5 Flash, and
**auto-submits simple forms while pausing for your review on forms with custom
questions**.

```bash
pip install -r requirements.txt -r requirements-apply.txt
python -m playwright install chromium
python -m src.apply --prepare-only      # safe first run: fills but never submits
python -m src.apply                     # real run (visible browser)
```

Runs on your machine (not CI) so you can watch, solve CAPTCHAs, and review before
submit. It needs your resume in `resumes/`, a filled `config/profile.yaml` (copy
`config/profile.example.yaml`), and optionally `GEMINI_API_KEY` for cover letters.
Every attempt is logged to `data/applications.json` so re-runs never double-apply.

**See [APPLYING.md](APPLYING.md) for the full guide, modes, and what to provide.**

## Legal / etiquette
Uses official public JSON APIs (Greenhouse, Lever, Ashby, Workday) and open,
community-maintained data — no scraping of LinkedIn/Indeed or other anti-bot sites.
Requests are rate-limited and retried politely. Respect each site's Terms of Service.
