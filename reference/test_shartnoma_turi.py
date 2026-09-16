"""Tests for the Shartnoma turi master data page of TASK-UZK-019.

The fourth page built out of MasterDataPage and the smallest: a table of names
and a form with one field.

What is specific to it is CONFLICT-004. Section 3.7 gives contract type a
maintainable page while the section 4.8 contract form fixes it to Import and
Local, and DEC-023 decides for section 3.7. So the two seeded types are a
starting point rather than the list, and the tests say so directly - one is
renamed and the other deleted - because TASK-UZK-034 and TASK-UZK-035 read this
table and must not inherit a fixed pair.
"""

from __future__ import annotations

from importlib import import_module

from django.apps import apps
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils.crypto import get_random_string

from accounts.models import UserType
from accounts.roles import ADMIN, MENEJER, assign_user_type
from reference.models import ShartnomaTuri

# No apostrophe: the page escapes one to &#x27;, which would make every
# assertion about the rendered name an assertion about HTML escaping.
# Not "Framework": the form placeholder reads "masalan: Import, Local,
# Framework...", so a test asserting a deleted row has left the page would
# find the word in the placeholder and pass or fail for the wrong reason.
ADDED_TYPE = "Tolling"

# The five DEC-010 seeds. Named here so the tests read against the decision
# rather than against a list retyped in six places.
SEEDED_TYPES = ("Import", "Mahalliy (Local)")

# One seeded type the tests rename and clash against.
RENAMEABLE = "Import"


def make_user(type_name: str = ADMIN):
    user = get_user_model().objects.create_user(
        username=f"user.{get_random_string(8).lower()}",
        password=get_random_string(24),
        first_name="Test",
        last_name=type_name,
    )
    assign_user_type(user, UserType.objects.get(name=type_name))
    return user


class ShartnomaTuriPageTestCase(TestCase):
    """An administrator on the Shartnoma Turi page."""

    def setUp(self) -> None:
        self.client.force_login(make_user(ADMIN))

    def create(self, **overrides):
        fields = {
            "name": ADDED_TYPE,
            "category_number": "",
        }
        fields.update(overrides)
        return self.client.post(reverse("shartnoma-turi-create"), fields)

    def page(self) -> str:
        return self.client.get(reverse("shartnoma-turi")).content.decode()


class SeedingTests(ShartnomaTuriPageTestCase):
    """DEC-023: two types to start with, as a starting point not a pair."""

    def test_the_two_decided_types_are_there(self) -> None:
        self.assertEqual(
            set(ShartnomaTuri.objects.values_list("name", flat=True)),
            set(SEEDED_TYPES),
        )

    def test_they_appear_on_the_page(self) -> None:
        page = self.page()

        for name in SEEDED_TYPES:
            with self.subTest(contract_type=name):
                self.assertIn(name, page)

    def test_a_seeded_contract_type_can_be_deleted(self) -> None:
        # Unlike the six User Types, these are examples. Nothing in the code
        # is written against their names, so nothing breaks when one goes.
        seeded = ShartnomaTuri.objects.get(name="Mahalliy (Local)")

        self.client.post(reverse("shartnoma-turi-delete", args=[seeded.pk]))
        seeded.refresh_from_db()

        self.assertFalse(seeded.is_active)

    def test_seeding_again_adds_nothing(self) -> None:
        # The migration runs get_or_create, so re-running it against a
        # database that already has the rows leaves them alone rather than
        # failing on the unique name.
        seed = import_module("reference.migrations.0009_seed_shartnoma_turlari")

        seed.seed_shartnoma_turlari(apps, None)

        self.assertEqual(ShartnomaTuri.objects.count(), len(SEEDED_TYPES))

    def test_a_seeded_contract_type_can_be_renamed(self) -> None:
        seeded = ShartnomaTuri.objects.get(name=RENAMEABLE)

        self.client.post(
            reverse("shartnoma-turi-update", args=[seeded.pk]),
            {"name": "Importdan", "category_number": ""},
        )
        seeded.refresh_from_db()

        self.assertEqual(seeded.name, "Importdan")


