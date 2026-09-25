from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import Session
from app.database import Base, set_user_scope
from app.models import Job, JobRanking, Source
from app.services.ranking import v2
from tests.test_ranking_v2 import profile


def test_refresh_releases_read_snapshot_and_filters_before_scoring(tmp_path, monkeypatch):
    from app import main
    engine = create_engine(f"sqlite:///{tmp_path / 'ranking.db'}", connect_args={'timeout':0.2})
    Base.metadata.create_all(engine)
    with engine.begin() as c:
        c.exec_driver_sql('PRAGMA journal_mode=WAL')
    scored = []
    real = v2.role_match
    def tracked(job, *args, **kwargs):
        assert not job.title.startswith('Senior'), 'Excluded job reached scoring'
        scored.append(job.id)
        return real(job, *args, **kwargs)
    monkeypatch.setattr(v2, 'role_match', tracked)
    with Session(engine, expire_on_commit=False, autoflush=False) as db:
        set_user_scope(db, 'ranking-test')
        p = profile(excluded=['senior'])
        source = Source(name='Example', kind='greenhouse', identifier='example')
        db.add_all([p, source]); db.flush()
        for i in range(64):
            db.add(Job(source_id=source.id, external_id=str(i),
                       title=('Senior ' if i % 2 else '') + 'Software Engineer',
                       company='Example', location='Israel', workplace='hybrid',
                       description='Develop Python software applications. At least 3 years experience.',
                       apply_url=f'https://example.com/jobs/{i}'))
        db.commit()
        commits = []
        def other_writer(session):
            with engine.begin() as c:
                c.execute(text("UPDATE profiles SET full_name='concurrent edit' WHERE user_id='ranking-test'"))
            commits.append(True)
        event.listen(db, 'after_commit', other_writer)
        main._rescore_v2_jobs(db, p, commit_every=50, priority_limit=8, stale_only=True)
        event.remove(db, 'after_commit', other_writer)
        rows = db.scalars(select(JobRanking)).all()
        assert len(rows) == 64
        assert len(scored) == 32 and len(set(scored)) == 32
        assert sum(row.eligibility_state == 'excluded' for row in rows) == 32
        assert len(commits) >= 3
    engine.dispose()
