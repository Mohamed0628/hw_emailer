"""Stateful engine tests: real evaluation/tracking with controlled browser mechanics."""
from pathlib import Path
import hashlib
from unittest.mock import Mock

import pytest

from src.apply import applog, runner
from src.apply.base import FillOutcome
from src.apply.engine import ApplicationEngine
from src.apply.policy import Mode
from src.models import ApplicantProfile, Job
from src.resumes import Resume, sections


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setattr(applog,'APPLOG_PATH',tmp_path/'applications.json')
    monkeypatch.setattr(applog,'APPLOG_CSV',tmp_path/'applications.csv')
    resumes=[]
    for name,text in [('digital','FPGA Verilog RTL Lattice ECP5 RGMII MDIO Ethernet PHY synthesis PCB Altium'),
                      ('rf','RF antenna VNA HFSS'),('analog','analog op amps ADC'),
                      ('power','power electronics MOSFET buck converter'),('controls','DC motor Simulink Quanser')]:
        path=tmp_path/(name+'.txt');path.write_text(text)
        resumes.append(Resume(name,str(path),hashlib.sha256(path.read_bytes()).hexdigest(),text,sections(text)))
    profile=ApplicantProfile(full_name='Test Candidate',email='candidate@example.test',available_start_date='2027-06-01')
    job=Job(company='Example',title='FPGA Hardware Engineer I',
            description='FPGA Verilog RTL Lattice ECP5 RGMII MDIO Ethernet PHY synthesis PCB Altium. Entry level.',
            locations=['Minneapolis, MN'],url='https://jobs.lever.co/example/abc')
    outcome=FillOutcome(job,job.url,resume_uploaded=True,submit_available=True,inventory_complete=True,form_fingerprint='stable')
    monkeypatch.setattr(runner,'fill_application',Mock(return_value=outcome))
    monkeypatch.setattr(runner,'inspect_application',Mock(return_value=outcome))
    submit=Mock(return_value=runner.SubmissionResult('submitted','confirmation observed'))
    monkeypatch.setattr(runner,'submit',submit)
    return profile,resumes,job,outcome,submit


def test_success_persisted_exactly_once(case):
    profile,resumes,job,outcome,submit=case
    engine=ApplicationEngine(profile,resumes)
    assert engine.process(job,Mock())=='submitted'
    assert engine.process(job,Mock())=='duplicate'
    assert submit.call_count==1
    saved=applog.load()[job.job_id]
    assert saved['resume_used']=='digital'
    assert saved['date_applied']
    assert [x['status'] for x in saved['attempts']]==['submitting','submitted']


@pytest.mark.parametrize('status',['failed','submission_unknown'])
def test_failure_status_logged(case,status):
    profile,resumes,job,outcome,submit=case
    submit.return_value=runner.SubmissionResult(status,'fixture failure')
    assert ApplicationEngine(profile,resumes).process(job,Mock())==status
    assert applog.load()[job.job_id]['failure_reason']=='fixture failure'


def test_prepare_only_never_calls_submit(case):
    profile,resumes,job,outcome,submit=case
    assert ApplicationEngine(profile,resumes,Mode.PREPARE_ONLY).process(job,Mock())=='prepared'
    submit.assert_not_called()


def test_high_value_held_before_opening_form(case):
    profile,resumes,job,outcome,submit=case
    job.title='RF Hardware Engineer I'
    job.description='RF antennas VNA HFSS S-parameters Smith chart impedance matching noise figure PCB board bring-up. Entry level.'
    assert ApplicationEngine(profile,resumes).process(job,Mock())=='high_value_review'
    runner.fill_application.assert_not_called()
    submit.assert_not_called()


def test_unknown_legal_question_blocks(case):
    profile,resumes,job,outcome,submit=case
    outcome.unknown_questions=['I certify government eligibility']
    assert ApplicationEngine(profile,resumes).process(job,Mock())=='needs_input'
    submit.assert_not_called()


def test_captcha_blocks_even_auto_eligible(case):
    profile,resumes,job,outcome,submit=case
    outcome.blockers=['CAPTCHA']
    assert ApplicationEngine(profile,resumes,Mode.AUTO_ELIGIBLE).process(job,Mock())=='needs_input'
    submit.assert_not_called()


def test_changed_form_blocks_before_click(case,monkeypatch):
    profile,resumes,job,outcome,submit=case
    fresh=FillOutcome(job,job.url,resume_uploaded=True,submit_available=True,inventory_complete=True,form_fingerprint='changed')
    monkeypatch.setattr(runner,'inspect_application',Mock(return_value=fresh))
    assert ApplicationEngine(profile,resumes).process(job,Mock())=='needs_input'
    submit.assert_not_called()


def test_quota_counts_uncertain_attempts_across_runs(case,monkeypatch):
    profile,resumes,job,outcome,submit=case
    from src.apply import engine as module
    monkeypatch.setattr(module,'settings',lambda:{'daily_limit':1,'allowed_auto_ats':['lever']})
    engine=ApplicationEngine(profile,resumes)
    assert engine.process(job,Mock())=='submitted'
    job.url='https://jobs.lever.co/example/def'
    job.application_url=None
    assert engine.process(job,Mock())=='needs_input'
    assert submit.call_count==1


def test_crash_reservation_prevents_second_submit(case):
    profile,resumes,job,outcome,submit=case
    state={};applog.record(state,job,'submitting');applog.save(state)
    assert ApplicationEngine(profile,resumes).process(job,Mock(),retry_failed=True)=='duplicate'
    submit.assert_not_called()


def test_unknown_question_not_bypassed_by_review(case):
    profile,resumes,job,outcome,submit=case
    outcome.unknown_questions=['Will you require sponsorship?']
    engine=ApplicationEngine(profile,resumes,Mode.REVIEW_ALL)
    assert engine.process(job,Mock(),review_callback=lambda *_:True)=='needs_input'
    submit.assert_not_called()


def test_exact_review_can_submit_safe_form(case):
    profile,resumes,job,outcome,submit=case
    engine=ApplicationEngine(profile,resumes,Mode.REVIEW_ALL)
    assert engine.process(job,Mock(),review_callback=lambda *_:True)=='submitted'
    assert submit.call_count==1


def test_prepare_only_blocker_never_reports_prepared(case):
    profile,resumes,job,outcome,submit=case
    outcome.blockers=['embedded form/frame requires manual inspection']
    assert ApplicationEngine(profile,resumes,Mode.PREPARE_ONLY).process(job,Mock())=='needs_input'
    saved=applog.load()[job.job_id]
    assert saved['status']=='needs_input'
    assert saved['blockers']==['embedded form/frame requires manual inspection']
    submit.assert_not_called()


def test_prepare_only_uncertain_resume_never_reports_prepared(case, monkeypatch):
    profile,resumes,job,outcome,submit=case
    from src.apply import engine as engine_module

    def fake_evaluate(target, _resumes):
        target.classification='AUTO_APPLY'
        target.selected_resume='digital'
        target.resume_fit_score=0
        target.resume_match={
            'selected_resume':'digital',
            'resume_fit_score':0,
            'alternative_resume':'rf',
            'confident':False,
            'evidence':[],
            'rankings':[],
            'reason':'fixture uncertainty',
        }
        target.decision_reasons=[]
        return target

    monkeypatch.setattr(engine_module,'evaluate',fake_evaluate)
    assert ApplicationEngine(profile,resumes,Mode.PREPARE_ONLY).process(job,Mock())=='needs_input'
    saved=applog.load()[job.job_id]
    assert saved['status']=='needs_input'
    assert 'uncertain resume match' in saved['note']
    submit.assert_not_called()
