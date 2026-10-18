"""Only a verified whole Comeet feed may retire an absent shared vacancy."""
import asyncio

import httpx
import pytest
from sqlalchemy import select

from app.collectors import official
from app.models import Application, Job, JobSourceIdentity, Source
from app.services import scanner
from test_unified_catalog_local import preview_db, items  # noqa: F401
from test_canonical_postgres import postgres_cluster  # noqa: F401


BOARD = 'https://www.comeet.com/jobs/voyantis/86.00B'
CURRENT_UID, OLD_UID = '89.E6C', 'F5.27C'
HTTP_CLIENT = httpx.AsyncClient


def _position(uid):
    slug = 'ai-native-software-engineer' if uid == CURRENT_UID else 'data-analyst'
    return {
        'uid': uid, 'name': 'Backend Software Engineer',
        'location': {'name': 'Tel Aviv, Israel'},
        'url_comeet_hosted_page': f'{BOARD}/{slug}/{uid}',
        'details': [{'name': 'Description', 'value': items()[0].description * 3}],
    }


def _seed(db, monkeypatch):
    source = db.scalar(select(Source))
    source.name, source.company_name = 'Voyantis Careers', 'Voyantis'
    source.kind, source.identifier = 'official_careers', 'voyantis'
    db.commit()
    source_id = source.id
    feed = {'status': 200, 'payload': [_position(CURRENT_UID), _position(OLD_UID)]}
    calls = []

    def response(request):
        calls.append(str(request.url))
        assert request.method == 'GET'
        assert str(request.url) == official.PRESETS['voyantis']['data_url']
        return httpx.Response(feed['status'], json=feed['payload'], request=request)

    monkeypatch.setattr(official.httpx, 'AsyncClient', lambda **kw: HTTP_CLIENT(
        transport=httpx.MockTransport(response), **kw))

    async def keep_feed_rows(rows, _preset, **_kwargs):
        return rows

    monkeypatch.setattr(official, '_hydrate_detail_rows', keep_feed_rows)
    first = asyncio.run(scanner.scan_all_sources(db, source_ids={source_id}, catalog_only=True))
    assert first['new'] == 2
    jobs = {job.external_id: job for job in db.scalars(select(Job))}
    assert set(jobs) == {CURRENT_UID, OLD_UID}
    assert all(job.is_active for job in jobs.values())
    assert calls == [official.PRESETS['voyantis']['data_url']]
    return source_id, jobs, feed, calls


@pytest.mark.parametrize('application_status', ['queued', 'failed', 'submitted'])
def test_verified_comeet_absence_deactivates_job_and_preserves_history(
    preview_db, monkeypatch, application_status,
):
    db = preview_db
    source_id, jobs, feed, calls = _seed(db, monkeypatch)
    old_id, current_id = jobs[OLD_UID].id, jobs[CURRENT_UID].id
    application = Application(job_id=old_id, status=application_status)
    db.add(application)
    db.commit()
    application_id = application.id
    feed['payload'] = [_position(CURRENT_UID)]

    result = asyncio.run(scanner.scan_all_sources(db, source_ids={source_id}, catalog_only=True))
    db.expire_all()

    assert result['removed'] == 1
    assert not db.get(Job, old_id).is_active
    assert db.get(Job, old_id).removed_at is not None
    assert db.get(Job, current_id).is_active
    assert db.get(Application, application_id).job_id == old_id
    assert db.get(Application, application_id).status == application_status
    identity = db.scalar(select(JobSourceIdentity).where(
        JobSourceIdentity.source_id == source_id, JobSourceIdentity.external_id == OLD_UID))
    assert not identity.is_active
    assert len(calls) == 2


def test_verified_comeet_absence_preserves_job_with_another_live_source(preview_db, monkeypatch):
    db = preview_db
    source_id, jobs, feed, calls = _seed(db, monkeypatch)
    old_id = jobs[OLD_UID].id
    other = Source(name='Other board', kind='greenhouse', identifier='other', career_track='shared')
    db.add(other)
    db.flush()
    other_identity = JobSourceIdentity(source_id=other.id, external_id='same-vacancy', job_id=old_id)
    db.add(other_identity)
    db.commit()
    other_identity_key = (other.id, 'same-vacancy')
    feed['payload'] = [_position(CURRENT_UID)]

    result = asyncio.run(scanner.scan_all_sources(db, source_ids={source_id}, catalog_only=True))
    db.expire_all()

    assert result['removed'] == 0
    assert db.get(Job, old_id).is_active
    assert db.get(JobSourceIdentity, other_identity_key).is_active
    voyantis_identity = db.scalar(select(JobSourceIdentity).where(
        JobSourceIdentity.source_id == source_id, JobSourceIdentity.external_id == OLD_UID))
    assert not voyantis_identity.is_active
    assert len(calls) == 2


@pytest.mark.parametrize('failure', ['malformed_row', 'http_403'])
def test_unverified_comeet_feed_cannot_deactivate_an_absent_job(preview_db, monkeypatch, failure):
    db = preview_db
    source_id, jobs, feed, calls = _seed(db, monkeypatch)
    old_id, current_id = jobs[OLD_UID].id, jobs[CURRENT_UID].id
    feed['payload'] = [_position(CURRENT_UID)]
    if failure == 'malformed_row':
        feed['payload'].append({'uid': 'not-a-valid-position', 'name': 'Software Engineer'})
    else:
        # An error body can resemble a successful partial list.
        feed['status'] = 403

    result = asyncio.run(scanner.scan_all_sources(db, source_ids={source_id}, catalog_only=True))
    db.expire_all()

    assert result['removed'] == 0
    assert db.get(Job, old_id).is_active and db.get(Job, current_id).is_active
    old_identity = db.scalar(select(JobSourceIdentity).where(
        JobSourceIdentity.source_id == source_id, JobSourceIdentity.external_id == OLD_UID))
    assert old_identity.is_active
    assert len(calls) == 2
