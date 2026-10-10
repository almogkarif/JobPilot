from sqlalchemy import create_engine, inspect, text

from app import database


def test_additive_question_wait_columns_preserve_existing_rows_and_are_idempotent():
    engine = create_engine('sqlite://')
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE blockers (id INTEGER PRIMARY KEY, question TEXT, answer TEXT)'))
        connection.execute(text("INSERT INTO blockers VALUES (1, 'Existing question', 'Existing answer')"))
        for _ in range(2):
            columns = {column['name'] for column in inspect(connection).get_columns('blockers')}
            database._add_runtime_compatibility_columns(connection, 'blockers', columns)
        row = connection.execute(text('SELECT question, answer, wait_attempt_id, wait_until FROM blockers')).one()
        assert tuple(row) == ('Existing question', 'Existing answer', None, None)
        columns = {column['name']: column for column in inspect(connection).get_columns('blockers')}
        assert columns['wait_attempt_id']['nullable'] and columns['wait_until']['nullable']
    engine.dispose()


def test_postgres_compatibility_declarations_do_not_backfill_or_scan_rows():
    class Connection:
        def __init__(self):
            self.statements = []

        def execute(self, statement):
            self.statements.append(str(statement))

    connection = Connection()
    database._add_runtime_compatibility_columns(connection, 'blockers', {'id', 'question', 'answer'})
    assert connection.statements == [
        'ALTER TABLE blockers ADD COLUMN wait_attempt_id INTEGER',
        'ALTER TABLE blockers ADD COLUMN wait_until TIMESTAMP WITH TIME ZONE',
    ]
    database._add_runtime_compatibility_columns(connection, 'blockers', {'wait_attempt_id', 'wait_until'})
    assert len(connection.statements) == 2
