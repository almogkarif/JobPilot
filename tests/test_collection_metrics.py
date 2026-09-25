from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session
from app.models import Base, Source, Job, CollectionObservation
from app.services.collection_metrics import record_observations, collection_metrics, seed_retained_history


def test_unique_history_survives_retries_recovery_and_catalog_deletion():
    engine=create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        source=Source(name='Employer',kind='official_careers',identifier='employer',company_name='Employer')
        db.add(source);db.flush()
        db.add(Job(source_id=source.id,external_id='123',title='Engineer',company='Employer',apply_url='https://example.com/123'))
        db.commit()
        seed_retained_history(db);seed_retained_history(db)
        record_observations(db,'official_careers','EMPLOYER',['123','123'])
        record_observations(db,'official_careers','employer',blocked_ids=['123','456'])
        record_observations(db,'official_careers','employer',['123','456'])
        db.commit()
        assert collection_metrics(db)['observed_unique']==2
        assert collection_metrics(db)['ever_blocked_unique']==2
        db.execute(delete(Job));db.commit()
        assert collection_metrics(db)['observed_unique']==2
        assert collection_metrics(db)['historical_coverage']=='partial'


def test_same_ids_on_different_boards_are_distinct_and_track_copies_not_counted():
    engine=create_engine('sqlite://');Base.metadata.create_all(engine)
    with Session(engine) as db:
        for track in ['computer_science','electrical_engineering']:
            s=Source(name=track,kind='official_careers',identifier='same',career_track=track)
            db.add(s);db.flush();db.add(Job(source_id=s.id,external_id='1',title='Engineer',company='Employer',apply_url='https://example.com',career_track=track))
        db.commit()
        assert collection_metrics(db)['observed_unique']==1
        record_observations(db,'official_careers','other',['1'])
        assert collection_metrics(db)['observed_unique']==2
        assert collection_metrics(db)['ever_blocked_unique']==0


def test_blocked_audit_matches_exact_urls_only():
    from app.services.collection_metrics import seed_verified_blocked_urls
    engine=create_engine('sqlite://');Base.metadata.create_all(engine)
    with Session(engine) as db:
        s=Source(name='Employer',kind='official_careers',identifier='employer');db.add(s);db.flush()
        for i in ('one','two'):
            db.add(Job(source_id=s.id,external_id=i,title='Engineer',company='Employer',apply_url='https://example.com/'+i))
        db.commit();seed_retained_history(db)
        seed_verified_blocked_urls(db,['https://example.com/one','https://example.com/missing'])
        seed_verified_blocked_urls(db,['https://example.com/one'])
        assert collection_metrics(db)['observed_unique']==2
        assert collection_metrics(db)['ever_blocked_unique']==1


def test_scanner_preserves_active_job_on_block_and_records_once(monkeypatch):
    import asyncio
    from app.services import scanner
    from app.models import Profile
    from app.collectors.base import PreserveExistingJobs
    engine=create_engine('sqlite://');Base.metadata.create_all(engine)
    class BlockedCollector:
        async def collect(self,*args):
            raise PreserveExistingJobs('HTTP403 job detail',blocked_external_ids=['1'])
    monkeypatch.setitem(scanner.COLLECTORS,'greenhouse',BlockedCollector)
    with Session(engine,expire_on_commit=False) as db:
        db.add(Profile(id=1,full_name='Test',location='Israel'))
        s=Source(name='Employer',kind='greenhouse',identifier='employer',enabled=True);db.add(s);db.flush()
        j=Job(source_id=s.id,external_id='1',title='Software Engineer',description='Existing verified description',company='Employer',location='Israel',apply_url='https://example.com/1',is_active=True)
        db.add(j);db.commit()
        for _ in range(2):asyncio.run(scanner.scan_all_sources(db))
        db.refresh(j)
        assert j.is_active and j.description=='Existing verified description'
        assert collection_metrics(db)['ever_blocked_unique']==1
        assert collection_metrics(db)['observed_unique']==1


def test_developer_history_remains_admin_only(monkeypatch):
    from types import SimpleNamespace
    import pytest
    from fastapi import HTTPException
    from app import main
    monkeypatch.setattr(main,'_developer_tools_allowed',lambda identity:False)
    request=SimpleNamespace(state=SimpleNamespace(identity=SimpleNamespace(role='user')))
    with pytest.raises(HTTPException) as error:
        main.developer_overview(request,db=None)
    assert error.value.status_code==403
