"""Workday keeps opportunity intelligence but can never use application mechanics."""
import hashlib
import json
from datetime import date
from unittest.mock import Mock

import pytest

from src import main
from src.apply import applog, cli, runner
from src.apply.base import FillOutcome
from src.apply.engine import ApplicationEngine
from src.apply.policy import Mode, decide
from src.apply.registry import get_applicator
from src.dedup import new_jobs, update_state
from src.evaluation import evaluate, evaluate_jobs
from src.identity import WORKDAY_MANUAL_REASON, is_workday_job
from src.models import ApplicantProfile, Job
from src.notify.email import build_html, build_text, group_by_category
from src.resumes import Resume, sections

RF = 'RF antennas VNA HFSS S-parameters Smith chart impedance matching noise figure PCB board bring-up. Entry level.'
POWER = 'Power electronics buck converter MOSFET gate driver power stage current sensing PCB Altium oscilloscope. Entry level.'
DIGITAL = 'FPGA Verilog RTL Lattice ECP5 RGMII MDIO Ethernet PHY synthesis PCB Altium. Entry level.'


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    monkeypatch.setattr(applog, 'APPLOG_PATH', tmp_path / 'applications.json')
    monkeypatch.setattr(applog, 'APPLOG_CSV', tmp_path / 'applications.csv')
    result = []
    for key, text in [('rf', RF), ('power', POWER), ('digital', DIGITAL),
                      ('hardware', 'analog op amps ADC transimpedance amplifier mixed signal sensor interfaces'),
                      ('controls', 'DC motor Simulink Quanser PID control motor modeling')]:
        path = tmp_path / (key + '.txt')
        path.write_text(text)
        result.append(Resume(key, str(path), hashlib.sha256(path.read_bytes()).hexdigest(), text, sections(text)))
    return result


def job_for(domain='rf', **overrides):
    titles = {'rf': 'RF Hardware Engineer I', 'power': 'Power Electronics Engineer I', 'digital': 'FPGA Hardware Engineer I'}
    return Job(**dict(dict(company='Example', title=titles[domain],
                          description={'rf': RF, 'power': POWER, 'digital': DIGITAL}[domain],
                          url=f'https://example.wd1.myworkdayjobs.com/en-US/External/job/Engineer_R123-{domain}',
                          source='workday:Example', ats='workday', locations=['Minneapolis, MN']), **overrides))


@pytest.mark.parametrize('domain', ['rf', 'power'])
def test_strong_workday_intelligence_email_and_dedup(catalog, domain):
    job = evaluate(job_for(domain), catalog)
    assert job.classification == 'HIGH_VALUE_REVIEW'
    assert job.career_fit_score >= 80
    assert job.selected_resume == domain
    assert len(job.resume_match['rankings']) == 5
    grouped = group_by_category([job], [])
    for content in (build_html(grouped, 1), build_text(grouped, 1)):
        for expected in (job.company, job.title, job.location_str, job.url,
                         WORKDAY_MANUAL_REASON, f'{job.career_fit_score}/100', f'Recommended resume: {domain}'):
            assert expected in content
    state = update_state({}, [job], date.today())
    assert new_jobs([job], state) == []
    assert len(evaluate_jobs([job, job.model_copy(update={'url': job.url + '?utm_source=test'})], catalog)) == 1
    assert job.model_dump()['application_restriction'] == WORKDAY_MANUAL_REASON


@pytest.mark.parametrize('mode', list(Mode))
@pytest.mark.parametrize('domain', ['rf', 'power', 'digital'])
def test_engine_never_prepares_workday_even_with_all_overrides(catalog, monkeypatch, mode, domain):
    from src.apply import engine
    job = job_for(domain)
    if domain == 'digital':
        assert evaluate(job, catalog).classification == 'AUTO_APPLY'
    forbidden = Mock(side_effect=AssertionError('Workday reached automation'))
    monkeypatch.setattr(engine, 'get_applicator', forbidden)
    monkeypatch.setattr(engine, 'settings', lambda: {'allowed_auto_ats': ['workday'], 'daily_limit': 999})
    monkeypatch.setattr(runner, 'fill_application', forbidden)
    monkeypatch.setattr(runner, 'inspect_application', forbidden)
    monkeypatch.setattr(runner, 'submit', forbidden)
    profile = ApplicantProfile(full_name='Example', email='test@example.test', available_start_date='2027-06-01')
    assert ApplicationEngine(profile, catalog, mode).process(job, Mock(), reviewed=True, review_callback=forbidden) == 'needs_input'
    forbidden.assert_not_called()
    saved = applog.load()[job.job_id]
    assert saved['resume_used'] == domain
    assert saved['application_restriction'] == WORKDAY_MANUAL_REASON
    assert saved['date_applied'] is None
    assert applog.daily_attempts(applog.load()) == 0


