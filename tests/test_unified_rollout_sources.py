import asyncio
import json

from sqlalchemy import select

from app.collectors.base import JobCollection, NormalizedJob
from app.models import Job, Source
from app.services import scanner, unified_catalog
from test_unified_catalog_local import preview_db, items, postgres_cluster  # noqa: F401


def test_new_verified_default_is_promoted_once_without_overriding_admin(preview_db, monkeypatch):
    from app.services import source_catalog
    sources = []
    for identifier, metadata in [('automatic', {'validation_status': 'pending_adapter'}),
                                 ('manual', {'validation_status': 'pending_adapter', 'enabled_override': False}),
                                 ('previous', {'validation_status': 'verified'})]:
        row = Source(name=identifier, kind='official_careers', identifier=identifier,
                     enabled=False, metadata_json=json.dumps(metadata))
        preview_db.add(row); sources.append(row)
    preview_db.commit()
    definitions = tuple(dict(name=row.name, kind=row.kind, identifier=row.identifier,
                             company_name='Example', enabled=True, validation_status='verified') for row in sources)
    monkeypatch.setattr(source_catalog, 'RECOMMENDED_SOURCES_BY_TRACK', {'computer_science': definitions})
    assert unified_catalog.install_unified_sources(preview_db) == 0
    assert [row.enabled for row in sources] == [True, False, False]
    assert all(json.loads(row.metadata_json)['validation_status'] == 'verified' for row in sources)
    sources[0].enabled = False; preview_db.commit()
    unified_catalog.install_unified_sources(preview_db)
    assert not sources[0].enabled


def test_scan_budget_defers_without_deactivating_existing_jobs(preview_db, monkeypatch):
    class Collector:
        async def collect(self, *args): return items()
    monkeypatch.setitem(scanner.COLLECTORS, 'greenhouse', Collector)
    first = asyncio.run(scanner.scan_all_sources(preview_db, catalog_only=True))
    assert first['new'] == 3
    monkeypatch.setattr(unified_catalog, 'MAX_SCAN_POSTINGS', 2)
    second = asyncio.run(scanner.scan_all_sources(preview_db, catalog_only=True))
    assert second['deferred_sources'] == 1
    assert len(preview_db.scalars(select(Job).where(Job.is_active.is_(True))).all()) == 3


def test_foreign_jobs_are_counted_but_not_persisted(preview_db, monkeypatch):
    class Collector:
        async def collect(self, *args):
            return JobCollection([*items(), NormalizedJob('foreign', 'Software Engineer', 'Example',
                'New York, United States', 'onsite', items()[0].description, 'https://example.com/jobs/foreign')])
    monkeypatch.setitem(scanner.COLLECTORS, 'greenhouse', Collector)
    result = asyncio.run(scanner.scan_all_sources(preview_db, catalog_only=True))
    assert result['filtered_foreign'] == 1 and result['new'] == 3
    assert preview_db.scalar(select(Job.id).where(Job.external_id == 'foreign')) is None


def test_daily_budget_refusal_preserves_jobs(preview_db, monkeypatch):
    from app.services import catalog_egress
    class Collector:
        async def collect(self, *args): return items()
    monkeypatch.setitem(scanner.COLLECTORS, 'greenhouse', Collector)
    asyncio.run(scanner.scan_all_sources(preview_db, catalog_only=True))
    monkeypatch.setattr(catalog_egress, 'reserve_catalog_egress', lambda _amount: False)
    result = asyncio.run(scanner.scan_all_sources(preview_db, catalog_only=True))
    assert result['deferred_sources'] == 1
    assert 'Daily catalog transfer budget' in result['errors'][0]['error']
    assert len(preview_db.scalars(select(Job).where(Job.is_active.is_(True))).all()) == 3
