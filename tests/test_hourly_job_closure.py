"""A detail budget must not preserve a posting absent from a verified inventory."""
import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select

from app.collectors import official, workday
from app.collectors.base import JobCollection
from app.models import Application, Job, JobSourceIdentity, Source
from app.services import scanner
from test_unified_catalog_local import preview_db, items  # noqa: F401
from test_canonical_postgres import postgres_cluster  # noqa: F401


@pytest.mark.parametrize('identifier', sorted(workday.FULL_INVENTORY_IDENTIFIERS))
def test_full_listing_is_checked_beyond_the_detail_budget(monkeypatch, identifier):
    pages, details = [], []
    async def payload(client, method, url, **kwargs):
        assert kwargs['bounded'] is True
        if method == 'POST':
            offset = kwargs['json']['offset']
            pages.append(offset)
            return {'total': 143 if offset == 0 else 0, 'jobPostings': [
                {'externalPath': f'/job/Israel-Haifa/Engineer_JR{i}', 'bulletFields': [f'JR{i}']}
                for i in range(offset, min(offset + 20, 143))]}
        details.append(url)
        return {'jobPostingInfo': {'title': 'Software Engineer', 'location': 'Haifa, Israel',
                'canApply': True, 'jobDescription': items()[0].description}}
    monkeypatch.setattr(workday, '_payload', payload)
    jobs = asyncio.run(workday.WorkdayCollector().collect(identifier))
    assert pages == list(range(0,143,20))
    assert set(jobs.listed_external_ids) == {f'JR{i}' for i in range(143)}
    assert len(jobs) == len(details) == (120 if identifier == 'nvidia' else 100)
    assert not jobs.complete


@pytest.mark.parametrize('status,closed', [(404, True), (410, True), (403, False), (429, False), (500, False)])
def test_workday_closure_is_distinct_from_blocked_detail(monkeypatch, status, closed):
    async def payload(client, method, url, **kwargs):
        if method == 'POST':
            return {'total': 1, 'jobPostings': [{'externalPath': '/job/Israel-Haifa/Engineer_JR1', 'bulletFields': ['JR1']}]}
        response = httpx.Response(status, request=httpx.Request('GET',url))
        response.raise_for_status()
    monkeypatch.setattr(workday, '_payload', payload)
    jobs = asyncio.run(workday.WorkdayCollector().collect('nvidia'))
    assert not jobs and jobs.listed_external_ids == ('JR1',)
    assert set(jobs.closed_external_ids) == ({'JR1'} if closed else set())
    assert set(jobs.blocked_external_ids) == (set() if closed else {'JR1'})


def test_workday_explicit_can_apply_false_overrides_stale_description(monkeypatch):
    async def payload(client, method, url, **kwargs):
        if method == 'POST':
            return {'total': 1, 'jobPostings': [{'externalPath': '/job/Israel-Haifa/Engineer_JR1', 'bulletFields': ['JR1']}]}
        return {'jobPostingInfo': {'title':'Software Engineer', 'jobDescription':items()[0].description, 'canApply':False}}
    monkeypatch.setattr(workday, '_payload', payload)
    jobs = asyncio.run(workday.WorkdayCollector().collect('nvidia'))
    assert not jobs and jobs.closed_external_ids == ('JR1',) and not jobs.blocked_external_ids


@pytest.mark.parametrize('failure', ['early_empty', 'changed_count', 'limit'])
def test_unverified_workday_inventory_never_authorizes_absence_removal(monkeypatch, failure):
    monkeypatch.setattr(workday, 'MAX_INVENTORY_RESULTS', 40)
    async def payload(client, method, url, **kwargs):
        if method == 'GET':
            return {'jobPostingInfo': {'title':'Software Engineer', 'jobDescription':items()[0].description}}
        offset = kwargs['json']['offset']
        total = 100 if failure=='limit' else 40
        return {'total':total+1 if offset and failure=='changed_count' else total,
                'jobPostings': [] if offset and failure=='early_empty' else [
                    {'externalPath': f'/job/Israel-Haifa/Engineer_JR{i}', 'bulletFields':[f'JR{i}']}
                    for i in range(offset, offset+20)]}
    monkeypatch.setattr(workday, '_payload', payload)
    jobs = asyncio.run(workday.WorkdayCollector().collect('nvidia'))
    assert jobs.listed_external_ids is None and not jobs.complete


