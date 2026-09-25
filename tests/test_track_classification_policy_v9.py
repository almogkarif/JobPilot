import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from app.services.track_classification import classify_job, degree_clauses, CS, EE

CASES=json.loads((Path(__file__).parent/'fixtures/track_classification/recovered_v9.json').read_text())

@pytest.mark.parametrize('case',CASES,ids=lambda c:str(c['id']))
def test_recovered_role_and_degree(case):
    result=classify_job(SimpleNamespace(**case))
    assert result.matched_tracks==(case['track'],)
    assert all(d.status!='review' for d in result.decisions)
    assert next(d.degree_color for d in result.decisions if d.track==case['track'])==case['color']

@pytest.mark.parametrize('degree',['Electrical / communication Engineering','Mechanical, Electrical, or Mechatronics Engineering'])
def test_shared_engineering_noun_keeps_preferred_status(degree):
    rows=degree_clauses('Preferred qualifications:\nBachelor degree in '+degree+' is an advantage.')
    assert any(EE in row['explicit'] and row['preferred'] for row in rows)

def test_unrelated_electrical_work_is_not_an_accepted_degree():
    rows=degree_clauses('Bachelor degree in Mechanical Engineering.\nExperience with electrical equipment and communication systems.')
    assert not any(EE in row['explicit'] for row in rows)

def test_it_integration_with_scripting_is_not_software_development():
    result=classify_job(SimpleNamespace(title='IT Integration Team Leader',description='Manage Linux administration, physical servers, network operations and systems integration. Python and automation experience required. Maintain Active Directory and support IT users.'))
    assert CS not in result.matched_tracks
