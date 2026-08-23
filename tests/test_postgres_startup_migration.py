from __future__ import annotations

import app.database as database_module
from app.config import settings


class _Scalars:
    def __init__(self, values):
        self._values = list(values)

    def all(self):
        return list(self._values)


class _Result:
    def __init__(self, *, scalar=None, scalars=(), first=None):
        self._scalar = scalar
        self._scalars = list(scalars)
        self._first = first

    def scalar(self):
        return self._scalar

    def scalars(self):
        return _Scalars(self._scalars)

    def first(self):
        return self._first


class _Inspector:
    def __init__(self, tables, columns):
        self._tables = list(tables)
        self._columns = dict(columns)

    def get_table_names(self):
        return list(self._tables)

    def get_columns(self, table):
        return list(self._columns.get(table, []))


class _Connection:
    def __init__(self, *, roles=()):
        self.roles = list(roles)
        self.statements: list[str] = []

    def execute(self, statement, params=None):
        sql = str(statement)
        self.statements.append(sql)
        if "pg_try_advisory_xact_lock" in sql:
            return _Result(scalar=True)
        if "SELECT auth_user_id FROM app_identity" in sql:
            return _Result(scalar="owner-user-id")
        if "SELECT rolname FROM pg_roles" in sql:
            return _Result(scalars=self.roles)
        if "SELECT 1 FROM profiles WHERE user_id" in sql:
            return _Result(first=None)
        return _Result()


def test_postgres_startup_skips_already_applied_rls_and_revokes(monkeypatch):
    connection = _Connection(roles=("anon", "authenticated"))
    inspector = _Inspector(
        ["app_identity"],
        {"app_identity": [{"name": "role"}, {"name": "last_seen_at"}, {"name": "last_login_at"}, {"name": "last_session_id"}]},
    )
    monkeypatch.setattr(database_module, "inspect", lambda _connection: inspector)
    monkeypatch.setattr(database_module, "_postgres_table_rls_enabled", lambda *_args: True)
    monkeypatch.setattr(database_module, "_postgres_role_has_table_grants", lambda *_args: False)
    monkeypatch.setattr(settings, "owner_email", "")

    database_module._postgres_multiuser_migration(connection)

    sql = "\n".join(connection.statements)
    assert "pg_try_advisory_xact_lock" in sql
    assert "ENABLE ROW LEVEL SECURITY" not in sql
    assert "REVOKE ALL PRIVILEGES" not in sql


def test_postgres_startup_skips_existing_not_null_and_indexes(monkeypatch):
    connection = _Connection(roles=())
    inspector = _Inspector(
        ["profiles"],
        {"profiles": [{"name": "user_id", "nullable": False}]},
    )
    monkeypatch.setattr(database_module, "inspect", lambda _connection: inspector)
    monkeypatch.setattr(
        database_module,
        "_postgres_index_names",
        lambda _connection, table: {"ix_profiles_user_id", "uq_profile_user_idx"} if table == "profiles" else set(),
    )

    database_module._postgres_multiuser_migration(connection)

    sql = "\n".join(connection.statements)
    assert "ALTER COLUMN user_id SET NOT NULL" not in sql
    assert "CREATE INDEX" not in sql
    assert "CREATE UNIQUE INDEX" not in sql


def test_postgres_startup_makes_removed_salary_column_insert_safe(monkeypatch):
    connection = _Connection(roles=())
    inspector = _Inspector(
        ["profiles"],
        {"profiles": [
            {"name": "user_id", "nullable": False},
            {"name": "salary_expectation", "nullable": False, "default": None},
        ]},
    )
    monkeypatch.setattr(database_module, "inspect", lambda _connection: inspector)
    monkeypatch.setattr(
        database_module,
        "_postgres_index_names",
        lambda _connection, table: {"ix_profiles_user_id", "uq_profile_user_idx"} if table == "profiles" else set(),
    )

    database_module._postgres_multiuser_migration(connection)

    sql = "\n".join(connection.statements)
    assert "ALTER TABLE profiles ALTER COLUMN salary_expectation SET DEFAULT ''" in sql


def test_postgres_startup_does_not_rewrite_existing_salary_default(monkeypatch):
    connection = _Connection(roles=())
    inspector = _Inspector(
        ["profiles"],
        {"profiles": [
            {"name": "user_id", "nullable": False},
            {"name": "salary_expectation", "nullable": False, "default": "''::character varying"},
        ]},
    )
    monkeypatch.setattr(database_module, "inspect", lambda _connection: inspector)
    monkeypatch.setattr(
        database_module,
        "_postgres_index_names",
        lambda _connection, table: {"ix_profiles_user_id", "uq_profile_user_idx"} if table == "profiles" else set(),
    )

    database_module._postgres_multiuser_migration(connection)

    sql = "\n".join(connection.statements)
    assert "ALTER COLUMN salary_expectation SET DEFAULT" not in sql


def test_postgres_startup_skips_migration_when_another_instance_holds_lock(monkeypatch):
    class _BusyConnection(_Connection):
        def execute(self, statement, params=None):
            sql = str(statement)
            self.statements.append(sql)
            if "pg_try_advisory_xact_lock" in sql:
                return _Result(scalar=False)
            raise AssertionError(f"migration continued after lock miss: {sql}")

    connection = _BusyConnection()
    acquired = database_module._postgres_multiuser_migration(connection)

    assert acquired is False
    assert len(connection.statements) == 1
    assert "pg_try_advisory_xact_lock" in connection.statements[0]
    assert "pg_advisory_xact_lock(" not in connection.statements[0]


def test_ensure_compatibility_skips_followups_when_postgres_lock_is_busy(monkeypatch):
    class _Dialect:
        name = "postgresql"

    class _Begin:
        def __enter__(self):
            return object()

        def __exit__(self, exc_type, exc, tb):
            return False

    class _Engine:
        dialect = _Dialect()

        def begin(self):
            return _Begin()

    followups: list[object] = []
    monkeypatch.setattr(database_module, "engine", _Engine())
    monkeypatch.setattr(database_module, "_postgres_multiuser_migration", lambda _connection: False)
    monkeypatch.setattr(
        database_module,
        "_migrate_plaintext_application_passwords",
        lambda connection: followups.append(connection),
    )

    database_module.ensure_compatibility_columns()

    assert followups == []
