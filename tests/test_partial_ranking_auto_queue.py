"""Unrelated pending rankings cannot starve fresh opted-in admin candidates."""
import pytest
from sqlalchemy import select

import app.main as main
from app.models import AppIdentity, Application, Job, JobRanking, Profile, UserJobState
from app.services import catalog_ranking, scanner
from tests.test_auto_queue_resource_bounds import AUTO_QUEUE, add_resume, queue_reader  # noqa: F401
from tests.test_catalog_ranking_bounds import bounded_ranking  # noqa: F401
from tests.test_canonical_postgres import postgres_cluster  # noqa: F401


def _prepare(queue_reader, monkeypatch, count=2, *, oversized=True, threshold=80):
    _engine, sessions, seed, dispatched = queue_reader
    monkeypatch.setattr(scanner, 'auto_queue_jobs', AUTO_QUEUE)
    with sessions() as db:
        profile = db.scalar(select(Profile))
        profile.auto_apply_threshold = threshold
        db.commit()
    ids = seed(count)
    with sessions() as db:
        pending = db.get(Job, ids[-1])
        if oversized:
            pending.description = 'א' * (128 * 1024)
        ranking = db.scalar(select(JobRanking).where(JobRanking.job_id == pending.id))
        ranking.stale = True
        db.commit()
    return sessions, ids, dispatched


@pytest.mark.parametrize('threshold', [80, 82])
def test_partial_ranking_queues_only_fresh_supported_admin_jobs_at_configured_threshold(
    queue_reader, monkeypatch, threshold,
):
    sessions, ids, dispatched = _prepare(queue_reader, monkeypatch, count=8, threshold=threshold)
    with sessions() as db:
        profile = db.scalar(select(Profile))
        profile.application_password = 'synthetic-saved-password'
        db.scalar(select(JobRanking).where(JobRanking.job_id == ids[0])).score = threshold + 1
        db.scalar(select(JobRanking).where(JobRanking.job_id == ids[1])).score = threshold - 1
        manual = db.get(Job, ids[2])
        manual.company = 'Intel'
        manual.apply_url = 'https://intel.wd1.myworkdayjobs.com/External/job/Israel/Engineer_JR123'
        for job_id, status in zip(ids[3:6], ['submitted', 'failed', 'manual_required']):
            db.add(Application(job_id=job_id, mode='auto', status=status))
        db.add(UserJobState(job_id=ids[6], status='hidden'))
        db.commit()

    result = catalog_ranking.rank_shared_catalog_for_user('one', 'computer_science', stale_only=True)

    assert result['deferred'] == 1 and result['reason'] == 'oversized_rows'
    assert result['auto_queued'] == 1
    with sessions() as db:
        queued = db.scalars(select(Application).where(Application.status == 'queued')).all()
        assert [row.job_id for row in queued] == [ids[0]]
        assert dispatched == [queued[0].id]
        assert {row.status for row in db.scalars(select(Application))} == {
            'queued', 'submitted', 'failed', 'manual_required',
        }
        pending = db.scalar(select(JobRanking).where(JobRanking.job_id == ids[-1]))
        assert pending.stale
    again = catalog_ranking.rank_shared_catalog_for_user('one', 'computer_science', stale_only=True)
    assert again['auto_queued'] == 0 and len(dispatched) == 1


@pytest.mark.parametrize('gate', ['disabled', 'old_opt_in', 'regular_user'])
def test_partial_ranking_preserves_unattended_permission_gates(queue_reader, monkeypatch, gate):
    sessions, _ids, dispatched = _prepare(queue_reader, monkeypatch)
    with sessions() as db:
        profile = db.scalar(select(Profile))
        if gate == 'disabled':
            profile.auto_submit_enabled = False
        elif gate == 'old_opt_in':
            profile.auto_submit_opt_in_version = 0
        else:
            db.scalar(select(AppIdentity)).role = 'user'
        db.commit()

    result = catalog_ranking.rank_shared_catalog_for_user('one', 'computer_science', stale_only=True)

    assert result['deferred'] == 1 and result['auto_queued'] == 0
    assert not dispatched
    with sessions() as db:
        assert db.scalar(select(Application.id)) is None


@pytest.mark.parametrize('gate', ['daily_catalog_byte_limit', 'resume_skills_row_limit'])
def test_ranking_budget_or_unreadable_default_cv_still_stops_enqueue(queue_reader, monkeypatch, gate):
    sessions, _ids, dispatched = _prepare(queue_reader, monkeypatch, oversized=False)
    if gate == 'daily_catalog_byte_limit':
        monkeypatch.setattr(catalog_ranking, 'reserve_catalog_egress', lambda _size: False)
    else:
        add_resume(sessions, skills='א' * (128 * 1024), is_default=True)
    monkeypatch.setattr(scanner, 'auto_queue_jobs',
                        lambda *_args: pytest.fail('Budget or unreadable CV must prevent queue reads'))

    result = catalog_ranking.rank_shared_catalog_for_user('one', 'computer_science', stale_only=True)

    assert result['deferred'] == 1 and result['reason'] == gate
    assert result['auto_queued'] == 0 and not dispatched
    with sessions() as db:
        assert db.scalar(select(Application.id)) is None


