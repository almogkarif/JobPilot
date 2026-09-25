import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.track_classification import classify_job, TRACKS, MAX_DESCRIPTION_CHARS

GOLD = json.loads((Path(__file__).parent / 'fixtures/track_classification/gold.json').read_text())


@pytest.mark.parametrize('case', GOLD, ids=lambda case: case['id'])
def test_manually_labeled_role_and_requirement_cases(case):
    result = classify_job(SimpleNamespace(title=case['title'], description=case['description']))
    assert set(result.matched_tracks) == set(case['matches']), result.to_dict()
    decisions = {row.track: row for row in result.decisions}
    for track in case.get('forbidden', []):
        assert decisions[track].status == 'outside', result.to_dict()
    for track in case.get('review', []):
        assert decisions[track].status == 'review', result.to_dict()


def test_truncated_input_never_automatically_admits_a_job():
    for description, truncated in [('x' * (MAX_DESCRIPTION_CHARS + 1), False), ('software engineer', True)]:
        result = classify_job(SimpleNamespace(title='Software Engineer', description=description, input_truncated=truncated))
        assert result.matched_tracks == ()
        assert all(item.status == 'review' for item in result.decisions)


def test_company_source_track_and_user_preferences_cannot_affect_classification():
    row = GOLD[1]
    for track in TRACKS:
        job = SimpleNamespace(title=row['title'], description=row['description'], company='GE HealthCare', career_track=track, score=100)
        assert set(classify_job(job).matched_tracks) == set(row['matches'])


def test_bare_qualifications_heading_ends_responsibilities_section():
    description = """What You'll Do
Analyze data and work with stakeholders on reports and business decisions across the organization.
Qualifications
Required Bachelor's degree in Industrial Engineering.
Nice to Have
Experience in mechanical engineering teams."""
    result = classify_job(SimpleNamespace(title='Total Rewards Analyst', description=description))
    assert result.matched_tracks == ('industrial_engineering',)


def test_generic_engineering_degree_admits_all_tracks_by_user_policy():
    description = """Develop distributed data pipelines and maintain production software. Build services and tools for data ingestion.
Requirements: BSc in Computer Science, Engineering or a related field."""
    result = classify_job(SimpleNamespace(title='Data Engineer', description=description))
    assert result.matched_tracks == TRACKS


REAL_JOBS = json.loads((Path(__file__).parent / 'fixtures/track_classification/real_jobs.json').read_text())


@pytest.mark.parametrize('case', REAL_JOBS, ids=lambda case: case['id'])
def test_reviewed_real_job_descriptions(case):
    result = classify_job(SimpleNamespace(title=case['title'], description=case['description']))
    assert set(result.matched_tracks) == set(case['matches']), (case['basis'], result.to_dict())


def test_unknown_role_family_goes_to_review_instead_of_silent_rejection():
    result = classify_job(SimpleNamespace(title='Strategy Specialist', description='Lead product strategy and collaborate across teams to understand customer needs and deliver a roadmap.'))
    assert all(row.status == 'review' for row in result.decisions)


@pytest.mark.parametrize('title', ['Full Stack Developer Agentic AI', 'Backend Developer', 'Data Scientist', 'QA Automation Engineer', 'Technical Product Manager'])
@pytest.mark.parametrize('requirement', [
    'BSc or MSc in Computer Science, Computer Engineering, Electrical Engineering, or related fields.',
    'תואר ראשון במדעי המחשב או בהנדסת חשמל - חובה.',
    'BSc in Electrical Engineering or equivalent practical experience.',
])
def test_explicit_ee_degree_admits_software_and_other_roles(title, requirement):
    description = 'Build reliable software services, analyze requirements and collaborate with teams to deliver products to customers.\nRequirements:\n' + requirement
    result = classify_job(SimpleNamespace(title=title, description=description))
    decision = next(item for item in result.decisions if item.track == 'electrical_engineering')
    assert decision.status == 'match'
    assert decision.reasons == ('accepted_ee_degree',)
    assert decision.evidence


def test_working_with_electrical_engineers_is_not_an_accepted_degree():
    description = '''Build frontend applications and backend services for electrical engineering teams. Develop software and maintain production systems.
Requirements: BSc in Computer Science or Software Engineering.'''
    assert classify_job(SimpleNamespace(title='Full Stack Developer', description=description)).matched_tracks == ('computer_science',)


def test_ee_degree_does_not_override_an_independent_mandatory_conflicting_degree():
    description = '''Develop software and coordinate delivery of complex systems across teams, working with product stakeholders.
Requirements:
BSc in Electrical Engineering.
Master's degree in Computer Science is required.'''
    decision = next(item for item in classify_job(SimpleNamespace(title='Software Engineer', description=description)).decisions if item.track == 'electrical_engineering')
    assert decision.status == 'outside'
    assert decision.reasons == ('required_degree_conflict',)


def test_software_degree_list_without_electrical_does_not_gain_ee_admission():
    description = '''Build and maintain software services, implement reliable APIs and automated tests, and collaborate with product teams.
Requirements: BSc in Computer Science or Computer Engineering.'''
    assert classify_job(SimpleNamespace(title='Software Engineer', description=description)).matched_tracks == ('computer_science',)