class CreationTests(ShartnomaTuriPageTestCase):
    """Save adds the contract_type to the list."""

    def test_a_created_contract_type_appears_in_the_table(self) -> None:
        self.create()

        self.assertIn(ADDED_TYPE, self.page())

    def test_creation_redirects_back_to_the_page(self) -> None:
        self.assertRedirects(self.create(), reverse("shartnoma-turi"))

    def test_a_name_is_required(self) -> None:
        response = self.create(name="")

        self.assertFalse(ShartnomaTuri.objects.filter(name="").exists())
        self.assertEqual(response.status_code, 200)

    def test_two_contract_types_cannot_share_a_name(self) -> None:
        response = self.create(name=RENAMEABLE)

        self.assertEqual(
            ShartnomaTuri.objects.filter(name__iexact=RENAMEABLE).count(), 1
        )
        self.assertContains(response, "Bu nom allaqachon mavjud")

    def test_a_name_differing_only_in_case_is_refused(self) -> None:
        response = self.create(name=RENAMEABLE.upper())

        self.assertEqual(
            ShartnomaTuri.objects.filter(name__iexact=RENAMEABLE).count(), 1
        )
        self.assertEqual(response.status_code, 200)

    def test_the_category_number_is_optional(self) -> None:
        self.create()

        self.assertIsNone(ShartnomaTuri.objects.get(name=ADDED_TYPE).category_number)

    def test_a_six_digit_category_number_is_accepted(self) -> None:
        self.create(category_number=100123)

        self.assertEqual(
            ShartnomaTuri.objects.get(name=ADDED_TYPE).category_number, 100123
        )

    def test_a_category_number_of_another_length_is_refused(self) -> None:
        # DEC-023: six digits, and 12345 or 1234567 are not six digits.
        for supplied in (12345, 1234567, 0):
            with self.subTest(category_number=supplied):
                response = self.create(category_number=supplied)

                self.assertFalse(
                    ShartnomaTuri.objects.filter(name=ADDED_TYPE).exists()
                )
                self.assertEqual(response.status_code, 200)


class CancelTests(ShartnomaTuriPageTestCase):
    """Cancel leaves no record behind."""

    def test_opening_the_form_and_leaving_creates_nothing(self) -> None:
        before = ShartnomaTuri.objects.count()

        self.client.get(reverse("shartnoma-turi"))

        self.assertEqual(ShartnomaTuri.objects.count(), before)

    def test_cancel_from_an_edit_changes_nothing(self) -> None:
        contract_type = ShartnomaTuri.objects.get(name=RENAMEABLE)

        self.client.get(f"{reverse('shartnoma-turi')}?edit={contract_type.pk}")
        self.client.get(reverse("shartnoma-turi"))

        contract_type.refresh_from_db()

        self.assertEqual(contract_type.name, RENAMEABLE)


class EditingTests(ShartnomaTuriPageTestCase):
    """Edit opens the form filled in and saves what was changed."""

    def setUp(self) -> None:
        super().setUp()
        self.create()
        self.contract_type = ShartnomaTuri.objects.get(name=ADDED_TYPE)

    def edit(self, **overrides):
        fields = {
            "name": "Tolling shartnoma",
            "category_number": "",
        }
        fields.update(overrides)
        return self.client.post(
            reverse("shartnoma-turi-update", args=[self.contract_type.pk]), fields
        )

    def test_the_form_opens_filled_in(self) -> None:
        page = self.client.get(
            f"{reverse('shartnoma-turi')}?edit={self.contract_type.pk}"
        )

        self.assertContains(page, f'value="{ADDED_TYPE}"')

    def test_the_form_posts_to_the_update_route_when_editing(self) -> None:
        page = self.client.get(
            f"{reverse('shartnoma-turi')}?edit={self.contract_type.pk}"
        )

        self.assertContains(
            page, reverse("shartnoma-turi-update", args=[self.contract_type.pk])
        )

    def test_an_edited_contract_type_shows_the_edited_values(self) -> None:
        self.edit(category_number=100456)

        self.contract_type.refresh_from_db()

        self.assertEqual(self.contract_type.name, "Tolling shartnoma")
        self.assertEqual(self.contract_type.category_number, 100456)

    def test_editing_does_not_create_a_second_record(self) -> None:
        before = ShartnomaTuri.objects.count()

        self.edit()

        self.assertEqual(ShartnomaTuri.objects.count(), before)

    def test_an_invalid_edit_keeps_the_form_on_the_record(self) -> None:
        # Otherwise Save on a rejected edit would silently become an Add.
        response = self.edit(name=RENAMEABLE)

        self.assertContains(
            response, reverse("shartnoma-turi-update", args=[self.contract_type.pk])
        )

    def test_editing_a_record_that_does_not_exist_is_a_not_found(self) -> None:
        response = self.client.get(f"{reverse('shartnoma-turi')}?edit=9999")

        self.assertEqual(response.status_code, 404)

    def test_an_edit_id_that_is_not_a_number_is_a_not_found(self) -> None:
        # ?edit= is the one place a pk reaches the page without going through
        # a URL converter, so it is the one place a non-number can arrive.
        response = self.client.get(f"{reverse('shartnoma-turi')}?edit=abc")

        self.assertEqual(response.status_code, 404)


