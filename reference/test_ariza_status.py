"""Tests for the Ariza Status master data page of TASK-UZK-016.

The third page of this shape and the first built out of MasterDataPage, so
what these prove is the shared quartet as much as the page: Save adds, Cancel
leaves nothing behind, Edit opens filled in, and Delete asks first and then
deactivates rather than removing (DEC-009).

The seeding tests are the ones that are specific to this page. DEC-017 seeds
four statuses as examples rather than as fixed system rows, and the difference
matters: unlike the six User Types, these may be renamed and deleted.
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
from reference.models import ArizaStatus

# No apostrophe: the page escapes one to &#x27;, which would make every
# assertion about the rendered name an assertion about HTML escaping.
ADDED_STATUS = "Kelishilmoqda"


def make_user(type_name: str = ADMIN):
    user = get_user_model().objects.create_user(
        username=f"user.{get_random_string(8).lower()}",
        password=get_random_string(24),
        first_name="Test",
        last_name=type_name,
    )
    assign_user_type(user, UserType.objects.get(name=type_name))
    return user


class ArizaStatusPageTestCase(TestCase):
    """An administrator on the Ariza Status page."""

    def setUp(self) -> None:
        self.client.force_login(make_user(ADMIN))

    def create(self, **overrides):
        fields = {
            "name": ADDED_STATUS,
            "badge_colour": "orange",
            "category_number": "",
        }
        fields.update(overrides)
        return self.client.post(reverse("ariza-status-create"), fields)

    def page(self) -> str:
        return self.client.get(reverse("ariza-status")).content.decode()


class SeedingTests(ArizaStatusPageTestCase):
    """DEC-017: four statuses to start with, as examples rather than rules."""

    def test_the_four_decided_statuses_are_there(self) -> None:
        self.assertEqual(
            set(ArizaStatus.objects.values_list("name", flat=True)),
            {"Yangi", "Qabul qilingan", "Tayinlangan", "Bekor qilingan"},
        )

    def test_they_appear_on_the_page(self) -> None:
        page = self.page()

        for name in ("Yangi", "Qabul qilingan", "Tayinlangan", "Bekor qilingan"):
            with self.subTest(status=name):
                self.assertIn(name, page)

    def test_a_seeded_status_can_be_deleted(self) -> None:
        # Unlike the six User Types, these are examples. Nothing in the code
        # is written against their names, so nothing breaks when one goes.
        seeded = ArizaStatus.objects.get(name="Tayinlangan")

        self.client.post(reverse("ariza-status-delete", args=[seeded.pk]))
        seeded.refresh_from_db()

        self.assertFalse(seeded.is_active)

    def test_seeding_again_adds_nothing(self) -> None:
        # The migration runs get_or_create, so re-running it against a
        # database that already has the rows leaves them alone rather than
        # failing on the unique name.
        seed = import_module("reference.migrations.0002_seed_ariza_statuses")

        seed.seed_ariza_statuses(apps, None)

        self.assertEqual(ArizaStatus.objects.count(), 4)

    def test_a_seeded_status_can_be_renamed(self) -> None:
        seeded = ArizaStatus.objects.get(name="Yangi")

        self.client.post(
            reverse("ariza-status-update", args=[seeded.pk]),
            {"name": "Yangi ariza", "badge_colour": "blue", "category_number": ""},
        )
        seeded.refresh_from_db()

        self.assertEqual(seeded.name, "Yangi ariza")


class CreationTests(ArizaStatusPageTestCase):
    """Save adds the status to the list."""

    def test_a_created_status_appears_in_the_table(self) -> None:
        self.create()

        self.assertIn(ADDED_STATUS, self.page())

    def test_creation_redirects_back_to_the_page(self) -> None:
        self.assertRedirects(self.create(), reverse("ariza-status"))

    def test_a_name_is_required(self) -> None:
        response = self.create(name="")

        self.assertFalse(ArizaStatus.objects.filter(name="").exists())
        self.assertEqual(response.status_code, 200)

    def test_two_statuses_cannot_share_a_name(self) -> None:
        response = self.create(name="Yangi")

        self.assertEqual(ArizaStatus.objects.filter(name__iexact="Yangi").count(), 1)
        self.assertContains(response, "Bu nom allaqachon mavjud")

    def test_a_name_differing_only_in_case_is_refused(self) -> None:
        response = self.create(name="YANGI")

        self.assertEqual(ArizaStatus.objects.filter(name__iexact="Yangi").count(), 1)
        self.assertEqual(response.status_code, 200)

    def test_a_created_status_keeps_its_badge_colour(self) -> None:
        self.create(badge_colour="green")

        self.assertEqual(
            ArizaStatus.objects.get(name=ADDED_STATUS).badge_colour, "green"
        )

    def test_the_badge_colour_becomes_a_class_the_stylesheet_defines(self) -> None:
        self.create(badge_colour="green")

        self.assertEqual(
            ArizaStatus.objects.get(name=ADDED_STATUS).badge_class, "badge-approved"
        )

    def test_the_category_number_is_optional(self) -> None:
        self.create()

        self.assertIsNone(ArizaStatus.objects.get(name=ADDED_STATUS).category_number)

    def test_a_six_digit_category_number_is_accepted(self) -> None:
        self.create(category_number=100123)

        self.assertEqual(
            ArizaStatus.objects.get(name=ADDED_STATUS).category_number, 100123
        )

    def test_a_category_number_of_another_length_is_refused(self) -> None:
        # DEC-023: six digits, and 12345 or 1234567 are not six digits.
        for supplied in (12345, 1234567, 0):
            with self.subTest(category_number=supplied):
                response = self.create(category_number=supplied)

                self.assertFalse(
                    ArizaStatus.objects.filter(name=ADDED_STATUS).exists()
                )
                self.assertEqual(response.status_code, 200)


class CancelTests(ArizaStatusPageTestCase):
    """Cancel leaves no record behind."""

    def test_opening_the_form_and_leaving_creates_nothing(self) -> None:
        before = ArizaStatus.objects.count()

        self.client.get(reverse("ariza-status"))

        self.assertEqual(ArizaStatus.objects.count(), before)

    def test_cancel_from_an_edit_changes_nothing(self) -> None:
        status = ArizaStatus.objects.get(name="Yangi")

        self.client.get(f"{reverse('ariza-status')}?edit={status.pk}")
        self.client.get(reverse("ariza-status"))

        status.refresh_from_db()

        self.assertEqual(status.name, "Yangi")


class EditingTests(ArizaStatusPageTestCase):
    """Edit opens the form filled in and saves what was changed."""

    def setUp(self) -> None:
        super().setUp()
        self.create()
        self.status = ArizaStatus.objects.get(name=ADDED_STATUS)

    def edit(self, **overrides):
        fields = {
            "name": "Kelishildi",
            "badge_colour": "blue",
            "category_number": "",
        }
        fields.update(overrides)
        return self.client.post(
            reverse("ariza-status-update", args=[self.status.pk]), fields
        )

    def test_the_form_opens_filled_in(self) -> None:
        page = self.client.get(f"{reverse('ariza-status')}?edit={self.status.pk}")

        self.assertContains(page, f'value="{ADDED_STATUS}"')

    def test_the_form_posts_to_the_update_route_when_editing(self) -> None:
        page = self.client.get(f"{reverse('ariza-status')}?edit={self.status.pk}")

        self.assertContains(
            page, reverse("ariza-status-update", args=[self.status.pk])
        )

    def test_an_edited_status_shows_the_edited_values(self) -> None:
        self.edit(category_number=100456)

        self.status.refresh_from_db()

        self.assertEqual(self.status.name, "Kelishildi")
        self.assertEqual(self.status.badge_colour, "blue")
        self.assertEqual(self.status.category_number, 100456)

    def test_editing_does_not_create_a_second_record(self) -> None:
        before = ArizaStatus.objects.count()

        self.edit()

        self.assertEqual(ArizaStatus.objects.count(), before)

    def test_an_invalid_edit_keeps_the_form_on_the_record(self) -> None:
        # Otherwise Save on a rejected edit would silently become an Add.
        response = self.edit(name="Yangi")

        self.assertContains(
            response, reverse("ariza-status-update", args=[self.status.pk])
        )

    def test_editing_a_record_that_does_not_exist_is_a_not_found(self) -> None:
        response = self.client.get(f"{reverse('ariza-status')}?edit=9999")

        self.assertEqual(response.status_code, 404)


class DeletionTests(ArizaStatusPageTestCase):
    """DEC-009: ask, then deactivate."""

    def setUp(self) -> None:
        super().setUp()
        self.create()
        self.status = ArizaStatus.objects.get(name=ADDED_STATUS)

    def delete(self):
        return self.client.post(
            reverse("ariza-status-delete", args=[self.status.pk])
        )

    def test_a_deleted_status_leaves_the_list(self) -> None:
        self.delete()

        self.assertNotIn(ADDED_STATUS, self.page())

    def test_a_deleted_status_still_exists(self) -> None:
        # So that an application already sitting in it still resolves.
        self.delete()

        self.status.refresh_from_db()

        self.assertFalse(self.status.is_active)
        self.assertTrue(ArizaStatus.objects.filter(pk=self.status.pk).exists())

    def test_a_deleted_status_leaves_the_active_queryset(self) -> None:
        # Which is what every drop-down in the application will be built on.
        self.delete()

        self.assertFalse(
            ArizaStatus.objects.active().filter(pk=self.status.pk).exists()
        )

    def test_the_page_asks_before_deleting(self) -> None:
        self.assertIn("onsubmit=\"return confirm(", self.page())

    def test_deletion_needs_a_post(self) -> None:
        response = self.client.get(
            reverse("ariza-status-delete", args=[self.status.pk])
        )

        self.status.refresh_from_db()

        self.assertEqual(response.status_code, 405)
        self.assertTrue(self.status.is_active)

    def test_deleting_twice_is_a_not_found(self) -> None:
        self.delete()

        self.assertEqual(self.delete().status_code, 404)

    def test_a_deleted_name_cannot_be_used_again(self) -> None:
        # Soft delete and a unique name meet here, and uniqueness wins: the
        # deactivated row keeps the name, so re-creating it is refused with a
        # validation error rather than silently reviving the old record.
        self.delete()

        response = self.create()

        self.assertEqual(ArizaStatus.objects.filter(name=ADDED_STATUS).count(), 1)
        # Without the apostrophe: the page escapes it to &#x27;.
        self.assertContains(response, "chirilgan yozuvga tegishli")


class PermissionTests(TestCase):
    """The page is Admin-only under DEC-015, and so are its actions."""

    def setUp(self) -> None:
        self.status = ArizaStatus.objects.get(name="Yangi")

    def test_a_manager_may_not_open_the_page(self) -> None:
        self.client.force_login(make_user(MENEJER))

        self.assertEqual(self.client.get(reverse("ariza-status")).status_code, 403)

    def test_a_manager_may_not_create(self) -> None:
        self.client.force_login(make_user(MENEJER))

        response = self.client.post(
            reverse("ariza-status-create"),
            {"name": ADDED_STATUS, "badge_colour": "orange", "category_number": ""},
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(ArizaStatus.objects.filter(name=ADDED_STATUS).exists())

    def test_a_manager_may_not_delete(self) -> None:
        self.client.force_login(make_user(MENEJER))

        response = self.client.post(
            reverse("ariza-status-delete", args=[self.status.pk])
        )
        self.status.refresh_from_db()

        self.assertEqual(response.status_code, 403)
        self.assertTrue(self.status.is_active)

    def test_an_anonymous_visitor_is_redirected(self) -> None:
        self.assertEqual(self.client.get(reverse("ariza-status")).status_code, 302)