@pytest.mark.parametrize('marker', ['ats', 'provider', 'source', 'url', 'application_url'])
def test_any_workday_evidence_overrides_conflicting_native_ats(marker):
    fields = dict(ats='lever', provider='lever', source='github:test', url='https://jobs.lever.co/example/123')
    fields[marker] = ('https://example.wd1.myworkdayjobs.com/jobs/123' if marker.endswith('url')
                      else 'WoRkDaY:Example' if marker == 'source' else ' WorkDay ')
    job = job_for(**fields)
    assert is_workday_job(job)
    assert get_applicator(job).ats == 'workday'


def test_dedup_cannot_erase_workday_provenance(catalog):
    ordinary = job_for('digital', url='https://jobs.lever.co/example/123', ats='lever', source='lever:Example')
    workday_copy = ordinary.model_copy(update={'source': 'workday:Example', 'ats': 'workday'})
    result = evaluate_jobs([ordinary, workday_copy], catalog)
    assert len(result) == 1
    assert is_workday_job(result[0])
    assert get_applicator(result[0]).ats == 'workday'


@pytest.mark.parametrize('mode', list(Mode))
def test_cli_workday_only_does_not_even_create_browser(catalog, tmp_path, monkeypatch, mode, capsys):
    path = tmp_path / 'jobs.json'
    path.write_text(json.dumps([job_for('digital').model_dump()]))
    monkeypatch.delenv('CI', raising=False)
    monkeypatch.setattr(cli, 'load_profile', lambda _: ApplicantProfile(full_name='Test', email='test@example.test'))
    monkeypatch.setattr(cli, 'load_resumes', lambda _: catalog)
    browser = Mock(side_effect=AssertionError('browser created'))
    monkeypatch.setattr(cli, 'BrowserSession', browser)
    assert cli.main(['--jobs-json', str(path), '--mode', mode.value, '--review-job', job_for('digital').job_id]) == 0
    browser.assert_not_called()
    assert 'needs_input' in capsys.readouterr().out


@pytest.mark.parametrize('mode', list(Mode))
def test_policy_cannot_override_boundary(catalog, mode):
    job = evaluate(job_for('digital'), catalog)
    outcome = FillOutcome(job, job.url, resume_uploaded=True, inventory_complete=True, submit_available=True)
    decision = decide(job, outcome, mode, ApplicantProfile(), reviewed=True)
    assert not decision.may_submit
    assert decision.reason == WORKDAY_MANUAL_REASON


def test_direct_runner_and_submit_are_defensive():
    job = job_for(ats='workday', url='https://jobs.lever.co/example/123')
    page, adapter = Mock(), Mock()
    for operation in (runner.fill_application, runner.inspect_application):
        assert operation(page, job, adapter, ApplicantProfile()).blockers == [WORKDAY_MANUAL_REASON]
    assert runner.submit(page, job=job).status == 'needs_input'
    assert page.mock_calls == []
    assert adapter.mock_calls == []
    page.url = 'https://example.myworkdaysite.com/recruiting/company/External/job/123'
    assert runner.submit(page).status == 'needs_input'
    assert page.mock_calls == []


@pytest.mark.parametrize('ats,url', [('greenhouse', 'https://boards.greenhouse.io/example/jobs/123'),
                                    ('lever', 'https://jobs.lever.co/example/123'),
                                    ('ashby', 'https://jobs.ashbyhq.com/example/123')])
def test_native_ats_still_uses_guarded_engine(catalog, monkeypatch, ats, url):
    job = job_for('digital', url=url, source=ats + ':Example', ats=ats)
    outcome = FillOutcome(job, url, resume_uploaded=True, submit_available=True, inventory_complete=True, form_fingerprint='stable')
    monkeypatch.setattr(runner, 'fill_application', Mock(return_value=outcome))
    monkeypatch.setattr(runner, 'inspect_application', Mock(return_value=outcome))
    submit = Mock(return_value=runner.SubmissionResult('submitted', 'fixture confirmation'))
    monkeypatch.setattr(runner, 'submit', submit)
    profile = ApplicantProfile(full_name='Test', email='test@example.test', available_start_date='2027-06-01')
    assert ApplicationEngine(profile, catalog).process(job, Mock()) == 'submitted'
    assert submit.call_count == 1
    assert job.application_restriction is None


def test_local_email_pipeline_loads_five_resumes_and_prints_workday(catalog, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(main, 'load_profile', lambda: ApplicantProfile(resumes=[{'id': r.id} for r in catalog]))
    loader = Mock(return_value=catalog)
    monkeypatch.setattr(main, 'load_resumes', loader)
    monkeypatch.setattr(main, 'collect_jobs', lambda **_: [job_for('rf'), job_for('power')])
    monkeypatch.setattr(main.config, 'state_path', lambda: tmp_path / 'seen.json')
    send = Mock(side_effect=AssertionError('production email'))
    monkeypatch.setattr(main.email_notify, 'send_email', send)
    assert main.run(True, True, False, None) == 0
    output = capsys.readouterr().out
    assert 'Resume: rf' in output and 'Resume: power' in output
    assert output.count(WORKDAY_MANUAL_REASON) == 2
    loader.assert_called_once()
    send.assert_not_called()
