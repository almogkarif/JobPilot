from __future__ import annotations

import asyncio
import json

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.collectors import expansion_ats
from app.collectors.base import PreserveExistingJobs
from app.collectors.official import OfficialCareersCollector
from app.database import Base
from app.models import Source
from app.services.location_filter import is_israel_location
from app.services.source_catalog import recommended_sources_for_track
from app.services.unified_catalog import install_unified_sources
from app.utils import dumps, loads

DESCRIPTION = ('Develop Python software and RF automation, work with engineering and operations teams. '
               'Design reliable services and test production systems. Responsibilities include architecture '
               'and data analysis. Requirements: BSc in Computer Science and two years of Python experience.')
UUID = '46f9829b-92e2-46da-b8d1-18cde1f11d7a'
ADDITIONS = {'cognyte', 'cellebrite', 'd-fend-solutions', 'scylladb', 'classiq', 'oligo-security', 'quantum-machines'}


def lever_row(**updates):
    row = {'id': UUID, 'text': 'Software Engineer', 'country': 'IL',
           'categories': {'location': 'Raanana, Center District'}, 'workplaceType': 'hybrid',
           'description': DESCRIPTION, 'lists': [{'text': 'Requirements', 'content': 'Experience with Python and SQL.'}],
           'additional': 'Work with a collaborative team.',
           'hostedUrl': f'https://jobs.lever.co/d-fendsolutions/{UUID}'}
    return row | updates


def test_new_lever_route_reads_full_requirements_and_real_country(monkeypatch):
    foreign = lever_row(id='77f9829b-92e2-46da-b8d1-18cde1f11d7a', country='GB',
                        categories={'location': 'London'}, description=DESCRIPTION + ' Headquarters in Israel.')
    foreign['hostedUrl'] = 'https://jobs.lever.co/d-fendsolutions/' + foreign['id']
    calls = []
    async def get(url):
        calls.append(url)
        return json.dumps([lever_row(), foreign])
    monkeypatch.setattr(expansion_ats, 'bounded_public_get', get)
    jobs = asyncio.run(OfficialCareersCollector().collect('d-fend-solutions', 'D-Fend Solutions'))
    assert calls == ['https://api.lever.co/v0/postings/d-fendsolutions?mode=json']
    assert len(jobs) == 2 and jobs.complete is False
    assert jobs[0].external_id == UUID
    assert jobs[0].workplace == 'hybrid'
    assert jobs[0].source_url == lever_row()['hostedUrl']
    assert 'Requirements\nExperience with Python and SQL.' in jobs[0].description
    assert 'Work with a collaborative team.' in jobs[0].description
    assert is_israel_location(jobs[0].location)
    assert not is_israel_location(jobs[1].location)


@pytest.mark.parametrize('updates', [
    {'hostedUrl': f'https://jobs.lever.co/different-employer/{UUID}'},
    {'hostedUrl': f'https://jobs.lever.co/d-fendsolutions/{UUID}/apply'},
    {'id': 'made-up-id'}, {'description': 'Apply now', 'lists': [], 'additional': ''},
    {'categories': []}, {'lists': 'Requirements are missing'}, {'lists': [None]},
    {'lists': [{'text': 'Requirements', 'content': 'Python'}] * 31},
    {'description': DESCRIPTION * 100 + ' Advanced degree is required.'},
])
def test_unverified_or_truncated_lever_rows_never_become_jobs(updates):
    with pytest.raises(PreserveExistingJobs):
        expansion_ats.parse_expansion_feed('d-fend-solutions', json.dumps([lever_row(**updates)]), 'D-Fend Solutions')


@pytest.mark.parametrize('payload', [[], {}, [lever_row(), lever_row()], [lever_row()] * 201])
def test_lever_empty_malformed_duplicate_and_oversize_lists_preserve_existing(payload):
    with pytest.raises(PreserveExistingJobs):
        expansion_ats.parse_expansion_feed('d-fend-solutions', json.dumps(payload), 'D-Fend Solutions')


@pytest.mark.parametrize('identifier', sorted(ADDITIONS - {'d-fend-solutions'}))
def test_new_comeet_boards_keep_exact_ids_requirements_and_partial_semantics(identifier):
    slug, uid, token = expansion_ats.COMEET_ROUTES[identifier]
    row = {'uid': 'AB.123', 'name': 'Data Analyst', 'location': {'name': 'Herzliya', 'country': 'IL'},
           'url_comeet_hosted_page': f'https://www.comeet.com/jobs/{slug}/{uid}/data-analyst/AB.123',
           'details': [{'name': 'Description', 'value': DESCRIPTION},
                       {'name': 'Requirements', 'value': 'BSc in Industrial Engineering is required.'}]}
    def document(value):
        return json.dumps(value) if token else '<script>var COMPANY_POSITIONS_DATA = ' + json.dumps(value) + ';</script>'
    jobs = expansion_ats.parse_expansion_feed(identifier, document([row]), identifier)
    assert len(jobs) == 1 and jobs.complete is False
    assert jobs[0].external_id == 'AB.123'
    assert 'BSc in Industrial Engineering is required.' in jobs[0].description
    assert is_israel_location(jobs[0].location)
    for invalid in [
        row | {'url_comeet_hosted_page': row['url_comeet_hosted_page'].replace(f'/{slug}/', '/wrong-board/')},
        row | {'details': [{'value': DESCRIPTION * 100}]},
        row | {'details': [{'value': DESCRIPTION}] * 31},
    ]:
        with pytest.raises(PreserveExistingJobs):
            expansion_ats.parse_expansion_feed(identifier, document([invalid]), identifier)


def test_new_boards_install_once_and_respect_admin_disable():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    try:
        for track in ('computer_science', 'industrial_engineering', 'electrical_engineering'):
            rows = recommended_sources_for_track(track)
            assert ADDITIONS <= {r['identifier'] for r in rows}
        with Session(engine) as db:
            install_unified_sources(db)
            sources = db.scalars(select(Source).where(Source.identifier.in_(ADDITIONS))).all()
            assert len(sources) == len(ADDITIONS)
            assert all(s.enabled and s.career_track == 'shared' for s in sources)
            first = sources[0]
            first.enabled = False
            first.metadata_json = dumps(loads(first.metadata_json, {}) | {'enabled_override': False})
            db.commit()
            assert install_unified_sources(db) == 0
            assert not db.get(Source, first.id).enabled
            assert len(db.scalars(select(Source).where(Source.identifier.in_(ADDITIONS))).all()) == len(ADDITIONS)
    finally:
        engine.dispose()
