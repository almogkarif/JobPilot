import pytest
from fastapi.testclient import TestClient

from app.main import app, _analyze_resume_record
from app.models import Profile, ResumeProfile
from app.services.resume_analysis import analyze_resume
from app.utils import loads


def test_header_does_not_invent_name_or_use_employer_city_and_website():
    result = analyze_resume('Professional Summary\nExperienced software engineer\nExperience\nAtlas Systems\nHaifa, Israel\nhttps://employer.example.com', Profile(skills_json='[]'))
    assert not {'full_name', 'location', 'portfolio_url'} & result['detected_profile'].keys()


def test_skills_and_degree_heading_are_not_a_person_name():
    result = analyze_resume('Python Docker Kubernetes\nBachelor of Science\nEducation', Profile(skills_json='[]'))
    assert 'full_name' not in result['detected_profile']


def test_hebrew_labeled_identity_and_international_phone():
    result = analyze_resume('קורות חיים\nשם מלא: דנה לוי\nכתובת: חיפה\ndana@example.com\n+972 (0)52-1234567', Profile(skills_json='[]'))
    assert result['detected_profile']['full_name'] == 'דנה לוי'
    assert result['detected_profile']['phone'] == '+972 (0)52-1234567'
    assert result['detected_profile']['location'] == 'חיפה'


def test_no_text_analysis_reports_warning_instead_of_success():
    resume = ResumeProfile(filename='scan.pdf', path='unused')
    _analyze_resume_record(resume, Profile(skills_json='[]'), extracted_text='')
    analysis = loads(resume.analysis_json, {})
    assert analysis['warning']
    assert analysis['detected_profile'] == {}


def test_international_phone_and_explicit_language_levels_autofill():
    from app.main import _autofill_profile_from_resume
    profile = Profile(phone='', skills_json='[]', application_profile_json='{}')
    analysis = analyze_resume('Dana Levi\n+972-52-1234567\nLanguages\nEnglish - fluent\nHebrew - Native', profile)
    applied = _autofill_profile_from_resume(profile, analysis)
    assert profile.phone == '0521234567'
    assert 'languages' in applied
    assert loads(profile.application_profile_json, {})['languages'] == [
        {'name': 'English', 'proficiency': 'Fluent'},
        {'name': 'Hebrew', 'proficiency': 'Native / Bilingual'},
    ]
    profile.application_profile_json = '{"languages":[{"name":"English","proficiency":"Advanced"}]}'
    _autofill_profile_from_resume(profile, analysis)
    assert loads(profile.application_profile_json, {})['languages'][0]['proficiency'] == 'Advanced'


def test_language_names_alone_and_conflicting_levels_are_not_guessed():
    analysis = analyze_resume('Languages\nEnglish\nHebrew - Native\nHebrew - Basic', Profile(skills_json='[]'))
    assert analysis['detected_languages'] == []


@pytest.mark.parametrize('endpoint', ['/api/profile/resume', '/api/resumes'])
def test_upload_fills_blank_contacts_and_preserves_existing_values(endpoint, tmp_path, monkeypatch):
    import app.main as main
    def store(kind, filename, content, content_type, **kwargs):
        path = tmp_path / filename
        path.write_bytes(content)
        return str(path)
    monkeypatch.setattr(main, 'save_bytes', store)
    with TestClient(app) as client:
        original = client.get('/api/profile').json()
        fields = ['full_name', 'email', 'phone', 'location', 'linkedin_url', 'github_url', 'portfolio_url']
        try:
            response = client.patch('/api/profile', json={field: '' for field in fields})
            assert response.status_code == 200
            content = b'Dana Levi\nLocation: Haifa, Israel\ndana@example.com\n052-1234567\nhttps://linkedin.com/in/dana-demo\nhttps://github.com/dana-demo\nhttps://dana.example.com\nEducation\nBSc in Computer Science'
            data = {'label': 'Autofill test'} if endpoint == '/api/resumes' else {}
            response = client.post(endpoint, data=data, files={'file': ('cv.txt', content, 'text/plain')})
            assert response.status_code == 200
            profile = client.get('/api/profile').json()
            assert profile['full_name'] == 'Dana Levi'
            assert profile['email'] == 'dana@example.com'
            assert profile['phone'] == '0521234567'
            assert profile['github_url'] == 'https://github.com/dana-demo'
            assert profile['portfolio_url'] == 'https://dana.example.com'
            # A later CV is a suggestion, not permission to replace saved identity.
            response = client.post(endpoint, data=data, files={'file': ('cv.txt', content.replace(b'Dana Levi', b'Maya Cohen').replace(b'dana@example.com', b'maya@example.com'), 'text/plain')})
            assert response.status_code == 200
            profile = client.get('/api/profile').json()
            assert profile['full_name'] == 'Dana Levi'
            assert profile['email'] == 'dana@example.com'
        finally:
            client.patch('/api/profile', json={field: original.get(field, '') for field in fields})


