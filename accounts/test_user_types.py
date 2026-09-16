"""Tests for the User Types master data page of TASK-UZK-015.

This page differs from the other master data pages in one way that matters: a
User Type is also a role, and accounts/permissions.py decides what each may
open by name. So the six DEC-013 fixes have to survive an administrator using
this page - renaming Menejer, or deleting Admin, would take somebody's access
away with nothing anywhere saying why.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils.crypto import get_random_string

from accounts.models import UserType
from accounts.permissions import may_open
from accounts.roles import (
    ADMIN,
    DEPARTMENT_USER_TYPES,
    MENEJER,
    assign_user_type,
    user_type_of,
)

# No apostrophe: the page escapes one to &#x27; and these tests read the
# rendered markup rather than parsing it.
ADDED_TYPE = "Xarid menejeri"


def make_user(type_name: str = ADMIN):
    user = get_user_model().objects.create_user(
        username=f"user.{get_random_string(8).lower()}",
        password=get_random_string(24),
        first_name="Test",
        last_name="User",
    )
    assign_user_type(user, UserType.objects.get(name=type_name))
    return user


class UserTypesPageTestCase(TestCase):
    """An administrator on the User Types page."""

    def setUp(self) -> None:
        self.client.force_login(make_user(ADMIN))

    def create(self, **overrides):
        fields = {
            "name": ADDED_TYPE,
            "badge_colour": "blue",
            "category_number": "",
        }
        fields.update(overrides)
        return self.client.post(reverse("user-types-create"), fields)

    def page(self) -> str:
        return self.client.get(reverse("user-types")).content.decode()


class ListingTests(UserTypesPageTestCase):
    """The six the department runs on are there from the first visit."""

    def test_every_department_type_is_listed(self) -> None:
        page = self.page()

        for name in DEPARTMENT_USER_TYPES:
            with self.subTest(user_type=name):
                self.assertIn(name, page)

    def test_a_system_role_is_marked_as_one(self) -> None:
        self.assertIn("tizim roli", self.page())

    def test_a_system_role_has_no_delete_control(self) -> None:
        admin_type = UserType.objects.get(name=ADMIN)

        self.assertNotIn(
            reverse("user-types-delete", args=[admin_type.pk]), self.page()
        )


class CreationTests(UserTypesPageTestCase):
    """An installation may add types of its own."""

    def test_a_created_type_appears_in_the_table(self) -> None:
        self.create()

        self.assertIn(ADDED_TYPE, self.page())

    def test_a_created_type_keeps_its_badge_colour(self) -> None:
        self.create(badge_colour="green")

        self.assertEqual(UserType.objects.get(name=ADDED_TYPE).badge_colour, "green")

    def test_the_badge_is_rendered_with_the_matching_class(self) -> None:
        self.create(badge_colour="green")

        self.assertIn("badge badge-approved", self.page())

    def test_a_name_already_taken_is_refused(self) -> None:
        response = self.create(name=MENEJER)

        self.assertContains(response, "Bu nom allaqachon mavjud")

    def test_a_six_digit_category_number_is_accepted(self) -> None:
        self.create(category_number=100123)

        self.assertEqual(
            UserType.objects.get(name=ADDED_TYPE).category_number, 100123
        )

    def test_a_category_number_of_another_length_is_refused(self) -> None:
        response = self.create(category_number=42)

        self.assertFalse(UserType.objects.filter(name=ADDED_TYPE).exists())
        self.assertEqual(response.status_code, 200)


class SystemRoleProtectionTests(UserTypesPageTestCase):
    """The six DEC-013 fixes have to survive this page."""

    def setUp(self) -> None:
        super().setUp()
        self.manager_type = UserType.objects.get(name=MENEJER)
        self.manager = make_user(MENEJER)

    def edit_manager_type(self, **overrides):
        fields = {"name": MENEJER, "badge_colour": "blue", "category_number": ""}
        fields.update(overrides)
        return self.client.post(
            reverse("user-types-update", args=[self.manager_type.pk]), fields
        )

    def test_the_name_of_a_system_role_cannot_be_changed(self) -> None:
        self.edit_manager_type(name="Boshqa nom")

        self.manager_type.refresh_from_db()

        self.assertEqual(self.manager_type.name, MENEJER)

    def test_renaming_does_not_take_anybody_access_away(self) -> None:
        # The point of the protection: the permission matrix is written
        # against these names, so a rename would silently deny the manager
        # every page they had.
        self.assertTrue(may_open(self.manager, "kelib-arizalar"))

        self.edit_manager_type(name="Boshqa nom")

        self.assertTrue(may_open(self.manager, "kelib-arizalar"))

    def test_the_form_shows_the_name_as_read_only(self) -> None:
        page = self.client.get(
            f"{reverse('user-types')}?edit={self.manager_type.pk}"
        ).content.decode()

        self.assertIn("readonly", page)
        self.assertIn("Tizim roli", page)

    def test_a_system_role_cannot_be_deleted(self) -> None:
        response = self.client.post(
            reverse("user-types-delete", args=[self.manager_type.pk])
        )

        self.manager_type.refresh_from_db()

        self.assertEqual(response.status_code, 403)
        self.assertTrue(self.manager_type.is_active)
        self.assertIsNotNone(user_type_of(self.manager))

    def test_the_badge_colour_of_a_system_role_can_be_changed(self) -> None:
        # Only the name is fixed; how it looks is the administrator's business.
        self.edit_manager_type(badge_colour="yellow")

        self.manager_type.refresh_from_db()

        self.assertEqual(self.manager_type.badge_colour, "yellow")


class AddedTypeTests(UserTypesPageTestCase):
    """A type the installation added behaves like any master data record."""

    def setUp(self) -> None:
        super().setUp()
        self.create()
        self.added = UserType.objects.get(name=ADDED_TYPE)

    def test_it_can_be_renamed(self) -> None:
        self.client.post(
            reverse("user-types-update", args=[self.added.pk]),
            {"name": "Yangi nom", "badge_colour": "blue", "category_number": ""},
        )

        self.added.refresh_from_db()

        self.assertEqual(self.added.name, "Yangi nom")

    def test_it_can_be_deleted(self) -> None:
        self.client.post(reverse("user-types-delete", args=[self.added.pk]))

        self.added.refresh_from_db()

        self.assertFalse(self.added.is_active)
        self.assertNotIn(ADDED_TYPE, self.page())

    def test_deleting_it_leaves_the_row_behind(self) -> None:
        # DEC-009, so a user assigned this type still resolves to a record.
        self.client.post(reverse("user-types-delete", args=[self.added.pk]))

        self.assertTrue(UserType.objects.filter(pk=self.added.pk).exists())

    def test_a_user_holding_a_deleted_type_loses_their_pages(self) -> None:
        # accounts/roles.py treats a deactivated type as no type at all, which
        # is exactly why the six the department runs on are protected.
        holder = make_user(ADMIN)
        assign_user_type(holder, self.added)

        self.client.post(reverse("user-types-delete", args=[self.added.pk]))

        self.assertIsNone(user_type_of(holder))

    def test_deletion_needs_a_post(self) -> None:
        response = self.client.get(
            reverse("user-types-delete", args=[self.added.pk])
        )

        self.added.refresh_from_db()

        self.assertEqual(response.status_code, 405)
        self.assertTrue(self.added.is_active)


class PermissionTests(TestCase):
    """The page is Admin-only under DEC-015, and so are its actions."""

    def test_a_manager_may_not_open_the_page(self) -> None:
        self.client.force_login(make_user(MENEJER))

        self.assertEqual(self.client.get(reverse("user-types")).status_code, 403)

    def test_a_manager_may_not_create_a_type(self) -> None:
        self.client.force_login(make_user(MENEJER))

        response = self.client.post(
            reverse("user-types-create"),
            {"name": "Yangi", "badge_colour": "blue", "category_number": ""},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(UserType.objects.count(), len(DEPARTMENT_USER_TYPES))

    def test_an_anonymous_visitor_is_redirected(self) -> None:
        self.assertEqual(self.client.get(reverse("user-types")).status_code, 302)
