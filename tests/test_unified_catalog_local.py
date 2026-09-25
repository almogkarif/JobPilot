import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import Base, set_user_scope
from app.models import Source, Job, JobTrack, Profile, Application
from app.collectors.base import JobCollection, NormalizedJob, PreserveExistingJobs
from app.services import scanner
from app.services.catalog_routing import unified_catalog_enabled, track_relevance
from app.services.unified_catalog import ensure_source_bindings
from app.services.career_tracks import CAREER_TRACKS
from test_canonical_postgres import postgres_cluster  # noqa: F401 - shared isolated cluster fixture


@pytest.fixture(params=['sqlite', 'postgresql'])
def preview_db(monkeypatch, tmp_path, request):
    from app import main
    # Preview scans use one shared status entry. Keep it scoped to this fixture
    # so later legacy-mode tests do not inherit a different status structure.
    monkeypatch.setattr(main, 'scan_states_by_user', {})
    monkeypatch.setattr(settings, 'unified_catalog_preview', True)
    monkeypatch.setattr(settings, 'auth_mode', 'local')
    # Every DB dependency is explicitly bound to a disposable test engine.
    monkeypatch.setattr(settings, 'database_url', 'sqlite://')
    cluster = None
    if request.param == 'postgresql':
        from uuid import uuid4
        from sqlalchemy import text
        from app.services.canonical_postgres import DATABASE_PREFIX, migrate_postgres_copy
        cluster = request.getfixturevalue('postgres_cluster')
        name = DATABASE_PREFIX + uuid4().hex
        with cluster.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
        engine = create_engine(cluster.url.set(database=name))
        monkeypatch.setattr(settings, 'database_url', engine.url.render_as_string(hide_password=False))
    else:
        engine = create_engine('sqlite:///'+str(tmp_path/'catalog.db'), connect_args={'check_same_thread':False})
    try:
        Base.metadata.create_all(engine)
        if cluster is not None:
            migrate_postgres_copy(engine, confirmed_copy=True)
        monkeypatch.setattr(scanner, 'SessionLocal', lambda: Session(engine))
        with Session(engine, expire_on_commit=False) as db:
            set_user_scope(db, 'preview-user')
            db.add(Profile(active_career_track='computer_science'))
            db.add(Source(name='Example', kind='greenhouse', identifier='example', company_name='Example'))
            db.commit()
            yield db
    finally:
        engine.dispose()
        if cluster is not None:
            with cluster.connect() as connection:
                connection.execute(text(f'DROP DATABASE "{name}"'))


def items():
    return JobCollection([
        NormalizedJob('cs', 'Backend Software Engineer', 'Example', 'Israel', 'hybrid',
            "Build Python backend APIs and distributed services. Requirements: Bachelor's degree in Computer Science. Three years of software development experience.", 'https://example.com/cs'),
        NormalizedJob('ie', 'Data Analyst', 'Example', 'Israel', 'hybrid',
            "Analyze business data, build SQL dashboards and reporting. Requirements: Bachelor's degree in Industrial Engineering and Management. Three years of data analysis experience.", 'https://example.com/ie'),
        NormalizedJob('both', 'Firmware Engineer', 'Example', 'Israel', 'hybrid',
            "Develop embedded firmware in C and C++ for microcontrollers. Requirements: Bachelor's degree in Electrical Engineering or Computer Science. Three years of firmware development experience.", 'https://example.com/both'),
    ])


