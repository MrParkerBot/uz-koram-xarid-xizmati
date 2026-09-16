"""Tests for departments: the page, the user link, and department_of.

DEC-018 makes departments Admin-maintained master data and has the section 4.9
Xarid Arizasi form fill one in from whoever is signed in. Three things follow,
and all three are tested here rather than left to TASK-UZK-030 to discover:

- there has to be somewhere to maintain them, which is a page the
  specification never describes;
- a user has to be attached to one;
- something has to answer which department a signed-in user belongs to, for
  every case including the ones that are not a department.

The page itself is the same shape as the other master data pages, so its tests
cover the same ground as theirs.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils.crypto import get_random_string

from accounts.models import UserProfile, UserType
from accounts.roles import ADMIN, MENEJER, assign_user_type, department_of
from reference.models import Department

# Without the apostrophe the real name would carry ("Texnik bo`lim"): the
# page escapes one to &#x27;, which would turn every assertion about the
# rendered name into an assertion about HTML escaping.
ADDED_DEPARTMENT = "Texnik bolim"


def make_user(type_name: str = ADMIN):
    user = get_user_model().objects.create_user(
        username=f"user.{get_random_string(8).lower()}",
        password=get_random_string(24),
        first_name="Test",
        last_name=type_name,
    )
    assign_user_type(user, UserType.objects.get(name=type_name))
    return user


class DepartmentPageTestCase(TestCase):
    """An administrator on the Bo`limlar page."""

    def setUp(self) -> None:
        self.client.force_login(make_user(ADMIN))

    def create(self, **overrides):
        fields = {"name": ADDED_DEPARTMENT, "category_number": ""}
        fields.update(overrides)
        return self.client.post(reverse("bolim-royhati-create"), fields)

    def page(self) -> str:
        return self.client.get(reverse("bolim-royhati")).content.decode()


class EmptyTableTests(DepartmentPageTestCase):
    """The page ships empty: the specification names no departments."""

    def test_nothing_is_seeded(self) -> None:
        self.assertEqual(Department.objects.count(), 0)

    def test_the_empty_page_renders(self) -> None:
        self.assertIn("Hozircha yozuv yo", self.page())


class CreationTests(DepartmentPageTestCase):
    """Save adds the department to the list."""

    def test_a_created_department_appears_in_the_table(self) -> None:
        self.create()

        self.assertIn(ADDED_DEPARTMENT, self.page())

    def test_creation_redirects_back_to_the_page(self) -> None:
        self.assertRedirects(self.create(), reverse("bolim-royhati"))

    def test_a_name_is_required(self) -> None:
        response = self.create(name="")

        self.assertEqual(Department.objects.count(), 0)
        self.assertEqual(response.status_code, 200)

    def test_two_departments_cannot_share_a_name(self) -> None:
        self.create()

        response = self.create()

        self.assertEqual(Department.objects.count(), 1)
        self.assertContains(response, "Bu nom allaqachon mavjud")


class DeletionTests(DepartmentPageTestCase):
    """DEC-009: ask, then deactivate."""

    def setUp(self) -> None:
        super().setUp()
        self.create()
        self.department = Department.objects.get()

    def delete(self):
        return self.client.post(
            reverse("bolim-royhati-delete", args=[self.department.pk])
        )

    def test_a_deleted_department_leaves_the_list(self) -> None:
        self.delete()

        self.assertNotIn(ADDED_DEPARTMENT, self.page())

    def test_a_deleted_department_still_exists(self) -> None:
        self.delete()
        self.department.refresh_from_db()

        self.assertFalse(self.department.is_active)
        self.assertEqual(Department.objects.count(), 1)

    def test_the_page_asks_before_deleting(self) -> None:
        self.assertIn("data-confirm=", self.page())

    def test_deletion_needs_a_post(self) -> None:
        response = self.client.get(
            reverse("bolim-royhati-delete", args=[self.department.pk])
        )
        self.department.refresh_from_db()

        self.assertEqual(response.status_code, 405)
        self.assertTrue(self.department.is_active)

    def test_a_department_somebody_belongs_to_survives_deletion(self) -> None:
        # The whole point of DEC-009 here: deleting a department must not take
        # the people in it with it, or strand the applications they raised.
        member = make_user(MENEJER)
        profile = UserProfile.objects.get(user=member)
        profile.department = self.department
        profile.save(update_fields=["department"])

        self.delete()
        profile.refresh_from_db()

        self.assertEqual(profile.department, self.department)


class UserLinkTests(TestCase):
    """DEC-018: a user belongs to a department, set on the Users page."""

    def setUp(self) -> None:
        self.client.force_login(make_user(ADMIN))
        self.department = Department.objects.create(name=ADDED_DEPARTMENT)

    def create_user(self, **overrides):
        fields = {
            "first_name": "Bobur",
            "last_name": "Toshmatov",
            "password": get_random_string(24),
            "phone_number": "90 123 45 67",
            "user_type": UserType.objects.get(name=MENEJER).pk,
            "department": self.department.pk,
        }
        fields.update(overrides)
        return self.client.post(reverse("user-create"), fields)

    def created_profile(self) -> UserProfile:
        return UserProfile.objects.get(user__first_name="Bobur")

    def test_a_user_can_be_given_a_department(self) -> None:
        self.create_user()

        self.assertEqual(self.created_profile().department, self.department)

    def test_the_department_is_optional(self) -> None:
        # DEC-018 says everybody belongs to one, but the users who existed
        # before departments did have none, and refusing to save them would
        # be worse than the gap.
        self.create_user(department="")

        self.assertIsNone(self.created_profile().department)

    def test_the_table_shows_which_department_a_user_is_in(self) -> None:
        # Otherwise the page captures the department and then hides it, and
        # the only way to check who is where is to open every row in turn.
        self.create_user()

        page = self.client.get(reverse("users")).content.decode()

        self.assertIn(ADDED_DEPARTMENT, page)

    def test_the_table_says_so_when_a_user_has_no_department(self) -> None:
        self.create_user(department="")

        page = self.client.get(reverse("users")).content.decode()

        self.assertIn("Belgilanmagan", page)

    def test_the_form_offers_only_active_departments(self) -> None:
        retired = Department.objects.create(name="Eski bolim")
        retired.is_active = False
        retired.save(update_fields=["is_active"])

        page = self.client.get(reverse("users")).content.decode()

        self.assertIn(ADDED_DEPARTMENT, page)
        self.assertNotIn("Eski bolim", page)

    def test_editing_a_user_keeps_the_department_it_shows(self) -> None:
        self.create_user()
        user = get_user_model().objects.get(first_name="Bobur")

        page = self.client.get(f"{reverse('users')}?edit={user.pk}").content.decode()

        self.assertIn(f'value="{self.department.pk}" selected', page)

    def test_a_department_can_be_taken_away_again(self) -> None:
        self.create_user()
        user = get_user_model().objects.get(first_name="Bobur")

        self.client.post(
            reverse("user-update", args=[user.pk]),
            {
                "first_name": "Bobur",
                "last_name": "Toshmatov",
                "password": "",
                "phone_number": "90 123 45 67",
                "user_type": UserType.objects.get(name=MENEJER).pk,
                "department": "",
            },
        )

        self.assertIsNone(self.created_profile().department)


class DepartmentOfTests(TestCase):
    """The three answers TASK-UZK-030 has to handle."""

    def setUp(self) -> None:
        self.department = Department.objects.create(name=ADDED_DEPARTMENT)

    def test_it_answers_the_department_of_a_member(self) -> None:
        member = make_user(MENEJER)
        profile = UserProfile.objects.get(user=member)
        profile.department = self.department
        profile.save(update_fields=["department"])

        self.assertEqual(department_of(member), self.department)

    def test_it_answers_none_for_somebody_with_no_department(self) -> None:
        self.assertIsNone(department_of(make_user(MENEJER)))

    def test_it_answers_none_for_an_anonymous_visitor(self) -> None:
        from django.contrib.auth.models import AnonymousUser

        self.assertIsNone(department_of(AnonymousUser()))

    def test_it_answers_none_for_a_deleted_department(self) -> None:
        # DEC-009 keeps the row for the records that already point at it, not
        # to keep offering it as somewhere a person currently works.
        member = make_user(MENEJER)
        profile = UserProfile.objects.get(user=member)
        profile.department = self.department
        profile.save(update_fields=["department"])

        self.department.is_active = False
        self.department.save(update_fields=["is_active"])

        self.assertIsNone(department_of(member))


class PermissionTests(TestCase):
    """The invented page is Admin-only, like every other master data page."""

    def setUp(self) -> None:
        self.department = Department.objects.create(name=ADDED_DEPARTMENT)

    def test_a_manager_may_not_open_the_page(self) -> None:
        self.client.force_login(make_user(MENEJER))

        self.assertEqual(
            self.client.get(reverse("bolim-royhati")).status_code, 403
        )

    def test_a_manager_may_not_create(self) -> None:
        self.client.force_login(make_user(MENEJER))

        response = self.client.post(
            reverse("bolim-royhati-create"),
            {"name": "Yangi", "category_number": ""},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(Department.objects.count(), 1)

    def test_a_manager_may_not_delete(self) -> None:
        self.client.force_login(make_user(MENEJER))

        response = self.client.post(
            reverse("bolim-royhati-delete", args=[self.department.pk])
        )
        self.department.refresh_from_db()

        self.assertEqual(response.status_code, 403)
        self.assertTrue(self.department.is_active)

    def test_an_anonymous_visitor_is_redirected(self) -> None:
        self.assertEqual(
            self.client.get(reverse("bolim-royhati")).status_code, 302
        )
