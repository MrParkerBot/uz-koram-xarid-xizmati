"""Shared test scaffolding.

Since TASK-UZK-009 every page requires a session, so a test that fetches one
has to sign in first. This is that step, in one place, rather than repeated in
every test module that walks the pages.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils.crypto import get_random_string


class SignedInTestCase(TestCase):
    """A test case whose client is already signed in.

    The account is an ordinary one: no role, no permissions beyond having a
    session. Role-based access arrives with TASK-UZK-010 and TASK-UZK-012, and
    tests written then will need accounts that differ from one another.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        cls.password = get_random_string(24)
        cls.user = get_user_model().objects.create_user(
            username="test.user",
            password=cls.password,
            first_name="Test",
            last_name="User",
        )

    def setUp(self) -> None:
        super().setUp()
        self.client.force_login(self.user)
