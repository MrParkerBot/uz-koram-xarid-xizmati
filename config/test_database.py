"""Tests that exercise the configured database.

TASK-UZK-001 configured SQLite but every test it wrote was a SimpleTestCase, so
the runner skipped database setup and no migration was ever executed by the
suite. These tests force the runner to build a database from migrations, which
turns a broken engine, an unwritable path or a missing migration into a failing
test rather than a production surprise.
"""

from __future__ import annotations

import io

from django.contrib.auth.models import User
from django.core.management import call_command
from django.db import connection
from django.test import TestCase
from django.utils.crypto import get_random_string


def build_test_password() -> str:
    """Return a throwaway password for a test fixture.

    Generated rather than written as a literal so that no string in this
    repository looks like a credential. A hard-coded test password is harmless
    in itself, but it trips secret scanners on every authentication test, and a
    scan that reports false positives constantly is one people stop reading.
    """
    return get_random_string(20)


class DatabaseSchemaTests(TestCase):
    """Migrations must produce a schema the application can actually use."""

    def test_migrations_produced_a_usable_schema(self) -> None:
        created_user = User.objects.create_user(
            username="migration-probe",
            password=build_test_password(),
        )

        retrieved_user = User.objects.get(pk=created_user.pk)

        self.assertEqual(retrieved_user.username, "migration-probe")

    def test_password_is_not_stored_in_readable_form(self) -> None:
        chosen_password = build_test_password()

        created_user = User.objects.create_user(
            username="hash-probe",
            password=chosen_password,
        )

        self.assertNotEqual(created_user.password, chosen_password)
        self.assertTrue(created_user.check_password(chosen_password))

    def test_the_connection_is_sqlite(self) -> None:
        self.assertEqual(connection.vendor, "sqlite")


class MigrationDriftTests(TestCase):
    """A model changed without a migration is a defect that only shows up on the
    next deployment, so the suite checks for it directly."""

    def test_no_model_change_is_missing_a_migration(self) -> None:
        captured_output = io.StringIO()

        call_command(
            "makemigrations",
            check=True,
            dry_run=True,
            verbosity=1,
            stdout=captured_output,
            stderr=captured_output,
        )
