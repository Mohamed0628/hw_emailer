"""Matching-only secrets preserve all-five results without carrying private prose."""
import hashlib
import json

import pytest

from src import main
from src.models import ApplicantProfile, Job
from src.resume_catalog import SECRET_NAME, export_catalog, load_catalog
from src.resumes import Resume, match_job


@pytest.fixture
def resumes():
    result = []
    texts = {'rf': 'RF antenna HFSS Smith chart impedance matching S11',
             'power': 'power electronics buck converter MOSFET gate driver current sensing',
             'hardware': 'PCB Altium schematic analog transimpedance amplifier ADC',
             'controls': 'DC motor Quanser Simulink PID control system identification',
             'digital': 'FPGA Verilog RTL Lattice ECP5 RGMII MDIO'}
    for key, text in texts.items():
        full = 'Private Candidate secret-contact@example.test\nProjects\n' + text
        result.append(Resume(key, '/private/resumes/' + key + '.pdf', hashlib.sha256(full.encode()).hexdigest(),
                             full, {'projects': text}))
    return result


def test_round_trip_matches_all_rankings_and_excludes_prose(resumes):
    encoded = export_catalog(resumes)
    assert 'Private Candidate' not in encoded
    assert 'secret-contact' not in encoded
    assert '/private' not in encoded
    reconstructed = load_catalog(encoded)
    assert all(r.text == '' and r.path == '' for r in reconstructed)
    for original in resumes:
        job = Job(company='Example', title='Hardware Engineer I', description=original.text, url='https://example.test/job')
        assert match_job(job, resumes).to_dict() == match_job(job, reconstructed).to_dict()


@pytest.mark.parametrize('change', ['version', 'vocabulary', 'count', 'duplicate_id', 'duplicate_hash', 'unknown_term', 'false_project', 'bad_hash'])
def test_invalid_catalog_fails_without_exposing_secret(resumes, change):
    data = json.loads(export_catalog(resumes))
    if change == 'version': data['version'] = 99
    if change == 'vocabulary': data['vocabulary_sha256'] = 'old'
    if change == 'count': data['resumes'].pop()
    if change == 'duplicate_id': data['resumes'][1]['id'] = data['resumes'][0]['id']
    if change == 'duplicate_hash': data['resumes'][1]['sha256'] = data['resumes'][0]['sha256']
    if change == 'unknown_term': data['resumes'][0]['terms'].append('secret-contact@example.test')
    if change == 'false_project': data['resumes'][0]['project_terms'].append('unknown project')
    if change == 'bad_hash': data['resumes'][0]['sha256'] = 'invalid'
    with pytest.raises(ValueError, match='Invalid or outdated') as error:
        load_catalog(json.dumps(data))
    assert 'secret-contact' not in str(error.value)


def test_discovery_uses_secret_without_pdf_files(resumes, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(SECRET_NAME, export_catalog(resumes))
    monkeypatch.setattr(main, 'load_profile', lambda: ApplicantProfile())
    monkeypatch.setattr(main, 'load_resumes', lambda _: pytest.fail('PDF access should not be needed'))
    job = Job(company='Example', title='RF Hardware Engineer I', locations=['Minneapolis, MN'],
              url='https://example.wd1.myworkdayjobs.com/External/job/Engineer_R1',
              description='RF antenna HFSS Smith chart impedance matching S11 PCB board bring-up. Entry level.')
    monkeypatch.setattr(main, 'collect_jobs', lambda **_: [job])
    monkeypatch.setattr(main.config, 'state_path', lambda: tmp_path / 'seen.json')
    assert main.run(True, False, False, None) == 0
    assert 'Resume: rf' in capsys.readouterr().out
    assert len(job.resume_match['rankings']) == 5
    assert job.application_restriction == 'Application: Manual — Workday'


def test_catalog_cannot_replace_files_in_application_cli(resumes, monkeypatch, capsys):
    from src.apply import cli
    monkeypatch.setenv(SECRET_NAME, export_catalog(resumes))
    monkeypatch.setattr(cli, 'load_profile', lambda _: ApplicantProfile())
    assert cli.main(['--dry-run']) == 1
    assert 'Configure all five reviewed resumes' in capsys.readouterr().out
