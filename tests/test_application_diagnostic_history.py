"""A prior form question is not the cause of a newer document-delivery failure."""
import json
from datetime import timedelta
from pathlib import Path
import subprocess

import pytest
from sqlalchemy import select

from app.database import set_user_scope
from app.models import Application, ApplicationAttempt, ApplicationEvent, Blocker, utcnow
from app.utils import dumps
from tests.test_job_id_search import job_search_catalog


@pytest.mark.parametrize('observed_in_latest_attempt', [False, True])
def test_diagnostics_use_newest_blocker_and_distinguish_prior_attempts(job_search_catalog, observed_in_latest_attempt):
    client, _, factory = job_search_catalog
    now = utcnow()
    with factory() as db:
        set_user_scope(db, 'local-owner')
        application = Application(job_id=2398, status='failed', mode='auto',
                                  originating_track='computer_science', last_error='Resume unavailable HTTP 503')
        db.add(application)
        db.flush()
        db.add_all([
            Blocker(application_id=application.id, kind='unknown_field', question='Older question', created_at=now-timedelta(days=4)),
            Blocker(application_id=application.id, kind='submit_not_sent', question='Visa sponsorship?',
                    explanation='Prior form validation failed', created_at=now-timedelta(days=2)),
            Blocker(application_id=application.id, kind='sign_in_failed', question='Resolved question',
                    status='resolved', created_at=now),
        ])
        attempt = ApplicationAttempt(application_id=application.id, attempt_number=3,
            idempotency_key='diagnostic-history', status='failed', error=application.last_error,
            started_at=now-timedelta(minutes=1), finished_at=now)
        db.add(attempt)
        db.flush()
        if observed_in_latest_attempt:
            db.add(ApplicationEvent(application_id=application.id, event_type='blocked', created_at=now,
                details_json=dumps({'kind':'submit_not_sent', 'attempt_id':attempt.id,
                                   'diagnostics':{'invalid_fields':['Visa sponsorship?']}})))
        db.commit()
        application_id = application.id
    response = client.get('/api/applications/failure-diagnostics', params={'application_id':application_id})
    assert response.status_code == 200, response.text
    row = response.json()['applications'][0]
    assert row['yellow_question']['question'] == 'Visa sponsorship?'
    assert row['blocker_is_historical'] is not observed_in_latest_attempt
    assert row['red_error']['last_error'] == 'Resume unavailable HTTP 503'
    assert row['red_error']['explanation'] == 'Prior form validation failed'
    with factory() as db:
        set_user_scope(db, 'local-owner')
        assert len(db.scalars(select(Blocker).where(Blocker.status=='open')).all()) == 2


@pytest.mark.parametrize('historical', [False, True])
def test_diagnostic_copy_labels_historical_question_separately(historical):
    javascript = (Path(__file__).parents[1] / 'app/static/app.js').read_text()
    functions = javascript[javascript.index('function compactDiagnosticValue'):javascript.index('async function copyApplicationFailureDiagnostics')]
    row = {'company':'Fixture', 'yellow_question':{'question':'Old question'},
           'red_error':{'explanation':'Form validation', 'last_error':'Resume HTTP 503'},
           'blocker_is_historical':historical}
    result = subprocess.run(['node','-e', functions + '\nprocess.stdout.write(applicationDiagnosticText(' + json.dumps(row) + ',0));'],
                            capture_output=True, text=True, check=True).stdout
    assert 'RED_ERROR raw: Resume HTTP 503' in result
    if historical:
        assert 'HISTORICAL_QUESTION text: Old question' in result
        assert 'HISTORICAL_BLOCKER explanation: Form validation' in result
        assert 'YELLOW_QUESTION text:' not in result
    else:
        assert 'YELLOW_QUESTION text: Old question' in result
        assert 'RED_ERROR explanation: Form validation' in result
