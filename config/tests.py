"""Tests for the application skeleton delivered by TASK-UZK-001."""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

from django.conf import settings
from django.test import SimpleTestCase
from django.urls import reverse

from config.settings import read_boolean_setting, read_list_setting

TEST_VARIABLE = "UZK_TEST_SETTING"


@contextmanager
def environment_variable(name: str, value: str) -> Iterator[None]:
    """Set an environment variable for the duration of the block."""
    previous_value = os.environ.get(name)
    os.environ[name] = value
    try:
        yield
    finally:
        if previous_value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = previous_value


class ServiceRootTests(SimpleTestCase):
    """The running application answers at the root URL."""

    def test_root_url_returns_successful_response(self) -> None:
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)

    def test_root_url_is_reachable_by_its_route_name(self) -> None:
        response = self.client.get(reverse("service-root"))

        self.assertEqual(response.status_code, 200)

    def test_unknown_url_returns_not_found_rather_than_an_error(self) -> None:
        response = self.client.get("/a-url-that-does-not-exist/")

        self.assertEqual(response.status_code, 404)


class SettingsDefaultTests(SimpleTestCase):
    """An unconfigured environment must produce the safe settings."""

    def test_debug_is_off_unless_the_environment_enables_it(self) -> None:
        self.assertFalse(
            settings.DEBUG,
            "DEBUG must default to off so an unconfigured deployment is safe.",
        )

    def test_secret_key_is_present_and_long_enough_to_be_generated(self) -> None:
        self.assertTrue(settings.SECRET_KEY)
        self.assertGreaterEqual(len(settings.SECRET_KEY), 32)

    def test_database_engine_is_sqlite(self) -> None:
        self.assertEqual(
            settings.DATABASES["default"]["ENGINE"],
            "django.db.backends.sqlite3",
        )


class BooleanSettingTests(SimpleTestCase):
    """`read_boolean_setting` decides whether a deployment runs in debug mode,
    so its handling of unrecognised input is worth pinning down."""

    def test_recognised_true_spellings_are_accepted(self) -> None:
        for spelling in ("1", "true", "TRUE", "yes", "on", " On "):
            with self.subTest(spelling=spelling):
                with environment_variable(TEST_VARIABLE, spelling):
                    self.assertTrue(
                        read_boolean_setting(TEST_VARIABLE, default=False)
                    )

    def test_recognised_false_spellings_are_accepted(self) -> None:
        for spelling in ("0", "false", "no", "off"):
            with self.subTest(spelling=spelling):
                with environment_variable(TEST_VARIABLE, spelling):
                    self.assertFalse(
                        read_boolean_setting(TEST_VARIABLE, default=True)
                    )

    def test_unrecognised_value_falls_back_to_the_default(self) -> None:
        with environment_variable(TEST_VARIABLE, "ture"):
            self.assertFalse(read_boolean_setting(TEST_VARIABLE, default=False))

    def test_missing_variable_uses_the_default(self) -> None:
        self.assertTrue(
            read_boolean_setting("UZK_VARIABLE_THAT_IS_NOT_SET", default=True)
        )


class ListSettingTests(SimpleTestCase):
    """`read_list_setting` supplies ALLOWED_HOSTS, so empty and padded input
    must not produce a host entry that matches nothing."""

    def test_comma_separated_values_are_split_and_stripped(self) -> None:
        with environment_variable(TEST_VARIABLE, "example.uz, 10.0.0.5 "):
            self.assertEqual(
                read_list_setting(TEST_VARIABLE, default=[]),
                ["example.uz", "10.0.0.5"],
            )

    def test_empty_value_falls_back_to_the_default(self) -> None:
        with environment_variable(TEST_VARIABLE, "   "):
            self.assertEqual(
                read_list_setting(TEST_VARIABLE, default=["localhost"]),
                ["localhost"],
            )
