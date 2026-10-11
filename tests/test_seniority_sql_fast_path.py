"""Execute the all-level shortcut and unchanged restricted filters on both DBs."""
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, and_, case, create_engine, func, select, text

from app.services.seniority import (
    LEVELS, PATTERNS, PRIORITY, PROFESSION_MANAGERS, SENIORITY_LEVELS,
    detect_title_level, selected_seniority_levels, seniority_visibility_condition,
)
from tests.test_canonical_postgres import postgres_cluster


TITLES = [None, '', 'Software Engineer', 'Internal Tools Engineer', 'SeniorJunior Engineer',
          'Project Manager', 'Product Manager', 'Program Manager', 'Senior Product Manager',
          'Senior Staff Engineering Manager', 'Lead Junior Developer', 'ג׳וניור מפתח',
          'מפתח ראש צוות', 'מפתח ללא ניסיון', 'מנהל פיתוח', 'QA Automation Engineer']
TITLES += [f'({term.upper()}) Software Engineer'
           for terms in SENIORITY_LEVELS.values() for term in sorted(terms)]


@pytest.fixture(params=['sqlite', 'postgresql'])
def seniority_sql_connection(request):
    engine = (request.getfixturevalue('postgres_cluster') if request.param == 'postgresql'
              else create_engine('sqlite://'))
    metadata = MetaData()
    rows = Table('seniority_titles', metadata, Column('id', Integer), Column('title', String))
    try:
        with engine.connect() as connection:
            # PostgreSQL fixture uses an isolated loopback cluster; temporary
            # nullable titles also cover the legacy CASE's NULL/unknown branch.
            connection.execute(text('CREATE TEMP TABLE seniority_titles (id INTEGER, title TEXT)'))
            connection.execute(rows.insert(), [{'id': index, 'title': title}
                                               for index, title in enumerate(TITLES)])
            try:
                yield connection, rows
            finally:
                connection.execute(text('DROP TABLE seniority_titles'))
    finally:
        if request.param == 'sqlite':
            engine.dispose()


def _legacy_visibility(profile, title):
    """Prior SQL behavior, retained only as an independent equivalence oracle."""
    lowered = func.lower(title)
    clauses = []
    for level in PRIORITY:
        matches = lowered.regexp_match(PATTERNS[level])
        if level == 'manager':
            matches = and_(matches, ~lowered.regexp_match(PROFESSION_MANAGERS))
        clauses.append((matches, level))
    return case(*clauses, else_='unknown').in_(selected_seniority_levels(profile))


@pytest.mark.parametrize('profile_values', [
    {'seniority_levels_json': json.dumps(LEVELS)},
    {'seniority_levels_json': json.dumps([*LEVELS, 'senior', 'unsupported'])},
    {},  # Legacy profile with no explicit restrictions selects every level.
    {'keywords_json': '[]', 'excluded_keywords_json': '["python"]'},
])
def test_all_levels_match_legacy_for_every_title_without_sql_regex(seniority_sql_connection, profile_values):
    connection, rows = seniority_sql_connection
    profile = SimpleNamespace(**profile_values)
    statement = select(rows.c.id).where(seniority_visibility_condition(profile, rows.c.title)).order_by(rows.c.id)
    legacy = select(rows.c.id).where(_legacy_visibility(profile, rows.c.title)).order_by(rows.c.id)
    actual = list(connection.scalars(statement))
    assert actual == list(connection.scalars(legacy)) == list(range(len(TITLES)))
    sql = str(statement.compile(dialect=connection.dialect, compile_kwargs={'literal_binds': True})).lower()
    assert 'regexp' not in sql and '~' not in sql and 'case' not in sql
    # The shortcut is only a visibility predicate: independent filters and SQL
    # pagination still select the same bounded set as the previous expression.
    assert list(connection.scalars(statement.where(rows.c.id >= 3).limit(4))) == [3, 4, 5, 6]


@pytest.mark.parametrize('selected', [[], ['junior'], ['junior', 'unknown'], ['manager'],
                                    ['student', 'entry level'], ['staff', 'lead'], ['senior']])
def test_restricted_seniority_preserves_legacy_and_python_results(seniority_sql_connection, selected):
    connection, rows = seniority_sql_connection
    profile = SimpleNamespace(seniority_levels_json=json.dumps(selected))
    statement = select(rows.c.id).where(seniority_visibility_condition(profile, rows.c.title)).order_by(rows.c.id)
    legacy = select(rows.c.id).where(_legacy_visibility(profile, rows.c.title)).order_by(rows.c.id)
    expected = [index for index, title in enumerate(TITLES) if detect_title_level(title) in selected]
    assert list(connection.scalars(statement)) == list(connection.scalars(legacy)) == expected
    sql = str(statement.compile(dialect=connection.dialect, compile_kwargs={'literal_binds': True})).lower()
    assert 'case' in sql and ('regexp' in sql or '~' in sql)


@pytest.mark.parametrize('profile_values,selected', [
    ({'keywords_json': '["junior"]'}, ['junior', 'unknown']),
    ({'excluded_keywords_json': '["senior"]'}, [level for level in LEVELS if level != 'senior']),
])
def test_legacy_restrictions_still_apply(seniority_sql_connection, profile_values, selected):
    connection, rows = seniority_sql_connection
    profile = SimpleNamespace(**profile_values)
    assert set(selected_seniority_levels(profile)) == set(selected)
    statement = select(rows.c.id).where(seniority_visibility_condition(profile, rows.c.title)).order_by(rows.c.id)
    assert list(connection.scalars(statement)) == [index for index, title in enumerate(TITLES)
                                                  if detect_title_level(title) in selected]
