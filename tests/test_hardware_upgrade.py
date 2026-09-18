"""Behavioral regressions for the shared discovery/application decision pipeline."""
import hashlib
import json
from pathlib import Path

import pytest

from src import career_fit
from src.apply import applog
from src.apply.answers import resolve
from src.apply.base import FillOutcome
from src.apply.policy import Mode, decide
from src.evaluation import evaluate
from src.identity import canonical_url, detect_ats, prefer_direct
from src.models import ApplicantProfile, Job
from src.resumes import Resume, match_job, sections, load_resumes


def job(title='Electrical Engineer I', description='PCB schematic capture Altium board bring-up oscilloscope. Entry level.', **kwargs):
    return Job(company='Example', title=title, description=description,
               url=kwargs.pop('url', 'https://jobs.lever.co/example/123'),
               locations=kwargs.pop('locations', ['Minneapolis, MN']), **kwargs)


@pytest.mark.parametrize('title,description', [
    ('RF Engineer I', 'RF antennas VNA S-parameters RF PCB validation. Entry level.'),
    ('Power Electronics Engineer I', 'Power electronics MOSFET converter gate driver control loop PCB. Entry level.'),
    ('Analog Engineer I', 'Analog mixed-signal PCB op amps low-noise signal conditioning. Entry level.'),
    ('Electrical Engineer I', 'PCB schematic board bring-up STM32 SPI. Entry level.'),
    ('Controls Engineer I', 'Motor control motor drives encoders HIL actuators. 1-2 years of experience.'),
])
def test_hardware_roles_pass(title, description):
    result = evaluate(job(title, description))
    assert result.classification != 'HARD_NO', result.decision_reasons
    assert result.career_fit_score >= 65

@pytest.mark.parametrize('title,description', [
    ('Firmware Engineer I', 'PCB STM32 SPI RTOS Linux C++ device drivers bootloader'),
    ('Embedded Software Engineer', 'PCB schematic reviews supporting Linux drivers and firmware'),
    ('Software Engineer I', 'C++ backend APIs'),
    ('Electrical Engineer I', 'Develop RTOS C++ device drivers bootloader Linux firmware'),
    ('Senior Electrical Engineer', 'PCB schematics oscilloscope'),
    ('Project Engineer I', 'PCB project schedules budgets'),
    ('Electrical Engineer I', 'PCB schematic capture. Required: 5 years of experience.'),
    ('Electrical Engineer I', 'PCB schematic capture. 0 years of experience with CAD. Minimum 5 years of experience with electronics.'),
])
def test_rejected_roles(title, description):
    assert evaluate(job(title, description)).classification == 'HARD_NO'


def test_minnesota_bonus_without_same_city_in_other_state():
    mn = career_fit.evaluate(job(locations=['Minneapolis, MN']))
    other = career_fit.evaluate(job(locations=['Plymouth, MA']))
    assert mn.location_fit == 10
    assert other.location_fit == 0
    assert mn.score > other.score


def test_senior_colleague_mentioned_in_description_does_not_reject():
    assert evaluate(job(description='PCB Altium schematics. Work with a senior engineer. 1-2 years of experience.')).classification != 'HARD_NO'


def test_inactive_and_expired_rejected():
    assert evaluate(job(active=False)).classification == 'HARD_NO'
    assert evaluate(job(deadline='2020-01-01')).classification == 'HARD_NO'


def test_company_does_not_rescue_generic_job():
    assert evaluate(job('Quality Engineer I', 'Own regulatory submissions and document control.')).classification == 'HARD_NO'


@pytest.fixture
def resumes(tmp_path):
    texts = {
        'rf': 'Projects\nRF antennas HFSS S-parameters impedance matching Smith chart VNA noise figure.\nSkills\nPCB Altium',
        'power': 'Projects\nPower electronics buck converters MOSFET gate drivers DC DC switching loops STM32 PWM.\nSkills\nPCB Altium',
        'hardware': 'Projects\nAnalog mixed signal photodiode transimpedance amplifiers low noise neural sensing PPG ADC signal conditioning.\nSkills\nPCB Altium',
        'controls': 'Projects\nDC motor motor control PID PI control Quanser Simulink system identification HIL encoders actuators.\nSkills\nPCB Altium',
        'digital': 'Projects\nFPGA Verilog RTL Lattice ECP5 RGMII MDIO Ethernet PHY synthesis.\nSkills\nPCB Altium C++ FreeRTOS',
    }
    result = []
    for name, text in texts.items():
        path = tmp_path / (name + '.txt')
        path.write_text(text)
        result.append(Resume(name, str(path), hashlib.sha256(path.read_bytes()).hexdigest(), text, sections(text)))
    return result


