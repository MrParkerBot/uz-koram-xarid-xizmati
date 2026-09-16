"""Tests for the Firmalar master data page of TASK-UZK-021.

DEC-011 makes suppliers master data because the dashboard counts them and ranks
the top ones, and a count over the firm names typed into each contract is not a
count of suppliers. So the rules that matter here are the ones that decide
whether two rows are the same firm: the name and the INN.

The INN carries most of the weight. It is optional, because the supplied
contract form leaves it optional and DEC-023 seeds an Import contract type, so
foreign suppliers with no Uzbek INN are expected. But it must be unique among
the firms that have one, or TASK-UZK-048 would count a firm entered twice as
two suppliers - which is the thing DEC-011 exists to prevent.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils.crypto import get_random_string

from accounts.models import UserType
from accounts.roles import ADMIN, MENEJER, assign_user_type
from reference.models import Supplier

ADDED_SUPPLIER = "Texnoprom LLC"
ADDED_INN = "123456789"


def make_user(type_name: str = ADMIN):
    user = get_user_model().objects.create_user(
        username=f"user.{get_random_string(8).lower()}",
        password=get_random_string(24),
        first_name="Test",
        last_name=type_name,
    )
    assign_user_type(user, UserType.objects.get(name=type_name))
    return user


class SupplierPageTestCase(TestCase):
    """An administrator on the Firmalar page."""

    def setUp(self) -> None:
        self.client.force_login(make_user(ADMIN))

    def create(self, **overrides):
        fields = {
            "name": ADDED_SUPPLIER,
            "inn": ADDED_INN,
            "daraja": "A",
            "category_number": "",
        }
        fields.update(overrides)
        return self.client.post(reverse("firmalar-create"), fields)

    def page(self) -> str:
        return self.client.get(reverse("firmalar")).content.decode()


class EmptyTableTests(SupplierPageTestCase):
    """The page ships empty: the specification names no suppliers."""

    def test_nothing_is_seeded(self) -> None:
        self.assertEqual(Supplier.objects.count(), 0)

    def test_the_empty_page_renders_and_says_so(self) -> None:
        self.assertIn("Hozircha firma yo", self.page())


class CreationTests(SupplierPageTestCase):
    """Save adds the supplier to the list."""

    def test_a_created_supplier_appears_with_its_details(self) -> None:
        self.create()
        page = self.page()

        self.assertIn(ADDED_SUPPLIER, page)
        self.assertIn(ADDED_INN, page)

    def test_creation_redirects_back_to_the_page(self) -> None:
        self.assertRedirects(self.create(), reverse("firmalar"))

    def test_a_name_is_required(self) -> None:
        response = self.create(name="")

        self.assertEqual(Supplier.objects.count(), 0)
        self.assertEqual(response.status_code, 200)

    def test_two_suppliers_cannot_share_a_name(self) -> None:
        self.create()

        response = self.create(inn="987654321")

        self.assertEqual(Supplier.objects.count(), 1)
        self.assertContains(response, "Bu nom allaqachon mavjud")

    def test_a_name_differing_only_in_case_is_refused(self) -> None:
        self.create()

        response = self.create(name=ADDED_SUPPLIER.upper(), inn="987654321")

        self.assertEqual(Supplier.objects.count(), 1)
        self.assertEqual(response.status_code, 200)


class InnTests(SupplierPageTestCase):
    """What decides whether two rows are the same firm."""

    def test_the_inn_is_optional(self) -> None:
        # A foreign supplier has no Uzbek INN, and DEC-023 seeds an Import
        # contract type, so foreign suppliers are expected. The supplied
        # contract form does not mark the field required either.
        self.create(inn="")

        self.assertEqual(Supplier.objects.get().inn, "")

    def test_several_suppliers_may_have_no_inn(self) -> None:
        # The uniqueness rule excludes the empty value, or the second foreign
        # firm could not be entered at all.
        self.create(inn="")
        self.create(name="Foreign Trading GmbH", inn="")

        self.assertEqual(Supplier.objects.count(), 2)

    def test_two_suppliers_cannot_share_an_inn(self) -> None:
        # Otherwise TASK-UZK-048 would count one firm as two suppliers.
        self.create()

        response = self.create(name="Texnoprom savdo")

        self.assertEqual(Supplier.objects.count(), 1)
        self.assertContains(response, "Bu INN allaqachon ro")

    def test_an_inn_held_by_a_deleted_supplier_says_so(self) -> None:
        # DEC-009 keeps the deleted row, so it keeps the INN. Being told the
        # INN exists, while looking at a list that does not contain it, is
        # the refusal worth spelling out.
        self.create()
        deleted = Supplier.objects.get()
        self.client.post(reverse("firmalar-delete", args=[deleted.pk]))

        response = self.create(name="Texnoprom savdo")

        self.assertEqual(Supplier.objects.count(), 1)
        # Without the apostrophe: the page escapes it to &#x27;.
        self.assertContains(response, "chirilgan firmaga tegishli")

    def test_an_inn_that_is_not_nine_digits_is_refused(self) -> None:
        # Nine is the supplied contract form's own maxlength and placeholder,
        # not a rule invented here.
        for supplied in ("12345678", "1234567890", "12345678x"):
            with self.subTest(inn=supplied):
                response = self.create(inn=supplied)

                self.assertEqual(Supplier.objects.count(), 0)
                self.assertEqual(response.status_code, 200)


class DarajaTests(SupplierPageTestCase):
    """DEC-025 adds the field and does not say what goes in it."""

    def test_the_daraja_is_optional(self) -> None:
        self.create(daraja="")

        self.assertEqual(Supplier.objects.get().daraja, "")

    def test_the_daraja_is_stored_as_typed(self) -> None:
        # Free text on purpose. Inventing a scale here would be inventing the
        # customer's supplier grading; TASK-UZK-048 filters on whatever the
        # department actually enters.
        self.create(daraja="Birinchi daraja")

        self.assertEqual(Supplier.objects.get().daraja, "Birinchi daraja")


class CountingTests(SupplierPageTestCase):
    """The acceptance criterion TASK-UZK-048 depends on."""

    def test_the_total_supplier_count_is_derivable(self) -> None:
        self.create()
        self.create(name="GazTrade", inn="987654321")

        self.assertEqual(Supplier.objects.active().count(), 2)

    def test_a_deleted_supplier_leaves_the_count(self) -> None:
        self.create()
        self.create(name="GazTrade", inn="987654321")
        self.client.post(
            reverse("firmalar-delete", args=[Supplier.objects.first().pk])
        )

        self.assertEqual(Supplier.objects.active().count(), 1)


class EditingTests(SupplierPageTestCase):
    """Edit opens the form filled in and saves what was changed."""

    def setUp(self) -> None:
        super().setUp()
        self.create()
        self.supplier = Supplier.objects.get()

    def test_the_form_opens_filled_in(self) -> None:
        page = self.client.get(f"{reverse('firmalar')}?edit={self.supplier.pk}")

        self.assertContains(page, f'value="{ADDED_SUPPLIER}"')
        self.assertContains(page, f'value="{ADDED_INN}"')

    def test_an_edited_supplier_shows_the_edited_values(self) -> None:
        self.client.post(
            reverse("firmalar-update", args=[self.supplier.pk]),
            {
                "name": "Texnoprom savdo",
                "inn": "987654321",
                "daraja": "B",
                "category_number": "",
            },
        )
        self.supplier.refresh_from_db()

        self.assertEqual(self.supplier.name, "Texnoprom savdo")
        self.assertEqual(self.supplier.inn, "987654321")
        self.assertEqual(self.supplier.daraja, "B")

    def test_keeping_its_own_inn_on_an_edit_is_not_a_clash(self) -> None:
        # The clash check has to exclude the row being edited, or changing a
        # supplier's Daraja would be refused for reusing its own INN.
        response = self.client.post(
            reverse("firmalar-update", args=[self.supplier.pk]),
            {
                "name": ADDED_SUPPLIER,
                "inn": ADDED_INN,
                "daraja": "B",
                "category_number": "",
            },
        )
        self.supplier.refresh_from_db()

        self.assertRedirects(response, reverse("firmalar"))
        self.assertEqual(self.supplier.daraja, "B")


class DeletionTests(SupplierPageTestCase):
    """DEC-009: ask, then deactivate."""

    def setUp(self) -> None:
        super().setUp()
        self.create()
        self.supplier = Supplier.objects.get()

    def delete(self):
        return self.client.post(
            reverse("firmalar-delete", args=[self.supplier.pk])
        )

    def test_a_deleted_supplier_leaves_the_list(self) -> None:
        self.delete()

        self.assertNotIn(ADDED_SUPPLIER, self.page())

    def test_a_deleted_supplier_still_exists(self) -> None:
        # So a contract already naming it still resolves.
        self.delete()
        self.supplier.refresh_from_db()

        self.assertFalse(self.supplier.is_active)
        self.assertEqual(Supplier.objects.count(), 1)

    def test_the_page_asks_before_deleting(self) -> None:
        self.assertIn("data-confirm=", self.page())

    def test_deletion_needs_a_post(self) -> None:
        response = self.client.get(
            reverse("firmalar-delete", args=[self.supplier.pk])
        )
        self.supplier.refresh_from_db()

        self.assertEqual(response.status_code, 405)
        self.assertTrue(self.supplier.is_active)

    def test_deleting_twice_is_a_not_found(self) -> None:
        self.delete()

        self.assertEqual(self.delete().status_code, 404)


class PermissionTests(TestCase):
    """The invented page is Admin-only, like every other master data page."""

    def setUp(self) -> None:
        self.supplier = Supplier.objects.create(
            name=ADDED_SUPPLIER, inn=ADDED_INN
        )

    def as_manager(self):
        self.client.force_login(make_user(MENEJER))

    def test_a_manager_may_not_open_the_page(self) -> None:
        self.as_manager()

        self.assertEqual(self.client.get(reverse("firmalar")).status_code, 403)

    def test_a_manager_may_not_create(self) -> None:
        self.as_manager()

        response = self.client.post(
            reverse("firmalar-create"),
            {"name": "GazTrade", "inn": "", "daraja": "", "category_number": ""},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(Supplier.objects.count(), 1)

    def test_a_manager_may_not_edit(self) -> None:
        self.as_manager()

        response = self.client.post(
            reverse("firmalar-update", args=[self.supplier.pk]),
            {"name": "Boshqa", "inn": "", "daraja": "", "category_number": ""},
        )
        self.supplier.refresh_from_db()

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.supplier.name, ADDED_SUPPLIER)

    def test_a_manager_may_not_delete(self) -> None:
        self.as_manager()

        response = self.client.post(
            reverse("firmalar-delete", args=[self.supplier.pk])
        )
        self.supplier.refresh_from_db()

        self.assertEqual(response.status_code, 403)
        self.assertTrue(self.supplier.is_active)

    def test_an_anonymous_visitor_is_redirected(self) -> None:
        self.assertEqual(self.client.get(reverse("firmalar")).status_code, 302)
