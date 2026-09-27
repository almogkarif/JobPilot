import asyncio
import json

from sqlalchemy import select

from app.models import Application, Job, Source
from app.services import scanner, source_catalog, source_retirements, unified_catalog
from test_unified_catalog_local import preview_db, postgres_cluster  # noqa: F401


def test_reviewed_retirement_skips_network_and_preserves_history(preview_db, monkeypatch):
    from datetime import datetime, timezone
    from app.models import JobSourceIdentity
    source = preview_db.scalar(select(Source))
    source.kind, source.identifier = 'greenhouse', 'armissecurity'
    source.enabled = True
    source.metadata_json = json.dumps({'enabled_override': True})
    job = Job(source_id=source.id, external_id='old', title='Engineer', career_track='shared',
              canonical_key='retired-history', is_active=True, company='Armis',
              apply_url='https://example.com/jobs/old')
    preview_db.add(job); preview_db.flush()
    application = Application(job_id=job.id, status='submitted')
    preview_db.add(application)
    preview_db.add(JobSourceIdentity(source_id=source.id, external_id='old', job_id=job.id,
                                    is_active=True, last_seen_at=datetime.now(timezone.utc)))
    preview_db.commit()
    ids = source.id, job.id, application.id
    class NeverCollect:
        async def collect(self, *args): raise AssertionError('Retired source must never make a network request')
    monkeypatch.setitem(scanner.COLLECTORS, 'greenhouse', NeverCollect)
    assert unified_catalog.unified_sources(preview_db) == []
    result = asyncio.run(scanner.scan_all_sources(preview_db, catalog_only=True))
    assert result['sources'] == 0
    assert preview_db.get(Job, ids[1]).is_active
    assert preview_db.get(Application, ids[2]).status == 'submitted'
    assert preview_db.get(Source, ids[0]).enabled  # No destructive repair or override mutation.
    monkeypatch.delitem(source_retirements.RETIRED_SOURCES, ('greenhouse', 'armissecurity'))
    assert [s.id for s in unified_catalog.unified_sources(preview_db)] == [ids[0]]


def test_recommended_install_does_not_add_or_resurrect_retired_sources(preview_db, monkeypatch):
    before = len(preview_db.scalars(select(Source)).all())
    definitions = (dict(name='Retired Armis', kind='greenhouse', identifier='armissecurity', company_name='Armis'),
                   dict(name='Retired CyberArk', kind='smartrecruiters', identifier='Cyberark1', company_name='CyberArk'))
    monkeypatch.setattr(source_catalog, 'RECOMMENDED_SOURCES_BY_TRACK', {'computer_science': definitions})
    assert unified_catalog.install_unified_sources(preview_db) == 0
    assert len(preview_db.scalars(select(Source)).all()) == before
    assert source_catalog.recommended_sources_for_track('computer_science') == ()
    assert source_catalog.recommended_source_status(preview_db) == []


def test_exact_board_identity_only():
    assert source_retirements.retirement_reason(' greenhouse ', 'ARMISSECURITY')
    assert source_retirements.retirement_reason('ashby', 'https://career.rafael.co.il/search/')
    assert not source_retirements.retirement_reason('greenhouse', 'armissecurity-new')
    assert not source_retirements.retirement_reason('smartrecruiters', 'ServiceNow')
    assert not source_retirements.retirement_reason('official_careers', 'paloalto')


def test_admin_views_exclude_retired_sources_and_test_button_rejects_them(preview_db, monkeypatch):
    from contextlib import contextmanager
    from fastapi import HTTPException
    import pytest
    from app import main
    from app.models import AppIdentity
    retired = preview_db.scalar(select(Source))
    retired.kind, retired.identifier, retired.name = 'greenhouse', 'armissecurity', 'Retired Armis'
    preview_db.add(Source(name='Available', kind='greenhouse', identifier='available'))
    preview_db.add(AppIdentity(auth_user_id='preview-user'))
    preview_db.commit()
    @contextmanager
    def tenant(_user):
        yield preview_db
    monkeypatch.setattr(main, 'user_session', tenant)
    monkeypatch.setattr(main, '_require_developer', lambda _request: None)
    monkeypatch.setattr(main, '_active_source_or_404', lambda *_args: retired)
    detail = main.developer_user_detail('preview-user', None, preview_db)
    assert detail['counts']['sources'] == 1
    section = main.developer_user_section('preview-user', 'sources', None, preview_db)
    assert [row['primary'] for row in section['items']] == ['Available']
    assert [row['name'] for row in main.list_sources(preview_db)] == ['Available']
    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.developer_test_source(retired.id, None, preview_db))
    assert exc.value.status_code == 400
