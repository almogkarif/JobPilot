"""Account-owned appearance is independent of search tracks and ranking."""
import json

import pytest
from sqlalchemy import inspect, select, text

import app.main as main
from app.database import set_user_scope, _add_runtime_compatibility_columns
from app.models import Profile
from app.services.career_tracks import CAREER_TRACK_BY_KEY
from tests.test_application_tracking_access import personal_tracking


DEFAULTS = {key: key for key in CAREER_TRACK_BY_KEY}
CS, IE, EE = 'computer_science', 'industrial_engineering', 'electrical_engineering'


def test_palette_persists_per_account_and_track_without_profile_or_ranking_changes(personal_tracking, monkeypatch):
    client, factory, _ = personal_tracking
    monkeypatch.setattr(main, '_career_track_stats', lambda *a, **kw: {key: {} for key in DEFAULTS})
    monkeypatch.setattr(main, 'install_recommended_sources', lambda *a, **kw: None)
    monkeypatch.setattr(main, '_rescore_v2_jobs', lambda *a, **kw: pytest.fail('Palette must not rescore jobs'))
    headers = {'Authorization': 'alpha'}
    assert client.get('/api/career-tracks', headers=headers).json()['color_palettes'] == DEFAULTS
    with factory() as db:
        set_user_scope(db, 'alpha')
        profile = db.scalar(select(Profile))
        before = {column.name: getattr(profile, column.name) for column in Profile.__table__.columns if column.name != 'color_palettes_json'}
    for track, palette in [(IE, EE), (CS, IE), (EE, CS)]:
        response = client.put('/api/settings/palette', headers=headers, json={'track': track, 'palette': palette})
        assert response.status_code == 200, response.text
    expected = {IE: EE, CS: IE, EE: CS}
    # Separate requests/sessions read durable preferences, never local browser storage.
    assert client.get('/api/career-tracks', headers=headers).json()['color_palettes'] == expected
    assert client.get('/api/career-tracks', headers={'Authorization': 'beta'}).json()['color_palettes'] == DEFAULTS
    with factory() as db:
        set_user_scope(db, 'alpha')
        profile = db.scalar(select(Profile))
        assert json.loads(profile.color_palettes_json) == expected
        assert {key: getattr(profile, key) for key in before} == before
        assert 'color_palettes' not in main._agent_profile_dict(profile)
    for track in (IE, EE, CS):
        response = client.put('/api/career-tracks/active', headers=headers, json={'track': track})
        assert response.status_code == 200, response.text
        assert response.json()['active_track'] == track
        assert response.json()['color_palettes'] == expected


@pytest.mark.parametrize('payload', [
    {'track': 'unknown', 'palette': EE}, {'track': IE, 'palette': 'red'},
    {'track': IE, 'palette': EE, 'user_id': 'beta'}, {'track': IE},
])
def test_palette_rejects_invalid_values_and_ownership_overrides(personal_tracking, payload):
    client, _, _ = personal_tracking
    response = client.put('/api/settings/palette', headers={'Authorization': 'alpha'}, json=payload)
    assert response.status_code == 422


def test_palette_requires_signed_in_account(personal_tracking):
    client, _, _ = personal_tracking
    payload = {'track': CS, 'palette': EE}
    assert client.put('/api/settings/palette', json=payload).status_code == 401
    assert client.put('/api/settings/palette', headers={'Authorization': 'guest'}, json=payload).status_code == 403


def test_existing_database_gains_palette_default_without_changing_user_data(personal_tracking):
    _, _, engine = personal_tracking
    with engine.begin() as connection:
        before = connection.execute(text('SELECT id, user_id, full_name, updated_at FROM profiles')).all()
        connection.execute(text('ALTER TABLE profiles DROP COLUMN color_palettes_json'))
        for _ in range(2):
            columns = {column['name'] for column in inspect(connection).get_columns('profiles')}
            _add_runtime_compatibility_columns(connection, 'profiles', columns)
        assert connection.execute(text('SELECT id, user_id, full_name, updated_at FROM profiles')).all() == before
        assert set(connection.execute(text('SELECT color_palettes_json FROM profiles')).scalars()) == {'{}'}


@pytest.mark.parametrize('raw', [None, 'null', '[]', '{"computer_science": []}', '{"electrical_engineering":"unknown"}'])
def test_old_or_invalid_palette_data_falls_back_to_track_defaults(raw):
    assert main._color_palettes(raw) == DEFAULTS
