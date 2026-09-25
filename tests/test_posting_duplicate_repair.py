import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from app.database import Base, set_user_scope
from app.models import Source, Job, Application, ApplicationEvent, UserJobState, JobTrack, JobSourceIdentity
from app.services.posting_duplicate_repair import repair_posting_duplicates


def test_repair_preserves_application_history_states_and_aliases():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        set_user_scope(db, 'one')
        source = Source(name='Gstat', kind='official_careers', identifier='g-stat')
        db.add(source); db.flush()
        first = Job(title='Data Analyst', company='Gstat', source_id=source.id, external_id='old', apply_url='https://g-stat.com/jobs/analyst/')
        second = Job(title='Data Analyst', company='Gstat', source_id=source.id, external_id='new', apply_url=first.apply_url)
        db.add_all([first, second]); db.flush()
        app = Application(job_id=second.id, user_id='one', status='submitted')
        db.add(app); db.flush()
        event = ApplicationEvent(application_id=app.id, user_id='one', event_type='submitted')
        db.add_all([event, UserJobState(job_id=first.id, user_id='one', status='new'),
            UserJobState(job_id=second.id, user_id='one', status='submitted'),
            JobTrack(job_id=second.id, career_track='industrial_engineering'),
            JobSourceIdentity(source_id=source.id, external_id='new', job_id=second.id)])
        db.commit()
        ids = first.id, second.id
        aid, eid = app.id, event.id
    result = repair_posting_duplicates(engine, [ids], confirmed_local=True)
    assert result['merged'] == 1
    with Session(engine) as db:
        set_user_scope(db, 'one')
        assert db.get(Application, aid).job_id == ids[0]
        assert db.get(ApplicationEvent, eid).application_id == aid
        assert db.get(Job, ids[1]).canonical_job_id == ids[0]
        states = db.scalars(select(UserJobState)).all()
        assert len(states) == 1 and states[0].status == 'submitted'
        assert db.scalar(select(JobTrack)).job_id == ids[0]
        assert db.scalar(select(JobSourceIdentity)).job_id == ids[0]
    assert repair_posting_duplicates(engine, [ids], confirmed_local=True)['already_merged'] == 1


def test_repair_rejects_unconfirmed_database():
    with pytest.raises(RuntimeError):
        repair_posting_duplicates(create_engine('sqlite://'), [])


@pytest.mark.parametrize('problem', ['content', 'applications', 'applying'])
def test_unsafe_repair_rolls_back(problem):
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        set_user_scope(db, 'one')
        source = Source(name='Gstat', kind='official_careers', identifier='g-stat')
        db.add(source); db.flush()
        jobs = [Job(title='Data Analyst', company='Gstat', source_id=source.id,
                    external_id=external, apply_url='https://g-stat.com/jobs/analyst/') for external in ['one', 'two']]
        if problem == 'content':
            jobs[1].description = 'Different vacancy'
        db.add_all(jobs); db.flush()
        if problem == 'applications':
            db.add_all([Application(job_id=j.id, status='submitted') for j in jobs])
        if problem == 'applying':
            db.add(Application(job_id=jobs[1].id, status='applying'))
        db.commit()
        ids = jobs[0].id, jobs[1].id
    with pytest.raises((ValueError, RuntimeError)):
        repair_posting_duplicates(engine, [ids], confirmed_local=True)
    with Session(engine) as db:
        assert db.get(Job, ids[1]).canonical_job_id is None
