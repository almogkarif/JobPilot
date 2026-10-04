from contextlib import contextmanager
from datetime import timedelta

import pytest
from fastapi import BackgroundTasks
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session

from app import main
from app.database import Base, set_user_scope
from app.models import AppIdentity, Application, Job, JobRanking, Profile, Source
from app.services import scanner
from app.services.ranking import service
from app.services.seniority import LEVELS
from app.utils import dumps


@pytest.fixture
def preference_queue_db(monkeypatch):
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    monkeypatch.setattr(main.settings, 'auth_mode', 'local')
    @contextmanager
    def user_session(user_id='preference-owner'):
        with Session(engine, expire_on_commit=False) as db:
            set_user_scope(db, user_id)
            yield db
    monkeypatch.setattr(main, 'user_session', user_session)
    dispatched = []
    monkeypatch.setattr(scanner, 'dispatch_application_workflow', dispatched.append)
    with user_session() as db:
        profile = Profile(full_name='Test Applicant', email='test@example.com', phone='0500000000',
            cv_path='/tmp/synthetic-cv.pdf', auto_submit_enabled=True, auto_submit_opt_in_version=1,
            auto_apply_threshold=50, years_experience=3, years_experience_options_json='["3"]',
            seniority_levels_json=dumps(LEVELS), skills_json='["Python"]',
            desired_titles_json='["software engineer"]', preferred_locations_json='["Israel"]',
            application_profile_json='{"degree_level":"bachelor"}')
        db.add_all([profile, AppIdentity(auth_user_id='preference-owner', email='test@example.com', role='admin')])
        source = Source(name='Preference test', kind='greenhouse', identifier='preference-test')
        db.add(source); db.flush()
        for number in range(4):
            opening = Job(source_id=source.id, external_id=str(number), company='Example',
                title='Senior Platform Software Engineer',
                description='Develop Python software. 3 years experience required. Python is required. '
                    'A bachelor degree in Computer Science is required. '
                    'Build reliable services for our software platform, collaborate with the team, '
                    'review software changes and maintain existing applications. '
                    'Investigate production problems and improve application reliability.',
                location='Israel', workplace='hybrid',
                apply_url=f'https://job-boards.greenhouse.io/example/jobs/{number}',
                is_active=number != 1,
                career_track='electrical_engineering' if number == 3 else 'computer_science')
            db.add(opening); db.flush()
            opening.source_fingerprint = service.job_fingerprint(opening)
            if number == 2:
                db.add(Application(job_id=opening.id, status='submitted', mode='auto'))
        db.commit()
    yield user_session, dispatched
    engine.dispose()


@pytest.mark.parametrize('mode', ['local', 'supabase'])
@pytest.mark.parametrize(('field', 'before', 'after'), [
    ('seniority_levels', ['junior', 'unknown'], list(LEVELS)),
    ('years_experience_options', ['0'], ['0', '1', '2', '3', '4', '5+']),
    ('excluded_keywords', ['platform'], []),
])
def test_saved_filter_rechecks_eligible_jobs_and_dispatches_once(preference_queue_db, monkeypatch, mode, field, before, after):
    sessions, dispatched = preference_queue_db
    monkeypatch.setattr(main.settings, 'auth_mode', mode)
    pending = []
    monkeypatch.setattr(main, '_queue_profile_derived_refresh', lambda *args, **kwargs: pending.append((args, kwargs)))
    with sessions() as db:
        profile = db.scalar(select(Profile))
        setattr(profile, f'{field}_json', dumps(before))
        if field == 'years_experience_options':
            profile.years_experience = 0
        main._rescore_v2_jobs(db, profile); db.commit()
        target = db.scalar(select(Job).where(Job.external_id == '0'))
        assert db.scalar(select(JobRanking).where(JobRanking.job_id == target.id)).eligibility_state == 'excluded'
        for change in ({field: after}, {'preferred_locations': ['Israel', 'Haifa']}):
            main._apply_profile_changes(profile, change, db,
                replace_application_profile=False, audit_scope='test', background_tasks=BackgroundTasks())
            while pending:
                args, kwargs = pending.pop(0)
                main._refresh_profile_derived_background(*args, **kwargs)
        db.expire_all()
        row = db.scalar(select(JobRanking).where(JobRanking.job_id == target.id))
        assert row.eligibility_state != 'excluded' and row.score >= profile.auto_apply_threshold
        queued = db.scalars(select(Application).where(Application.status == 'queued')).all()
        assert [application.job_id for application in queued] == [target.id]
        assert dispatched == [queued[0].id]


@pytest.mark.parametrize('invalid', ['profile_digest', 'job_digest', 'profile_changed', 'disabled', 'below_threshold'])
def test_auto_queue_rejects_obsolete_or_ineligible_snapshot(preference_queue_db, invalid):
    sessions, dispatched = preference_queue_db
    with sessions() as db:
        profile = db.scalar(select(Profile))
        main._rescore_v2_jobs(db, profile); db.commit()
        target = db.scalar(select(Job).where(Job.external_id == '0'))
        ranking = db.scalar(select(JobRanking).where(JobRanking.job_id == target.id))
        assert ranking.score >= profile.auto_apply_threshold
        if invalid == 'profile_digest':
            ranking.profile_fingerprint = 'obsolete'
        elif invalid == 'job_digest':
            target.source_fingerprint = 'new-employer-content'
        elif invalid == 'profile_changed':
            db.execute(update(Profile).where(Profile.id == profile.id).values(
                seniority_levels_json='[]', updated_at=profile.updated_at + timedelta(seconds=1),
            ).execution_options(synchronize_session=False))
        elif invalid == 'disabled':
            profile.auto_submit_enabled = False
        else:
            profile.auto_apply_threshold = ranking.score + 1
        db.commit()
        assert scanner.auto_queue_jobs(db, profile) == 0
        assert dispatched == []
