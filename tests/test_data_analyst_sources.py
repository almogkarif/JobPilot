import asyncio

import httpx
import pytest
from bs4 import BeautifulSoup
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.collectors.official import OfficialCareersCollector, _extract_gstat_job_rows, PRESETS
from app.collectors.base import PreserveExistingJobs
from app.database import Base
from app.models import Source
from app.services.source_catalog import install_recommended_sources, recommended_sources_for_track
from app.services.source_quality import SourceDataQualityError, validate_source_payload
from app.services.matching import track_job_relevance


def card(number, *, form_id=None, target=None):
    return f'''<div class="row"><div class="job-title" data-id="{number}">Data Analyst - JB-{number}</div>
    <div class="job-data" id="job-data-{number}"><div class="job-inner-col text-col">
    Junior Data Analyst team {number}: SQL, Python, Power BI, business analysis and reporting.
    Work with business stakeholders to analyze performance and design dashboards.
    Support operational planning, data quality, and marketing analysis.</div>
    <div class="job-inner-col text-col">Requirements: SQL and Excel. Industrial engineering degree.</div>
    <div class="share-div"><a href="https://www.linkedin.com/shareArticle?url={target or f'https://g-stat.com/jobs/analyst-{number}/'}">Share</a></div>
    <form><input name="job" value="{form_id if form_id is not None else number}" /></form></div></div>'''


def mock_board(monkeypatch, html):
    async def get(self, url, **kwargs):
        assert url == PRESETS['g-stat']['url']
        return httpx.Response(200, text=html, request=httpx.Request('GET', url))
    monkeypatch.setattr(httpx.AsyncClient, 'get', get)


def test_gstat_full_collection_keeps_real_ids_descriptions_and_israel_scope(monkeypatch):
    mock_board(monkeypatch, '<div class="jobs_accordion">' + ''.join(card(i) for i in range(30)) + '</div>')
    jobs = asyncio.run(OfficialCareersCollector().collect('g-stat'))
    assert len(jobs) == 30
    assert jobs.complete is False  # A capped/single page must never close missing historical jobs.
    assert jobs[0].external_id == '0'
    assert jobs[0].apply_url == 'https://g-stat.com/jobs/analyst-0/'
    assert 'Requirements: SQL and Excel' in jobs[0].description
    assert 'Share' not in jobs[0].description
    assert jobs[0].location == 'Israel'
    assert track_job_relevance(jobs[0], 'industrial_engineering')[0]
    validate_source_payload('G-STAT', jobs)
    for job in jobs:
        job.apply_url = job.apply_url.replace('g-stat.com', 'example.com')
    with pytest.raises(SourceDataQualityError, match='generic Israel'):
        validate_source_payload('Untrusted links', jobs)
    for job in jobs:
        job.apply_url = job.apply_url.replace('example.com', 'g-stat.com')
    for job in jobs:
        job.metadata.clear()
    with pytest.raises(SourceDataQualityError, match='generic Israel'):
        validate_source_payload('Unverified board', jobs)


def test_gstat_parser_rejects_mismatched_forms_external_links_and_duplicates():
    html = '<div class="jobs_accordion">' + card(1) + card(1) + card(2, form_id=9) + card(3, target='https://example.com/jobs/3/') + '</div>'
    rows = _extract_gstat_job_rows(BeautifulSoup(html, 'html.parser'))
    assert len(rows) == 1
    assert rows[0]['href'] == 'https://g-stat.com/jobs/analyst-1/'


def test_gstat_missing_markup_preserves_existing_jobs(monkeypatch):
    mock_board(monkeypatch, '<html><h1>Careers</h1><p>Page unavailable</p></html>')
    with pytest.raises(PreserveExistingJobs):
        asyncio.run(OfficialCareersCollector().collect('g-stat'))


def test_new_analyst_catalog_is_track_scoped_idempotent_and_respects_disabled_sources():
    identifiers = {'g-stat', 'melio', 'autods', 'nift'}
    assert not identifiers.intersection(row['identifier'] for row in recommended_sources_for_track('electrical_engineering'))
    # Melio already exists in CS; preserve that independent source.
    assert not {'g-stat', 'autods', 'nift'}.intersection(row['identifier'] for row in recommended_sources_for_track('computer_science'))
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        install_recommended_sources(db, 'industrial_engineering')
        rows = db.scalars(select(Source).where(Source.identifier.in_(identifiers))).all()
        assert len(rows) == 4
        assert all(row.enabled and row.career_track == 'industrial_engineering' for row in rows)
        rows[0].enabled = False
        db.commit()
        assert install_recommended_sources(db, 'industrial_engineering') == 0
        db.refresh(rows[0])
        assert not rows[0].enabled
        assert len(db.scalars(select(Source).where(Source.identifier.in_(identifiers))).all()) == 4
    engine.dispose()
