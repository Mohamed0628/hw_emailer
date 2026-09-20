"""Inventory every visible form control; fill only exact known meanings."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from .answers import resolve, normalize
from ..models import ApplicantProfile

_CLOSED_PHRASES = ("no longer accepting", "no longer available", "not accepting applications",
                  "isn't hiring for this role", "is not hiring for this role", "this position has been filled",
                  "this role has been filled", "applications are closed", "posting is closed", "job is closed",
                  "job not found", "job you requested was not found", "posting not found", "page not found")


def text_looks_closed(text: str) -> bool:
    return any(p in (text or "").lower()[:1200] for p in _CLOSED_PHRASES)


def looks_closed(page) -> bool:
    return text_looks_closed(page.inner_text("body"))


# The snapshot contains field metadata, never sent to an LLM or printed to logs.
INVENTORY_JS = r"""() => {
 const visible = el => !!(el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden');
 const text = el => (el?.textContent || '').trim().replace(/\s+/g, ' ');
 const labelText = el => {
   if(!el) return '';
   const copy=el.cloneNode(true);
   copy.querySelectorAll('input,textarea,select,button,[role="combobox"]').forEach(n=>n.remove());
   return text(copy);
 };
 const metaLabel = el => {
   const raw=(el.getAttribute('name')||el.id||'').trim();
   if(!raw) return '';
   const parts=raw.split(/[\[\].:_-]+/).filter(Boolean);
   return (parts[parts.length-1]||raw).replace(/\s+/g,' ');
 };
 const containerFor = el => el.closest(
   'fieldset,[role="radiogroup"],[class*="application-question"],[class*="question"],[class*="field"],[data-field]'
 );
 const containerQuestion = el => {
   const box=containerFor(el);
   if(!box) return '';
   const labelled=(box.getAttribute('aria-labelledby')||'').split(/\s+/).filter(Boolean)
     .map(id=>labelText(document.getElementById(id))).join(' ');
   if(labelled) return labelled;
   if(box.getAttribute('aria-label')) return box.getAttribute('aria-label');
   const kids=Array.from(box.children||[]);
   const candidate=kids.find(n =>
     n.matches?.('legend,label,h1,h2,h3,h4,p,[class*="label"],[class*="question-title"],[class*="question-label"]')
   );
   return labelText(candidate);
 };
 const label = el => {
   const ids=(el.getAttribute('aria-labelledby')||'').split(/\s+/).filter(Boolean);
   return ids.map(id=>labelText(document.getElementById(id))).join(' ') ||
     Array.from(el.labels||[]).map(labelText).join(' ') ||
     el.getAttribute('aria-label') ||
     labelText(el.closest('label')) ||
     containerQuestion(el) ||
     el.getAttribute('placeholder') ||
     metaLabel(el) || '';
 };
 const nodes=Array.from(document.querySelectorAll(
   'input,textarea,select,[role="combobox"],[role="checkbox"],[role="radiogroup"],[contenteditable="true"]'
 ));
 const fields=[]; const grouped=new Set();
 nodes.forEach((el,index)=>{
   if(el.closest('[role="combobox"]') && el.getAttribute('role')!=='combobox') return;
   const role=(el.getAttribute('role')||'').toLowerCase();
   let type=(role||el.type||el.tagName).toLowerCase();
   if(type==='radiogroup') return;
   if(role==='checkbox' && el.tagName!=='INPUT') return;
   if(['hidden','submit','button','reset'].includes(type)||el.disabled) return;
   if(!visible(el)&&type!=='file') return;

   let members=[el];
   let question=label(el);
   let groupKey='';
   const name=el.getAttribute('name')||'';

   if(type==='radio') {
     const group=el.closest('fieldset,[role="radiogroup"],[class*="application-question"],[class*="question"],[data-field]');
     if(name) members=nodes.filter(n=>n.type==='radio'&&n.name===name);
     else if(group) members=Array.from(group.querySelectorAll('input[type="radio"]'));
     groupKey='radio:'+(name||group?.getAttribute('aria-labelledby')||group?.getAttribute('aria-label')||question);
     if(grouped.has(groupKey)) return;
     grouped.add(groupKey);
     question=containerQuestion(el)||question||'Unlabeled radio group';
   } else if(type==='checkbox' && name) {
     const same=nodes.filter(n=>n.type==='checkbox'&&n.name===name);
     if(same.length>1) {
       members=same;
       type='checkboxgroup';
       groupKey='checkbox:'+name;
       if(grouped.has(groupKey)) return;
       grouped.add(groupKey);
       question=containerQuestion(el)||question||'Unlabeled checkbox group';
     }
   }

   el.setAttribute('data-hw-field',String(index));
   const group=el.closest('fieldset,[role="radiogroup"],[class*="application-question"],[class*="question"],[data-field]');
   const scope=group||el.closest('section')||el.closest('[data-voluntary]');
   const voluntary=/voluntary|self.identification/i.test(text(scope)) || scope?.getAttribute('data-voluntary')==='true';
   const options=el.tagName==='SELECT'
     ?Array.from(el.options).filter(o=>o.value&&!o.disabled).map(o=>({label:text(o),value:o.value}))
     :type==='radio'||type==='checkboxgroup'
       ?members.map(n=>({label:label(n),value:n.value}))
       :[];
   const required=type==='radio'||type==='checkboxgroup'
     ?!!(group?.getAttribute('aria-required')==='true'||members.some(n=>n.required||n.getAttribute('aria-required')==='true'))
     :!!(el.required||el.getAttribute('aria-required')==='true'||el.querySelector?.('[required],[aria-required="true"]'));
   const customValue=type==='combobox'
     ?(el.getAttribute('aria-valuetext')||el.querySelector?.('input')?.value||el.getAttribute('data-value')||text(el)||'')
     :'';
   const value=type==='radio'
     ?(members.find(n=>n.checked)?.value||'')
     :type==='checkboxgroup'
       ?members.filter(n=>n.checked).map(n=>n.value)
       :type==='checkbox'?el.checked:type==='combobox'?customValue:el.value||'';
   fields.push({
     index,type,tag:el.tagName,label:question,required,value,options,name,voluntary,
     files:type==='file'?Array.from(el.files||[]).map(f=>f.name):[],
     custom:type==='combobox'||!['INPUT','TEXTAREA','SELECT'].includes(el.tagName)
   });
 });
 return fields;
}"""


@dataclass
class FormAudit:
    fields: list[dict] = field(default_factory=list)
    filled: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)
    required: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    resume_uploaded: bool = False
    complete: bool = False
    fingerprint: str = ""


def _resume_label(label: str) -> bool:
    return normalize(label) in {"resume", "cv", "resume/cv", "resume / cv", "attach resume", "upload resume", "resume cv"}


def _clean_label(label: str) -> str:
    text = re.sub(r"[✱＊*]+", "", (label or "")).strip()
    # Lever/react-select autocomplete status text can be included in the
    # accessible label even though it is not part of the question.
    text = re.sub(
        r"(?i)\\b(?:no location found\\.?\\s*try entering a different location|loading)(?:\\s*[:.]?\\s*)?.*$",
        "",
        text,
    ).strip()
    return re.sub(r"\\s+", " ", text)


def _consequential_optional(label: str) -> bool:
    """Optional questions that still require an explicit configured answer/review."""
    return bool(re.search(
        r"(?i)\b(?:sponsor\w*|work\s+author\w*|citizen\w*|country|clearance\w*|"
        r"background\w*|relocat\w*|salary|compensation|hourly\s+rate|availability|"
        r"start\s+date|graduat\w*|gpa|reference\w*|certif\w*|government\s+id|"
        r"passport|driver'?s?\s+license)\b",
        label or "",
    ))


def blockers(page, profile: ApplicantProfile) -> list[str]:
    result = []
    captcha_frames = page.locator(
        'iframe[src*="recaptcha"],iframe[src*="hcaptcha"],iframe[src*="challenges.cloudflare"]'
    )
    sitekeys = page.locator('[data-sitekey]')
    response = page.locator(
        'textarea[name="g-recaptcha-response"],textarea[name="h-captcha-response"],'
        'input[name="cf-turnstile-response"]'
    )
    solved = False
    for i in range(response.count()):
        try:
            if (response.nth(i).input_value() or "").strip():
                solved = True
                break
        except Exception:
            continue
    visible_frame = any(
        captcha_frames.nth(i).is_visible() for i in range(captcha_frames.count())
    )
    visible_sitekey = any(
        sitekeys.nth(i).is_visible() for i in range(sitekeys.count())
    )
    if not solved and (visible_sitekey or visible_frame):
        result.append("CAPTCHA/anti-bot challenge requires human action")
    if page.locator('input[type="password"]').count():
        result.append("authentication requires human action")
    # Do not block merely because a page contains an iframe. Modern ATS pages commonly
    # embed analytics, upload helpers, or dormant CAPTCHA frames. Actual CAPTCHA/auth
    # challenges are handled explicitly above; application controls still must inventory.
    form_text = [page.inner_text('body')]  # SPAs may render forms without a <form> element
    for body in form_text:
        for match in re.finditer(r"(?i)by\s+(?:clicking|submitting|sending|applying|proceeding)[^.\n]*(?:agree|consent|certify|acknowledge)[^.\n]*", body):
            text = match.group()
            if re.search(r"(?i)\bcookies?\b", text):
                continue
            answer = resolve(text, profile)
            if not answer.known or answer.value is not True:
                result.append("unconfigured submission attestation: " + text[:240])
    return result


def audit_and_fill(page, profile: ApplicantProfile, *, fill: bool = True) -> FormAudit:
    result = FormAudit()
    try:
        result.blockers = blockers(page, profile)
        if any('authentication' in b for b in result.blockers):
            return result
        result.fields = page.evaluate(INVENTORY_JS)
        if not isinstance(result.fields, list) or not result.fields:
            result.blockers.append("no form controls inventoried")
            return result
        if len(result.fields) > 100:
            result.blockers.append("form exceeds bounded inventory; review manually")
            return result
        for item in result.fields:
            label = _clean_label(item['label']) or '<unlabeled field>'
            el = page.locator(f'[data-hw-field="{item["index"]}"]')
            if item['custom']:
                if item['type'] != 'combobox':
                    if item['required'] or _consequential_optional(label):
                        result.unknown.append(label + " (unsupported custom widget)")
                    continue
                answer = resolve(label, profile, None, item['voluntary'])
                if not answer.known or not isinstance(answer.value, str):
                    if item['required'] or _consequential_optional(label):
                        result.unknown.append(label + " (unsupported custom widget): " + answer.reason)
                    continue
                expected = str(answer.value).strip()
                current = str(item.get('value') or '').strip()
                current_norm = normalize(current)
                expected_norm = normalize(expected)
                if current_norm == expected_norm or current_norm.startswith(expected_norm + ","):
                    result.filled.append(label)
                    continue
                if not fill:
                    if item['required']:
                        result.unknown.append(label + ": custom widget value not verified")
                    continue
                try:
                    el.click()
                    page.keyboard.type(expected)
                    options = page.get_by_role('option')
                    visible = [
                        options.nth(i)
                        for i in range(options.count())
                        if options.nth(i).is_visible()
                    ]
                    expected_norm = normalize(expected)
                    exact = [
                        opt for opt in visible
                        if normalize(opt.inner_text()) == expected_norm
                    ]
                    matches = exact
                    if not matches:
                        # React-select style city widgets often render e.g.
                        # "Minneapolis, Minnesota, United States" while the profile
                        # stores the exact city "Minneapolis". Accept only one unique
                        # option whose visible label begins with that configured value.
                        matches = [
                            opt for opt in visible
                            if normalize(opt.inner_text()).startswith(expected_norm + ",")
                        ]
                    if len(matches) != 1:
                        result.unknown.append(label + ": no unique configured custom option")
                        continue
                    matches[0].click()
                    refreshed = page.evaluate(INVENTORY_JS)
                    updated = next(
                        (x for x in refreshed if x['index'] == item['index']),
                        None,
                    )
                    updated_value = normalize(str((updated or {}).get('value') or ''))
                    if not updated or not (
                        updated_value == expected_norm or updated_value.startswith(expected_norm + ",")
                    ):
                        result.blockers.append(label + ": custom widget value not verified")
                    else:
                        result.filled.append(label)
                except Exception as exc:
                    result.blockers.append(
                        label + ": custom widget fill failed: " + type(exc).__name__
                    )
                continue
            if item['type'] == 'checkboxgroup':
                answer = resolve(label, profile, [o['label'] for o in item['options']] or None, item['voluntary'])
                if not answer.known:
                    if item['required'] or _consequential_optional(label):
                        result.unknown.append(label + ': ' + answer.reason)
                    continue
                selected = next((o for o in item['options'] if o['label'] == answer.value), None)
                if selected is None:
                    result.unknown.append(label + ': configured option not found')
                    continue
                if fill:
                    group_name = item.get('name') or ''
                    candidates = page.locator('input[type="checkbox"]')
                    for i in range(candidates.count()):
                        candidate = candidates.nth(i)
                        if candidate.get_attribute('name') == group_name:
                            candidate.set_checked(candidate.get_attribute('value') == selected['value'])
                result.filled.append(label)
                continue
            if item['type'] == 'file':
                if not _resume_label(label):
                    if item['required'] or _consequential_optional(label):
                        result.unknown.append(label + " (unrecognized upload purpose)")
                    continue
                if fill and profile.resume_path:
                    el.set_input_files(profile.resume_path)
                files = el.evaluate('(el)=>Array.from(el.files||[]).map(f=>f.name)')
                from pathlib import Path
                result.resume_uploaded = bool(profile.resume_path and files == [Path(profile.resume_path).name])
                if not result.resume_uploaded:
                    result.required.append(label)
                continue
            answer = resolve(label, profile, [o['label'] for o in item['options']] or None, item['voluntary'])
            if not answer.known:
                # Blank optional questions may be left unanswered. Required or
                # prefilled unknown controls still require review.
                if item['required'] or item['value'] or _consequential_optional(label):
                    result.unknown.append(label + ': ' + answer.reason)
                continue
            value = answer.value
            if item['type'] == 'checkbox':
                if not isinstance(value, bool):
                    result.unknown.append(label + ': checkbox needs explicit true/false')
                    continue
                if fill:
                    el.set_checked(value)
                matches = el.is_checked() == value
            elif item['type'] == 'radio':
                option = next(o for o in item['options'] if o['label'] == value)
                if fill:
                    group = el.get_attribute('name')
                    candidates = page.locator('input[type="radio"]')
                    for i in range(candidates.count()):
                        candidate = candidates.nth(i)
                        if candidate.get_attribute('name') == group and candidate.get_attribute('value') == option['value']:
                            candidate.check()
                matches = page.evaluate(INVENTORY_JS)[result.fields.index(item)]['value'] == option['value']
            elif item['tag'] == 'SELECT':
                option = next(o for o in item['options'] if o['label'] == value)
                if fill:
                    el.select_option(value=option['value'])
                matches = el.input_value() == option['value']
            else:
                if fill:
                    el.fill(str(value))
                matches = el.input_value().strip() == str(value).strip()
            if not matches:
                result.blockers.append(label + ': value not verified')
            else:
                result.filled.append(label)
        # A fresh snapshot catches conditional fields after answers are filled.
        after = page.evaluate(INVENTORY_JS)
        signature = lambda xs: [(x['label'],x['type'],x['required'],x['options']) for x in xs]
        if signature(after) != signature(result.fields):
            result.blockers.append('form changed after filling; inspect again')
        result.fingerprint = hashlib.sha256(json.dumps(after, sort_keys=True).encode()).hexdigest()
        for x in after:
            if x['required'] and not (x['value'] or x['files']):
                result.required.append(_clean_label(x['label']) or '<unlabeled required field>')
        result.complete = True
    except Exception as exc:
        # Never interpret a selector or script failure as a simple form.
        result.blockers.append('form inspection failed: ' + type(exc).__name__)
    return result




def prompt_for_missing_answers(page, profile: ApplicantProfile) -> dict[str, str | bool]:
    """Ask only for real required/consequential facts missing from the local profile.

    AUTO_ELIGIBLE uses this as a human-intervention fallback. The returned answers
    are exact question -> value pairs; callers may persist them locally and retry.
    """
    try:
        items = page.evaluate(INVENTORY_JS)
    except Exception:
        return {}
    if not isinstance(items, list):
        return {}

    answers: dict[str, str | bool] = {}
    seen: set[str] = set()
    for item in items:
        label = _clean_label(str(item.get("label") or ""))
        if not label or label.startswith("<unlabeled"):
            continue
        key = normalize(label)
        if key in seen:
            continue
        seen.add(key)

        required = bool(item.get("required"))
        if not required and not _consequential_optional(label):
            continue
        if item.get("type") == "file":
            continue

        options = [
            str(o.get("label") or "").strip()
            for o in (item.get("options") or [])
            if str(o.get("label") or "").strip()
        ]
        existing = resolve(label, profile, options or None, bool(item.get("voluntary")))
        if existing.known:
            continue

        print("\nApplication needs one factual answer:")
        print("  " + label)
        if options:
            for i, option in enumerate(options, 1):
                print(f"    {i}. {option}")
            raw = input("Choose a number (blank = leave this application paused): ").strip()
            if not raw:
                continue
            try:
                idx = int(raw) - 1
            except ValueError:
                idx = -1
            if 0 <= idx < len(options):
                answers[label] = options[idx]
                continue
            exact = [o for o in options if normalize(o) == normalize(raw)]
            if len(exact) == 1:
                answers[label] = exact[0]
            else:
                print("  Answer not recognized; leaving this application paused.")
            continue

        if item.get("type") == "checkbox":
            raw = input("Answer yes/no (blank = leave this application paused): ").strip().casefold()
            if raw in {"y", "yes", "true", "1"}:
                answers[label] = True
            elif raw in {"n", "no", "false", "0"}:
                answers[label] = False
            elif raw:
                print("  Answer not recognized; leaving this application paused.")
            continue

        raw = input("Enter the exact answer (blank = leave this application paused): ").strip()
        if raw:
            answers[label] = raw

    return answers

def find_submit_button(page):
    # "Apply now" can navigate to another step and is not a confirmed submit action.
    loc = page.get_by_role('button', name=re.compile(r'^(submit application|send application|submit)$', re.I))
    candidates = [loc.nth(i) for i in range(loc.count()) if loc.nth(i).is_visible() and loc.nth(i).is_enabled()]
    return candidates[0] if len(candidates) == 1 else None


def fill_text_fields(page, profile):
    return audit_and_fill(page, profile).filled


def find_unfilled_required(page):
    return [x['label'] for x in page.evaluate(INVENTORY_JS) if x['required'] and not(x['value'] or x['files'])]


def fill_cover_letter(page, text):
    loc = page.get_by_label(re.compile(r'^cover letter\s*\*?$', re.I))
    if loc.count() == 1:
        loc.fill(text)
        return True
    return False
