"""Tests for the User Specialty master data page of TASK-UZK-014.

The page is the first of the eight the specification describes in the same
shape, so what is proved here is the shape as much as the page: Save adds,
Cancel leaves nothing behind, Edit opens filled in, and Delete asks first and
then deactivates rather than removing (DEC-009).
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils.crypto import get_random_string

from accounts.models import UserSpecialty, UserType
from accounts.roles import ADMIN, MENEJER, assign_user_type


def make_user(type_name: str = ADMIN):
    user = get_user_model().objects.create_user(
        username=f"user.{get_random_string(8).lower()}",
        password=get_random_string(24),
        first_name="Test",
        last_name=type_name,
    )
    assign_user_type(user, UserType.objects.get(name=type_name))
    return user


class SpecialtyPageTestCase(TestCase):
    """An administrator on the User Specialty page."""

    def setUp(self) -> None:
        self.client.force_login(make_user(ADMIN))

    def create(self, **overrides):
        fields = {"name": "Mexanik muhandis", "category_number": ""}
        fields.update(overrides)
        return self.client.post(reverse("user-specialty-create"), fields)

    def page(self) -> str:
        return self.client.get(reverse("user-specialty")).content.decode()


class CreationTests(SpecialtyPageTestCase):
    """Save adds the record to the list."""

    def test_a_created_record_appears_in_the_table(self) -> None:
        self.create()

        self.assertIn("Mexanik muhandis", self.page())

    def test_creation_redirects_back_to_the_page(self) -> None:
        self.assertRedirects(self.create(), reverse("user-specialty"))

    def test_a_name_is_required(self) -> None:
        response = self.create(name="")

        self.assertEqual(UserSpecialty.objects.count(), 0)
        self.assertEqual(response.status_code, 200)

    def test_two_records_cannot_share_a_name(self) -> None:
        self.create()

        response = self.create()

        self.assertEqual(UserSpecialty.objects.count(), 1)
        self.assertEqual(response.status_code, 200)

    def test_the_category_number_is_optional(self) -> None:
        self.create()

        self.assertIsNone(UserSpecialty.objects.get().category_number)

    def test_a_six_digit_category_number_is_accepted(self) -> None:
        self.create(category_number=100123)

        self.assertEqual(UserSpecialty.objects.get().category_number, 100123)

    def test_a_category_number_of_another_length_is_refused(self) -> None:
        # DEC-023: six digits, and 12345 or 1234567 are not six digits.
        for supplied in (12345, 1234567, 0):
            with self.subTest(category_number=supplied):
                response = self.create(category_number=supplied)

                self.assertEqual(UserSpecialty.objects.count(), 0)
                self.assertEqual(response.status_code, 200)


class CancelTests(SpecialtyPageTestCase):
    """Cancel leaves no record behind."""

    def test_opening_the_form_and_leaving_creates_nothing(self) -> None:
        self.client.get(reverse("user-specialty"))

        self.assertEqual(UserSpecialty.objects.count(), 0)

    def test_cancel_from_an_edit_changes_nothing(self) -> None:
        self.create()
        specialty = UserSpecialty.objects.get()

        self.client.get(f"{reverse('user-specialty')}?edit={specialty.pk}")
        self.client.get(reverse("user-specialty"))

        specialty.refresh_from_db()

        self.assertEqual(specialty.name, "Mexanik muhandis")


class EditingTests(SpecialtyPageTestCase):
    """Edit opens the form filled in and saves what was changed."""

    def setUp(self) -> None:
        super().setUp()
        self.create()
        self.specialty = UserSpecialty.objects.get()

    def test_the_form_opens_filled_in(self) -> None:
        page = self.client.get(
            f"{reverse('user-specialty')}?edit={self.specialty.pk}"
        )

        self.assertContains(page, 'value="Mexanik muhandis"')

    def test_an_edited_record_shows_the_edited_values(self) -> None:
        self.client.post(
            reverse("user-specialty-update", args=[self.specialty.pk]),
            {"name": "Elektrik muhandis", "category_number": 100456},
        )

        self.specialty.refresh_from_db()

        self.assertEqual(self.specialty.name, "Elektrik muhandis")
        self.assertEqual(self.specialty.category_number, 100456)

    def test_editing_does_not_create_a_second_record(self) -> None:
        self.client.post(
            reverse("user-specialty-update", args=[self.specialty.pk]),
            {"name": "Texnolog", "category_number": ""},
        )

        self.assertEqual(UserSpecialty.objects.count(), 1)

    def test_editing_a_record_that_does_not_exist_is_a_not_found(self) -> None:
        response = self.client.get(f"{reverse('user-specialty')}?edit=9999")

        self.assertEqual(response.status_code, 404)


class DeletionTests(SpecialtyPageTestCase):
    """DEC-009: ask, then deactivate."""

    def setUp(self) -> None:
        super().setUp()
        self.create()
        self.specialty = UserSpecialty.objects.get()

    def delete(self):
        return self.client.post(
            reverse("user-specialty-delete", args=[self.specialty.pk])
        )

    def test_a_deleted_record_leaves_the_list(self) -> None:
        self.delete()

        self.assertNotIn("Mexanik muhandis", self.page())

    def test_a_deleted_record_still_exists(self) -> None:
        # So that a person or an application already referring to it resolves.
        self.delete()

        self.specialty.refresh_from_db()

        self.assertFalse(self.specialty.is_active)
        self.assertEqual(UserSpecialty.objects.count(), 1)

    def test_a_deleted_record_leaves_the_active_queryset(self) -> None:
        # Which is what every drop-down in the application will be built on.
        self.delete()

        self.assertEqual(UserSpecialty.objects.active().count(), 0)

    def test_the_page_asks_before_deleting(self) -> None:
        self.assertIn("onsubmit=\"return confirm(", self.page())

    def test_deletion_needs_a_post(self) -> None:
        response = self.client.get(
            reverse("user-specialty-delete", args=[self.specialty.pk])
        )

        self.specialty.refresh_from_db()

        self.assertEqual(response.status_code, 405)
        self.assertTrue(self.specialty.is_active)

    def test_deleting_twice_is_a_not_found(self) -> None:
        self.delete()

        self.assertEqual(self.delete().status_code, 404)

    def test_a_deleted_name_cannot_be_used_again(self) -> None:
        # Soft delete and a unique name meet here, and uniqueness wins: the
        # deactivated row keeps the name, so re-creating it is refused with a
        # validation error rather than silently reviving the old record.
        # Whether an administrator should instead be able to restore it is
        # recorded as a question for the customer.
        self.delete()

        response = self.create()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(UserSpecialty.objects.count(), 1)
        self.assertFalse(UserSpecialty.objects.get().is_active)


class PermissionTests(TestCase):
    """The page is Admin-only under DEC-015, and so are its actions."""

    def setUp(self) -> None:
        self.specialty = UserSpecialty.objects.create(name="Texnolog")

    def test_a_manager_may_not_open_the_page(self) -> None:
        self.client.force_login(make_user(MENEJER))

        self.assertEqual(
            self.client.get(reverse("user-specialty")).status_code, 403
        )

    def test_a_manager_may_not_create(self) -> None:
        self.client.force_login(make_user(MENEJER))

        response = self.client.post(
            reverse("user-specialty-create"), {"name": "Yangi"}
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(UserSpecialty.objects.count(), 1)

    def test_a_manager_may_not_delete(self) -> None:
        self.client.force_login(make_user(MENEJER))

        response = self.client.post(
            reverse("user-specialty-delete", args=[self.specialty.pk])
        )
        self.specialty.refresh_from_db()

        self.assertEqual(response.status_code, 403)
        self.assertTrue(self.specialty.is_active)

    def test_an_anonymous_visitor_is_redirected(self) -> None:
        self.assertEqual(
            self.client.get(reverse("user-specialty")).status_code, 302
        )
