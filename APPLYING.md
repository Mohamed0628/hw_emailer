# Local hardware applications

The browser runner uses the same eligibility and career evaluation as discovery.
Install application dependencies, install Chromium, and configure all five resumes
before opening any forms. The default policy is `AUTO_SAFE`, capped at five
submission attempts per UTC day across repeated runs.

## Candidate and resumes

Copy `config/candidate.example.yaml` to `config/candidate.yaml`. Supply full name,
email, the known contact fields, exact available start date, and five resume entries:

```yaml
resumes:
  - id: rf
    path: resumes/rf.pdf
    reviewed: true
    sha256: "the SHA256 of the reviewed file"
```

Use five distinct files/IDs. PDF, UTF-8 `.txt` and `.md` are supported. Scanned PDFs
without extractable text require review/OCR first. Compute hashes using Python:

```bash
python -c "import hashlib,pathlib; print(hashlib.sha256(pathlib.Path('resumes/rf.pdf').read_bytes()).hexdigest())"
```

Do not set `reviewed: true` until the document has been read. A hash mismatch stops
execution. The matcher never assigns a domain solely from the filename. All five
rankings and the selected file hash are stored with each attempt. Gaps are suggested
areas for review, never instructions to invent skills.

`common_answers` from a legacy profile is still accepted, but **only exact complete
question labels match**. New answers belong in `confirmed_answers`:

```yaml
confirmed_answers:
  "A complete question exactly as it appears on the application": "Your verified answer"
```

Checkbox attestations require an explicit YAML boolean. Work authorization,
sponsorship, citizenship, clearance, criminal history, conflicts, relocation,
required salary and legal attestations remain unknown unless explicitly configured.
Top-level legacy `work_authorization` and `requires_sponsorship` values do not
silently answer differently worded consequential questions.

Optional demographic configuration uses keys `gender`, `race`, `veteran`,
`disability`. Currently supported values are documented in
`src/apply/answers.py`. Mapping requires a clearly voluntary section and a unique
matching option. It never infers Hispanic ethnicity or past disability history.
Optional unanswered demographics stay blank. Uncertain required options pause.

## Modes and commands

| Mode | Submission behavior |
| --- | --- |
| `PREPARE_ONLY` | Fills recognized fields, records preparation, never submits. |
| `REVIEW_ALL` | Requests interactive review; every safety gate still applies. |
| `AUTO_SAFE` | Submits only ordinary eligible jobs with complete, verified known forms. |
| `AUTO_ELIGIBLE` | Same mandatory gates as AUTO_SAFE. No unsafe “submit everything” mode. |

Old names `auto_simple_review_hard`, `review_all`, `auto_all` map to the protected
new modes. `auto_all` cannot bypass blockers.

```bash
# Pure evaluation: no browser, tracker writes, messages or applications.
python -m src.apply --dry-run --jobs-json tests/fixtures/hardware_jobs.json --limit 10
# Live discovery with local five-resume comparison, still no browser.
python -m src.apply --dry-run --limit 10
# Fill only. PREPARE_ONLY does not send an application, but it does enter/upload
# your candidate data to the employer's form.
python -m src.apply --prepare-only --company "Example" --limit 1
# Normal local operation; watch the headed browser.
python -m src.apply --limit 3
python -m src.apply --mode REVIEW_ALL --limit 1
# Explicit review of one valuable/uncertain job from a previous report:
python -m src.apply --review-job JOB_ID --limit 1
```

`--review-job` shows the selected resume and asks you to inspect the filled browser
and type the job ID. It can resolve a resume-ranking tie; it cannot bypass unknown
answers, CAPTCHAs, duplicate guards or failed inspection. Fill verified answers into
configuration and rerun when required. Valuable roles are otherwise held before
uploading candidate data. `--headless` only works with PREPARE_ONLY; browser
execution is rejected when `CI` is set. Tests are a separate, intercepted harness.

## ATS support

| ATS | Stage |
| --- | --- |
| Greenhouse, Lever, Ashby | Best-effort native-control filling, gated submission and explicit confirmation detection |
| Workday, iCIMS, SmartRecruiters | Recognized, linked and tracked for manual review; no automated fill/submit |
| Other/custom sites | Manual only |

Iframe-based forms, custom combobox widgets, unfamiliar upload purposes,
CAPTCHAs and authentication stop automatic progress. This conservative adapter
support does not claim every form on a supported platform works. Query parameters
are preserved; spoofed ATS hostname substrings cannot authorize uploads. A final
inventory checks for conditional questions, unexpected fields and changed values.
An ordinary “Apply now” navigation button is never treated as submission.

## Tracker, duplicates and recovery

`data/applications.json` is authoritative; `data/applications.csv` is a readable
mirror. Entries include requisition/company/title/location, URLs, ATS/source,
discovery/application dates, classification, score/evidence, selected resume,
all five rankings, unknown questions, review brief, outcome and attempt history.

The first update of a legacy log creates `data/applications.legacy.bak` before
writing. Existing IDs/fields are preserved. Writes are atomic; an OS file lock
prevents simultaneous application processes. Corruption stops execution.

Before a submit click, `submitting` is durably saved. Only a newly observed explicit
application confirmation becomes `submitted`. A timeout/ambiguous click becomes
`submission_unknown` and cannot be retried automatically. Crashes that leave
`submitting` have the same protection. Check the employer portal/confirmation email,
then reconcile the local record explicitly. Do not delete the tracker to retry.

Legacy `reviewed`, `submitted`, `skipped` and `closed` remain protected. Known
`failed` attempts can use `--retry-failed`; unconfirmed attempts cannot. Strong
identities use requisition IDs and canonical URLs. A same-company/title/location
record without distinct requisition IDs is held as a possible duplicate.

## Letters

Automatic Gemini drafting and unconditional cover-letter filling have been removed.
No LLM provider is required. To use a letter, review it against the selected resume
and configure a UTF-8 text file under `approved_cover_letters`, keyed by canonical
job URL. Only a field exactly labeled “Cover letter” receives that text. Unrecognized
essay questions and required file uploads pause. There is no lone-textarea fallback.
`--no-cover-letter` suppresses configured letters too.

## Common pauses

- **Missing candidate data:** fill only facts you know; leave everything else unknown.
- **Low-confidence resume:** compare the five rankings and use explicit one-job review.
- **Unknown field:** add its complete label and verified answer to `confirmed_answers`.
- **Custom widget or iframe:** finish manually; do not broaden labels to force a match.
- **No confirmation:** reconcile with the employer before permitting any further attempt.
- **Changed resume:** read the replacement, update its hash, and rerun the dry run.
- **Quota:** wait until the next UTC day or deliberately change the policy limit.

Browser fixture tests and mocked engine tests exercise these behaviors without
contacting production applications. Live ATS layouts still require PREPARE_ONLY
validation on your machine before you rely on automatic submission.