def test_one_collection_routes_to_all_tracks_and_keeps_ids(preview_db, monkeypatch):
    calls = []
    class Collector:
        async def collect(self, *args):
            calls.append(args)
            return items()
    monkeypatch.setitem(scanner.COLLECTORS, 'greenhouse', Collector)
    result = asyncio.run(scanner.scan_all_sources(preview_db, catalog_only=True))
    assert result['status'] == 'ok' and len(calls) == 1
    expected = {'computer_science': {'cs', 'both'}, 'electrical_engineering': {'both'}, 'industrial_engineering': {'ie'}}
    rows = preview_db.scalars(select(Job).where(Job.is_active.is_(True))).all()
    before = {j.external_id: j.id for j in rows}
    assert len(rows) == 3
    for track, ids in expected.items():
        assigned = set(preview_db.scalars(select(JobTrack.job_id).where(JobTrack.career_track == track)))
        assert {j.external_id for j in rows if j.id in assigned} == ids
    j = next(j for j in rows if j.external_id == 'cs')
    application = Application(job_id=j.id, status='submitted')
    preview_db.add(application); preview_db.commit()
    application_id = application.id
    asyncio.run(scanner.scan_all_sources(preview_db, catalog_only=True, career_track='industrial_engineering'))
    assert len(calls) == 2  # one additional request per new scan, not three
    rows = preview_db.scalars(select(Job).where(Job.is_active.is_(True))).all()
    assert {j.external_id: j.id for j in rows} == before
    assert preview_db.get(Application, application_id).job_id == j.id


def test_sources_and_enabled_state_are_identical_across_tracks(preview_db):
    from app import main
    from app.schemas import SourceUpdate
    ensure_source_bindings(preview_db); preview_db.commit()
    profile = preview_db.scalar(select(Profile))
    lists = []
    for track in CAREER_TRACKS:
        profile.active_career_track = track.key
        lists.append(main.list_sources(preview_db))
    assert lists[0] == lists[1] == lists[2]
    assert len(lists[0]) == 1 and lists[0][0]['career_track'] == 'shared'
    request = SimpleNamespace(state=SimpleNamespace(identity=SimpleNamespace(role='admin')))
    main.edit_source(lists[0][0]['id'], SourceUpdate(enabled=False), request, preview_db)
    assert not any(s.enabled for s in preview_db.scalars(select(Source)))


def test_blocked_board_is_fetched_once_and_preserves_all_tracks(preview_db, monkeypatch):
    class Collector:
        async def collect(self, *args): return items()
    monkeypatch.setitem(scanner.COLLECTORS, 'greenhouse', Collector)
    asyncio.run(scanner.scan_all_sources(preview_db, catalog_only=True))
    original = {j.id for j in preview_db.scalars(select(Job).where(Job.is_active.is_(True)))}
    calls = []
    class Blocked:
        async def collect(self, *args):
            calls.append(args)
            raise PreserveExistingJobs('Access blocked', blocked_external_ids=['both'])
    monkeypatch.setitem(scanner.COLLECTORS, 'greenhouse', Blocked)
    result = asyncio.run(scanner.scan_all_sources(preview_db, catalog_only=True))
    assert result['status'] == 'partial' and len(calls) == 1
    assert {j.id for j in preview_db.scalars(select(Job).where(Job.is_active.is_(True)))} == original


def test_preview_cannot_activate_in_cloud(preview_db, monkeypatch):
    monkeypatch.setattr(settings, 'auth_mode', 'supabase')
    assert not unified_catalog_enabled()
    monkeypatch.setattr(settings, 'auth_mode', 'local')
    monkeypatch.setattr(settings, 'database_url', 'postgresql://example/db')
    assert not unified_catalog_enabled()


def test_review_content_is_not_routed_or_auto_submitted(preview_db):
    j = SimpleNamespace(title='Software Engineer', description='')
    assert not any(track_relevance(j, track.key)[0] for track in CAREER_TRACKS)
    profile = preview_db.scalar(select(Profile)); profile.auto_submit_enabled = True
    assert scanner.auto_queue_jobs(preview_db, profile) == 0


