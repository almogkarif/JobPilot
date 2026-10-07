from sqlalchemy import select, text

from app.main import _dashboard_role_visibility_condition
from app.models import Job, Profile
from tests.test_canonical_postgres import postgres_cluster  # noqa: F401


def test_qa_preference_filter_runs_on_postgres(postgres_cluster):
    qa_titles = [
        'QA Software Engineer', 'Software QA Engineer', 'QA Automation Developer',
        'SQA Engineer', 'QAE Engineer', 'Quality-Assurance Engineer',
        'QualityAssurance Engineer', 'בודק/ת תוכנה', 'בודקות תוכנה',
        'מהנדס בדיקות תוכנה',
    ]
    other_titles = ['Backend Engineer', 'Qatar Backend Engineer', 'Automation Engineer']
    with postgres_cluster.connect() as connection:
        connection.execute(text('CREATE TEMP TABLE jobs (title TEXT)'))
        connection.execute(text('INSERT INTO jobs (title) VALUES (:title)'),
                           [{'title': title} for title in qa_titles + other_titles])
        profile = Profile(desired_titles_json='["software engineer", "automation"]')
        statement = select(Job.title).where(
            _dashboard_role_visibility_condition(profile, 'computer_science'),
        )
        assert set(connection.scalars(statement)) == set(other_titles)
        profile.desired_titles_json = '["qa"]'
        statement = select(Job.title).where(
            _dashboard_role_visibility_condition(profile, 'computer_science'),
        )
        assert set(connection.scalars(statement)) == set(qa_titles + other_titles)
