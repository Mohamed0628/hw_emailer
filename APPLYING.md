# Auto-apply (local)

The daily bot finds and emails you internships. This tool **applies** to them —
it opens each job's application form in a real browser, fills your details,
generates a tailored cover letter with Gemini 2.5 Flash, and either auto-submits
simple forms or pauses for you to review forms with custom questions.

It runs **on your machine** (not GitHub Actions) so you can watch the browser,
solve any CAPTCHA, and review before anything is submitted.

## How it decides to submit (default mode)
`auto_simple_review_hard` (set in `config/settings.yaml` → `apply.mode`):

- **Simple form** (only standard fields: name, email, resume, links) → **auto-submitted**.
- **Hard form** (has custom/essay/required questions it couldn't fill) → **pauses**,
  shows you what's missing, and waits for you to complete it in the browser and
  press Enter to submit (or `s` to skip, `q` to quit).

Other modes: `review_all` (always pause), `auto_all` (submit everything — riskiest).

## What you need to provide
1. **Your resume** — drop the PDF in `resumes/` (e.g. `resumes/your_name.pdf`).
2. **Your profile** — `cp config/profile.example.yaml config/profile.yaml` and fill it in.
   Required: `full_name`, `email`, `resume_path`. Strongly recommended: `phone`,
   `school`, `graduation_date`, `linkedin`, `github`, `current_location`, and a
   concrete `summary` (this grounds the cover letter in your real experience).
   Both files are gitignored — your data never leaves your machine.
3. **(Optional) Gemini API key** for cover letters — `GEMINI_API_KEY` in `.env`
   (get one free at https://aistudio.google.com/apikey). Without it, applications
   still go through, just without a generated cover letter.

## Setup
```bash
source .venv/bin/activate
pip install -r requirements.txt -r requirements-apply.txt
python -m playwright install chromium     # one-time browser download
```

## Use it
```bash
# SAFEST FIRST RUN: fill forms but never submit — see exactly what it does
python -m src.apply --prepare-only --limit 3

# Real run (auto-simple / review-hard), visible browser, default daily limit
python -m src.apply

# Useful flags
python -m src.apply --company Stripe        # only this company
python -m src.apply --category quant         # only quant roles
python -m src.apply --limit 5                # cap this run
python -m src.apply --mode review_all        # pause on every form
python -m src.apply --no-cover-letter        # skip cover-letter generation
```

It only considers jobs whose ATS it can fill (**Greenhouse, Lever, Ashby**) and
that you haven't already applied to. Every attempt is logged to
`data/applications.json` (status: submitted / reviewed / skipped / failed /
prepared), so re-runs never double-apply.

## Scope & honest expectations
- **Coverage:** Greenhouse / Lever / Ashby today. Workday and custom career sites
  aren't auto-fillable yet — you'll still get those in the email digest to apply by hand.
- **Field filling is best-effort.** Forms vary; the tool fills what it confidently
  recognizes and flags the rest for your review. Verified working on live Greenhouse
  forms (fills name/email/phone/links/school + resume, detects custom questions).
  Expect to tune selectors as you hit new form variants — the review step is the safety net.
- **CAPTCHAs / logins:** solve them yourself in the visible browser, then continue.
- **Cover letters** are AI-drafted (Gemini 2.5 Flash) from your `summary` — **read
  them before submit**; the tool is instructed never to invent experience, but you
  own what goes out.

## Etiquette / ToS
This automates **your own** applications at modest volume. It uses each ATS's normal
public application form — no CAPTCHA-bypass, no bot-detection evasion. Many career
sites' terms restrict automated submission; review-before-submit (the default for
non-trivial forms) keeps a human in the loop. Apply thoughtfully — quality over volume.
