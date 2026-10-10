"""Account handoffs must not store credentials as reusable application answers."""
import pytest
from sqlalchemy import func, select

from app.database import set_user_scope
from app.models import AnswerMemory, Application, Blocker
from tests.test_guided_submission_admin_gate import guided_gate_api, headers


@pytest.mark.parametrize('kind', [
    'email_verification_required', 'account_creation_failed', 'account_validation_required',
])
def test_account_blocker_rejects_answer_memory_and_automatic_requeue(guided_gate_api, kind):
    ctx = guided_gate_api
    application_id = ctx.applications['member']
    with ctx.sessions() as db:
        set_user_scope(db, 'guided-gate-member')
        application = db.get(Application, application_id)
        application.status = 'needs_input'
        application.answers_json = '{}'
        blocker = Blocker(application_id=application_id, kind=kind,
                          field_label='Candidate account', question='Candidate account verification')
        db.add(blocker)
        db.commit()
        blocker_id = blocker.id

    response = ctx.client.post(f'/api/blockers/{blocker_id}/resolve', headers=headers('member'), json={
        'answer': 'Synthetic credential that must never become an answer', 'remember': True,
    })
    assert response.status_code == 409, response.text
    with ctx.sessions() as db:
        set_user_scope(db, 'guided-gate-member')
        application = db.get(Application, application_id)
        blocker = db.get(Blocker, blocker_id)
        assert application.status == 'needs_input' and application.answers_json == '{}'
        assert blocker.status == 'open' and blocker.answer == '' and not blocker.remember_answer
        assert db.scalar(select(func.count()).select_from(AnswerMemory)) == 0
    assert ctx.dispatches == []
