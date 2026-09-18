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
 const label = el => {
   const ids=(el.getAttribute('aria-labelledby')||'').split(/\s+/).filter(Boolean);
   return ids.map(id=>text(document.getElementById(id))).join(' ') ||
     Array.from(el.labels||[]).map(text).join(' ') || el.getAttribute('aria-label') ||
     el.getAttribute('placeholder') || '';
 };
 const nodes=Array.from(document.querySelectorAll('input,textarea,select,[role="combobox"],[role="checkbox"],[role="radiogroup"],[contenteditable="true"]'));
 const fields=[]; const radios=new Set();
 nodes.forEach((el,index)=>{
   const type=(el.type||el.getAttribute('role')||el.tagName).toLowerCase();
   if(['hidden','submit','button','reset'].includes(type)||el.disabled) return;
   if(!visible(el)&&type!=='file') return;
   el.setAttribute('data-hw-field',String(index));
   const group=el.closest('fieldset');
   let question=label(el);
   let members=[el];
   if(type==='radio') {
     if(!el.name) { question='Unlabeled radio group'; }
     else {if(radios.has(el.name)) return;radios.add(el.name);members=nodes.filter(n=>n.type==='radio'&&n.name===el.name);}
     question=text(group?.querySelector('legend')) || el.getAttribute('aria-label') || 'Unlabeled radio group';
   }
   const scope=group||el.closest('section')||el.closest('[data-voluntary]');
   const voluntary=/voluntary|self.identification/i.test(text(scope)) || scope?.getAttribute('data-voluntary')==='true';
   const options=el.tagName==='SELECT'?Array.from(el.options).filter(o=>o.value&&!o.disabled).map(o=>({label:text(o),value:o.value})):
     type==='radio'?members.map(n=>({label:label(n),value:n.value})):[];
   fields.push({index,type,tag:el.tagName,label:question,required:el.required||el.getAttribute('aria-required')==='true',
     value:type==='radio'?(members.find(n=>n.checked)?.value||''):type==='checkbox'?el.checked:el.value||'',
     options,voluntary,files:type==='file'?Array.from(el.files||[]).map(f=>f.name):[],
     custom:!['INPUT','TEXTAREA','SELECT'].includes(el.tagName)||!!el.getAttribute('role')});
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


def blockers(page, profile: ApplicantProfile) -> list[str]:
    result = []
    if page.locator('iframe[src*="recaptcha"],iframe[src*="hcaptcha"],iframe[src*="challenges.cloudflare"],[data-sitekey]').count():
        result.append("CAPTCHA/anti-bot challenge requires human action")
    if page.locator('input[type="password"]').count():
        result.append("authentication requires human action")
    # Unknown frames may contain application questions invisible to the main inventory.
    if page.locator('iframe').count():
        result.append("embedded form/frame requires manual inspection")
    form_text = page.locator('form').all_text_contents()
    for body in form_text:
        for match in re.finditer(r"(?i)by\s+(?:clicking|submitting|sending)[^.\n]*(?:agree|consent|certify|acknowledge)[^.\n]*", body):
            answer = resolve(match.group(), profile)
            if not answer.known or answer.value is not True:
                result.append("unconfigured submission attestation: " + match.group()[:240])
    return result


def audit_and_fill(page, profile: ApplicantProfile, *, fill: bool = True) -> FormAudit:
    result = FormAudit()
    try:
        result.blockers = blockers(page, profile)
        if any('CAPTCHA' in b or 'authentication' in b or 'frame' in b for b in result.blockers):
            return result
        result.fields = page.evaluate(INVENTORY_JS)
        if not isinstance(result.fields, list) or not result.fields:
            result.blockers.append("no form controls inventoried")
            return result
        if len(result.fields) > 100:
            result.blockers.append("form exceeds bounded inventory; review manually")
            return result
        for item in result.fields:
            label = item['label'] or '<unlabeled field>'
            el = page.locator(f'[data-hw-field="{item["index"]}"]')
            if item['custom']:
                result.unknown.append(label + " (unsupported custom widget)")
                continue
            if item['type'] == 'file':
                if not _resume_label(label):
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
                # Optional standard contact fields and optional demographics may be left blank.
                from .answers import DEMOGRAPHIC_FIELDS
                optional = normalize(label) in {'phone','phone number','linkedin','linkedin profile','github','website','portfolio','gpa','cover letter'} or normalize(label) in DEMOGRAPHIC_FIELDS
                if item['required'] or not optional or item['value']:
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
                result.required.append(x['label'] or '<unlabeled required field>')
        result.complete = True
    except Exception as exc:
        # Never interpret a selector or script failure as a simple form.
        result.blockers.append('form inspection failed: ' + type(exc).__name__)
    return result


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
