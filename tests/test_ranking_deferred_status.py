"""A paused budget is visible without hydrating jobs, and clears after catch-up."""
from sqlalchemy import event, select

from app import main
from app.models import Job, JobRanking, Profile
from tests.test_catalog_ranking_bounds import bounded_ranking
from tests.test_canonical_postgres import postgres_cluster
from tests.test_ranking_profile_bounds import cloud_profile_ranking


def test_status_exposes_deferral_and_clears_it_after_actual_backlog_drains(cloud_profile_ranking):
    engine, sessions, add_jobs = cloud_profile_ranking
    add_jobs(2)
    key = ('one', 'computer_science')
    main._set_ranking_refresh_progress(*key, phase='deferred', completed=0, total=2,
                                      deferred=2, reason='daily_catalog_byte_limit')
    loaded = []
    event.listen(main.Session, 'loaded_as_persistent', record := lambda _db, obj:
                 loaded.append(obj.id) if isinstance(obj, (Job, JobRanking)) else None)
    try:
        with sessions() as db:
            result = main.personal_ranking_status(db=db)
    finally:
        event.remove(main.Session, 'loaded_as_persistent', record)
    assert result['phase'] == 'deferred' and not result['running'] and not result['ready']
    assert result['deferred'] == 2 and result['reason'] == 'daily_catalog_byte_limit'
    assert not loaded
    with sessions() as db:
        main._rescore_v2_jobs(db, db.scalar(select(Profile)))
        db.commit()
    # Scheduled ranking does not have to alter old in-process UI progress.
    with sessions() as db:
        result = main.personal_ranking_status(db=db)
    assert result['ready'] and result['phase'] == 'complete'
    assert result['deferred'] == 0 and result['reason'] == '' and result['message'] == ''
