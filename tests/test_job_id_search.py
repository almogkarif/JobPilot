import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.database import Base, get_db, set_user_scope
from app.main import app
from app.models import Job, JobTrack, Profile, Source, UserJobState


@pytest.fixture(params=[False, True], ids=['legacy', 'unified'])
def job_search_catalog(request, tmp_path, monkeypatch):
    url = f'sqlite:///{tmp_path / "job-search.db"}'
    monkeypatch.setattr(settings, 'auth_mode', 'local')
    monkeypatch.setattr(settings, 'database_url', url)
    monkeypatch.setattr(settings, 'unified_catalog_preview', request.param)
    engine = create_engine(url, connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        set_user_scope(db, 'local-owner')
        db.add(Profile(active_career_track='computer_science', seniority_levels_json='["unknown"]'))
        source = Source(name='ID search fixture', kind='custom', identifier='https://example.invalid')
        db.add(source)
        db.flush()
        for job_id, title in ((2398, 'Software Engineer'), (23989, 'Backend Engineer'),
                              (2400, 'Reference 2398 Engineer'), (3400, 'Another Track Engineer')):
            track = 'electrical_engineering' if job_id == 3400 else 'computer_science'
            db.add(Job(id=job_id, source_id=source.id, external_id=str(job_id), title=title,
                       company='Search Fixture', career_track=track, location='Haifa, Israel',
                       description=('SearchBodyToken and reference 2398. ' * 3000),
                       apply_url=f'https://example.invalid/jobs/{job_id}'))
            db.add(JobTrack(job_id=job_id, career_track=track))
        db.commit()

    def isolated_db():
        with factory() as db:
            set_user_scope(db, 'local-owner')
            yield db

    monkeypatch.setitem(app.dependency_overrides, get_db, isolated_db)
    # No lifespan: the fixture needs no startup, catalog installation or scheduler.
    client = TestClient(app)
    try:
        yield client, engine, factory
    finally:
        client.close()
        engine.dispose()


@pytest.mark.parametrize('query', ['2398', '#2398', '  # 2398  ', '0002398'])
def test_id_search_returns_only_exact_job_and_matching_count(job_search_catalog, query):
    client, _, _ = job_search_catalog
    response = client.get('/api/jobs', params={'query': query, 'paginated': True, 'page': 9, 'page_size': 1})
    assert response.status_code == 200
    result = response.json()
    assert [job['id'] for job in result['items']] == [2398]
    assert result['total'] == result['pages'] == result['page'] == 1
    assert sum(location['count'] for location in result['location_options']) == 1
    assert 'description' not in result['items'][0]


@pytest.mark.parametrize('query', ['#999999', '0', '#0', '9' * 200, '#9223372036854775808'])
def test_unknown_or_oversized_id_returns_empty_results(job_search_catalog, query):
    client, _, _ = job_search_catalog
    response = client.get('/api/jobs', params={'query': query, 'paginated': True})
    assert response.status_code == 200
    assert response.json()['items'] == []
    assert response.json()['total'] == 0


@pytest.mark.parametrize('query, expected', [
    ('Reference 2398 Engineer', {2400}), ('Search Fixture', {2398, 23989, 2400}),
    ('SearchBodyToken', {2398, 23989, 2400}), ('#2398', {2398}),
])
def test_text_search_and_legacy_list_response_still_work(job_search_catalog, query, expected):
    client, _, _ = job_search_catalog
    response = client.get('/api/jobs', params={'query': query})
    assert response.status_code == 200
    assert {job['id'] for job in response.json()} == expected


def test_id_search_preserves_track_visibility_and_submitted_toggle(job_search_catalog):
    client, _, factory = job_search_catalog
    assert client.get('/api/jobs', params={'query': '#3400'}).json() == []
    with factory() as db:
        set_user_scope(db, 'local-owner')
        db.add(UserJobState(job_id=2398, status='submitted'))
        db.commit()
    assert client.get('/api/jobs', params={'query': '#2398', 'exclude_submitted': True}).json() == []
    assert [row['id'] for row in client.get('/api/jobs', params={'query': '#2398'}).json()] == [2398]
    with factory() as db:
        set_user_scope(db, 'local-owner')
        state = db.query(UserJobState).filter_by(job_id=2398).one()
        state.status = 'hidden'
        db.commit()
    assert client.get('/api/jobs', params={'query': '#2398'}).json() == []


def test_id_search_works_in_each_professional_track(job_search_catalog):
    client, _, factory = job_search_catalog
    for track in ('industrial_engineering', 'electrical_engineering', 'computer_science'):
        with factory() as db:
            set_user_scope(db, 'local-owner')
            db.query(Profile).one().active_career_track = track
            db.get(Job, 2398).career_track = track
            mapping = db.query(JobTrack).filter_by(job_id=2398).one()
            mapping.career_track = track
            db.commit()
        response = client.get('/api/jobs', params={'query': '#2398'})
        assert response.status_code == 200
        assert [row['id'] for row in response.json()] == [2398]
