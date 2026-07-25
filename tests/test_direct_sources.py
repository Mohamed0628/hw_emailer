"""Tests for direct Minnesota career-board adapters."""

from __future__ import annotations

import json

from src import config
from src.sources import direct
from src.sources.direct import (
    ADPSource,
    CareerPageSource,
    JazzHRSource,
    PaylocitySource,
    UKGProSource,
    WordPressJobsSource,
)


class DummySession:
    pass


def test_jazzhr_extracts_detail_json_ld(monkeypatch):
    board = """
    <div class='job'>
      <h3>Electrical Engineer I</h3>
      <p>Minneapolis, MN</p>
      <a href='/apply/ABC123/electrical-engineer-i'>Apply Now</a>
    </div>
    """
    detail_html = """
    <script type='application/ld+json'>
    {
      "@type": "JobPosting",
      "title": "Electrical Engineer I",
      "description": "Bachelor's degree and 0-2 years of experience.",
      "datePosted": "2026-07-20",
      "employmentType": "FULL_TIME",
      "jobLocation": {"address": {
        "addressLocality": "Minneapolis", "addressRegion": "MN"
      }}
    }
    </script>
    """

    def fake_text(session, url):
        return board if url.endswith("/apply") else detail_html

    monkeypatch.setattr(direct, "request_text", fake_text)
    jobs = JazzHRSource("Enterra Medical", "https://example.applytojob.com/apply").fetch(
        DummySession()
    )

    assert len(jobs) == 1
    assert jobs[0].title == "Electrical Engineer I"
    assert jobs[0].locations == ["Minneapolis, MN"]
    assert "0-2 years" in jobs[0].description
    assert jobs[0].ats == "jazzhr"


def test_paylocity_feed(monkeypatch):
    payload = {
        "jobs": [
            {
                "jobTitle": "Embedded Hardware Engineer",
                "applyUrl": "https://example.com/apply/1",
                "publishedDate": "2026-07-21T12:00:00Z",
                "description": "Design embedded electronics and circuit boards.",
                "requirements": "Bachelor's degree with 0-2 years of experience.",
                "hiringDepartment": "Engineering",
                "jobLocation": {"city": "Eden Prairie", "state": "MN"},
                "jobTypesArray": [{"name": "Full-time"}],
            }
        ]
    }
    monkeypatch.setattr(direct, "request_json", lambda *args, **kwargs: payload)

    jobs = PaylocitySource("Beacon EmbeddedWorks", "board-guid").fetch(DummySession())

    assert len(jobs) == 1
    assert jobs[0].title == "Embedded Hardware Engineer"
    assert jobs[0].locations == ["Eden Prairie, MN"]
    assert "circuit boards" in jobs[0].description
    assert jobs[0].department == "Engineering"
    assert jobs[0].ats == "paylocity"


def test_ukg_public_board_and_detail(monkeypatch):
    list_payload = {
        "totalCount": 1,
        "opportunities": [
            {
                "Id": "42",
                "Title": "Controls Engineer I",
                "PostedDate": "2026-07-22T10:00:00Z",
                "BriefDescription": "Controls role",
            }
        ],
    }
    detail_payload = {
        "Id": "42",
        "Title": "Controls Engineer I",
        "Description": "Bachelor's degree and 0 years of experience required.",
        "PostedDate": "2026-07-22T10:00:00Z",
        "JobCategoryName": "Engineering",
        "FullTime": True,
        "Locations": [
            {
                "Address": {
                    "City": "Plymouth",
                    "State": {"Code": "MN"},
                    "Country": {"Name": "United States"},
                }
            }
        ],
    }
    detail_html = (
        "<script>new US.Opportunity.CandidateOpportunityDetail("
        + json.dumps(detail_payload)
        + ");</script>"
    )
    monkeypatch.setattr(direct, "request_json", lambda *args, **kwargs: list_payload)
    monkeypatch.setattr(direct, "request_text", lambda *args, **kwargs: detail_html)

    jobs = UKGProSource(
        "Banner Engineering",
        "recruiting.ultipro.com",
        "ban1010",
        "board-guid",
    ).fetch(DummySession())

    assert len(jobs) == 1
    assert jobs[0].title == "Controls Engineer I"
    assert jobs[0].locations == ["Plymouth, MN"]
    assert jobs[0].employment_type == "Full-time"
    assert "0 years" in jobs[0].description
    assert jobs[0].ats == "ukg"