def test_same_canonical_job_has_independent_track_rankings(preview_db, monkeypatch):
    from app.models import JobRanking
    from app.services.ranking.service import persist_v2_result, get_settings
    from app.services.matching import build_match_context
    class Collector:
        async def collect(self, *args): return items()
    monkeypatch.setitem(scanner.COLLECTORS,'greenhouse',Collector)
    asyncio.run(scanner.scan_all_sources(preview_db,catalog_only=True))
    profile=preview_db.scalar(select(Profile))
    job=preview_db.scalar(select(Job).where(Job.external_id=='both'))
    config=get_settings(preview_db)
    ranks={}
    for track in ('computer_science','electrical_engineering'):
        profile.active_career_track=track
        row=persist_v2_result(preview_db,job,profile,config,context=build_match_context(profile,[],career_track=track))
        preview_db.commit()
        ranks[track]=row.id
        assert row.career_track==track
        assert not row.error
    assert len(set(ranks.values()))==2
    assert len(preview_db.scalars(select(JobRanking).execution_options(all_ranking_tracks=True)).all())==2
    assert len(preview_db.scalars(select(Job).where(Job.external_id=='both')).all())==1


def test_multi_track_application_is_queued_once(preview_db, monkeypatch):
    from app.models import JobRanking
    from app.services.ranking.service import get_settings, get_ranking_engine
    class Collector:
        async def collect(self,*args): return items()
    monkeypatch.setitem(scanner.COLLECTORS,'greenhouse',Collector)
    asyncio.run(scanner.scan_all_sources(preview_db,catalog_only=True))
    profile=preview_db.scalar(select(Profile)); profile.auto_submit_enabled=True; profile.auto_submit_opt_in_version=1
    job=preview_db.scalar(select(Job).where(Job.external_id=='both'))
    config=get_settings(preview_db)
    for track in ('computer_science','electrical_engineering'):
        preview_db.add(JobRanking(job_id=job.id,career_track=track,engine='v2',score=100,
            engine_version=get_ranking_engine().version,config_version=config.config_version,
            eligibility_state='realistic',stale=False))
    preview_db.commit()
    dispatched=[]
    monkeypatch.setattr(scanner,'automatic_submit_ready_for_profile',lambda *a:True)
    monkeypatch.setattr(scanner,'automatic_submission_pause',lambda *a:None)
    monkeypatch.setattr(scanner,'dispatch_application_workflow',lambda app_id:dispatched.append(app_id))
    assert scanner.auto_queue_jobs(preview_db,profile)==1
    profile.active_career_track='electrical_engineering'
    assert scanner.auto_queue_jobs(preview_db,profile)==0
    assert len(dispatched)==1
    application=preview_db.scalar(select(Application).where(Application.job_id==job.id))
    assert application.originating_track=='computer_science'


@pytest.fixture
def preview_api(preview_db,monkeypatch,tmp_path):
    from fastapi.testclient import TestClient
    from app import main, database
    engine=preview_db.get_bind()
    monkeypatch.setattr(database,'SessionLocal',lambda:Session(engine,expire_on_commit=False))
    monkeypatch.setattr(main,'SessionLocal',database.SessionLocal)
    monkeypatch.setattr(main,'SECURITY_FILE',tmp_path/'no-lock.json')
    monkeypatch.setattr(main,'_queue_profile_derived_refresh',lambda *a,**kw:None)
    def get_db():
        with Session(engine,expire_on_commit=False) as db:
            set_user_scope(db,'preview-user')
            yield db
    main.app.dependency_overrides[database.get_db]=get_db
    class Collector:
        async def collect(self,*args): return items()
    monkeypatch.setitem(scanner.COLLECTORS,'greenhouse',Collector)
    asyncio.run(scanner.scan_all_sources(preview_db,catalog_only=True))
    # No lifespan: no startup jobs, scheduler, or external workers in integration tests.
    client=TestClient(main.app)
    try:
        yield client
    finally:
        client.close()
        main.app.dependency_overrides.pop(database.get_db,None)


