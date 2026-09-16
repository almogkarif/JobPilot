from types import SimpleNamespace

import pytest

from app.services.matching import track_job_relevance
from tests.test_ranking_v2 import job, profile, score

TRACK = 'industrial_engineering'
HQA_REQUIREMENTS = '''Requirements
B.Sc. in Mechanical Engineering, Electronics Engineering or Optical Engineering
Experience in system and product development with familiarity in maturation processes
Experience in building processes, leading investigations and driving continuous improvement activities
Familiarity with manufacturing processes, NPI and serial production
Systemic and analytical thinking with strong data analysis skills'''


@pytest.mark.parametrize('title,description', [
    ('(HQA) Design Quality Engineer', HQA_REQUIREMENTS),
    ('Quality Engineer', 'Requirements: BSc in Mechanical Engineering. Process improvement and data analysis.'),
    ('Project Manager', 'Requirements: Bachelor’s degree in Electrical Engineering or Computer Science'),
    ('מנהל.ת פרויקטים', 'דרישות התפקיד\nתואר בהנדסת מכונות\nניסיון בתכנון ייצור'),
    ('מנהל פרויקט', 'תואר ראשון בהנדסת חשמל/ מחשבים – חובה'),
    ('Engineering Program Manager Soc Silicon Group', 'B.Sc / M. Sc in Electrical Engineering or Computer Engineering'),
    ('Data Analyst', 'Requirements: Bachelor’s degree in law (LL.B. or equivalent).'),
    ('Legal Operations Specialist', 'Legal workflows, reporting, operations and project planning'),
    ('Senior Security Operations Engineer', 'Operations, planning, data analysis and KPIs'),
    ('Network Analyst', 'Network protocols, data analysis, operations and planning'),
    ('HR Business Partner', 'Workforce planning, operations and Excel'),
    ('Quality Engineer', 'Work with industrial engineering teams.\nRequirements:\nB.Sc. in Mechanical Engineering'),
])
def test_required_specialism_cannot_be_overridden_by_generic_title_or_skills(title, description):
    assert not track_job_relevance(SimpleNamespace(title=title, description=description), TRACK)[0]


@pytest.mark.parametrize('title,description', [
    ('Quality Engineer', 'BSc in Mechanical Engineering or Industrial Engineering'),
    ('Quality Engineer', 'Bachelor’s degree in Engineering, Life Sciences, or a related field'),
    ('Quality Engineer', 'Requirements:\nProcess improvement and data analysis\nPreferred Qualifications:\nBSc in Mechanical Engineering'),
    ('Quality Engineer', 'BSc in Mechanical Engineering - advantage'),
    ('Quality Engineer', 'BSc in Mechanical Engineering or equivalent practical experience'),
    ('Quality Engineer', 'Collaborate with Mechanical Engineering on process improvement'),
    ('מנהל/ת איכות בפרויקטים', 'תואר ראשון בהנדסת מכונות / תעשייה וניהול - חובה'),
    ('מנהל/ת איכות בפרויקטים', 'תואר ראשון בהנדסת מכונות / תעשיה וניהול - חובה'),
    ('מנהל פרויקט', 'תואר ראשון בהנדסה - חובה\nתואר ראשון בהנדסת מכונות - יתרון משמעותי'),
    ('Mechanical Production Planner', 'תואר ראשון בהנדסת תעו"נ / לוגיסטיקה'),
    ('Data Analyst', 'BSc in Computer Science, Statistics or Industrial Engineering'),
    ('Data Analyst', 'SQL, dashboards and data analysis'),
    ('Supply Chain Analyst', 'Supply chain, inventory, ERP and planning'),
    ('Total Rewards Analyst', 'Bachelor’s degree in Human Resources, Industrial Engineering, or a related field'),
    ('Microwave Radar Project Lead', 'תואר בהנדסה תעשייה וניהול / מנהל עסקים וכדומה'),
])
def test_related_roles_and_explicit_degree_alternatives_remain_available(title, description):
    assert track_job_relevance(SimpleNamespace(title=title, description=description), TRACK)[0]


def test_hqa_is_excluded_even_with_matching_title_skills_and_bachelor_degree():
    candidate = profile(TRACK, years=1, skills=['data analysis', 'process improvement'], titles=['quality engineer'])
    candidate.application_profile_json = '{"degree_level":"bachelor"}'
    result = score(candidate, job('(HQA) Design Quality Engineer', HQA_REQUIREMENTS, track=TRACK))
    assert result.eligibility['state'] == 'excluded'
    assert result.eligibility['career_track_status'] == 'mismatch'
