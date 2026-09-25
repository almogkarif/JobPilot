"""User decisions from the classification review, 2026-09-16."""
from types import SimpleNamespace
import pytest
from app.services.track_classification import classify_job, CS, EE, IE

@pytest.mark.parametrize('title,requirement,tracks,colors', [
 ('Backend Developer', 'BSc in Industrial Engineering.', (IE,), ('yellow','red','green')),
 ('Backend Developer', 'BSc in Engineering.', (CS,EE,IE), ('yellow','yellow','yellow')),
 ('Backend Developer', 'BSc in Computer Science or a related field.', (CS,EE,IE), ('green','yellow','yellow')),
 ('Backend Developer', 'BSc in Computer Science.', (CS,), ('green','red','red')),
 ('Backend Developer', '', (CS,), ('yellow','red','red')),
 ('Backend Developer', "Bachelor's degree.", (CS,), ('yellow','red','red')),
 ('Data Analyst', '', (CS,IE), ('red','red','red')),
 ('Data Analyst', 'BSc in Economics or Statistics.', (), ('red','red','red')),
 ('Data Analyst', 'Preferred Qualifications: BSc in Economics or Statistics.', (CS,IE), ('red','red','red')),
 ('Data Analyst', 'BSc in Industrial Engineering.', (IE,), ('red','red','green')),
 ('Data Analyst', "Bachelor's degree.", (CS,IE), ('red','red','red')),
 ('Quality Engineer', 'BSc in Mechanical Engineering.', (), ('red','red','red')),
 ('Quality Engineer', '', (IE,), ('red','red','red')),
 ('Hardware Engineer', '', (EE,), ('red','red','red')),
 ('Firmware Engineer', '', (CS,EE), ('yellow','red','red')),
 ('Backend Developer', 'BSc in Computer Science or equivalent practical experience.', (CS,), ('green','yellow','yellow')),
 ('Hardware Engineer', 'BSc in Electrical Engineering or a related field.', (CS,EE,IE), ('yellow','green','yellow')),
 ('Supply Chain Analyst', 'BSc in Industrial Engineering or a related field.', (IE,), ('red','red','green')),
 ('Data Analyst', 'BSc in Industrial Engineering preferred.', (CS,IE), ('red','red','yellow')),
])
def test_agreed_track_and_degree_policy(title, requirement, tracks, colors):
    description = 'Improve production processes and quality, analyze data, support supply chain and process improvement across teams.\nRequirements:\n' + requirement
    result = classify_job(SimpleNamespace(title=title,description=description))
    assert result.matched_tracks == tracks, result.to_dict()
    assert tuple(d.degree_color for d in result.decisions) == colors

@pytest.mark.parametrize('title,degree,track', [('Backend Developer','Computer Science',CS),('Hardware Engineer','Electrical Engineering',EE),('Supply Chain Analyst','Industrial Engineering',IE)])
def test_preferred_and_experience_alternative_degree_colors(title,degree,track):
    for suffix,color in [(' preferred.','yellow'),(' or equivalent practical experience.','green')]:
        result=classify_job(SimpleNamespace(title=title,description='Develop products and improve processes with cross-functional teams, maintaining quality and reliable delivery.\nRequirements:\nBSc in '+degree+suffix))
        decision=next(d for d in result.decisions if d.track==track)
        assert decision.degree_color==color
        assert decision.degree_evidence