def test_adp_list_and_detail(monkeypatch):
    listing = {
        "jobRequisitions": [
            {
                "itemID": "item-1",
                "clientRequisitionID": "EE-101",
                "requisitionTitle": "Test Engineer I",
                "postDate": "2026-07-23T09:00:00Z",
                "requisitionLocations": [
                    {"nameCode": {"shortName": "Maple Grove, MN"}}
                ],
                "workLevelCode": {"shortName": "Full-time"},
                "jobCategoryCode": {"shortName": "Engineering"},
            }
        ]
    }
    detail_payload = {
        "requisitionDescription": (
            "Bachelor's degree in Electrical Engineering and 0-2 years experience."
        )
    }

    def fake_json(session, method, url, **kwargs):
        return detail_payload if url.endswith("/item-1") else listing

    monkeypatch.setattr(direct, "request_json", fake_json)
    jobs = ADPSource("Circuit Check", "company-cid").fetch(DummySession())

    assert len(jobs) == 1
    assert jobs[0].title == "Test Engineer I"
    assert jobs[0].locations == ["Maple Grove, MN"]
    assert "0-2 years" in jobs[0].description
    assert "jobId=EE-101" in jobs[0].url
    assert jobs[0].ats == "adp"


def test_wordpress_jobs_archive(monkeypatch):
    board = """
    <article>
      <h2>R&amp;D Electrical Engineer I</h2>
      <p>Burnsville, MN</p>
      <a href='https://example.com/jobs/rd-electrical-engineer/'>View Job</a>
    </article>
    """
    detail_html = """
    <script type='application/ld+json'>
    {
      "@type": "JobPosting",
      "title": "R&D Electrical Engineer I",
      "description": "Develop medical-device electronics and PCB prototypes.",
      "jobLocation": {"address": {
        "addressLocality": "Burnsville", "addressRegion": "MN"
      }}
    }
    </script>
    """

    def fake_text(session, url):
        return board if url == "https://example.com/careers/" else detail_html

    monkeypatch.setattr(direct, "request_text", fake_text)
    jobs = WordPressJobsSource(
        "Imricor Medical Systems",
        "https://example.com/careers/",
        "/jobs/",
    ).fetch(DummySession())

    assert len(jobs) == 1
    assert jobs[0].title == "R&D Electrical Engineer I"
    assert jobs[0].locations == ["Burnsville, MN"]
    assert "PCB prototypes" in jobs[0].description
    assert jobs[0].ats == "wordpress"


def test_embedded_career_page_links(monkeypatch):
    board = """
    <section class='opening'>
      <h3>Early Career Field Service Engineer</h3>
      <p>Shoreview, MN</p>
      <a href='https://jobs.dayforcehcm.com/en-US/company/jobs/415'>Apply</a>
    </section>
    """
    detail_html = """
    <script type='application/ld+json'>
    {
      "@type": "JobPosting",
      "title": "Early Career Field Service Engineer",
      "description": "Commission robotic and automated systems.",
      "jobLocation": {"address": {
        "addressLocality": "Shoreview", "addressRegion": "MN"
      }}
    }
    </script>
    """

    def fake_text(session, url):
        return board if url == "https://example.com/careers/" else detail_html

    monkeypatch.setattr(direct, "request_text", fake_text)
    jobs = CareerPageSource(
        "PAR Systems",
        "https://example.com/careers/",
        "jobs.dayforcehcm.com",
    ).fetch(DummySession())

    assert len(jobs) == 1
    assert jobs[0].title == "Early Career Field Service Engineer"
    assert jobs[0].locations == ["Shoreview, MN"]
    assert "robotic" in jobs[0].description
    assert jobs[0].ats == "career-page"


def test_ten_minnesota_direct_targets_are_configured():
    config.direct_companies.cache_clear()
    configured = config.direct_companies()
    count = sum(len(entries or []) for entries in configured.values())
    assert count == 10
