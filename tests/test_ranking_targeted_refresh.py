from sqlalchemy import event, select

from app import main
from app.models import Job, JobRanking, Profile
from app.services.ranking import service
from app.services.matching import build_match_context
from tests.test_ranking_filter_first import ranking_db


def add_job(db, original, external_id, title):
    j = Job(source_id=original.source_id, external_id=external_id, title=title,
            company='Example', description=original.description, location='Israel', workplace='hybrid',
            apply_url=f'https://example.com/{external_id}')
    db.add(j); db.flush()
    j.source_fingerprint = service.job_fingerprint(j)
    return j


def test_title_filter_save_downloads_only_affected_jobs(ranking_db, monkeypatch):
    monkeypatch.setattr(main.settings, 'auth_mode', 'local')
    with ranking_db('one') as db:
        p = db.scalar(select(Profile)); p.years_experience = 3.0
        original = db.scalar(select(Job))
        normal = add_job(db, original, 'normal', 'Software Engineer')
        student = add_job(db, original, 'student', 'Student Software Engineer')
        settings = service.get_settings(db)
        for j in (original, normal, student):
            service.persist_v2_result(db, j, p, settings, context=build_match_context(p))
        ids = (original.id, normal.id, student.id)
        db.commit()
        before = {r.job_id: (r.evaluated_at, r.result_json) for r in db.scalars(select(JobRanking))}
    with ranking_db('one') as db:
        p = db.scalar(select(Profile))
        loaded = []
        @event.listens_for(db, 'loaded_as_persistent')
        def loaded_job(session, instance):
            if isinstance(instance, Job): loaded.append(instance.id)
        main._apply_profile_changes(p, {'excluded_keywords': ['senior', 'student']}, db,
                                    replace_application_profile=False, audit_scope='test')
        assert loaded == [ids[2]]
        for row in db.scalars(select(JobRanking)):
            if row.job_id != ids[2]:
                assert (row.evaluated_at, row.result_json) == before[row.job_id]
            else:
                assert row.eligibility_state == 'excluded'
        # Relaxation again loads just the affected student; its cached score returns.
        loaded.clear()
        main._apply_profile_changes(p, {'excluded_keywords': ['senior']}, db,
                                    replace_application_profile=False, audit_scope='test')
        assert loaded == [ids[2]]
        assert db.scalar(select(JobRanking).where(JobRanking.job_id == ids[2])).score > 0


def test_title_filter_does_not_preserve_invalid_or_other_users_results(ranking_db, monkeypatch):
    monkeypatch.setattr(main.settings, 'auth_mode', 'local')
    with ranking_db('one') as db:
        p = db.scalar(select(Profile)); p.excluded_keywords_json = '[]'
        j = db.scalar(select(Job)); settings = service.get_settings(db)
        service.persist_v2_result(db, j, p, settings)
        # A source edit must still be processed even when its title is unaffected.
        j.description += ' SQL is required.'
        j.source_fingerprint = service.job_fingerprint(j)
        db.commit()
    with ranking_db('two') as db:
        from tests.test_ranking_v2 import profile
        p = profile(); p.user_id = 'two'; db.add(p); db.flush()
        service.persist_v2_result(db, db.scalar(select(Job)), p, service.get_settings(db))
        db.commit()
        row = db.scalar(select(JobRanking))
        other_before = (row.profile_fingerprint, row.evaluated_at, row.result_json)
    with ranking_db('one') as db:
        p = db.scalar(select(Profile))
        main._apply_profile_changes(p, {'excluded_keywords': ['student']}, db,
                                    replace_application_profile=False, audit_scope='test')
        row = db.scalar(select(JobRanking))
        assert row.job_fingerprint == db.scalar(select(Job)).source_fingerprint
        assert not row.stale
    with ranking_db('two') as db:
        row = db.scalar(select(JobRanking))
        assert (row.profile_fingerprint, row.evaluated_at, row.result_json) == other_before


