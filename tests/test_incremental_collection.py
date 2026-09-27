import asyncio
from copy import deepcopy
import json
from hashlib import sha256

import pytest
from sqlalchemy import select

from app.collectors.base import JobCollection, PreserveExistingJobs
from app.collectors.incremental import (
    CHECKPOINT_KEY, MAX_CHECKPOINT_BYTES, clean_checkpoint,
    collect_detail_batch, collection_window, current_window,
)
from app.models import Job, Source
from app.services import scanner, catalog_egress
from app.utils import loads
from test_unified_catalog_local import preview_db, items, postgres_cluster  # noqa: F401


async def identity(value):
    return value


def test_three_runs_resume_after_restart_and_reordered_inventory():
    previous, seen = {}, []
    for values in [list(range(45)), list(reversed(range(45))), list(range(45))]:
        with collection_window(previous) as window:
            batch = asyncio.run(collect_detail_batch(values, identity, key=str, scope='example'))
        assert len(batch) <= 20
        assert not set(batch).intersection(seen)
        seen.extend(batch)
        previous = json.loads(json.dumps(clean_checkpoint(window.checkpoint)))
    assert len(seen) == 45 and window.details_complete
    assert current_window() is None
    with collection_window(previous):
        assert asyncio.run(collect_detail_batch(range(46), identity, key=str, scope='example'))


def test_completed_details_survive_slow_requests_and_cancel_pending_tasks():
    cancelled = []
    async def fetch(value):
        if value == 'fast':
            return value
        try:
            await asyncio.sleep(60)
        finally:
            cancelled.append(value)
    with collection_window(timeout=.08) as window:
        batch = asyncio.run(collect_detail_batch(['slow', 'fast'], fetch, key=str, scope='example'))
    assert batch == ['fast'] and cancelled == ['slow']
    assert window.interrupted and window.batch_pending == 1
    assert window.checkpoint['retry']


def test_new_ids_and_permanent_failure_do_not_starve_forward_progress():
    previous, seen = {}, set()
    async def fetch(value):
        return None if value == 7 else value
    for run in range(7):
        with collection_window(previous) as window:
            seen.update(asyncio.run(collect_detail_batch(range(50 + (run > 0)), fetch, key=str, scope='example')))
        previous = clean_checkpoint(window.checkpoint)
    assert seen == set(range(51)) - {7}
    assert len(previous['retry']) <= 4


def test_permanent_failure_at_end_of_sort_order_does_not_pin_cycle():
    values = list(range(45))
    blocked = max(values, key=lambda value: sha256(str(value).encode()).hexdigest())
    previous, cycles, observed = {}, 0, set()
    async def fetch(value): return None if value == blocked else value
    for _ in range(12):
        with collection_window(previous) as window:
            observed.update(asyncio.run(collect_detail_batch(values, fetch, key=str, scope='example')))
        previous = window.checkpoint
        cycles += window.details_complete
    assert cycles >= 3
    assert observed == set(values) - {blocked}


