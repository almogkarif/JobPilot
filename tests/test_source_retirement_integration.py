import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.config import settings
from app.models import Application, Job, JobSourceIdentity, Source
from app.services import scanner
from app.services.catalog_freshness import expire_unverified_jobs
from app.services.scan_runtime import scheduled_scan_due
from test_unified_catalog_local import preview_db, postgres_cluster  # noqa: F401


def _utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


@pytest.mark.parametrize('targeted', [False, True])
def test_legacy_scan_excludes_reviewed_source_even_when_enabled_or_targeted(preview_db, monkeypatch, targeted):
    monkeypatch.setattr(settings, 'unified_catalog_preview', False)
    source = preview_db.scalar(select(Source))
    source.kind, source.identifier = 'greenhouse', 'armissecurity'
    source.career_track = 'computer_science'
    source.enabled = True
    source.last_error = 'Previously unavailable'
    source.metadata_json = json.dumps({'enabled_override': True})
    job = Job(source_id=source.id, external_id='retained', title='Engineer', company='Armis',
              career_track='computer_science', is_active=True,
              apply_url='https://example.com/jobs/retained')
    preview_db.add(job)
    preview_db.flush()
    application = Application(job_id=job.id, status='submitted')
    preview_db.add(application)
    preview_db.commit()
    source_id, job_id, application_id = source.id, job.id, application.id
    calls = []

    class Collector:
        async def collect(self, *args):
            calls.append(args)
            raise AssertionError('Excluded source reached its network collector')

    monkeypatch.setitem(scanner.COLLECTORS, 'greenhouse', Collector)
    result = asyncio.run(scanner.scan_all_sources(
        preview_db, career_track='computer_science', catalog_only=True,
        source_ids={source_id} if targeted else None,
    ))
    preview_db.expire_all()
    assert calls == []
    assert result['status'] == 'no_sources' and result['sources'] == 0
    assert preview_db.get(Job, job_id).is_active
    assert preview_db.get(Application, application_id).status == 'submitted'
    retained = preview_db.get(Source, source_id)
    assert retained.enabled and retained.last_scanned_at is None
    assert retained.last_error == 'Previously unavailable'
    assert json.loads(retained.metadata_json) == {'enabled_override': True}


@pytest.mark.parametrize('unified', [False, True])
def test_scheduler_ignores_recent_timestamp_from_reviewed_source(preview_db, monkeypatch, unified):
    monkeypatch.setattr(settings, 'unified_catalog_preview', unified)
    monkeypatch.setattr(settings, 'timezone', 'UTC')
    now = datetime(2026, 9, 27, 12, 30, tzinfo=timezone.utc)
    available = preview_db.scalar(select(Source))
    available.career_track = 'shared' if unified else 'computer_science'
    available.last_scanned_at = now.replace(hour=11, minute=55)
    retired = Source(name='Reviewed unavailable board', kind='greenhouse', identifier='ARMISSECURITY/',
                     career_track=available.career_track, enabled=True,
                     last_scanned_at=now.replace(minute=10))
    preview_db.add(retired)
    preview_db.commit()

    due, scheduled, latest = scheduled_scan_due(preview_db, 'computer_science', now_local=now)
    assert due
    assert scheduled == now.replace(minute=0)
    assert latest == now.replace(hour=11, minute=55)

    # A real available board scanned this hour still suppresses the duplicate run.
    available.last_scanned_at = now.replace(minute=5)
    preview_db.commit()
    due, _, latest = scheduled_scan_due(preview_db, 'computer_science', now_local=now)
    assert not due and latest == now.replace(minute=5)


def test_retired_jobs_expire_at_fourteen_days_without_deleting_application_history(preview_db):
    now = datetime(2026, 9, 27, 12, tzinfo=timezone.utc)
    retired = preview_db.scalar(select(Source))
    retired.kind, retired.identifier = 'greenhouse', 'armissecurity'
    retired.enabled = True
    retired.metadata_json = json.dumps({'enabled_override': True})
    replacement = Source(name='Current employer board', kind='greenhouse', identifier='current-board',
                         career_track='shared', enabled=True)
    preview_db.add(replacement)
    preview_db.flush()

    jobs = []
    identities = []
    for key, last_seen in (
        ('boundary', now - timedelta(days=14)),
        ('fresh', now - timedelta(days=14) + timedelta(seconds=1)),
        ('verified-elsewhere', now - timedelta(days=30)),
    ):
        job = Job(source_id=retired.id, external_id=key, canonical_key='retirement-' + key,
                  career_track='shared', title='Software Engineer', company='Armis', is_active=True,
                  apply_url='https://example.com/jobs/' + key)
        preview_db.add(job)
        preview_db.flush()
        identity = JobSourceIdentity(source_id=retired.id, external_id=key, job_id=job.id,
                                     is_active=True, last_seen_at=last_seen)
        preview_db.add(identity)
        jobs.append(job)
        identities.append(identity)
    preview_db.add(JobSourceIdentity(source_id=replacement.id, external_id='current-id', job_id=jobs[2].id,
                                    is_active=True, last_seen_at=now))
    application = Application(job_id=jobs[0].id, status='submitted',
                              submitted_at=now - timedelta(days=20), notes='Retain submission history')
    preview_db.add(application)
    preview_db.commit()
    job_ids = [job.id for job in jobs]
    identity_keys = [(identity.source_id, identity.external_id) for identity in identities]
    source_id, application_id = retired.id, application.id

    assert expire_unverified_jobs(preview_db, now=now - timedelta(seconds=1)) == 0
    preview_db.commit()
    preview_db.expire_all()
    assert all(preview_db.get(Job, job_id).is_active for job_id in job_ids)

    assert expire_unverified_jobs(preview_db, now=now) == 1
    preview_db.commit()
    preview_db.expire_all()
    assert [preview_db.get(Job, job_id).is_active for job_id in job_ids] == [False, True, True]
    assert [preview_db.get(JobSourceIdentity, key).is_active for key in identity_keys] == [False, True, False]
    retained_application = preview_db.get(Application, application_id)
    assert retained_application.job_id == job_ids[0]
    assert retained_application.status == 'submitted'
    assert retained_application.notes == 'Retain submission history'
    assert _utc(retained_application.submitted_at) == now - timedelta(days=20)
    assert _utc(preview_db.get(Job, job_ids[0]).removed_at) == now
    assert preview_db.get(Source, source_id).enabled
    assert json.loads(preview_db.get(Source, source_id).metadata_json) == {'enabled_override': True}
    assert expire_unverified_jobs(preview_db, now=now) == 0
