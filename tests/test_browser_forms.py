"""Real Chromium fixtures. Every HTTP request is intercepted; no live applications."""
import os
from pathlib import Path

import pytest

from src.apply.answers import normalize
from src.apply.fields import audit_and_fill
from src.apply.runner import submit
from src.models import ApplicantProfile


@pytest.fixture(scope='module')
def browser():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        if os.environ.get('REQUIRE_BROWSER_TESTS') == '1':
            pytest.fail('Playwright is required by this CI job')
        pytest.skip('Install requirements-apply.txt for browser fixtures')
    with sync_playwright() as pw:
        try:
            b=pw.chromium.launch(headless=True)
        except Exception as exc:
            if os.environ.get('REQUIRE_BROWSER_TESTS') == '1':
                raise
            pytest.skip('Chromium unavailable locally: '+type(exc).__name__)
        yield b
        b.close()


@pytest.fixture
def form(browser,tmp_path):
    context=browser.new_context()
    # No request can leave the test, even if a fixture accidentally embeds a resource.
    context.route('**/*',lambda route:route.fulfill(status=200,body=''))
    page=context.new_page()
    page.set_default_timeout(1000)
    resume=tmp_path/'test-resume.pdf';resume.write_bytes(b'%PDF-1.4\nfixture')
    profile=ApplicantProfile(full_name='Test Candidate',email='candidate@example.test',resume_path=str(resume),
                             demographics={'gender':'male','race':'black','veteran':'not_veteran','disability':'not_disabled'})
    yield page,profile
    context.close()


BASE='''<form onsubmit="event.preventDefault();document.body.innerHTML='Application submitted';">
<label>Full name<input name="name" required></label>
<label>Email<input name="email" type="email" required></label>
<label>Resume<input name="resume" type="file" required></label>
{extra}<button type="submit">Submit application</button></form>'''


def render(page,extra=''):
    page.set_content(BASE.format(extra=extra))


def test_standard_fields_and_resume_verified(form):
    page,profile=form;render(page)
    result=audit_and_fill(page,profile)
    assert result.complete and result.resume_uploaded
    assert not result.unknown and not result.required and not result.blockers
    assert page.locator('input[name="name"]').input_value()=='Test Candidate'
    assert submit(page).status=='submitted'


def test_female_not_accidentally_selected_for_male(form):
    page,profile=form
    render(page,'<fieldset><legend>Voluntary self-identification</legend><label>Gender<select required><option value="">Choose</option><option>Female</option><option>Male</option></select></label></fieldset>')
    result=audit_and_fill(page,profile)
    assert page.locator('select').input_value()=='Male'
    assert not result.unknown


def test_native_radio_demographic_group(form):
    page,profile=form
    render(page,'<fieldset data-voluntary="true"><legend>Gender</legend><label>Female<input type="radio" name="gender" value="female"></label><label>Male<input type="radio" name="gender" value="male"></label></fieldset>')
    result=audit_and_fill(page,profile)
    assert not result.blockers
    assert page.locator('input[value="male"]').is_checked()


def test_optional_unknown_field_still_pauses(form):
    page,profile=form;render(page,'<label>Will you require sponsorship?<select><option value="">Choose</option><option>Yes</option><option>No</option></select></label>')
    result=audit_and_fill(page,profile)
    assert result.unknown
    assert page.locator('select').input_value()==''


def test_unknown_prefilled_attestation_still_pauses(form):
    page,profile=form;render(page,'<label>I agree to a background check<input type="checkbox" checked></label>')
    result=audit_and_fill(page,profile)
    assert result.unknown


def test_configured_attestation_can_be_filled(form):
    page,profile=form;render(page,'<label>I certify these answers are accurate<input type="checkbox" required></label>')
    profile.confirmed_answers={'I certify these answers are accurate':True}
    result=audit_and_fill(page,profile)
    assert not result.unknown and not result.required
    assert page.locator('input[type="checkbox"]').is_checked()


def test_wrong_upload_field_not_given_resume(form):
    page,profile=form;render(page,'<label>Government ID<input type="file"></label>')
    result=audit_and_fill(page,profile)
    assert any('unrecognized upload purpose' in s for s in result.unknown)
    assert page.get_by_label('Government ID').evaluate('(el)=>el.files.length')==0


