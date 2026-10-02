from pathlib import Path

import pytest
from datetime import datetime, timezone
from types import SimpleNamespace
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.auth import AuthIdentity
from app.database import Base
from app.models import AppIdentity
import app.main as main


JS = (Path(__file__).resolve().parents[1] / "app/static/app.js").read_text()


def test_developer_users_distinguish_login_from_background_activity():
    assert "כניסה אחרונה" in JS
    assert "u.last_login_at||u.claimed_at" in JS
    assert "פעילות" in JS
    assert "developerDate(u.last_seen_at)" in JS


@pytest.fixture
def activity_roster():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        # Logins deliberately disagree with activity order. Ties remain stable.
        for id, seen, login in [(1, 1, 5), (2, 5, 1), (3, 3, 4), (4, 3, 2)]:
            db.add(AppIdentity(id=id, auth_user_id=f'user-{id}', email=f'{id}@example.com',
                               last_seen_at=datetime(2026, 10, seen, tzinfo=timezone.utc),
                               last_login_at=datetime(2026, 10, login, tzinfo=timezone.utc)))
        db.commit()
        yield db
    engine.dispose()


def test_developer_users_are_ordered_by_latest_activity(activity_roster):
    request = SimpleNamespace(state=SimpleNamespace(identity=AuthIdentity('owner', 'owner@example.com', role='admin')))
    payload = main.admin_users(request, activity_roster)
    assert [user['id'] for user in payload['users']] == ['user-2', 'user-3', 'user-4', 'user-1']
    assert payload['users'][0]['last_login_at'].day == 1
    assert payload['count'] == 4