def _seed(db, monkeypatch):
    class Collector:
        async def collect(self, *args): return items()
    monkeypatch.setitem(scanner.COLLECTORS,'greenhouse',Collector)
    asyncio.run(scanner.scan_all_sources(db,catalog_only=True))
    return {job.external_id:job for job in db.scalars(select(Job))}


@pytest.mark.parametrize('inventory', [None, ('cs','ie'), ()])
def test_hourly_inventory_closes_only_verified_absence_and_retains_history(preview_db,monkeypatch,inventory):
    db=preview_db
    jobs=_seed(db,monkeypatch)
    app=Application(job_id=jobs['both'].id,status='submitted')
    db.add(app);db.commit();app_id=app.id
    class Collector:
        async def collect(self,*args):
            return JobCollection(complete=False,listed_external_ids=inventory,blocked_external_ids=('cs',))
    monkeypatch.setitem(scanner.COLLECTORS,'greenhouse',Collector)
    result=asyncio.run(scanner.scan_all_sources(db,catalog_only=True))
    db.expire_all()
    assert {j.external_id for j in db.scalars(select(Job).where(Job.is_active.is_(True)))} == (set(jobs) if inventory is None else set(inventory))
    assert result['removed'] == (0 if inventory is None else len(jobs)-len(inventory))
    assert db.get(Application,app_id).status=='submitted'


def test_explicit_closure_in_partial_scan_keeps_unvisited_and_other_live_sources(preview_db,monkeypatch):
    db=preview_db
    jobs=_seed(db,monkeypatch)
    first=db.scalar(select(Source))
    other=Source(name='Other',kind='greenhouse',identifier='other',career_track='shared')
    db.add(other);db.flush()
    db.add(JobSourceIdentity(source_id=other.id,external_id='same-live-role',job_id=jobs['ie'].id))
    db.commit()
    class Collector:
        async def collect(self,*args):
            return JobCollection(complete=False,closed_external_ids=('cs','ie'),blocked_external_ids=('both',))
    monkeypatch.setitem(scanner.COLLECTORS,'greenhouse',Collector)
    result=asyncio.run(scanner.scan_all_sources(db,source_ids={first.id},catalog_only=True))
    db.expire_all()
    assert result['removed']==1
    assert not db.get(Job,jobs['cs'].id).is_active
    assert db.get(Job,jobs['ie'].id).is_active and db.get(Job,jobs['both'].id).is_active


def test_verified_presence_renews_old_identity_without_downloading_its_description(preview_db,monkeypatch):
    db=preview_db
    jobs=_seed(db,monkeypatch)
    for row in db.scalars(select(JobSourceIdentity)):
        row.last_seen_at=datetime.now(timezone.utc)-timedelta(days=15)
    db.commit()
    class Collector:
        async def collect(self,*args): return JobCollection(complete=False,listed_external_ids=tuple(jobs))
    monkeypatch.setitem(scanner.COLLECTORS,'greenhouse',Collector)
    result=asyncio.run(scanner.scan_all_sources(db,catalog_only=True))
    db.expire_all()
    assert result['expired']==0
    assert all(row.is_active for row in db.scalars(select(Job)))