def test_captcha_and_auth_block(form):
    page,profile=form;render(page,'<div data-sitekey="fixture"></div><input type="password">')
    result=audit_and_fill(page,profile)
    assert any('CAPTCHA' in s for s in result.blockers)
    assert any('authentication' in s for s in result.blockers)


def test_dynamic_field_after_filling_is_detected(form):
    page,profile=form;render(page)
    page.evaluate('''() => document.querySelector('input[name="email"]').addEventListener('input',()=>{
      if(!document.getElementById('dynamic')){
        const label=document.createElement('label');label.id='dynamic';label.innerHTML='Citizenship<input required>';
        document.querySelector('form').append(label);
      }
    })''')
    result=audit_and_fill(page,profile)
    assert any('form changed' in s for s in result.blockers)


def test_silent_inspection_failure_never_simple(form):
    page,profile=form;page.close()
    result=audit_and_fill(page,profile)
    assert not result.complete and result.blockers


def test_generic_thank_you_is_not_confirmation(form,monkeypatch):
    page,profile=form;render(page)
    audit_and_fill(page,profile)
    page.evaluate('''() => document.querySelector('form').onsubmit=e=>{e.preventDefault();document.body.innerHTML='Thank you for visiting'}''')
    # Preserve the real browser wait while bounding this negative-case test.
    wait=page.wait_for_function
    monkeypatch.setattr(page,'wait_for_function',lambda expression,**kw:wait(expression,arg=kw.get('arg'),timeout=150))
    assert submit(page).status=='submission_unknown'


def test_custom_combobox_blocks(form):
    page,profile=form;render(page,'<div role="combobox" aria-label="Country">Choose</div>')
    result=audit_and_fill(page,profile)
    assert any('unsupported custom widget' in s for s in result.unknown)


def test_implied_legal_consent_needs_exact_confirmation(form):
    page,profile=form;render(page,'<p>By submitting this application, I consent to background screening.</p>')
    result=audit_and_fill(page,profile)
    assert any('attestation' in s for s in result.blockers)


def test_redirect_to_different_requisition_never_uploads(form):
    from src.apply.runner import inspect_application
    from src.apply.lever import LeverApplicator
    from src.models import Job
    page,profile=form
    page.goto('https://jobs.lever.co/example/wrong/apply')
    render(page)
    job=Job(company='Example',title='Hardware Engineer I',url='https://jobs.lever.co/example/expected')
    result=inspect_application(page,job,LeverApplicator(),profile,fill=True)
    assert any('requisition' in b for b in result.blockers)
    assert page.locator('input[type="file"]').evaluate('(el)=>el.files.length')==0


def test_optional_unknown_text_field_can_remain_blank(form):
    page,profile=form
    render(page,'<label>Preferred First Name<input></label>')
    result=audit_and_fill(page,profile)
    assert not any('Preferred First Name' in s for s in result.unknown)


def test_optional_unrecognized_upload_can_remain_blank(form):
    page,profile=form
    render(page,'<label>Portfolio attachment<input type="file"></label>')
    result=audit_and_fill(page,profile)
    assert not any('Portfolio attachment' in s for s in result.unknown)


def test_exact_known_custom_combobox_can_be_filled(form):
    page,profile=form
    profile.school='University of Minnesota'
    page.set_content('''
      <form>
        <label>Full name<input name="name" required></label>
        <label>Email<input name="email" type="email" required></label>
        <label>Resume<input name="resume" type="file" required></label>
        <div role="combobox" aria-label="School" aria-required="true"><input required></div>
        <div role="option"
             onclick="document.querySelector('[role=combobox]').setAttribute('aria-valuetext','University of Minnesota')">
          University of Minnesota
        </div>
        <button type="submit">Submit application</button>
      </form>
    ''')
    result=audit_and_fill(page,profile)
    assert 'School' in result.filled
    assert not any('School' in s for s in result.unknown)
    assert not any('School' in s for s in result.blockers)


def test_cookie_consent_text_is_not_application_attestation(form):
    page,profile=form
    render(page,'<p>By clicking Accept, you agree to the use of cookies.</p>')
    result=audit_and_fill(page,profile)
    assert not any('cookies' in s.lower() for s in result.blockers)
