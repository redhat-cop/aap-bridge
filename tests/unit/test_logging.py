"""Tests for logging utilities."""

from aap_migration.utils.logging import redact_database_url


def test_redact_database_url_masks_postgresql_password():
    url = "postgresql://aap_migration_user:redhat@localhost:5432/aap_migration"
    assert redact_database_url(url) == "postgresql://***@localhost:5432/aap_migration"


def test_redact_database_url_leaves_sqlite_unchanged():
    url = "sqlite:///data/state.db"
    assert redact_database_url(url) == url


def test_redact_database_url_leaves_url_without_credentials_unchanged():
    url = "postgresql://localhost:5432/aap_migration"
    assert redact_database_url(url) == url


def test_redact_database_url_masks_mysql_password():
    url = "mysql://dbuser:s3cret@db.example.com/mydb"
    assert redact_database_url(url) == "mysql://***@db.example.com/mydb"
