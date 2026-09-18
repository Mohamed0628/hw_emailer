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
- Workday/iCIMS/SmartRecruiters/custom application adapters are explicitly manual.
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
