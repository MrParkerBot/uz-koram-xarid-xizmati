"""Tests for the Users page of TASK-UZK-011.

Three things carry the weight here: a password must survive the round trip
hashed and unreadable (DEC-020), deleting must deactivate rather than remove
(DEC-009), and editing must not quietly reset a password nobody typed.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.test import TestCase
from django.urls import reverse
from django.utils.crypto import get_random_string

from accounts.forms import derive_username
from accounts.models import UserProfile, UserType
from accounts.roles import ADMIN, MENEJER, assign_user_type

NEW_PASSWORD = get_random_string(24)
REPLACEMENT_PASSWORD = get_random_string(24)


class UsersPageTestCase(TestCase):
    """Somebody signed in, looking at the Users page."""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.administrator = get_user_model().objects.create_user(
            username="admin.user",
            password=get_random_string(24),
            first_name="Abdulloh",
            last_name="Karimov",
        )
        cls.admin_type = UserType.objects.get(name=ADMIN)
        cls.manager_type = UserType.objects.get(name=MENEJER)
        # The Users page is Admin-only under DEC-015, so the account running
        # these tests has to be one.
        assign_user_type(cls.administrator, cls.admin_type)

    def setUp(self) -> None:
        super().setUp()
        self.client.force_login(self.administrator)

    def create_user(self, **overrides) -> HttpResponse:
        """Post the create form with sensible defaults."""
        fields = {
            "first_name": "Bobur",
            "last_name": "Toshmatov",
            "password": NEW_PASSWORD,
            "phone_number": "90 111 22 33",
            "user_type": self.manager_type.pk,
        }
        fields.update(overrides)
        return self.client.post(reverse("user-create"), fields)


class UserCreationTests(UsersPageTestCase):
    """A created user appears in the table."""

    def test_a_created_user_appears_in_the_list(self) -> None:
        self.create_user()

        page = self.client.get(reverse("users")).content.decode()

        self.assertIn("Bobur Toshmatov", page)

    def test_a_created_user_keeps_the_details_they_were_given(self) -> None:
        self.create_user()

        created = get_user_model().objects.get(first_name="Bobur")

        self.assertEqual(created.last_name, "Toshmatov")
        self.assertEqual(created.profile.phone_number, "90 111 22 33")
        self.assertEqual(created.profile.user_type, self.manager_type)

    def test_a_user_can_be_created_without_a_type(self) -> None:
        # Somebody has to exist before anybody decides what they are for, and
        # accounts.roles refuses a user with no type anyway.
        self.create_user(user_type="")

        created = get_user_model().objects.get(first_name="Bobur")

        self.assertIsNone(created.profile.user_type)

    def test_creation_redirects_back_to_the_list(self) -> None:
        response = self.create_user()

        self.assertRedirects(response, reverse("users"))

    def test_a_missing_password_is_refused(self) -> None:
        response = self.create_user(password="")

        self.assertFalse(get_user_model().objects.filter(first_name="Bobur").exists())
        self.assertContains(response, "Majburiy maydon")

    def test_a_weak_password_is_refused(self) -> None:
        # The project's AUTH_PASSWORD_VALIDATORS apply here as they do at the
        # login form; an administrator must not be able to set "12345" for
        # somebody else.
        response = self.create_user(password="12345")

        self.assertFalse(get_user_model().objects.filter(first_name="Bobur").exists())
        self.assertEqual(response.status_code, 200)

    def test_a_rejected_submission_reopens_the_form(self) -> None:
        # Otherwise the person is returned to a closed dialog and has to guess
        # what went wrong.
        response = self.create_user(password="")

        self.assertNotIn(
            'id="user-modal" class="modal-overlay hidden"', response.content.decode()
        )


class UsernameDerivationTests(UsersPageTestCase):
    """The form captures no username, but the login page asks for one."""

    def test_a_username_is_derived_from_the_name(self) -> None:
        self.create_user()

        self.assertTrue(
            get_user_model().objects.filter(username="bobur.toshmatov").exists()
        )

    def test_a_second_person_with_the_same_name_gets_their_own(self) -> None:
        self.create_user()
        self.create_user()

        usernames = set(
            get_user_model()
            .objects.filter(first_name="Bobur")
            .values_list("username", flat=True)
        )

        self.assertEqual(usernames, {"bobur.toshmatov", "bobur.toshmatov2"})

    def test_the_derived_username_is_shown_in_the_table(self) -> None:
        # Nobody can sign in with a name they were never told.
        self.create_user()

        page = self.client.get(reverse("users")).content.decode()

        self.assertIn("bobur.toshmatov", page)

    def test_a_name_that_slugifies_to_nothing_still_produces_a_username(self) -> None:
        self.assertTrue(derive_username("", ""))


class PasswordHandlingTests(UsersPageTestCase):
    """DEC-020: hashed, never displayed, resettable but not readable."""

    def test_the_password_is_stored_hashed(self) -> None:
        self.create_user()

        created = get_user_model().objects.get(first_name="Bobur")

        self.assertNotIn(NEW_PASSWORD, created.password)
        self.assertTrue(created.check_password(NEW_PASSWORD))

    def test_the_new_user_can_sign_in_with_it(self) -> None:
        self.create_user()
        self.client.logout()

        signed_in = self.client.login(
            username="bobur.toshmatov", password=NEW_PASSWORD
        )

        self.assertTrue(signed_in)

    def test_no_password_appears_on_the_page(self) -> None:
        self.create_user()

        page = self.client.get(reverse("users")).content.decode()

        self.assertNotIn(NEW_PASSWORD, page)

    def test_the_edit_form_does_not_return_the_password(self) -> None:
        self.create_user()
        created = get_user_model().objects.get(first_name="Bobur")

        page = self.client.get(f"{reverse('users')}?edit={created.pk}")

        self.assertNotContains(page, NEW_PASSWORD)

    def test_the_password_column_is_not_built(self) -> None:
        # DEC-020 supersedes the table definition in section 3.3.
        page = self.client.get(reverse("users")).content.decode()

        self.assertNotIn("<th>Parol</th>", page)


class UserEditingTests(UsersPageTestCase):
    """An edited user shows the edited values."""

    def setUp(self) -> None:
        super().setUp()
        self.create_user()
        self.edited = get_user_model().objects.get(first_name="Bobur")

    def edit(self, **overrides):
        fields = {
            "first_name": "Bobur",
            "last_name": "Toshmatov",
            "password": "",
            "phone_number": "90 111 22 33",
            "user_type": self.manager_type.pk,
        }
        fields.update(overrides)
        return self.client.post(
            reverse("user-update", args=[self.edited.pk]), fields
        )

    def test_an_edited_user_shows_the_edited_values(self) -> None:
        self.edit(last_name="Toshmatova", phone_number="93 555 66 77")

        self.edited.refresh_from_db()

        self.assertEqual(self.edited.last_name, "Toshmatova")
        self.assertEqual(self.edited.profile.phone_number, "93 555 66 77")

    def test_a_type_can_be_changed(self) -> None:
        self.edit(user_type=self.admin_type.pk)

        self.assertEqual(
            UserProfile.objects.get(user=self.edited).user_type, self.admin_type
        )

    def test_an_empty_password_leaves_the_current_one_alone(self) -> None:
        # Changing somebody's phone number must not silently lock them out.
        self.edit(phone_number="93 555 66 77")

        self.edited.refresh_from_db()

        self.assertTrue(self.edited.check_password(NEW_PASSWORD))

    def test_a_supplied_password_replaces_the_current_one(self) -> None:
        self.edit(password=REPLACEMENT_PASSWORD)

        self.edited.refresh_from_db()

        self.assertTrue(self.edited.check_password(REPLACEMENT_PASSWORD))
        self.assertFalse(self.edited.check_password(NEW_PASSWORD))

    def test_editing_does_not_change_the_username(self) -> None:
        # The username is what they sign in with; renaming somebody must not
        # take their login away.
        self.edit(first_name="Boburbek")

        self.edited.refresh_from_db()

        self.assertEqual(self.edited.username, "bobur.toshmatov")

    def test_the_edit_form_opens_filled_in(self) -> None:
        page = self.client.get(f"{reverse('users')}?edit={self.edited.pk}")

        self.assertContains(page, 'value="Toshmatov"')
        self.assertContains(page, "90 111 22 33")

    def test_editing_a_user_who_does_not_exist_is_a_not_found(self) -> None:
        response = self.client.get(f"{reverse('users')}?edit=9999")

        self.assertEqual(response.status_code, 404)


class UserDeletionTests(UsersPageTestCase):
    """DEC-009: deleting is deactivating."""

    def setUp(self) -> None:
        super().setUp()
        self.create_user()
        self.deleted = get_user_model().objects.get(first_name="Bobur")

    def delete(self):
        return self.client.post(reverse("user-delete", args=[self.deleted.pk]))

    def test_a_deleted_user_leaves_the_list(self) -> None:
        self.delete()

        page = self.client.get(reverse("users")).content.decode()

        self.assertNotIn("Bobur Toshmatov", page)

    def test_a_deleted_user_still_exists(self) -> None:
        # Everything that already refers to them has to keep resolving.
        self.delete()

        self.assertTrue(get_user_model().objects.filter(pk=self.deleted.pk).exists())

    def test_a_deleted_user_cannot_sign_in(self) -> None:
        self.delete()
        self.client.logout()

        signed_in = self.client.login(
            username="bobur.toshmatov", password=NEW_PASSWORD
        )

        self.assertFalse(signed_in)

    def test_deletion_needs_a_post(self) -> None:
        # A link that deletes can be followed by anything that fetches URLs.
        response = self.client.get(reverse("user-delete", args=[self.deleted.pk]))

        self.deleted.refresh_from_db()

        self.assertEqual(response.status_code, 405)
        self.assertTrue(self.deleted.is_active)

    def test_the_page_asks_before_deleting(self) -> None:
        # DEC-009 requires a confirmation.
        page = self.client.get(reverse("users")).content.decode()

        self.assertIn("onsubmit=\"return confirm(", page)

    def test_deleting_someone_already_deleted_is_a_not_found(self) -> None:
        self.delete()

        response = self.delete()

        self.assertEqual(response.status_code, 404)


class AnonymousAccessTests(TestCase):
    """The page and its actions are closed, like every other page."""

    def test_the_list_redirects_an_anonymous_visitor(self) -> None:
        response = self.client.get(reverse("users"))

        self.assertEqual(response.status_code, 302)

    def test_creating_redirects_an_anonymous_visitor(self) -> None:
        response = self.client.post(reverse("user-create"), {})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(get_user_model().objects.count(), 0)


class PhoneNumberTests(UsersPageTestCase):
    """The page prints +998 in front of whatever is stored."""

    def test_the_documented_format_is_accepted(self) -> None:
        self.create_user(phone_number="90 123 45 67")

        self.assertTrue(get_user_model().objects.filter(first_name="Bobur").exists())

    def test_a_number_in_another_shape_is_refused(self) -> None:
        for supplied in ("901234567", "+998 90 123 45 67", "telefon yo'q", "   "):
            with self.subTest(phone_number=supplied):
                response = self.create_user(phone_number=supplied)

                self.assertFalse(
                    get_user_model().objects.filter(first_name="Bobur").exists()
                )
                self.assertEqual(response.status_code, 200)

    def test_the_country_code_is_not_stored_twice(self) -> None:
        # The page renders a literal +998 before the field, so a number that
        # carried one would read "+998 +998 90 ...".
        self.create_user(phone_number="90 123 45 67")

        page = self.client.get(reverse("users")).content.decode()

        self.assertIn("+998 90 123 45 67", page)
        self.assertNotIn("+998 +998", page)


class SelfDeletionTests(UsersPageTestCase):
    """Nobody deletes the account they are signed in with."""

    def test_deleting_your_own_account_is_refused(self) -> None:
        response = self.client.post(
            reverse("user-delete", args=[self.administrator.pk])
        )

        self.administrator.refresh_from_db()

        self.assertEqual(response.status_code, 403)
        self.assertTrue(self.administrator.is_active)

    def test_deleting_somebody_else_still_works(self) -> None:
        self.create_user()
        other = get_user_model().objects.get(first_name="Bobur")

        self.client.post(reverse("user-delete", args=[other.pk]))

        other.refresh_from_db()

        self.assertFalse(other.is_active)