class DeletionTests(ShartnomaTuriPageTestCase):
    """DEC-009: ask, then deactivate."""

    def setUp(self) -> None:
        super().setUp()
        self.create()
        self.contract_type = ShartnomaTuri.objects.get(name=ADDED_TYPE)

    def delete(self):
        return self.client.post(
            reverse("shartnoma-turi-delete", args=[self.contract_type.pk])
        )

    def test_a_deleted_contract_type_leaves_the_list(self) -> None:
        self.delete()

        self.assertNotIn(ADDED_TYPE, self.page())

    def test_a_deleted_contract_type_still_exists(self) -> None:
        # So that an application already sitting in it still resolves.
        self.delete()

        self.contract_type.refresh_from_db()

        self.assertFalse(self.contract_type.is_active)
        self.assertTrue(ShartnomaTuri.objects.filter(pk=self.contract_type.pk).exists())

    def test_a_deleted_contract_type_leaves_the_active_queryset(self) -> None:
        # Which is what every drop-down in the application will be built on.
        self.delete()

        self.assertFalse(
            ShartnomaTuri.objects.active().filter(pk=self.contract_type.pk).exists()
        )

    def test_the_page_asks_before_deleting(self) -> None:
        self.assertIn("data-confirm=", self.page())

    def test_deletion_needs_a_post(self) -> None:
        response = self.client.get(
            reverse("shartnoma-turi-delete", args=[self.contract_type.pk])
        )

        self.contract_type.refresh_from_db()

        self.assertEqual(response.status_code, 405)
        self.assertTrue(self.contract_type.is_active)

    def test_deleting_twice_is_a_not_found(self) -> None:
        self.delete()

        self.assertEqual(self.delete().status_code, 404)

    def test_a_deleted_name_cannot_be_used_again(self) -> None:
        # Soft delete and a unique name meet here, and uniqueness wins: the
        # deactivated row keeps the name, so re-creating it is refused with a
        # validation error rather than silently reviving the old record.
        self.delete()

        response = self.create()

        self.assertEqual(ShartnomaTuri.objects.filter(name=ADDED_TYPE).count(), 1)
        # Without the apostrophe: the page escapes it to &#x27;.
        self.assertContains(response, "chirilgan yozuvga tegishli")


class PermissionTests(TestCase):
    """The page is Admin-only under DEC-015, and so are its actions."""

    def setUp(self) -> None:
        self.contract_type = ShartnomaTuri.objects.get(name=RENAMEABLE)

    def test_a_manager_may_not_open_the_page(self) -> None:
        self.client.force_login(make_user(MENEJER))

        self.assertEqual(self.client.get(reverse("shartnoma-turi")).status_code, 403)

    def test_a_manager_may_not_create(self) -> None:
        self.client.force_login(make_user(MENEJER))

        response = self.client.post(
            reverse("shartnoma-turi-create"),
            {"name": ADDED_TYPE, "category_number": ""},
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(ShartnomaTuri.objects.filter(name=ADDED_TYPE).exists())

    def test_a_manager_may_not_edit(self) -> None:
        # accounts/test_permissions.py walks the page views and the Users
        # page's actions, but not a master data page's actions, so each of
        # the four routes is proved here.
        self.client.force_login(make_user(MENEJER))

        response = self.client.post(
            reverse("shartnoma-turi-update", args=[self.contract_type.pk]),
            {"name": "Boshqa nom", "category_number": ""},
        )
        self.contract_type.refresh_from_db()

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.contract_type.name, RENAMEABLE)

    def test_a_manager_may_not_delete(self) -> None:
        self.client.force_login(make_user(MENEJER))

        response = self.client.post(
            reverse("shartnoma-turi-delete", args=[self.contract_type.pk])
        )
        self.contract_type.refresh_from_db()

        self.assertEqual(response.status_code, 403)
        self.assertTrue(self.contract_type.is_active)

    def test_an_anonymous_visitor_is_redirected(self) -> None:
        self.assertEqual(self.client.get(reverse("shartnoma-turi")).status_code, 302)