def test_official_closed_detail_survives_empty_partial_payload(monkeypatch):
    monkeypatch.setitem(official.PRESETS,'closure-fixture',dict(company='Fixture',url='https://fixture.example/jobs',
        id_pattern=r'/job/(\d+)',http_first=True,static_only=True,hydrate_details=True))
    async def listing(_preset):
        return [dict(href='https://fixture.example/job/123',title='Software Engineer',text=items()[0].description)]
    monkeypatch.setattr(official,'_collect_static_rows',listing)
    real_client=httpx.AsyncClient
    monkeypatch.setattr(official.httpx,'AsyncClient',lambda **kw:real_client(
        transport=httpx.MockTransport(lambda request:httpx.Response(410,request=request)),**kw))
    result=asyncio.run(official.OfficialCareersCollector().collect('closure-fixture'))
    assert not result and not result.complete
    assert result.closed_external_ids==('123',) and not result.blocked_external_ids


def test_workday_detail_timeout_keeps_verified_inventory_and_completed_jobs(monkeypatch):
    from app.collectors.incremental import collection_window
    cancelled=[]
    async def payload(client, method, url, **kwargs):
        if method=='POST':
            return {'total':2,'jobPostings':[{'externalPath':f'/job/Israel-Haifa/Engineer_{i}','bulletFields':[str(i)]} for i in (1,2)]}
        if url.endswith('_1'):
            return {'jobPostingInfo':{'title':'Software Engineer','jobDescription':items()[0].description}}
        try:
            await asyncio.sleep(60)
        finally:
            cancelled.append(url)
    monkeypatch.setattr(workday,'_payload',payload)
    with collection_window(timeout=.2) as window:
        jobs=asyncio.run(workday.WorkdayCollector().collect('nvidia'))
    assert len(jobs)==1 and set(jobs.listed_external_ids)=={'1','2'}
    assert window.interrupted and cancelled and not jobs.complete
    assert not jobs.closed_external_ids


def test_workday_detail_cursor_reaches_beyond_the_first_120_jobs(monkeypatch):
    from app.collectors.incremental import collection_window, clean_checkpoint
    async def payload(client, method, url, **kwargs):
        if method=='POST':
            offset=kwargs['json']['offset']
            return {'total':143,'jobPostings':[{'externalPath':f'/job/Israel-Haifa/Engineer_{i}','bulletFields':[str(i)]}
                for i in range(offset,min(offset+20,143))]}
        return {'jobPostingInfo':{'title':'Software Engineer','jobDescription':items()[0].description}}
    monkeypatch.setattr(workday,'_payload',payload)
    previous,seen={},set()
    for _ in range(2):
        with collection_window(previous) as window:
            jobs=asyncio.run(workday.WorkdayCollector().collect('nvidia'))
        assert not seen.intersection(j.external_id for j in jobs)
        seen.update(j.external_id for j in jobs)
        previous=clean_checkpoint(window.checkpoint)
        assert len(jobs.listed_external_ids)==143
    assert len(seen)==143


def test_scanner_keeps_workday_inventory_when_detail_is_blocked(preview_db,monkeypatch):
    from sqlalchemy import event
    db=preview_db
    jobs=_seed(db,monkeypatch)
    source=db.scalar(select(Source))
    source.kind,source.identifier='workday','nvidia'
    db.commit()
    async def payload(client,method,url,**kwargs):
        if method=='POST':
            return {'total':1,'jobPostings':[{'externalPath':'/job/Israel-Haifa/Engineer_cs','bulletFields':['cs']}]}
        httpx.Response(403,request=httpx.Request('GET',url)).raise_for_status()
    monkeypatch.setattr(workday,'_payload',payload)
    queries=[]
    def record(_c,_cursor,sql,*_args): queries.append(sql.lower())
    engine=db.get_bind()
    event.listen(engine,'before_cursor_execute',record)
    try:
        result=asyncio.run(scanner.scan_all_sources(db,catalog_only=True))
    finally:
        event.remove(engine,'before_cursor_execute',record)
    assert result['removed']==2 and result['partial_sources']==1
    assert result['per_source'][0]['inventory_verified'] is True
    assert result['per_source'][0]['inventory_count']==1
    assert not any('jobs.description' in sql for sql in queries)
    db.expire_all()
    assert {j.external_id for j in db.scalars(select(Job).where(Job.is_active.is_(True)))}=={'cs'}