def test_canonical_api_switches_membership_and_keeps_submitted_history(preview_api,preview_db):
    client=preview_api
    source_lists=[]; job_lists={}
    for track in ('computer_science','electrical_engineering','industrial_engineering'):
        response=client.put('/api/career-tracks/active',json={'track':track})
        assert response.status_code==200,response.text
        source_lists.append(client.get('/api/sources').json())
        dashboard=client.get('/api/dashboard')
        assert dashboard.status_code==200,dashboard.text
        assert dashboard.json()['total_jobs']==(2 if track=='computer_science' else 1)
        result=client.get('/api/jobs')
        assert result.status_code==200,result.text
        job_lists[track]=result.json()
    # First switch to a different track installs the full common recommended list.
    assert source_lists[1]==source_lists[2]
    cs={j['title']:j['id'] for j in job_lists['computer_science']}
    ee={j['title']:j['id'] for j in job_lists['electrical_engineering']}
    assert cs['Firmware Engineer']==ee['Firmware Engineer']
    jid=cs['Firmware Engineer']
    client.put('/api/career-tracks/active',json={'track':'computer_science'})
    submitted=client.post(f'/api/jobs/{jid}/mark-submitted')
    assert submitted.status_code==200,submitted.text
    aid=submitted.json()['id']
    client.put('/api/career-tracks/active',json={'track':'electrical_engineering'})
    detail=client.get(f'/api/jobs/{jid}').json()
    assert detail['status']=='submitted' and detail['application_id']==aid
    history=client.get(f'/api/applications/{aid}/timeline')
    assert history.status_code==200,history.text
    assert history.json()['application']['status']=='submitted'


def test_browser_uses_canonical_api_when_switching_tracks(preview_api,tmp_path):
    from urllib.parse import urlsplit
    from playwright.sync_api import sync_playwright
    client=preview_api
    # Install the union once so the browser compares complete source catalogs.
    client.put('/api/career-tracks/active',json={'track':'electrical_engineering'})
    client.put('/api/career-tracks/active',json={'track':'computer_science'})
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        page=browser.new_page(locale='he-IL',viewport={'width':1440,'height':1000})
        errors=[]; failures=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        def route_request(route):
            request=route.request
            parsed=urlsplit(request.url)
            if parsed.hostname!='jobpilot.test':
                route.fulfill(status=404,body='');return
            path=parsed.path+('?' + parsed.query if parsed.query else '')
            if parsed.path=='/api/onboarding':
                route.fulfill(json={'current_version':2,'completed':True,'step':'done','skipped':False});return
            response=client.request(request.method,path,content=request.post_data_buffer,
                                    headers={'content-type':request.headers.get('content-type','application/json')})
            if response.status_code>=500: failures.append((path,response.status_code))
            route.fulfill(status=response.status_code,body=response.content,
                          headers={'content-type':response.headers.get('content-type','application/json')})
        page.route('**/*',route_request)
        page.goto('http://jobpilot.test/')
        page.wait_for_function("document.body.dataset.careerTrack === 'computer_science'")
        sources=page.evaluate("async()=> (await fetch('/api/sources')).json()")
        assert len(sources)>1
        for track,expected in [('electrical_engineering',1),('industrial_engineering',1),('computer_science',2)]:
            page.evaluate("clearProfileDirtyState()")
            page.locator('#career-switcher-trigger').click()
            page.locator(f'[data-career-track="{track}"]').click()
            page.wait_for_function('(track)=>document.body.dataset.careerTrack===track',arg=track)
            page.wait_for_function('(track)=>state.dashboard?.career_track===track',arg=track)
            assert page.locator('[data-metric-tone="jobs"] strong').inner_text()==str(expected)
            result=page.evaluate("async()=> (await fetch('/api/dashboard')).json()")
            assert result['total_jobs']==expected
            assert page.evaluate("async()=> (await fetch('/api/sources')).json()")==sources
        page.screenshot(path=str(tmp_path/'canonical-dashboard.png'),full_page=True)
        assert not errors,errors
        assert not failures,failures
        browser.close()


def test_deduplication_does_not_merge_generic_career_pages():
    from app.services.unified_catalog import canonical_job_key
    assert canonical_job_key('official','example','first','https://example.com/careers/israel') != canonical_job_key('official','example','second','https://example.com/careers/israel')
    assert canonical_job_key('greenhouse','example','42','https://example.com/jobs/42?utm_source=a') == canonical_job_key('official','example','other','https://example.com/jobs/42')


