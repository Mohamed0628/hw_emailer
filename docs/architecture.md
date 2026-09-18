# Architecture and migration

## Assessment

The original repository already had modular ATS collectors, community parsing,
parallel collection, detailed category filters, description-aware experience rules,
Minnesota targeting, seen-job state, SMTP notifications and local Playwright filling.
Those structures are retained.

The original application CLI called older title-only filters while discovery used
the newer career gate. Firmware/RTOS keywords scored as core hardware. Form filling
matched broad substrings, uploaded to the first file control when uncertain, and
could put a cover letter in an unrelated textarea. A submit click without explicit
confirmation was recorded as success. Tracker read errors silently reset history.
The baseline suite had 188 passing and 14 failing tests, including several taxonomy
alias collisions and stale company-count/priority expectations.

## Current flow

1. Existing sources normalize jobs, now retaining supplied ATS requisition IDs.
2. Canonical identities prefer direct descriptions over duplicate community rows.
3. `evaluation.py` combines preserved cohort/location/experience rules with the
   hardware gate in `career_fit.py`. `signals.py` owns the configurable technical
   vocabulary shared with resume matching.
4. Local `resumes.py` validates all five reviewed file hashes and ranks technical
   evidence deterministically. Its output does not establish legal eligibility or
   guarantee every job requirement is met.
5. `ApplicationEngine` coordinates adapters, exact answers, policy and durable state.
6. Native-control inventory fails closed. Policy approves a candidate/form combination
   only after another inventory immediately before the click.
7. A saved reservation precedes submission; explicit new confirmation is required.

Legacy filtering modules remain useful, tested category/cohort helpers. The new
entry points do not use them as standalone submission authorization. Firmware
remains a recognizable taxonomy label for diagnostics and historic state.

## Boundaries

- Browser execution is local. CI runs only intercepted fixtures and ordinary tests.
- No LLM is used for scoring, answers or letters. The former Gemini dependency was
  removed, so a provider abstraction is unnecessary. Future semantic assistance must
  remain separate from deterministic submission gates.
- Workday is discovery/email-only, independently of adapters and configuration.
  `identity.is_workday_job` checks ATS, provider, source and both URLs; duplicate
  consolidation retains restrictive Workday provenance. JSON reports expose the
  computed `application_restriction`; fit classifications are unchanged. CLI avoids
  browser creation, engine returns `needs_input` before adapters, and policy/runner
  entry points independently refuse Workday. Submission also checks the current URL.
- iCIMS/SmartRecruiters/custom application adapters remain explicitly manual.
- Optional unknown contact/demographic fields can be left blank. Other unknown fields,
  including optional custom questions, block automation.
- Native radio/select/checkbox controls are supported. Custom widgets and iframes
  require manual work. CAPTCHA/authentication is never bypassed.
- A matching public ATS host is required to enter candidate data. Redirects are
  rechecked. This is not a fraud-detection guarantee: verify employer legitimacy.
- Resume scores are heuristic, reviewable coverage measures. A five-point margin
  and configured minimum are needed for automatic selection. Explicit one-job
  review can affirm a tie without relaxing truthfulness or form safety gates.

## Migration and cleanup

No committed seen-job data is rewritten by this change. Legacy job IDs remain
stable; canonical/requisition identities add duplicate checks. Application records
retain existing fields and gain schema version 2 plus attempt history when updated.
The original JSON is backed up before first migration. Unreadable state fails closed.

The malformed tracked `config/profile.yaml` filename with trailing chevrons was
removed from the development branch after a private local backup. Its contents were
not trusted as candidate answers. A tracked debug log was likewise removed. These
removals do not erase historical Git commits.

The obsolete software-digest workflow referenced a missing configuration file and
an unsupported CLI flag; it was removed. The existing hourly hardware digest and
its state-merge mechanism are retained. No browser application workflow was added.

## Verification

Tests cover changed career priorities, taxonomy precedence, early-career experience,
all-five matching, demographic mappings, legal questions, duplicate URL variants,
legacy migration, atomic state behavior, quota, form mutation, CAPTCHA, confirmation
and failure logging. Browser fixtures route every request locally and use synthetic
candidate data. No production application, external outreach or notification is part
of this verification.

The five supplied PDFs and private candidate setup are delivered separately from Git.
Their facts are not embedded in application code or public test fixtures.

## Workday discovery bounds and endpoint follow-up

Workday uses a dedicated HTTP policy: 3-second connect and 8-second read timeout,
at most two attempts for timeout/connection failures, 408, 429 or 5xx, with a
0.5-second retry delay. Other 4xx and invalid JSON are not retried. A failed listing
request ends searches for that employer endpoint in the current run, preserving
earlier results. Other employers continue in the existing worker pool. A later
scheduled run can try the source again; none are permanently disabled.

Details are fetched once per distinct posting. Individual 404/422 detail errors
do not block the next posting; 401/403 or three consecutive systemic failures stop
remaining detail requests and retain the listing metadata. Missing descriptions
are not invented and may fail normal relevance checks. Healthy pagination and all
configured search terms remain available. Repeated definitions of the same company
and endpoint are consolidated with the union of search terms and detail settings.
Requests timeouts bound connect/read waits, not total elapsed runtime for a healthy
large employer or a server that continuously streams data.

The supplied local-run log (not a new live endpoint audit) shows repeated 422s for:

- Cepheid: `vhr-cepheid.wd1.myworkdayjobs.com/wday/cxs/vhr-cepheid/External_English/jobs`
- Otis: `otis.wd5.myworkdayjobs.com/wday/cxs/otis/REC_Ext_Gateway/jobs`

These tenant/site configurations need separate verification against current company
career links; a 422 alone does not prove the source is obsolete. The same log showed
slow Applied Materials (134.1s), GE Vernova (128.9s), Cisco (97.4s), Medtronic (96.6s),
Johnson Controls (89.8s), and Abbott (88.3s). Timing alone is not a reason to disable
them: they may have many legitimate search/detail requests. No company sources are
removed or globally disabled in this change.
