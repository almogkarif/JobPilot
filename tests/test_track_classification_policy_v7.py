from types import SimpleNamespace
import pytest
from app.services.track_classification import classify_job, degree_clauses, CS, EE, IE

BASE='Work with multiple teams to investigate requirements, document results and deliver reliable outcomes for the organization. '

@pytest.mark.parametrize('title,body,expected',[
 ('Senior FinOps Engineer','Analyze cloud costs, budgets and forecasts. Use Python and Terraform.',(IE,)),
 ('Supplier NPI Electronics Engineering Manager','Responsibilities: Maintain supplier processes.\nElectrical Engineering degree - Must.',(EE,)),
 ('Retail Specialist',"Responsibilities: Manage partner accounts.\nBachelor's degree in Industrial Engineering or Economics - mandatory.",(IE,)),
 ('Senior Agentic Systems Engineer','Build developer tools and integrations.',(CS,)),
 ('Staff Engineer','As a Staff Software Engineer, build software systems and backend systems.',(CS,)),
 ('Validation Engineer','Work as a Software Quality Assurance engineer, testing applications.',(CS,)),
 ('Aerodynamic Design Engineer','Requirements: תואר ראשון באווירונאוטיקה או מכונות - חובה',()),
 ('Procurement Manager','Requirements: Degree in Engineering or Industrial Engineering.',(EE,IE)),
])
def test_audit_regressions(title,body,expected):
 r=classify_job(SimpleNamespace(title=title,description=BASE+body))
 assert r.matched_tracks==expected,r.to_dict()

@pytest.mark.parametrize('title,text',[
 ('Senior Silicon Engineer','Senior Silicon Engineer Israel, Multiple Locations, Multiple Locations + 1 more Posted 15 days ago'),
 ('מהנדס.ת חשמל במחלקת הנדסה','מהנדס.ת חשמל במחלקת הנדסה משרה מלאה מכון לשם הוסף למועדפים את: מהנדס.ת חשמל במחלקת הנדסה'),
])
def test_listing_metadata_is_not_a_job_description(title,text):
 r=classify_job(SimpleNamespace(title=title,description=text))
 assert all(d.reasons==('missing_job_content',) for d in r.decisions)


def test_honors_advantage_does_not_weaken_mandatory_degree():
 rows=degree_clauses('Requirements:\nתואר ראשון בהנדסת תעשייה וניהול - חובה (סיום בהצטיינות יתרון משמעותי)')
 assert rows[0]['preferred'] is False
 assert IE in rows[0]['explicit']


def test_degree_in_collaboration_responsibilities_is_not_a_requirement():
 assert not degree_clauses('Responsibilities: Work with colleagues holding a degree in Computer Science to deliver outcomes.')


def test_hebrew_graduate_prefix_preserves_discipline():
 r=classify_job(SimpleNamespace(title='Development Project Lead',description=BASE+'\nRequirements:\nמהנדס תעשייה וניהול או תואר ראשון'))
 assert IE in r.matched_tracks


import json
from pathlib import Path

REAL = json.loads((Path(__file__).parent / 'fixtures/track_classification/audit_real_jobs_v7.json').read_text())

@pytest.mark.parametrize('case', REAL, ids=lambda case: str(case['id']))
def test_reviewed_snapshot_examples(case):
    result=classify_job(SimpleNamespace(title=case['title'],description=case['description']))
    assert set(result.matched_tracks)==set(case['matches']),result.to_dict()