def test_local_preview_cannot_dispatch_external_workflows(preview_db,monkeypatch):
    from app.services import github_actions
    def unexpected(*args,**kwargs): raise AssertionError('No network dispatch is allowed')
    monkeypatch.setattr(github_actions.httpx,'post',unexpected)
    with pytest.raises(RuntimeError,match='disabled for the local'):
        github_actions.dispatch_application_workflow(123)


def test_local_preview_never_gives_a_task_to_an_agent(preview_api):
    response = preview_api.get('/api/agent/tasks/next', params={'agent_id': 'preview-check'})
    assert response.status_code == 200
    assert response.json() == {'task': None}


def test_postgres_preview_startup_requires_migration_receipt(preview_db, monkeypatch):
    from sqlalchemy import text
    from app.services.catalog_routing import validate_preview_startup
    engine = preview_db.get_bind()
    if engine.dialect.name != 'postgresql':
        validate_preview_startup(engine)
        return
    monkeypatch.setattr(settings, 'storage_mode', 'local')
    monkeypatch.setattr(settings, 'scheduler_enabled', False)
    validate_preview_startup(engine)
    with engine.begin() as connection:
        connection.execute(text("UPDATE catalog_migration_archive SET migration_version='incompatible' "
                                "WHERE entity_table='__migration__'"))
    with pytest.raises(RuntimeError, match='explicitly migrated'):
        validate_preview_startup(engine)


def test_fully_auto_submitted_job_stays_out_of_dashboard_in_both_tracks(preview_api,preview_db):
    from app.models import JobRanking, ApplicationAttempt
    from app.services.ranking.service import get_settings,get_ranking_engine
    job=preview_db.scalar(select(Job).where(Job.external_id=='both'))
    config=get_settings(preview_db)
    for track in ('computer_science','electrical_engineering'):
        preview_db.add(JobRanking(job_id=job.id,career_track=track,engine='v2',score=100,tier='top_match',
            engine_version=get_ranking_engine().version,config_version=config.config_version,
            eligibility_state='realistic',stale=False))
    preview_db.commit()
    assert job.id in {j['id'] for j in preview_api.get('/api/dashboard').json()['recent_jobs']}
    response=preview_api.post(f'/api/jobs/{job.id}/mark-submitted')
    assert response.status_code==200,response.text
    preview_db.expire_all()
    application=preview_db.get(Application,response.json()['id']);application.mode='auto'
    preview_db.add(ApplicationAttempt(application_id=application.id,idempotency_key='canonical-submitted',
        status='verified',verification_state='verified'))
    preview_db.commit()
    for track in ('computer_science','electrical_engineering'):
        preview_api.put('/api/career-tracks/active',json={'track':track})
        dashboard=preview_api.get('/api/dashboard').json()
        assert job.id not in {j['id'] for j in dashboard['recent_jobs']}
        detail=preview_api.get(f'/api/jobs/{job.id}').json()
        assert detail['status']=='submitted' and detail['application_id']==application.id


def test_canonical_fingerprint_survives_sqlite_timezone_roundtrip(preview_db):
    from datetime import datetime,timezone
    from app.services.ranking.service import job_fingerprint_values
    stamp=datetime(2026,9,23,8,0)
    args=('shared','Engineer','Description','Israel','hybrid')
    assert job_fingerprint_values(*args,stamp)==job_fingerprint_values(*args,stamp.replace(tzinfo=timezone.utc))


