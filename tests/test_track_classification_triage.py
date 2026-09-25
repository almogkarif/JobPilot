"""Regressions found while reviewing v3's unresolved rows."""
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from app.services.track_classification import classify_job, CS, EE, IE

CASES = json.loads((Path(__file__).parent/'fixtures/track_classification/triage_real_jobs.json').read_text())

@pytest.mark.parametrize('case', CASES, ids=lambda c: str(c['id']))
def test_real_requirement_parsing(case):
    result=classify_job(SimpleNamespace(**case))
    assert result.matched_tracks==tuple(case['expected_tracks']), result.to_dict()
    for track,color in case['expected_colors'].items():
        decision=next(d for d in result.decisions if d.track==track)
        assert decision.degree_color==color
    assert all(d.status!='review' for d in result.decisions)

@pytest.mark.parametrize('requirement', ['Ph.D. in Statistics is required.', 'BSc in Mathematics or Statistics.', 'תואר ראשון במתמטיקה או סטטיסטיקה - חובה'])
def test_data_scientist_other_mandatory_degree_is_excluded(requirement):
    job=SimpleNamespace(title='Data Scientist',description='Develop machine learning models and analyze datasets with Python and SQL for business applications.\nRequirements:\n'+requirement)
    assert classify_job(job).matched_tracks==()

@pytest.mark.parametrize('title,description', [('Senior Software Engineer','Apply now'),('Bb661a53 79b8 459d A8df 5dd419d62596','Apply now')])
def test_missing_content_is_data_issue_not_track_policy(title,description):
    result=classify_job(SimpleNamespace(title=title,description=description))
    assert result.matched_tracks==()
    assert all(d.reasons==('missing_job_content',) for d in result.decisions)


def test_academic_shorthand_does_not_read_colleagues_as_required_degree():
    job=SimpleNamespace(title='Backend Developer',description='Develop software services and maintain production APIs for our customers.\nResponsibilities:\nWork with CS and EE teams.\nמהנדס תעשייה וניהול מוביל את צוות הלקוחות.\nRequirements:\nPython experience and knowledge of REST APIs.')
    result=classify_job(job)
    assert result.matched_tracks==(CS,)
    assert all(d.degree_color!='green' for d in result.decisions)


def test_it_operations_without_development_is_not_cs():
    job=SimpleNamespace(title='Data Center Engineer, HPC and AI', description="""Operate infrastructure, install servers and troubleshoot Linux, storage and networking for the data center.
Requirements: MCSE or MCITP/CCNA certification. Three years of lab management experience.
Preferred Qualifications: Scripting experience in Bash and/or Python.""")
    result=classify_job(job)
    assert result.matched_tracks==()
    assert next(d for d in result.decisions if d.track==CS).reasons==('nondevelopment_it_operations',)


def test_development_devops_is_not_excluded_as_it_operations():
    job=SimpleNamespace(title='Senior DevOps Engineer',description='Develop automation frameworks and software tools in Python, implement CI/CD pipelines and maintain reliable production infrastructure.')
    assert classify_job(job).matched_tracks==(CS,)


def test_hebrew_data_analyst_with_sql_and_dashboards_is_shared():
    job=SimpleNamespace(title='אנליסט/ית ניתוח ותכנון',description='ניתוח נתונים עסקיים, פיתוח דוחות ודשבורדים להנהלת החברה ועבודה עם מאגרי מידע וכלי אנליזה מתקדמים.\nדרישות:\nתואר ראשון רלוונטי - חובה\nניסיון ב-SQL וב-SAS - חובה')
    result=classify_job(job)
    assert result.matched_tracks==(CS,IE)
    assert all(d.degree_color=='red' for d in result.decisions)
