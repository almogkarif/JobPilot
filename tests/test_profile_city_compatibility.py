from fastapi.testclient import TestClient
from app.main import app, _autofill_profile_from_resume, _profile_dict
from app.models import Profile
from app.utils import loads
from agent.fields import known_value


def test_resume_location_populates_address_city_without_replacing_existing_location():
    profile = Profile(location='Haifa, Israel', skills_json='[]', application_profile_json='{}')
    _autofill_profile_from_resume(profile, {'detected_profile': {'location': 'Tel Aviv, Israel'}})
    assert loads(profile.application_profile_json, {})['city'] == 'Haifa'
    assert profile.location == 'Haifa, Israel'


def test_saving_city_updates_legacy_agent_location_but_not_search_preferences():
    with TestClient(app) as client:
        before = client.get('/api/profile').json()
        try:
            response = client.patch('/api/profile', json={'application_profile': {'city': 'Rehovot'}})
            assert response.status_code == 200
            saved = response.json()
            assert saved['location'] == 'Rehovot'
            assert saved['application_profile']['city'] == 'Rehovot'
            assert known_value('Current location', 'text', saved, {}, []).value == 'Rehovot'
            assert saved['preferred_locations'] == before['preferred_locations']
            saved = client.patch('/api/profile', json={'application_profile': {'city': ''}}).json()
            assert saved['location'] == ''
            assert not saved['application_profile'].get('city')
        finally:
            client.patch('/api/profile', json={'application_profile': {'city': before['application_profile'].get('city','')}})
            client.patch('/api/profile', json={'location':before['location']})
