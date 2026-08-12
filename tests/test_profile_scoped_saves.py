from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.services.career_tracks import COMPUTER_SCIENCE, INDUSTRIAL_ENGINEERING


def _switch(client: TestClient, track: str) -> dict:
    response = client.put('/api/career-tracks/active', json={'track': track})
    assert response.status_code == 200, response.text
    return response.json()['profile']


def test_profile_patch_updates_only_supplied_card_fields_and_merges_application_profile():
    with TestClient(app) as client:
        _switch(client, COMPUTER_SCIENCE)
        original = client.get('/api/profile').json()
        original_phone = original['phone']
        original_skills = list(original['skills'])
        original_titles = list(original['desired_titles'])
        original_application = dict(original['application_profile'])
        marker_phone = '0501239876'
        marker_skill = 'ScopedSaveSkill'
        marker_city = 'ScopedSaveCity'

        try:
            response = client.patch('/api/profile', json={'phone': marker_phone})
            assert response.status_code == 200, response.text
            after_contact = response.json()
            assert after_contact['phone'] == marker_phone
            assert after_contact['skills'] == original_skills
            assert after_contact['desired_titles'] == original_titles
            assert after_contact['application_profile'] == original_application

            response = client.patch('/api/profile', json={'skills': [*original_skills, marker_skill]})
            assert response.status_code == 200, response.text
            after_skills = response.json()
            assert marker_skill in after_skills['skills']
            assert after_skills['phone'] == marker_phone
            assert after_skills['desired_titles'] == original_titles
            assert after_skills['application_profile'] == original_application

            response = client.patch('/api/profile', json={'application_profile': {'city': marker_city}})
            assert response.status_code == 200, response.text
            after_city = response.json()
            assert after_city['application_profile']['city'] == marker_city
            for key, value in original_application.items():
                if key != 'city':
                    assert after_city['application_profile'].get(key) == value
            assert marker_skill in after_city['skills']
            assert after_city['phone'] == marker_phone
        finally:
            client.patch('/api/profile', json={
                'phone': original_phone,
                'skills': original_skills,
                'application_profile': {'city': original_application.get('city', '')},
            })


def test_skills_persist_independently_per_career_track_after_partial_saves():
    cs_marker = 'PersistOnlyCS'
    iem_marker = 'PersistOnlyIEM'
    with TestClient(app) as client:
        cs_original = _switch(client, COMPUTER_SCIENCE)
        cs_skills = list(cs_original['skills'])
        iem_original = _switch(client, INDUSTRIAL_ENGINEERING)
        iem_skills = list(iem_original['skills'])

        try:
            _switch(client, COMPUTER_SCIENCE)
            saved_cs = client.patch('/api/profile', json={'skills': [*cs_skills, cs_marker]}).json()
            assert cs_marker in saved_cs['skills']

            _switch(client, INDUSTRIAL_ENGINEERING)
            saved_iem = client.patch('/api/profile', json={'skills': [*iem_skills, iem_marker]}).json()
            assert iem_marker in saved_iem['skills']
            assert cs_marker not in saved_iem['skills']

            restored_cs = _switch(client, COMPUTER_SCIENCE)
            assert cs_marker in restored_cs['skills']
            assert iem_marker not in restored_cs['skills']

            restored_iem = _switch(client, INDUSTRIAL_ENGINEERING)
            assert iem_marker in restored_iem['skills']
            assert cs_marker not in restored_iem['skills']
        finally:
            _switch(client, COMPUTER_SCIENCE)
            client.patch('/api/profile', json={'skills': cs_skills})
            _switch(client, INDUSTRIAL_ENGINEERING)
            client.patch('/api/profile', json={'skills': iem_skills})
            _switch(client, COMPUTER_SCIENCE)
