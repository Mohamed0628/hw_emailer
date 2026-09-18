"""No live network: bounded Workday failures and lossless partial discovery."""
from unittest.mock import Mock

import pytest
import requests

from src.models import Job
from src.parallel_collect import collect_sources
from src.sources.base import Source
from src.sources.workday import WorkdaySource, REQUEST_TIMEOUT
from src.sources import workday


def response(data=None, status=200):
    return Mock(status_code=status, json=Mock(return_value=data))


def posting(n=1):
    return {'title': 'RF Hardware Engineer I', 'externalPath': f'/job/Engineer_R{n}', 'locationsText': 'Minneapolis, MN'}


def listing(*postings, total=None):
    return response({'jobPostings': list(postings), 'total': len(postings) if total is None else total})


def source(**kwargs):
    return WorkdaySource('Example', 'example', 1, 'External', search_texts=['rf', 'hardware', 'electrical'], **kwargs)


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    sleeper = Mock()
    monkeypatch.setattr(workday.time, 'sleep', sleeper)
    return sleeper


@pytest.mark.parametrize('status', [400, 401, 403, 404, 422])
def test_deterministic_4xx_stops_source_without_retries_or_more_queries(status, no_real_sleep, caplog):
    session = Mock()
    session.request.return_value = response(status=status)
    assert source().fetch(session) == []
    assert session.request.call_count == 1
    no_real_sleep.assert_not_called()
    assert f'HTTP {status}' in caplog.text
    assert 'workday:Example' in caplog.text


@pytest.mark.parametrize('failure', [requests.Timeout(), requests.ConnectionError(), response(status=503), response(status=429)])
def test_transient_failure_has_one_bounded_retry(failure, no_real_sleep):
    session = Mock()
    session.request.side_effect = [failure, failure]
    assert source().fetch(session) == []
    assert session.request.call_count == 2
    assert no_real_sleep.call_args.args == (0.5,)
    assert all(c.kwargs['timeout'] == REQUEST_TIMEOUT for c in session.request.call_args_list)


def test_transient_recovery_and_healthy_queries_preserved():
    session = Mock()
    session.request.side_effect = [requests.Timeout(), listing(posting()), listing(posting(), posting(2)), listing(posting(3))]
    jobs = source().fetch(session)
    assert len(jobs) == 3
    assert len({j.url for j in jobs}) == 3
    assert all(j.ats == 'workday' for j in jobs)
    assert [c.kwargs['json']['searchText'] for c in session.request.call_args_list] == ['rf', 'rf', 'hardware', 'electrical']


def test_later_page_failure_preserves_jobs_and_still_fetches_details():
    session = Mock()
    session.request.side_effect = [listing(posting(), total=40), response(status=422),
                                   response({'jobPostingInfo': {'jobReqId': 'R1', 'jobDescription': '<p>RF antenna HFSS</p>'}})]
    jobs = source(fetch_details=True).fetch(session)
    assert len(jobs) == 1
    assert jobs[0].description == 'RF antenna HFSS'
    assert jobs[0].requisition_id == 'R1'
    assert [c.args[0] for c in session.request.call_args_list] == ['POST', 'POST', 'GET']


def test_missing_individual_detail_does_not_hide_other_jobs():
    session = Mock()
    session.request.side_effect = [listing(posting(), posting(2)), listing(), listing(), response(status=404),
                                   response({'jobPostingInfo': {'jobDescription': 'RF PCB antennas', 'jobReqId': 'R2'}})]
    jobs = source(fetch_details=True).fetch(session)
    assert len(jobs) == 2
    assert not jobs[0].description
    assert jobs[1].description == 'RF PCB antennas'
    assert session.request.call_count == 5


def test_forbidden_details_stop_without_losing_listing_records():
    session = Mock()
    session.request.side_effect = [listing(posting(), posting(2), posting(3)), listing(), listing(), response(status=403)]
    jobs = source(fetch_details=True).fetch(session)
    assert len(jobs) == 3
    assert session.request.call_count == 4


def test_repeated_transient_detail_failures_open_circuit(caplog):
    session = Mock()
    session.request.side_effect = [listing(*(posting(n) for n in range(5))), listing(), listing()] + [requests.Timeout()] * 6
    jobs = source(fetch_details=True).fetch(session)
    assert len(jobs) == 5
    assert session.request.call_count == 9  # three queries, at most two tries on three details
    assert 'stopping failing detail requests' in caplog.text


def test_malformed_later_page_does_not_discard_successes():
    session = Mock()
    session.request.side_effect = [listing(posting(), total=40), response({'jobPostings': 'bad'})]
    assert len(source().fetch(session)) == 1


def test_failure_isolated_from_other_employers(monkeypatch):
    from src import parallel_collect
    class Healthy(Source):
        name = 'greenhouse:Healthy'
        def fetch(self, session):
            return [Job(company='Healthy', title='Hardware Engineer I', url='https://boards.greenhouse.io/healthy/jobs/1')]
    broken = source()
    valid = WorkdaySource('Valid Workday', 'valid', 1, 'External')
    def make_session():
        session = Mock()
        def request(method, url, **kwargs):
            if 'example.wd1' in url:
                raise requests.Timeout()
            return listing(posting())
        session.request.side_effect = request
        return session
    monkeypatch.setattr(parallel_collect, 'make_session', make_session)
    jobs = collect_sources([broken, Healthy(), valid])
    assert {j.company for j in jobs} == {'Healthy', 'Valid Workday'}


def test_duplicate_company_endpoints_merge_searches_without_disabling_details(monkeypatch):
    from src.sources import registry
    monkeypatch.setattr(registry.github_lists, 'build_sources', lambda: [])
    monkeypatch.setattr(registry, 'workday_search_terms', lambda _: [])
    monkeypatch.setattr(registry.config, '_load_yaml', lambda _: {})
    monkeypatch.setattr(registry.config, 'direct_companies', lambda: {})
    monkeypatch.setattr(registry.config, 'companies', lambda: {'workday': [
        {'company': 'Example', 'tenant': 'example', 'site': 'External', 'search_texts': ['rf'], 'fetch_details': False},
        {'company': 'Example', 'tenant': 'example', 'site': 'External', 'search_texts': ['hardware', 'rf'], 'fetch_details': True},
        {'company': 'Other', 'tenant': 'other', 'site': 'External', 'search_texts': ['electrical']},
    ]})
    sources = registry.build_all_sources()
    assert len(sources) == 2
    assert sources[0].search_texts == ['rf', 'hardware']
    assert sources[0].fetch_details is True


def test_malformed_json_does_not_retry(no_real_sleep):
    session = Mock()
    session.request.return_value = response()
    session.request.return_value.json.side_effect = ValueError('invalid JSON')
    assert source().fetch(session) == []
    assert session.request.call_count == 1
    no_real_sleep.assert_not_called()
