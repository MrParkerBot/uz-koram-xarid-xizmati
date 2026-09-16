"""Tests for the Shartnoma Status master data page of TASK-UZK-017.

The second page built out of MasterDataPage. The quartet it shares with Ariza
Status is proved again here rather than assumed: the two pages are wired
separately, and a route pointing at the wrong table would pass every test that
only exercised the other page.

The seeding tests carry the weight specific to this page. Sections 4.3 to 4.6
print five contract statuses as fixed counter columns and section 3.5 makes
them editable master data; DEC-010 settles it in favour of section 3.5. So the
five are seeded as examples, every one of them can be renamed and deleted, and
these tests say so - because TASK-UZK-044 and TASK-UZK-045 have to generate
their columns from this table rather than from the document's illustration.
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
from reference.models import ShartnomaStatus

# No apostrophe: the page escapes one to &#x27;, which would make every
# assertion about the rendered name an assertion about HTML escaping.
ADDED_STATUS = "Imzolanmoqda"

# The five DEC-010 seeds. Named here so the tests read against the decision
# rather than against a list retyped in six places.
SEEDED_STATUSES = (
    "Boshlang`ich xolatda",
    "Birjaga qo`yilgan",
    "Shartnoma tuzilgan",
    "Yetkazib berilgan",
    "Bekor qilingan",
)

# One seeded status the tests rename and clash against. A backtick rather than
# an apostrophe, which is what the supplied pages use for these names.
RENAMEABLE = "Boshlang`ich xolatda"


def make_user(type_name: str = ADMIN):
    user = get_user_model().objects.create_user(
        username=f"user.{get_random_string(8).lower()}",
        password=get_random_string(24),
        first_name="Test",
        last_name=type_name,
    )
    assign_user_type(user, UserType.objects.get(name=type_name))
    return user


class ShartnomaStatusPageTestCase(TestCase):
    """An administrator on the Shartnoma Status page."""

    def setUp(self) -> None:
        self.client.force_login(make_user(ADMIN))

    def create(self, **overrides):
        fields = {
            "name": ADDED_STATUS,
            "badge_colour": "orange",
            "category_number": "",
        }
        fields.update(overrides)
        return self.client.post(reverse("shartnoma-status-create"), fields)

    def page(self) -> str:
        return self.client.get(reverse("shartnoma-status")).content.decode()


class SeedingTests(ShartnomaStatusPageTestCase):
    """DEC-010: five statuses to start with, as examples rather than a set."""

    def test_the_five_decided_statuses_are_there(self) -> None:
        self.assertEqual(
            set(ShartnomaStatus.objects.values_list("name", flat=True)),
            set(SEEDED_STATUSES),
        )

    def test_they_appear_on_the_page(self) -> None:
        page = self.page()

        for name in SEEDED_STATUSES:
            with self.subTest(status=name):
                self.assertIn(name, page)

    def test_they_are_listed_in_the_order_the_work_moves_through_them(self) -> None:
        # Not alphabetically, which would put Bekor qilingan first and the
        # starting state third. DEC-010 has the reports generate one column
        # per active status, so this is also the order those columns come out
        # in, and the document illustrates them in workflow order.
        self.assertEqual(
            list(ShartnomaStatus.objects.active().values_list("name", flat=True)),
            list(SEEDED_STATUSES),
        )

    def test_a_new_status_is_appended_rather_than_sorted_in(self) -> None:
        self.create()

        listed = list(
            ShartnomaStatus.objects.active().values_list("name", flat=True)
        )

        self.assertEqual(listed[-1], ADDED_STATUS)

    def test_a_seeded_status_can_be_deleted(self) -> None:
        # Unlike the six User Types, these are examples. Nothing in the code
        # is written against their names, so nothing breaks when one goes.
        seeded = ShartnomaStatus.objects.get(name="Birjaga qo`yilgan")

        self.client.post(reverse("shartnoma-status-delete", args=[seeded.pk]))
        seeded.refresh_from_db()

        self.assertFalse(seeded.is_active)

    def test_seeding_again_adds_nothing(self) -> None:
        # The migration runs get_or_create, so re-running it against a
        # database that already has the rows leaves them alone rather than
        # failing on the unique name.
        seed = import_module("reference.migrations.0004_seed_shartnoma_statuses")

        seed.seed_shartnoma_statuses(apps, None)

        self.assertEqual(ShartnomaStatus.objects.count(), len(SEEDED_STATUSES))

    def test_a_seeded_status_can_be_renamed(self) -> None:
        seeded = ShartnomaStatus.objects.get(name=RENAMEABLE)

        self.client.post(
            reverse("shartnoma-status-update", args=[seeded.pk]),
            {"name": "Boshlanishida", "badge_colour": "blue", "category_number": ""},
        )
        seeded.refresh_from_db()

        self.assertEqual(seeded.name, "Boshlanishida")


class CreationTests(ShartnomaStatusPageTestCase):
    """Save adds the status to the list."""

    def test_a_created_status_appears_in_the_table(self) -> None:
        self.create()

        self.assertIn(ADDED_STATUS, self.page())

    def test_creation_redirects_back_to_the_page(self) -> None:
        self.assertRedirects(self.create(), reverse("shartnoma-status"))

    def test_a_name_is_required(self) -> None:
        response = self.create(name="")

        self.assertFalse(ShartnomaStatus.objects.filter(name="").exists())
        self.assertEqual(response.status_code, 200)

    def test_two_statuses_cannot_share_a_name(self) -> None:
        response = self.create(name=RENAMEABLE)

        self.assertEqual(
            ShartnomaStatus.objects.filter(name__iexact=RENAMEABLE).count(), 1
        )
        self.assertContains(response, "Bu nom allaqachon mavjud")

    def test_a_name_differing_only_in_case_is_refused(self) -> None:
        response = self.create(name=RENAMEABLE.upper())

        self.assertEqual(
            ShartnomaStatus.objects.filter(name__iexact=RENAMEABLE).count(), 1
        )
        self.assertEqual(response.status_code, 200)

    def test_a_created_status_keeps_its_badge_colour(self) -> None:
        self.create(badge_colour="green")

        self.assertEqual(
            ShartnomaStatus.objects.get(name=ADDED_STATUS).badge_colour, "green"
        )

    def test_the_badge_colour_becomes_a_class_the_stylesheet_defines(self) -> None:
        self.create(badge_colour="green")

        self.assertEqual(
            ShartnomaStatus.objects.get(name=ADDED_STATUS).badge_class, "badge-approved"
        )

    def test_the_category_number_is_optional(self) -> None:
        self.create()

        self.assertIsNone(ShartnomaStatus.objects.get(name=ADDED_STATUS).category_number)

    def test_a_six_digit_category_number_is_accepted(self) -> None:
        self.create(category_number=100123)

        self.assertEqual(
            ShartnomaStatus.objects.get(name=ADDED_STATUS).category_number, 100123
        )

    def test_a_category_number_of_another_length_is_refused(self) -> None:
        # DEC-023: six digits, and 12345 or 1234567 are not six digits.
        for supplied in (12345, 1234567, 0):
            with self.subTest(category_number=supplied):
                response = self.create(category_number=supplied)

                self.assertFalse(
                    ShartnomaStatus.objects.filter(name=ADDED_STATUS).exists()
                )
                self.assertEqual(response.status_code, 200)


class CancelTests(ShartnomaStatusPageTestCase):
    """Cancel leaves no record behind."""

    def test_opening_the_form_and_leaving_creates_nothing(self) -> None:
        before = ShartnomaStatus.objects.count()

        self.client.get(reverse("shartnoma-status"))

        self.assertEqual(ShartnomaStatus.objects.count(), before)

    def test_cancel_from_an_edit_changes_nothing(self) -> None:
        status = ShartnomaStatus.objects.get(name=RENAMEABLE)

        self.client.get(f"{reverse('shartnoma-status')}?edit={status.pk}")
        self.client.get(reverse("shartnoma-status"))

        status.refresh_from_db()

        self.assertEqual(status.name, RENAMEABLE)


class EditingTests(ShartnomaStatusPageTestCase):
    """Edit opens the form filled in and saves what was changed."""

    def setUp(self) -> None:
        super().setUp()
        self.create()
        self.status = ShartnomaStatus.objects.get(name=ADDED_STATUS)

    def edit(self, **overrides):
        fields = {
            "name": "Imzolandi",
            "badge_colour": "blue",
            "category_number": "",
        }
        fields.update(overrides)
        return self.client.post(
            reverse("shartnoma-status-update", args=[self.status.pk]), fields
        )

    def test_the_form_opens_filled_in(self) -> None:
        page = self.client.get(f"{reverse('shartnoma-status')}?edit={self.status.pk}")

        self.assertContains(page, f'value="{ADDED_STATUS}"')

    def test_the_form_posts_to_the_update_route_when_editing(self) -> None:
        page = self.client.get(f"{reverse('shartnoma-status')}?edit={self.status.pk}")

        self.assertContains(
            page, reverse("shartnoma-status-update", args=[self.status.pk])
        )

    def test_an_edited_status_shows_the_edited_values(self) -> None:
        self.edit(category_number=100456)

        self.status.refresh_from_db()

        self.assertEqual(self.status.name, "Imzolandi")
        self.assertEqual(self.status.badge_colour, "blue")
        self.assertEqual(self.status.category_number, 100456)

    def test_editing_does_not_create_a_second_record(self) -> None:
        before = ShartnomaStatus.objects.count()

        self.edit()

        self.assertEqual(ShartnomaStatus.objects.count(), before)

    def test_an_invalid_edit_keeps_the_form_on_the_record(self) -> None:
        # Otherwise Save on a rejected edit would silently become an Add.
        response = self.edit(name=RENAMEABLE)

        self.assertContains(
            response, reverse("shartnoma-status-update", args=[self.status.pk])
        )

    def test_editing_a_record_that_does_not_exist_is_a_not_found(self) -> None:
        response = self.client.get(f"{reverse('shartnoma-status')}?edit=9999")

        self.assertEqual(response.status_code, 404)

    def test_an_edit_id_that_is_not_a_number_is_a_not_found(self) -> None:
        # ?edit= is the one place a pk reaches the page without going through
        # a URL converter, so it is the one place a non-number can arrive.
        response = self.client.get(f"{reverse('shartnoma-status')}?edit=abc")

        self.assertEqual(response.status_code, 404)


class DeletionTests(ShartnomaStatusPageTestCase):
    """DEC-009: ask, then deactivate."""

    def setUp(self) -> None:
        super().setUp()
        self.create()
        self.status = ShartnomaStatus.objects.get(name=ADDED_STATUS)

    def delete(self):
        return self.client.post(
            reverse("shartnoma-status-delete", args=[self.status.pk])
        )

    def test_a_deleted_status_leaves_the_list(self) -> None:
        self.delete()

        self.assertNotIn(ADDED_STATUS, self.page())

    def test_a_deleted_status_still_exists(self) -> None:
        # So that an application already sitting in it still resolves.
        self.delete()

        self.status.refresh_from_db()

        self.assertFalse(self.status.is_active)
        self.assertTrue(ShartnomaStatus.objects.filter(pk=self.status.pk).exists())

    def test_a_deleted_status_leaves_the_active_queryset(self) -> None:
        # Which is what every drop-down in the application will be built on.
        self.delete()

        self.assertFalse(
            ShartnomaStatus.objects.active().filter(pk=self.status.pk).exists()
        )

    def test_the_page_asks_before_deleting(self) -> None:
        self.assertIn("data-confirm=", self.page())

    def test_deletion_needs_a_post(self) -> None:
        response = self.client.get(
            reverse("shartnoma-status-delete", args=[self.status.pk])
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

        self.assertEqual(ShartnomaStatus.objects.filter(name=ADDED_STATUS).count(), 1)
        # Without the apostrophe: the page escapes it to &#x27;.
        self.assertContains(response, "chirilgan yozuvga tegishli")


class PermissionTests(TestCase):
    """The page is Admin-only under DEC-015, and so are its actions."""

    def setUp(self) -> None:
        self.status = ShartnomaStatus.objects.get(name=RENAMEABLE)

    def test_a_manager_may_not_open_the_page(self) -> None:
        self.client.force_login(make_user(MENEJER))

        self.assertEqual(self.client.get(reverse("shartnoma-status")).status_code, 403)

    def test_a_manager_may_not_create(self) -> None:
        self.client.force_login(make_user(MENEJER))

        response = self.client.post(
            reverse("shartnoma-status-create"),
            {"name": ADDED_STATUS, "badge_colour": "orange", "category_number": ""},
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(ShartnomaStatus.objects.filter(name=ADDED_STATUS).exists())

    def test_a_manager_may_not_edit(self) -> None:
        # accounts/test_permissions.py walks the page views and the Users
        # page's actions, but not a master data page's actions, so each of
        # the four routes is proved here.
        self.client.force_login(make_user(MENEJER))

        response = self.client.post(
            reverse("shartnoma-status-update", args=[self.status.pk]),
            {"name": "Boshqa nom", "badge_colour": "blue", "category_number": ""},
        )
        self.status.refresh_from_db()

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.status.name, RENAMEABLE)

    def test_a_manager_may_not_delete(self) -> None:
        self.client.force_login(make_user(MENEJER))

        response = self.client.post(
            reverse("shartnoma-status-delete", args=[self.status.pk])
        )
        self.status.refresh_from_db()

        self.assertEqual(response.status_code, 403)
        self.assertTrue(self.status.is_active)

    def test_an_anonymous_visitor_is_redirected(self) -> None:
        self.assertEqual(self.client.get(reverse("shartnoma-status")).status_code, 302)