def test_worker_cancellation_propagates_and_does_not_commit_checkpoint():
    async def run():
        async def slow(_):
            await asyncio.sleep(60)
        with collection_window() as window:
            task = asyncio.create_task(collect_detail_batch([1], slow, key=str, scope='example'))
            await asyncio.sleep(0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert window.checkpoint == {}
    asyncio.run(run())
    assert current_window() is None


def test_checkpoint_is_bounded_and_contains_no_job_bodies():
    raw = {'v': 1, 'scope': 'x' * 160, 'cursor': 'a'*64,
           'retry': [f'{i:064x}' for i in range(2000)], 'page': 79,
           'description': 'private' * 10000, 'nested': {'token': 'secret'}}
    value = clean_checkpoint(raw)
    assert set(value) == {'v', 'scope', 'cursor', 'retry', 'page'}
    assert len(value['retry']) == 4
    assert len(json.dumps(value).encode()) <= MAX_CHECKPOINT_BYTES
    assert clean_checkpoint({'v': 2, 'scope': 'old'}) == {}
    with collection_window():
        with pytest.raises(PreserveExistingJobs):
            asyncio.run(collect_detail_batch(range(2001), identity, key=str, scope='example'))


def _install_batch_collector(db, monkeypatch, count=23):
    source = db.scalar(select(Source))
    source.kind, source.identifier = 'official_careers', 'icl'
    db.commit()
    payload = []
    for number in range(count):
        job = deepcopy(items()[0])
        job.external_id = str(number)
        job.title += f' {number}'
        job.location = 'Haifa, Israel'
        job.apply_url = f'https://example.com/job/{number}'
        job.description += f' Team reference {number}.'
        payload.append(job)
    class Collector:
        async def collect(self, *args):
            batch = await collect_detail_batch(payload, identity, key=lambda j: j.external_id, scope='fixture')
            # Even an adapter incorrectly claiming complete cannot close old jobs.
            return JobCollection(batch, complete=True)
    monkeypatch.setitem(scanner.COLLECTORS, 'official_careers', Collector)
    return source


def test_scan_checkpoint_commits_with_jobs_and_partial_never_closes_others(preview_db, monkeypatch):
    source = _install_batch_collector(preview_db, monkeypatch)
    first = asyncio.run(scanner.scan_all_sources(preview_db, catalog_only=True))
    assert first['new'] == 20 and first['partial_sources'] == 1, first['errors']
    checkpoint = loads(source.metadata_json, {})[CHECKPOINT_KEY]
    assert checkpoint['cursor']
    original = {job.external_id: job.id for job in preview_db.scalars(select(Job))}
    preview_db.expire_all()  # Reload the durable state instead of relying on helper memory.
    second = asyncio.run(scanner.scan_all_sources(preview_db, catalog_only=True))
    assert second['new'] == 3 and second['removed'] == 0
    saved = {job.external_id: job.id for job in preview_db.scalars(select(Job).where(Job.is_active.is_(True)))}
    assert len(saved) == 23 and all(saved[key] == value for key, value in original.items())
    third = asyncio.run(scanner.scan_all_sources(preview_db, catalog_only=True))
    assert third['new'] == third['updated'] == 0 and third['unchanged'] == 20
    assert third['removed'] == 0
    assert first['per_source'][0]['batch_pending'] == 3


def test_egress_deferral_does_not_advance_checkpoint_or_lose_next_batch(preview_db, monkeypatch):
    source = _install_batch_collector(preview_db, monkeypatch)
    asyncio.run(scanner.scan_all_sources(preview_db, catalog_only=True))
    previous = loads(source.metadata_json, {})[CHECKPOINT_KEY]
    with monkeypatch.context() as patch:
        patch.setattr(catalog_egress, 'reserve_catalog_egress', lambda *_: False)
        result = asyncio.run(scanner.scan_all_sources(preview_db, catalog_only=True))
    assert result['deferred_sources'] == 1
    assert loads(source.metadata_json, {})[CHECKPOINT_KEY] == previous
    assert asyncio.run(scanner.scan_all_sources(preview_db, catalog_only=True))['new'] == 3


def test_all_blocked_batch_reports_deferral_but_does_not_starve_later_jobs(preview_db, monkeypatch):
    source = _install_batch_collector(preview_db, monkeypatch)
    original = scanner.COLLECTORS['official_careers']
    class Blocked:
        async def collect(self, *args):
            await original().collect(*args)
            raise PreserveExistingJobs('All attempted details unavailable')
    with monkeypatch.context() as patch:
        patch.setitem(scanner.COLLECTORS, 'official_careers', Blocked)
        result = asyncio.run(scanner.scan_all_sources(preview_db, catalog_only=True))
    assert result['deferred_sources'] == 1 and result['new'] == 0
    assert loads(source.metadata_json, {})[CHECKPOINT_KEY]['cursor']
    assert asyncio.run(scanner.scan_all_sources(preview_db, catalog_only=True))['new'] == 3


def test_oversized_returned_payload_does_not_advance_checkpoint(preview_db, monkeypatch):
    source = _install_batch_collector(preview_db, monkeypatch)
    original = scanner.COLLECTORS['official_careers']
    class Invalid:
        async def collect(self, *args):
            batch = await original().collect(*args)
            return JobCollection([batch[0]] * 2001, complete=False)
    with monkeypatch.context() as patch:
        patch.setitem(scanner.COLLECTORS, 'official_careers', Invalid)
        result = asyncio.run(scanner.scan_all_sources(preview_db, catalog_only=True))
    assert result['deferred_sources'] == 1 and result['new'] == 0
    assert CHECKPOINT_KEY not in loads(source.metadata_json, {})
    assert asyncio.run(scanner.scan_all_sources(preview_db, catalog_only=True))['new'] == 20