def test_pdf_columns_joined_on_one_line_keep_both_language_levels():
    analysis = analyze_resume('Languages\nEnglish - fluent Hebrew - Native\nhttps://example.com', Profile(skills_json='[]'))
    assert analysis['detected_languages'] == [{'name':'English','proficiency':'Fluent'}, {'name':'Hebrew','proficiency':'Native / Bilingual'}]


@pytest.mark.parametrize('degree, expected', [('B.Sc. Computer Science','bachelor'), ('M.Sc. Engineering','master'), ('Ph.D. Physics','phd'), ('תואר ראשון במדעי המחשב','bachelor'), ('High school diploma',''), ('Planning a Ph.D.','')])
def test_explicit_academic_degree_only(degree, expected):
    analysis = analyze_resume('Education\n'+degree+'\nExperience\nTutoring Ph.D. students', Profile(skills_json='[]'))
    assert analysis['detected_degree_level'] == expected


def test_degree_autofill_preserves_existing_choice():
    from app.main import _autofill_profile_from_resume
    profile=Profile(skills_json='[]',application_profile_json='{}')
    analysis=analyze_resume('Education\nB.Sc. Computer Science\nM.Sc. Engineering',profile)
    _autofill_profile_from_resume(profile,analysis)
    assert loads(profile.application_profile_json,{})['degree_level']=='master'
    _autofill_profile_from_resume(profile,{'detected_profile':{},'detected_degree_level':'phd'})
    assert loads(profile.application_profile_json,{})['degree_level']=='master'


def test_education_keeps_degree_and_transfer_track_separate():
    from app.main import _autofill_profile_from_resume
    text = """Education
2021-2025 Technion - Israel Institute of Technology, B.Sc. Computer Science, GPA 83.1
• Dean's List - Winter Semester 2022/2023
2020-2021 The Open University of Israel, Technion Computer Science Transfer Track, GPA 90
Experience
Software Engineer
"""
    profile = Profile(skills_json='[]', application_profile_json='{}')
    analysis = analyze_resume(text, profile)
    expected = {'degree_level':'bachelor','education_school':'Technion - Israel Institute of Technology','education_field':'Computer Science','education_grade':'83.1','education_start_date':'2021','education_end_date':'2025'}
    assert analysis['detected_education'] == expected
    _autofill_profile_from_resume(profile,analysis)
    extra=loads(profile.application_profile_json,{})
    assert all(extra[key]==value for key,value in expected.items())


def test_education_month_precision_and_higher_degree_do_not_mix():
    text='Education\n2018-2021 Example University, B.Sc. Physics, GPA 88\n2022-10 - 2024-06 Another University, M.Sc. Computer Science, GPA 95\nSkills\nPython'
    result=analyze_resume(text,Profile(skills_json='[]'))['detected_education']
    assert result['degree_level']=='master'
    assert result['education_school']=='Another University'
    assert result['education_grade']=='95'
    assert result['education_start_date']=='2022-10'
    assert result['education_end_date']=='2024-06'


def test_education_saved_other_school_is_not_completed_from_different_degree():
    from app.main import _autofill_profile_from_resume
    profile=Profile(skills_json='[]',application_profile_json='{"education_school":"Saved University","degree_level":"bachelor","education_grade":"99"}')
    analysis=analyze_resume('Education\n2021-2025 Other University, B.Sc. Physics, GPA 80',profile)
    _autofill_profile_from_resume(profile,analysis)
    extra=loads(profile.application_profile_json,{})
    assert extra['education_school']=='Saved University' and extra['education_grade']=='99'
    assert not extra.get('education_field')
