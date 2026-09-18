# hw_emailer

Hardware-focused job discovery, explainable screening, five-resume comparison,
and a local application assistant. RF, power electronics, PCB, analog/mixed-signal,
physical controls, semiconductor, medtech and avionics hardware are the targets.
Firmware/software-focused jobs are rejected; supporting embedded work in a genuine
hardware role is acceptable.

## Start here

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m src.main --dry-run
```

Discovery uses existing Greenhouse, Lever, Ashby, Workday, iCIMS, company-page and
community sources. The hourly GitHub Actions digest remains in
`.github/workflows/daily.yml`. Application execution is local only.

```bash
pip install -r requirements-apply.txt
python -m playwright install chromium
cp config/candidate.example.yaml config/candidate.yaml
# Add five reviewed resumes and their SHA256 hashes; fill known candidate fields.
python -m src.apply --dry-run --jobs-json tests/fixtures/hardware_jobs.json --limit 10
python -m src.apply --prepare-only --limit 3
```

See [APPLYING.md](APPLYING.md) before enabling applications.

## Decisions

Both commands use `src/evaluation.py` and the same hardware career gate.

| Class | Behavior |
| --- | --- |
| `AUTO_APPLY` | Eligible ordinary hardware fit. Submission still requires every form, resume and candidate gate. |
| `HIGH_VALUE_REVIEW` | Valuable technical fit. Held for customization and explicit interactive review. |
| `HARD_NO` | Wrong career, seniority, experience, location/cohort, inactive posting or insufficient hardware evidence. |

Career scoring separates hardware evidence, hands-on work, entry level, company
fit and Minnesota location. Programming words alone earn no positive points.
Every result carries its evidence. The taxonomy still recognizes firmware so it
can explain exclusions; recognizing a category does not make it eligible.

Resume matching compares all five reviewed documents using technical evidence
from their full text, including coursework, projects, skills and experience.
Job-title and required-skill evidence weigh more than preferred skills. It reports
all five rankings, selected and alternative resumes, gaps and confidence.
A score measures vocabulary coverage, not a guarantee of meeting qualifications.
No years of experience, citizenship, GPA or accomplishments are inferred.

## Configuration

| File | Purpose |
| --- | --- |
| `config/job_preferences.yaml` | Hardware domains, supporting embedded signals, software dominance, target companies |
| `config/career_fit.yaml` | Explainable weights, minimum discovery score and high-value threshold |
| `config/application_policy.yaml` | Modes, run/daily limits, resume confidence, supported automatic ATSs |
| `config/candidate.yaml` | Private candidate facts, all five resume files/hashes, exact confirmed answers |
| `config/filters.yaml`, `category_taxonomy.yaml` | Existing cohort, location and detailed category rules |
| `config/companies*.yaml`, `direct_companies*.yaml` | Company source catalogs |
| `config/github_lists.yaml` | Community feeds, including companies outside existing catalogs |
| `config/sources.yaml` | Default Workday searches and bounded detail retrieval |
| `config/settings.yaml` | HTTP, notification and discovery-state settings |

`config/profile.yaml` remains a legacy loading fallback. Private profiles, resumes,
application logs, backups and review reports are gitignored. Examples contain no
candidate facts. File hashes must be refreshed only after reviewing changed resumes.

## Email and state

Copy `.env.example` to `.env` and set `GMAIL_USER`, `GMAIL_APP_PASSWORD` and
`EMAIL_TO`. Put the same values in repository Secrets for scheduled discovery.
The application profile and resumes do not belong in Actions secrets or artifacts.

```bash
python -m src.main --test-notify  # Explicitly sends a sample notification
python -m src.main --seed        # Mark current matches seen without sending
python -m src.main              # Discover, email and update seen state
```

Seen-job IDs remain compatible with existing history. Canonical URLs and
requisition IDs additionally detect source/tracking-link variants. Direct listings
with descriptions take precedence over community duplicates. Failed email delivery
does not advance seen state. Corrupt state stops processing instead of silently
starting fresh.

High-value digest entries include the technical reasons, keywords, recommended
customization and an outreach research task. The local email runner loads the same
five reviewed resumes from `config/candidate.yaml` as the application runner, so
its digest includes the selected resume and evidence for every eligible role.
CI has no private resume catalog, so its email explicitly reports that a resume
recommendation is unavailable; no recommendation is invented. Configure the private
catalog in the machine running discovery to enable all-five comparison. An invalid
configured catalog stops the run before sending. The local application tracker
contains the actual five-resume ranking and review brief. Contacts and
unknown deadlines are never invented and outreach is never automatically sent.

## Growing coverage

Community feeds admit employers that are not already in a company YAML file.
The existing discovery command can probe new company names and the master CSV:

```bash
python -m src.discover --company "Example Electronics"
python -m src.discover --priority A --limit 20
python -m src.discover --write-config
```

Review company identity and board ownership before adding discovered tokens.
This is not a universal web search engine. Workday tenants/custom sites still
need their public careers URLs configured. iCIMS discovery already exists;
SmartRecruiters currently has a manual application adapter, not a discovery source.

## Verification

```bash
python -m pytest -q
# Require real, fully intercepted browser fixtures locally:
REQUIRE_BROWSER_TESTS=1 python -m pytest tests/test_browser_forms.py -q
```

CI installs Chromium and requires browser fixtures. Fixtures intercept every
network request; they do not submit production applications. Without Chromium,
the browser tests are explicitly skipped locally. All other tests still run.

See [architecture and migration](docs/architecture.md) for implementation boundaries
and staged ATS support. Quality and truthful applications take priority over volume.
