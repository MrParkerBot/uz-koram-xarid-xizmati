"""Shared test scaffolding.

Since TASK-UZK-009 every page requires a session, so a test that fetches one
has to sign in first. This is that step, in one place, rather than repeated in
every test module that walks the pages.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils.crypto import get_random_string

from accounts.models import UserType
from accounts.roles import ADMIN, assign_user_type


class SignedInTestCase(TestCase):
    """A test case whose client is signed in as an Admin.

    Admin because TASK-UZK-012 closed every page to the types DEC-015 permits,
    and the tests that use this base are about pages rather than about
    permissions: they need an account that can reach what they are testing.
    The permission matrix itself is tested in accounts/tests/test_permissions.py,
    with an account per type.
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
        assign_user_type(cls.user, UserType.objects.get(name=ADMIN))

    def setUp(self) -> None:
        super().setUp()
        self.client.force_login(self.user)