def test_partial_ranking_cannot_bypass_the_queue_shared_transfer_budget(queue_reader, monkeypatch):
    _sessions, _ids, dispatched = _prepare(queue_reader, monkeypatch)
    reservations, queue_deferrals = [], []
    monkeypatch.setattr(catalog_ranking, 'reserve_catalog_egress',
                        lambda size: reservations.append(size) or False)

    def queue(db, profile):
        result = AUTO_QUEUE(db, profile)
        queue_deferrals.append(db.info.get('auto_queue_deferred', {}).get('reason'))
        return result

    monkeypatch.setattr(scanner, 'auto_queue_jobs', queue)
    result = catalog_ranking.rank_shared_catalog_for_user('one', 'computer_science', stale_only=True)

    assert result['reason'] == 'oversized_rows' and result['auto_queued'] == 0
    assert queue_deferrals == ['daily_catalog_byte_limit']
    assert len(reservations) == 1 and reservations[0] > 0
    assert not dispatched


def _background_rank(sessions, monkeypatch):
    monkeypatch.setattr(main, 'user_session', sessions)
    monkeypatch.setattr(main, '_profile_refresh_progress', {})
    summaries = []
    original = main._rescore_v2_jobs
    def rescore(*args, **kwargs):
        result = original(*args, **kwargs)
        summaries.append(result)
        return result
    monkeypatch.setattr(main, '_rescore_v2_jobs', rescore)
    main._refresh_profile_derived_background(
        'one', 'computer_science', rescore_jobs=False, rank_v2=True,
    )
    assert len(summaries) == 1
    return summaries[0]


def test_preference_background_partial_ranking_queues_fresh_candidate_without_waiting_for_oversized_row(
    queue_reader, monkeypatch,
):
    sessions, ids, dispatched = _prepare(queue_reader, monkeypatch)

    summary = _background_rank(sessions, monkeypatch)

    assert summary['deferred'] == 1 and summary['reason'] == 'oversized_rows'
    with sessions() as db:
        queued = db.scalars(select(Application)).all()
        assert [row.job_id for row in queued] == [ids[0]]
        assert dispatched == [queued[0].id]
        assert db.scalar(select(JobRanking.stale).where(JobRanking.job_id == ids[-1]))
    assert summary['auto_queue_allowed'] is True
    main._refresh_profile_derived_background(
        'one', 'computer_science', rescore_jobs=False, rank_v2=True,
    )
    assert len(dispatched) == 1


@pytest.mark.parametrize('gate', [
    'daily_catalog_byte_limit', 'resume_skills_row_limit', 'refresh_byte_limit',
])
def test_preference_background_budget_or_unreadable_default_cv_prevents_queue_reads(
    queue_reader, monkeypatch, gate,
):
    sessions, _ids, dispatched = _prepare(queue_reader, monkeypatch, oversized=False)
    if gate == 'daily_catalog_byte_limit':
        monkeypatch.setattr(catalog_ranking, 'reserve_catalog_egress', lambda _size: False)
    elif gate == 'resume_skills_row_limit':
        add_resume(sessions, skills='א' * (128 * 1024), is_default=True)
    else:
        # This reason can mean an unreadable CV, not only an incomplete job page.
        add_resume(sessions, skills='["python"]', is_default=True)
        monkeypatch.setattr(catalog_ranking, 'MAX_RANKING_REFRESH_BYTES', 1000)
    monkeypatch.setattr(scanner, 'auto_queue_jobs',
                        lambda *_args: pytest.fail('Budget or unreadable CV must prevent queue reads'))

    summary = _background_rank(sessions, monkeypatch)

    assert summary['deferred'] == 1 and summary['reason'] == gate
    assert summary['auto_queue_allowed'] is False
    assert not dispatched
    with sessions() as db:
        assert db.scalar(select(Application.id)) is None


def test_preference_background_partial_ranking_reuses_queue_transfer_reservation(queue_reader, monkeypatch):
    sessions, _ids, dispatched = _prepare(queue_reader, monkeypatch)
    reservations, queue_deferrals = [], []
    monkeypatch.setattr(catalog_ranking, 'reserve_catalog_egress',
                        lambda size: reservations.append(size) or False)
    def queue(db, profile):
        count = AUTO_QUEUE(db, profile)
        queue_deferrals.append(db.info.get('auto_queue_deferred', {}).get('reason'))
        return count
    monkeypatch.setattr(scanner, 'auto_queue_jobs', queue)

    summary = _background_rank(sessions, monkeypatch)

    assert summary['deferred'] == 1 and summary['reason'] == 'oversized_rows'
    assert queue_deferrals == ['daily_catalog_byte_limit']
    assert len(reservations) == 1 and reservations[0] > 0
    assert not dispatched


def test_preference_background_without_ranking_preserves_existing_queue_behavior(queue_reader, monkeypatch):
    sessions, ids, dispatched = _prepare(queue_reader, monkeypatch)
    monkeypatch.setattr(main, 'user_session', sessions)
    monkeypatch.setattr(main, '_rescore_v2_jobs',
                        lambda *_args, **_kwargs: pytest.fail('No ranking was requested'))

    main._refresh_profile_derived_background('one', 'computer_science', rescore_jobs=False)

    with sessions() as db:
        queued = db.scalars(select(Application)).all()
        assert [row.job_id for row in queued] == [ids[0]]
        assert dispatched == [queued[0].id]