@pytest.mark.parametrize('title,description,expected', [
    ('RF Engineer I', 'RF antennas HFSS S-parameters impedance matching Smith chart VNA', 'rf'),
    ('Power Electronics Engineer I', 'MOSFET buck converters gate drivers switching loops PWM', 'power'),
    ('Analog Engineer I', 'Photodiode transimpedance amplifiers low noise PPG signal conditioning', 'hardware'),
    ('Controls Engineer I', 'DC motor PID Quanser Simulink system identification encoders', 'controls'),
    ('FPGA Hardware Engineer I', 'Verilog RTL Lattice ECP5 RGMII MDIO Ethernet PHY synthesis', 'digital'),
])
def test_all_five_resumes_compared(resumes, title, description, expected):
    result = match_job(job(title, description), resumes)
    assert result.selected_resume == expected
    assert result.confident
    assert len(result.rankings) == 5
    assert result.alternative_resume != expected


def test_equal_resume_evidence_pauses(resumes):
    result = match_job(job(description='PCB Altium'), resumes)
    assert not result.confident


def test_hash_mismatch_blocks_catalog(resumes, tmp_path):
    profile = ApplicantProfile(resumes=[{'id':r.id,'path':r.path,'sha256':r.sha256,'reviewed':True} for r in resumes])
    # A source file changed since the analysis must be reviewed again.
    Path(resumes[0].path).write_text('changed')
    with pytest.raises(ValueError, match='changed since review'):
        load_resumes(profile, tmp_path)


@pytest.mark.parametrize('label,configured,options,expected', [
    ('Gender', {'gender':'male'}, ['Female','Male'], 'Male'),
    ('Race', {'race':'black'}, ['White','Black or African American'], 'Black or African American'),
    ('Veteran status', {'veteran':'not_veteran'}, ['I am a protected veteran','I am not a protected veteran'], 'I am not a protected veteran'),
    ('Disability status', {'disability':'not_disabled'}, ['I have a disability','I do not have a disability'], 'I do not have a disability'),
])
def test_voluntary_demographics(label, configured, options, expected):
    profile = ApplicantProfile(demographics=configured)
    assert resolve(label, profile, options, voluntary=True).value == expected
    assert not resolve(label, profile, options, voluntary=False).known


def test_no_ethnicity_or_disability_history_inference():
    profile = ApplicantProfile(demographics={'race':'black','disability':'not_disabled'})
    assert not resolve('Race', profile, ['Black (Not Hispanic or Latino)'], True).known
    assert not resolve('Disability status', profile, ['No, I do not have a disability and have never had one'], True).known


@pytest.mark.parametrize('question', ['Will you require sponsorship?', 'Are you a US citizen?', 'Years of Altium experience?', 'I certify that I have no conflicts of interest', 'Are you willing to relocate?'])
def test_unknown_consequential_answers_never_guessed(question):
    assert not resolve(question, ApplicantProfile()).known


def test_location_substring_is_not_relocation_answer():
    profile = ApplicantProfile(current_location='Minneapolis', confirmed_answers={'Are you willing to relocate?': False})
    assert resolve('Current location', profile).value == 'Minneapolis'
    assert not resolve('Preferred relocation location', profile).known
    assert resolve('Are you willing to relocate?', profile).value is False


def ready():
    j = job(classification='AUTO_APPLY', resume_match={'confident':True})
    outcome = FillOutcome(j,j.url,resume_uploaded=True,submit_available=True,inventory_complete=True)
    profile = ApplicantProfile(available_start_date='2027-06-01')
    return j, outcome, profile


@pytest.mark.parametrize('mode', list(Mode))
def test_high_value_never_automatically_submits(mode):
    j, outcome, profile = ready()
    j.classification = 'HIGH_VALUE_REVIEW'
    assert not decide(j,outcome,mode,profile).may_submit


@pytest.mark.parametrize('change', [
    {'unknown_questions':['legal certification']}, {'blockers':['CAPTCHA']}, {'inventory_complete':False},
    {'resume_uploaded':False}, {'submit_available':False}, {'unfilled_required':['Email']},
])
def test_submission_requires_all_gates(change):
    j, outcome, profile = ready()
    for k,v in change.items(): setattr(outcome,k,v)
    for mode in [Mode.AUTO_SAFE,Mode.AUTO_ELIGIBLE]:
        assert not decide(j,outcome,mode,profile).may_submit


def test_auto_safe_known_form_passes():
    j,outcome,profile=ready()
    assert decide(j,outcome,Mode.AUTO_SAFE,profile).may_submit
    assert not decide(j,outcome,Mode.PREPARE_ONLY,profile).may_submit
    assert not decide(j,outcome,Mode.AUTO_SAFE,profile,'duplicate').may_submit


