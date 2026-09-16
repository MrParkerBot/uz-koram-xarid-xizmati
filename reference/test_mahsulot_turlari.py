"""Tests for the Mahsulot Turlari master data page of TASK-UZK-018.

The third page built out of MasterDataPage and the first whose fields are not
the two status tables' fields. What is specific to it is the category number:
required, unique and six digits, where every other master data page treats the
number as optional. Those rules are stricter than the specification states
outright, so they are tested rather than assumed.

This page also ships empty, which the two status pages do not. The empty table
is therefore a case worth proving rather than a state nobody will see.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils.crypto import get_random_string

from accounts.models import UserType
from accounts.roles import ADMIN, MENEJER, assign_user_type
from reference.models import MahsulotTuri

# No apostrophe: the page escapes one to &#x27;, which would make every
# assertion about the rendered name an assertion about HTML escaping.
ADDED_CATEGORY = "Metallurgiya"
ADDED_NUMBER = 100042


def make_user(type_name: str = ADMIN):
    user = get_user_model().objects.create_user(
        username=f"user.{get_random_string(8).lower()}",
        password=get_random_string(24),
        first_name="Test",
        last_name=type_name,
    )
    assign_user_type(user, UserType.objects.get(name=type_name))
    return user


class MahsulotTuriPageTestCase(TestCase):
    """An administrator on the Mahsulot Turlari page."""

    def setUp(self) -> None:
        self.client.force_login(make_user(ADMIN))

    def create(self, **overrides):
        fields = {
            "category_number": ADDED_NUMBER,
            "name": ADDED_CATEGORY,
            "description": "Metall va qorishmalar",
        }
        fields.update(overrides)
        return self.client.post(reverse("mahsulot-turlari-create"), fields)

    def page(self) -> str:
        return self.client.get(reverse("mahsulot-turlari")).content.decode()


class EmptyTableTests(MahsulotTuriPageTestCase):
    """The page ships with nothing in it, unlike the two status pages."""

    def test_nothing_is_seeded(self) -> None:
        # DEC-017 and DEC-010 name starting values for the status tables.
        # Nothing names any here, and the prototype's six samples are an
        # illustration rather than the customer's taxonomy.
        self.assertEqual(MahsulotTuri.objects.count(), 0)

    def test_the_empty_page_renders_and_says_so(self) -> None:
        page = self.page()

        self.assertIn("Hozircha kategoriya yo", page)


class CreationTests(MahsulotTuriPageTestCase):
    """Save adds the category to the list."""

    def test_a_created_category_appears_in_the_table(self) -> None:
        self.create()
        page = self.page()

        self.assertIn(ADDED_CATEGORY, page)
        self.assertIn(str(ADDED_NUMBER), page)

    def test_the_description_appears_in_the_table(self) -> None:
        self.create()

        self.assertIn("Metall va qorishmalar", self.page())

    def test_creation_redirects_back_to_the_page(self) -> None:
        self.assertRedirects(self.create(), reverse("mahsulot-turlari"))

    def test_a_name_is_required(self) -> None:
        response = self.create(name="")

        self.assertEqual(MahsulotTuri.objects.count(), 0)
        self.assertEqual(response.status_code, 200)

    def test_a_category_number_is_required(self) -> None:
        # The one master data page where it is. The supplied form marks it so
        # and calls it a code, and TASK-UZK-046 reports purchases by category.
        response = self.create(category_number="")

        self.assertEqual(MahsulotTuri.objects.count(), 0)
        self.assertEqual(response.status_code, 200)

    def test_the_description_is_optional(self) -> None:
        self.create(description="")

        self.assertEqual(MahsulotTuri.objects.get().description, "")

    def test_two_categories_cannot_share_a_name(self) -> None:
        self.create()

        response = self.create(category_number=200031)

        self.assertEqual(MahsulotTuri.objects.count(), 1)
        self.assertContains(response, "Bu nom allaqachon mavjud")

    def test_a_name_differing_only_in_case_is_refused(self) -> None:
        self.create()

        response = self.create(name=ADDED_CATEGORY.upper(), category_number=200031)

        self.assertEqual(MahsulotTuri.objects.count(), 1)
        self.assertEqual(response.status_code, 200)

    def test_two_categories_cannot_share_a_number(self) -> None:
        # Otherwise the TASK-UZK-046 report would merge them.
        self.create()

        response = self.create(name="Kimyoviy moddalar")

        self.assertEqual(MahsulotTuri.objects.count(), 1)
        self.assertContains(response, "Bu raqam allaqachon mavjud")

    def test_a_number_held_by_a_deleted_category_says_so(self) -> None:
        # DEC-009 keeps the deleted row, so it keeps the number. Being told
        # the number exists, while looking at a list that does not contain it,
        # is the one refusal worth spelling out - the same reason the name has
        # two messages rather than one.
        self.create()
        deleted = MahsulotTuri.objects.get()
        self.client.post(reverse("mahsulot-turlari-delete", args=[deleted.pk]))

        response = self.create(name="Kimyoviy moddalar")

        self.assertEqual(MahsulotTuri.objects.count(), 1)
        # Without the apostrophe: the page escapes it to &#x27;.
        self.assertContains(response, "chirilgan kategoriyaga tegishli")

    def test_a_six_digit_number_is_accepted(self) -> None:
        self.create()

        self.assertEqual(MahsulotTuri.objects.get().category_number, ADDED_NUMBER)

    def test_a_number_of_another_length_is_refused(self) -> None:
        # DEC-023 resolves CONFLICT-002: six digits, not the table's five.
        for supplied in (12345, 1234567, 0):
            with self.subTest(category_number=supplied):
                response = self.create(category_number=supplied)

                self.assertEqual(MahsulotTuri.objects.count(), 0)
                self.assertEqual(response.status_code, 200)


class OrderingTests(MahsulotTuriPageTestCase):
    """Listed by the code, which is what the department identifies them by."""

    def test_categories_are_listed_by_their_number(self) -> None:
        self.create(category_number=300015, name="Elektr uskunalar")
        self.create(category_number=100042, name="Metallurgiya")
        self.create(category_number=200031, name="Kimyoviy moddalar")

        listed = MahsulotTuri.objects.active().values_list(
            "category_number", flat=True
        )

        self.assertEqual(list(listed), [100042, 200031, 300015])


class CancelTests(MahsulotTuriPageTestCase):
    """Cancel leaves no record behind."""

    def test_opening_the_form_and_leaving_creates_nothing(self) -> None:
        self.client.get(reverse("mahsulot-turlari"))

        self.assertEqual(MahsulotTuri.objects.count(), 0)

    def test_cancel_from_an_edit_changes_nothing(self) -> None:
        self.create()
        category = MahsulotTuri.objects.get()

        self.client.get(f"{reverse('mahsulot-turlari')}?edit={category.pk}")
        self.client.get(reverse("mahsulot-turlari"))
        category.refresh_from_db()

        self.assertEqual(category.name, ADDED_CATEGORY)


class EditingTests(MahsulotTuriPageTestCase):
    """Edit opens the form filled in and saves what was changed."""

    def setUp(self) -> None:
        super().setUp()
        self.create()
        self.category = MahsulotTuri.objects.get()

    def edit(self, **overrides):
        fields = {
            "category_number": 100043,
            "name": "Metall va qorishmalar",
            "description": "Yangilangan tavsif",
        }
        fields.update(overrides)
        return self.client.post(
            reverse("mahsulot-turlari-update", args=[self.category.pk]), fields
        )

    def test_the_form_opens_filled_in(self) -> None:
        page = self.client.get(
            f"{reverse('mahsulot-turlari')}?edit={self.category.pk}"
        )

        self.assertContains(page, f'value="{ADDED_CATEGORY}"')
        self.assertContains(page, f'value="{ADDED_NUMBER}"')

    def test_an_edited_category_shows_the_edited_values(self) -> None:
        self.edit()
        self.category.refresh_from_db()

        self.assertEqual(self.category.category_number, 100043)
        self.assertEqual(self.category.name, "Metall va qorishmalar")
        self.assertEqual(self.category.description, "Yangilangan tavsif")

    def test_editing_does_not_create_a_second_record(self) -> None:
        self.edit()

        self.assertEqual(MahsulotTuri.objects.count(), 1)

    def test_an_invalid_edit_keeps_the_form_on_the_record(self) -> None:
        # Otherwise Save on a rejected edit would silently become an Add.
        response = self.edit(category_number=123)

        self.assertContains(
            response, reverse("mahsulot-turlari-update", args=[self.category.pk])
        )

    def test_editing_a_record_that_does_not_exist_is_a_not_found(self) -> None:
        response = self.client.get(f"{reverse('mahsulot-turlari')}?edit=9999")

        self.assertEqual(response.status_code, 404)

    def test_an_edit_id_that_is_not_a_number_is_a_not_found(self) -> None:
        response = self.client.get(f"{reverse('mahsulot-turlari')}?edit=abc")

        self.assertEqual(response.status_code, 404)


class DeletionTests(MahsulotTuriPageTestCase):
    """DEC-009: ask, then deactivate."""

    def setUp(self) -> None:
        super().setUp()
        self.create()
        self.category = MahsulotTuri.objects.get()

    def delete(self):
        return self.client.post(
            reverse("mahsulot-turlari-delete", args=[self.category.pk])
        )

    def test_a_deleted_category_leaves_the_list(self) -> None:
        self.delete()

        self.assertNotIn(ADDED_CATEGORY, self.page())

    def test_a_deleted_category_still_exists(self) -> None:
        # So that an application line already referring to it still resolves.
        self.delete()
        self.category.refresh_from_db()

        self.assertFalse(self.category.is_active)
        self.assertEqual(MahsulotTuri.objects.count(), 1)

    def test_a_deleted_category_leaves_the_active_queryset(self) -> None:
        self.delete()

        self.assertEqual(MahsulotTuri.objects.active().count(), 0)

    def test_the_page_asks_before_deleting(self) -> None:
        self.assertIn("data-confirm=", self.page())

    def test_deletion_needs_a_post(self) -> None:
        response = self.client.get(
            reverse("mahsulot-turlari-delete", args=[self.category.pk])
        )
        self.category.refresh_from_db()

        self.assertEqual(response.status_code, 405)
        self.assertTrue(self.category.is_active)

    def test_deleting_twice_is_a_not_found(self) -> None:
        self.delete()

        self.assertEqual(self.delete().status_code, 404)

    def test_a_deleted_number_cannot_be_used_again(self) -> None:
        # The deactivated row keeps the number, so re-creating it is refused
        # rather than silently reviving the old record.
        self.delete()

        response = self.create(name="Boshqa nom")

        self.assertEqual(MahsulotTuri.objects.count(), 1)
        self.assertEqual(response.status_code, 200)


class PermissionTests(TestCase):
    """The page is Admin-only under DEC-015, and so are its actions."""

    def setUp(self) -> None:
        self.category = MahsulotTuri.objects.create(
            category_number=100042, name="Metallurgiya"
        )

    def post_as_manager(self, url, payload=None):
        self.client.force_login(make_user(MENEJER))
        return self.client.post(url, payload or {})

    def test_a_manager_may_not_open_the_page(self) -> None:
        self.client.force_login(make_user(MENEJER))

        self.assertEqual(
            self.client.get(reverse("mahsulot-turlari")).status_code, 403
        )

    def test_a_manager_may_not_create(self) -> None:
        response = self.post_as_manager(
            reverse("mahsulot-turlari-create"),
            {"category_number": 200031, "name": "Yangi", "description": ""},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(MahsulotTuri.objects.count(), 1)

    def test_a_manager_may_not_edit(self) -> None:
        response = self.post_as_manager(
            reverse("mahsulot-turlari-update", args=[self.category.pk]),
            {"category_number": 200031, "name": "Boshqa", "description": ""},
        )
        self.category.refresh_from_db()

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.category.name, "Metallurgiya")

    def test_a_manager_may_not_delete(self) -> None:
        response = self.post_as_manager(
            reverse("mahsulot-turlari-delete", args=[self.category.pk])
        )
        self.category.refresh_from_db()

        self.assertEqual(response.status_code, 403)
        self.assertTrue(self.category.is_active)

    def test_an_anonymous_visitor_is_redirected(self) -> None:
        self.assertEqual(
            self.client.get(reverse("mahsulot-turlari")).status_code, 302
        )
