import json

import pytest

from app.models import Profile
from app.services.resume_analysis import analyze_resume
from app.services.resume_employment import detect_resume_employment


@pytest.mark.parametrize('header,expected', [
    ('Software Engineer at Acme', ('Software Engineer', 'Acme')),
    ('Acme | Data Analyst', ('Data Analyst', 'Acme')),
    ('QA Engineer — Example Ltd', ('QA Engineer', 'Example Ltd')),
    ('חברת דוגמה | מנהל פרויקטים', ('מנהל פרויקטים', 'חברת דוגמה')),
])
def test_employer_and_role_order(header, expected):
    result = detect_resume_employment(f'Work Experience\n{header}\n2020–2023\n• Built dashboards\nEducation\n2015-2019 Some College')
    assert len(result) == 1
    assert (result[0]['job_title'], result[0]['company']) == expected
    assert result[0]['start_date'] == '2020'
    assert result[0]['end_date'] == '2023'
    assert result[0]['description'] == '• Built dashboards'


def test_multiple_roles_dates_and_current_job():
    result = detect_resume_employment('''Professional Experience
Jan 2018 - December 2020 | Analyst at Example
• Reporting
03/2021 – Present | Developer at Other
Full-time
• Built APIs
Skills
Python''')
    assert len(result) == 2
    assert result[0] == dict(job_title='Developer', company='Other', start_date='2021-03',
                             end_date='', employment_type='Full-time', description='• Built APIs')
    assert result[1]['end_date'] == '2020-12'
    assert 'Reporting' not in result[0]['description']


def test_explicit_hebrew_labels_and_iso_months():
    result = detect_resume_employment('ניסיון תעסוקתי\nתפקיד: רכז תפעול\nחברה: דוגמה\nמיקום: חיפה\n2022-02 עד 2024-08\nהשכלה')
    assert result == [dict(job_title='רכז תפעול', company='דוגמה', location='חיפה', start_date='2022-02', end_date='2024-08')]


@pytest.mark.parametrize('text', [
    'Projects\nDeveloper at Example\n2020-2023',
    'Work Experience\nExample | Something\n2020-2023',
    'Education\n2019-2022 Software Engineer at University',
    'Work Experience\n• Worked as Engineer at Example\n2020-2023',
])
def test_ambiguous_or_non_employment_not_invented(text):
    assert detect_resume_employment(text) == []


def test_autofill_persists_all_roles_and_is_idempotent():
    from app.main import _autofill_profile_from_resume
    profile = Profile(skills_json='[]', application_profile_json='{}')
    analysis = analyze_resume('Work Experience\nEngineer at One\n2018-2020\nDeveloper at Two\n2021-present', profile)
    assert 'work_experiences' in _autofill_profile_from_resume(profile, analysis)
    extra = json.loads(profile.application_profile_json)
    assert len(extra['work_experiences']) == 2
    assert extra['current_company'] == 'Two'
    assert 'work_experiences' not in _autofill_profile_from_resume(profile, analysis)


@pytest.mark.parametrize('saved', [{'current_company':'Saved'}, {'work_experiences':[{'company':'Saved','job_title':'Edited'}]}])
def test_saved_experience_never_overwritten(saved):
    from app.main import _autofill_profile_from_resume
    profile = Profile(skills_json='[]', application_profile_json=json.dumps(saved))
    analysis = analyze_resume('Work Experience\nEngineer at New\n2020-2024', profile)
    assert 'work_experiences' not in _autofill_profile_from_resume(profile, analysis)
    extra = json.loads(profile.application_profile_json)
    for key, value in saved.items():
        assert extra[key] == value


@pytest.mark.parametrize('header', ['Developer\nExample Ltd', 'Example Ltd\nDeveloper'])
def test_stacked_header(header):
    result = detect_resume_employment(f'Employment History\n{header}\n2020-2024\n• Delivered releases')
    assert result[0]['company'] == 'Example Ltd'
    assert result[0]['job_title'] == 'Developer'


def test_dates_in_achievement_do_not_split_employment():
    result = detect_resume_employment('Work Experience\nEngineer at Example\n2018-present\n• Led 2020-2022 migration')
    assert len(result) == 1
    assert result[0]['description'] == '• Led 2020-2022 migration'


def test_company_first_labels_do_not_overwrite_previous_employer():
    result = detect_resume_employment('Experience\nCompany: One\nTitle: Analyst\n2020-2021\nCompany: Two\nTitle: Developer\n2022-2023')
    assert [(item['company'], item['job_title']) for item in result] == [('Two', 'Developer'), ('One', 'Analyst')]


@pytest.mark.parametrize('heading', [
    'Example Labs, Research Student - Machine Learning (Full-Time)',
    'Research Student - Machine Learning, Example Labs (Full-Time)',
])
def test_date_then_comma_header_preserves_title_specialty(heading):
    result = detect_resume_employment(f'Experience\n2022-2024\n{heading}\n• Trained models\nSkills\nPython')
    assert result == [dict(start_date='2022', end_date='2024', company='Example Labs',
                          job_title='Research Student - Machine Learning',
                          employment_type='Full-time', description='• Trained models')]


def test_comma_header_multiple_roles_and_no_military_leak():
    result = detect_resume_employment('Experience\n2019-2021\nExample, Data Analyst\n• Built reports\n2022-2025\nOther, QA Engineer\n• Tested products\nMilitary Service\n2015-2018\nUnit, Administrator')
    assert [(item['company'], item['job_title']) for item in result] == [('Other', 'QA Engineer'), ('Example', 'Data Analyst')]


def test_comma_header_autofills_profile():
    from app.main import _autofill_profile_from_resume
    profile = Profile(skills_json='[]', application_profile_json='{}')
    analysis = analyze_resume('Experience\n2022-2024\nExample Labs, Research Student - Machine Learning (Full-Time)\n• Trained models', profile)
    assert 'work_experiences' in _autofill_profile_from_resume(profile, analysis)
    assert json.loads(profile.application_profile_json)['work_experiences'][0]['company'] == 'Example Labs'


@pytest.mark.parametrize('heading', ['Employment Experience', 'Professional Background', 'Career History', 'נסיון תעסוקתי'])
@pytest.mark.parametrize('header', ['Example Ltd\nSoftware Engineer', 'Software Engineer\nExample Ltd'])
def test_dates_before_stacked_header(heading, header):
    result = detect_resume_employment(f'{heading}\n2020-2024\n{header}\n• Built services\nEducation\nSome College')
    assert result == [dict(start_date='2020', end_date='2024', company='Example Ltd',
                          job_title='Software Engineer', description='• Built services')]


def test_date_only_block_does_not_consume_next_section():
    assert detect_resume_employment('Experience\n2020-2024\nEducation\nSoftware Engineer') == []