def test_tracking_url_variants_same_requisition_and_legacy_records():
    original=job(url='https://jobs.lever.co/example/abc?utm_source=feed')
    state={original.job_id:{'status':'submitted','company':original.company,'title':original.title,'url':original.url}}
    duplicate=job(url='https://jobs.lever.co/example/abc/apply?utm_source=email')
    assert applog.duplicate(duplicate,state)
    different=job(url='https://jobs.lever.co/example/def')
    assert applog.duplicate(different,state) is None


def test_possible_duplicate_title_without_requisition_pauses():
    original=job(url='https://example.com/career/a')
    state={}
    applog.record(state,original,'submitted')
    assert applog.duplicate(job(url='https://example.com/career/b'),state)


def test_uncertain_submission_never_retried():
    original=job()
    for status in ['submitting','submission_unknown']:
        state={}
        applog.record(state,original,status)
        assert applog.duplicate(original,state,retry_failed=True)


def test_confirmation_recorded_once_and_not_downgraded():
    state={};j=job()
    applog.record(state,j,'submitting')
    applog.record(state,j,'submitted')
    applog.record(state,j,'submitted')
    applog.record(state,j,'failed')
    assert state[j.job_id]['status']=='submitted'
    assert sum(a['status']=='submitted' for a in state[j.job_id]['attempts'])==1


def test_corrupt_tracker_fails_closed(tmp_path,monkeypatch):
    path=tmp_path/'applications.json';path.write_text('{broken')
    monkeypatch.setattr(applog,'APPLOG_PATH',path)
    with pytest.raises(ValueError): applog.load()
    assert path.read_text()=='{broken'


def test_migration_preserves_legacy_state(tmp_path,monkeypatch):
    path=tmp_path/'applications.json';old={'abc':{'status':'submitted','note':'historical'}}
    path.write_text(json.dumps(old))
    monkeypatch.setattr(applog,'APPLOG_PATH',path)
    monkeypatch.setattr(applog,'APPLOG_CSV',tmp_path/'applications.csv')
    state=applog.load();applog.record(state,job(),'prepared');applog.save(state)
    assert applog.load()['abc']==old['abc']
    assert json.loads(path.with_suffix('.legacy.bak').read_text())==old


def test_ats_hostname_cannot_be_spoofed():
    assert detect_ats('https://greenhouse.io.evil.example/jobs/123') is None
    assert detect_ats('https://evil.example/greenhouse.io/jobs/123') is None
    assert detect_ats('https://job-boards.greenhouse.io/x/jobs/123')=='greenhouse'


def test_direct_postings_win_over_community_duplicates():
    community=job(source='githublist:feed',description='')
    direct=job(source='lever:Example')
    assert prefer_direct([community,direct])==[direct]


def test_lever_query_stays_after_apply_path():
    from src.apply.lever import LeverApplicator
    j=job(url='https://jobs.lever.co/example/abc?source=feed')
    assert LeverApplicator().application_url(j)=='https://jobs.lever.co/example/abc/apply?source=feed'


def test_range_lower_bound_not_overlapped_as_single_year_count():
    from src.smart_filters import assess_entry_level
    result=assess_entry_level(job(description="Bachelor's degree and 1-5 years of experience."),{})
    assert result.bachelor_min_years==1


def test_failed_email_preserves_seen_state(monkeypatch,tmp_path):
    from src import main,config
    from src.dedup import load_state
    j=job()
    path=tmp_path/'seen.json';path.write_text('{}')
    monkeypatch.setattr(main,'collect_jobs',lambda **_: [j])
    monkeypatch.setattr(config,'state_path',lambda:path)
    monkeypatch.setattr(main.email_notify,'send_email',lambda *_:False)
    assert main.run(False,True,False,None)==1
    assert load_state(path)=={}


def test_seen_state_url_variant_preserves_legacy_history():
    from src.dedup import new_jobs
    j=job(url='https://jobs.lever.co/example/abc?utm_source=old')
    state={j.job_id:{'company':j.company,'title':j.title,'url':j.url,'first_seen':'2026-01-01'}}
    assert new_jobs([job(url='https://jobs.lever.co/example/abc/apply?utm_source=new')],state)==[]


def test_preferred_experience_does_not_inherit_neighboring_required_clause():
    from src.smart_filters import assess_entry_level
    j=job(description="Bachelor's degree and 1-2 years of experience required. Five-axis PCB testing. 5 years of experience preferred.")
    assert assess_entry_level(j,{}).eligible


def test_suspicious_url_is_rejected():
    assert evaluate(job(url='javascript:alert(1)')).classification=='HARD_NO'