def test_canonical_filter_refresh_only_scores_newly_eligible_jobs(preview_db, monkeypatch):
    from app import main
    from app.services.catalog_routing import job_in_track
    from app.services.ranking import service, v2

    class Collector:
        async def collect(self, *args): return items()

    monkeypatch.setitem(scanner.COLLECTORS, 'greenhouse', Collector)
    asyncio.run(scanner.scan_all_sources(preview_db, catalog_only=True))
    profile = preview_db.scalar(select(Profile))
    profile.excluded_keywords_json = '["backend"]'
    config = service.get_settings(preview_db)
    jobs = preview_db.scalars(select(Job).where(job_in_track('computer_science'))).all()
    ids = {job.external_id: job.id for job in jobs}
    calls = []
    real = v2.role_match

    def tracked(job, *args, **kwargs):
        calls.append(job.id)
        return real(job, *args, **kwargs)

    monkeypatch.setattr(v2, 'role_match', tracked)
    for job in jobs:
        service.persist_v2_result(preview_db, job, profile, config)
    preview_db.commit()
    assert calls == [ids['both']]
    calls.clear()
    main._apply_profile_changes(profile, {'excluded_keywords': []}, preview_db,
                                replace_application_profile=False, audit_scope='test')
    assert calls == [ids['cs']]
    calls.clear()
    main._apply_profile_changes(profile, {'excluded_keywords': ['backend']}, preview_db,
                                replace_application_profile=False, audit_scope='test')
    main._apply_profile_changes(profile, {'excluded_keywords': []}, preview_db,
                                replace_application_profile=False, audit_scope='test')
    assert calls == []  # Previously scored jobs reuse their score after hiding/showing.


@pytest.mark.parametrize('identifier,posting_url', [
    ('g-stat', 'https://g-stat.com/jobs/junior-data-analyst/'),
    ('proteantecs', 'https://www.proteantecs.com/careerinfo?pi=05.F69'),
])
def test_gstat_republished_slug_keeps_job_and_application(preview_db, monkeypatch, identifier, posting_url):
    from app.models import JobSourceIdentity
    source = preview_db.scalar(select(Source))
    source.kind, source.identifier = 'official_careers', identifier
    preview_db.commit()
    external_id = '33937'
    class Collector:
        async def collect(self, *args):
            item = items()[1]
            item.external_id = external_id
            item.apply_url = posting_url
            return JobCollection([item])
    monkeypatch.setitem(scanner.COLLECTORS, 'official_careers', Collector)
    asyncio.run(scanner.scan_all_sources(preview_db, catalog_only=True))
    job = preview_db.scalar(select(Job))
    original_id = job.id
    # Simulate the old board-ID-based canonical key, before this fix.
    job.canonical_key = 'legacy-key'
    application = Application(job_id=job.id, status='submitted')
    preview_db.add(application)
    preview_db.commit()
    external_id = '33971'
    asyncio.run(scanner.scan_all_sources(preview_db, catalog_only=True))
    preview_db.expire_all()
    rows = preview_db.scalars(select(Job)).all()
    assert len(rows) == 1 and rows[0].id == original_id and rows[0].is_active
    assert preview_db.get(Application, application.id).job_id == original_id
    aliases = preview_db.scalars(select(JobSourceIdentity)).all()
    assert {alias.external_id for alias in aliases} == {'33937', '33971'}
    assert {alias.job_id for alias in aliases} == {original_id}


def test_gstat_slug_identity_changes_only_for_distinct_postings():
    from app.services.unified_catalog import canonical_job_key
    key = lambda eid, path: canonical_job_key('official_careers', 'g-stat', eid, 'https://g-stat.com'+path)
    assert key('old', '/jobs/data-analyst/') == key('new', '/jobs/data-analyst/')
    assert key('old', '/jobs/data-analyst/') != key('new', '/jobs/business-analyst/')
    assert key('old', '/jobs/') != key('new', '/jobs/')


def test_proteantecs_query_posting_id_is_stable_and_specific():
    from app.services.unified_catalog import canonical_job_key
    key = lambda eid, url: canonical_job_key('official_careers', 'proteantecs', eid, url)
    url = 'https://www.proteantecs.com/careerinfo?pi=05.F69'
    assert key('old', url) == key('new', url)
    assert key('old', url) != key('new', url.replace('05.F69', 'OTHER'))
    for generic in ['https://www.proteantecs.com/careerinfo', 'https://www.proteantecs.com/careerinfo?pi=',
                    'https://example.com/careerinfo?pi=05.F69']:
        assert key('old', generic) != key('new', generic)
