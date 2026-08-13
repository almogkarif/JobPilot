from sqlalchemy import Text

from app import database


def test_postgres_compatibility_migration_has_sqlalchemy_text_type_available():
    assert database.Text is Text
