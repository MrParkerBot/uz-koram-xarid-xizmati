"""Tests for the Shartnoma Kiritish form of TASK-UZK-035.

Three things carry this task.

The contract value is computed. REQ-SHARTNOMA-006 calls it the total price for
everything, so the test that matters is not that the total is right on a
well-behaved form - it is that posting a qiymati does nothing, because a value
somebody can send is a value that can disagree with the rows it is supposed to
be the sum of.

The application is chosen from a narrowed list. REQ-ROLE-007 has the
specialist forming a contract on the basis of the application assigned to
them, and a drop-down is a suggestion: the test posts an application that is
not on it.

And Cancel. REQ-SHARTNOMA-007 says no data is saved, and the way that is built
is that Cancel has no route at all - so the test is that a form filled in and
abandoned leaves the database as it was.
"""

from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.utils import IntegrityError
from django.test import TestCase
from django.urls import reverse
from django.utils.crypto import get_random_string

from accounts.models import UserType
from accounts.roles import (
    ADMIN,
    BOLIM_BOSHLIGI,
    DIREKTOR,
    KATTA_MUTAXASIS,
    MENEJER,
    USERS,
    assign_user_type,
)
from applications.models import Application, Contract, ContractItem
from applications.test_support import a_pdf
from reference.models import (
    Department,
    MahsulotTuri,
    ShartnomaStatus,
    ShartnomaTuri,
    Supplier,
)


def make_user(type_name: str = ADMIN, first_name: str = "Test"):
    user = get_user_model().objects.create_user(
        username=f"user.{get_random_string(8).lower()}",
        password=get_random_string(24),
        first_name=first_name,
        last_name=type_name,
    )
    assign_user_type(user, UserType.objects.get(name=type_name))
    return user


class ContractEntryTestCase(TestCase):
    """An assigned application, a firm to buy from, and a form to fill in."""

    def setUp(self) -> None:
        self.department = Department.objects.create(name="Texnik bolim")
        self.category = MahsulotTuri.objects.create(
            category_number=100042, name="Metallurgiya"
        )
        self.supplier = Supplier.objects.create(
            name="Metall Savdo MCHJ", inn="123456789"
        )
        self.buyer = make_user(ADMIN, first_name="Alisher")
        self.specialist = make_user(KATTA_MUTAXASIS, first_name="Dilnoza")
        self.application = self.an_assigned_application()
        self.client.force_login(self.buyer)
        self.url = reverse("shartnoma-yaratish")

    def an_application(self) -> Application:
        return Application.raise_application(
            items=[
                {
                    "mahsulot_turi": self.category,
                    "buyurtma_nomi": "Bolt M12",
                    "buyurtma_soni": 500,
                    "olchov_birligi": "ta",
                }
            ],
            department=self.department,
        )

    def an_assigned_application(self, specialist=None) -> Application:
        """An application carried to the stage a contract is formed from.

        Through the real transitions rather than by writing the stage, so that
        a change to what assignment means reaches this fixture rather than
        leaving it describing a state the workflow no longer produces.
        """
        application = self.an_application()
        application.accept(self.buyer)
        application.assign(self.buyer, specialist or self.specialist)

        return application

    def payload(self, rows: int = 1, **overrides) -> dict:
        form = {
            "application": self.application.pk,
            "supplier": self.supplier.pk,
            "shartnoma_turi": "",
            "status": "",
            "shartnoma_sanasi": "2026-09-17",
            "tolash_muddati": "",
            "muddat_talabi": "",
            "izoh": "",
            "form-TOTAL_FORMS": str(rows),
            "form-INITIAL_FORMS": "0",
            "form-MIN_NUM_FORMS": "1",
            "form-MAX_NUM_FORMS": "1000",
        }
        for index in range(rows):
            form |= {
                f"form-{index}-buyurtma_nomi": f"Bolt M{index + 1}",
                f"form-{index}-part_number": f"PN-000{index + 1}",
                f"form-{index}-buyurtma_soni": "500",
                f"form-{index}-olchov_birligi": "ta",
                f"form-{index}-narxi": "250000.00",
            }
        form.update(overrides)
        return form

    def create(self, rows: int = 1, pdf=None, **overrides):
        """Post the form, attaching a PDF unless the test says otherwise.

        pdf=False posts without one, which TASK-UZK-036 refuses.
        """
        payload = self.payload(rows, **overrides)
        if pdf is not False:
            payload["pdf"] = pdf if pdf is not None else a_pdf("shartnoma.pdf")

        return self.client.post(self.url, payload)

    def page(self) -> str:
        return self.client.get(reverse("kelishinlingan")).content.decode()

    def table(self) -> str:
        body = self.page().split('<tbody id="kelish-tbody">', 1)[1]

        return body.split("</tbody>", 1)[0]


class CreationTests(ContractEntryTestCase):
    """Entering a contract."""

    def test_creating_produces_one_contract(self) -> None:
        response = self.create()

        self.assertRedirects(response, reverse("kelishinlingan"))
        contract = Contract.objects.get()
        self.assertEqual(contract.application, self.application)
        self.assertEqual(contract.supplier, self.supplier)
        self.assertEqual(contract.created_by, self.buyer)
        self.assertEqual(contract.stage, Contract.Stage.AGREED)

    def test_the_contract_is_numbered_on_saving(self) -> None:
        self.create()

        self.assertTrue(
            Contract.objects.get().shartnoma_raqami.startswith("SHT-")
        )

    def test_every_row_is_stored(self) -> None:
        self.create(rows=3)

        rows = list(Contract.objects.get().items.all())
        self.assertEqual(
            [row.buyurtma_nomi for row in rows],
            ["Bolt M1", "Bolt M2", "Bolt M3"],
        )
        self.assertEqual(
            [row.part_number for row in rows],
            ["PN-0001", "PN-0002", "PN-0003"],
        )

    def test_the_header_fields_are_stored(self) -> None:
        turi = ShartnomaTuri.objects.get(name="Import")
        status = ShartnomaStatus.objects.filter(is_active=True).first()

        self.create(
            shartnoma_turi=turi.pk,
            status=status.pk,
            tolash_muddati="2026-12-31",
            muddat_talabi="2026-11-30",
            izoh="Shoshilinch",
        )

        contract = Contract.objects.get()
        self.assertEqual(contract.shartnoma_turi, turi)
        self.assertEqual(contract.status, status)
        self.assertEqual(contract.shartnoma_sanasi.isoformat(), "2026-09-17")
        self.assertEqual(contract.tolash_muddati.isoformat(), "2026-12-31")
        self.assertEqual(contract.muddat_talabi.isoformat(), "2026-11-30")
        self.assertEqual(contract.izoh, "Shoshilinch")

    def test_the_new_contract_is_listed(self) -> None:
        self.create()

        contract = Contract.objects.get()
        row = self.table()
        self.assertIn(contract.shartnoma_raqami, row)
        self.assertIn(contract.qiymati_display, row)
        self.assertIn("PN-0001", row)


class ValueTests(ContractEntryTestCase):
    """Umumiy Narx and Shartnoma qiymati (REQ-SHARTNOMA-006)."""

    def test_a_line_total_is_the_price_times_the_quantity(self) -> None:
        self.create()

        row = ContractItem.objects.get()
        self.assertEqual(row.umumiy_narx, Decimal("125000000.00"))

    def test_a_fractional_quantity_is_priced_to_the_soum(self) -> None:
        # 2.5 kg at 1 000,33 is 2 500,825, and nobody pays a fraction of a
        # tiyin. Half up, so it is 2 500,83 rather than quietly truncated.
        self.create(
            **{
                "form-0-buyurtma_soni": "2.5",
                "form-0-olchov_birligi": "kg",
                "form-0-narxi": "1000.33",
            }
        )

        self.assertEqual(
            ContractItem.objects.get().umumiy_narx, Decimal("2500.83")
        )

    def test_the_contract_value_is_the_sum_of_the_rows(self) -> None:
        self.create(rows=3)

        contract = Contract.objects.get()
        self.assertEqual(contract.qiymati, Decimal("375000000.00"))
        self.assertEqual(
            contract.qiymati,
            sum(row.umumiy_narx for row in contract.items.all()),
        )

    def test_a_posted_contract_value_is_ignored(self) -> None:
        # The whole point of computing it. A form field would be a field
        # somebody could post a different number in, and the number is what
        # the department is agreeing to pay.
        self.create(qiymati="1.00")

        self.assertEqual(
            Contract.objects.get().qiymati, Decimal("125000000.00")
        )


class RefusalTests(ContractEntryTestCase):
    """What the form will not accept."""

    def assertNothingStored(self, response) -> None:
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Contract.objects.count(), 0)
        self.assertEqual(ContractItem.objects.count(), 0)

    def test_a_contract_with_no_rows_is_refused(self) -> None:
        self.assertNothingStored(self.create(rows=0))

    def test_a_row_with_no_price_is_refused(self) -> None:
        self.assertNothingStored(self.create(**{"form-0-narxi": ""}))

    def test_a_row_priced_at_nothing_is_refused(self) -> None:
        self.assertNothingStored(self.create(**{"form-0-narxi": "0"}))

    def test_a_negative_price_is_refused(self) -> None:
        self.assertNothingStored(self.create(**{"form-0-narxi": "-250000"}))

    def test_a_negative_quantity_is_refused(self) -> None:
        self.assertNothingStored(self.create(**{"form-0-buyurtma_soni": "-5"}))

    def test_a_contract_with_no_firm_is_refused(self) -> None:
        self.assertNothingStored(self.create(supplier=""))

    def test_a_contract_with_no_date_is_refused(self) -> None:
        self.assertNothingStored(self.create(shartnoma_sanasi=""))

    def test_a_refused_form_comes_back_filled_in(self) -> None:
        response = self.create(**{"form-0-narxi": ""})
        page = response.content.decode()

        self.assertIn("Bolt M1", page)
        self.assertIn("PN-0001", page)
        self.assertIn("Shartnoma yaratilmadi", page)

    def test_the_database_refuses_a_price_the_form_never_saw(self) -> None:
        # The rule is on the column as well as on the form, which is what the
        # review of #33 settled about order quantities: a form is one way in.
        self.create()
        contract = Contract.objects.get()

        with self.assertRaises(IntegrityError):
            ContractItem.objects.create(
                contract=contract,
                buyurtma_nomi="Vint",
                buyurtma_soni=Decimal("1"),
                olchov_birligi="ta",
                narxi=Decimal("0"),
            )

    def test_raise_contract_refuses_an_empty_contract(self) -> None:
        with self.assertRaises(ValueError):
            Contract.raise_contract(
                items=[],
                application=self.application,
                supplier=self.supplier,
                created_by=self.buyer,
                pdf=a_pdf("shartnoma.pdf"),
            )

    def test_raise_contract_refuses_a_value_somebody_supplies(self) -> None:
        with self.assertRaises(ValueError):
            Contract.raise_contract(
                items=[
                    {
                        "buyurtma_nomi": "Vint",
                        "buyurtma_soni": Decimal("1"),
                        "olchov_birligi": "ta",
                        "narxi": Decimal("10.00"),
                    }
                ],
                application=self.application,
                supplier=self.supplier,
                created_by=self.buyer,
                pdf=a_pdf("shartnoma.pdf"),
                qiymati=Decimal("1.00"),
            )


class CancelTests(ContractEntryTestCase):
    """REQ-SHARTNOMA-007: Cancel saves nothing."""

    def test_opening_the_form_and_leaving_stores_nothing(self) -> None:
        # Cancel is a button that closes the window. There is no route for it
        # to reach, which is how "no data is saved" is built: nothing was
        # posted, so there is nothing to undo.
        self.assertIn("Shartnoma Kiritish", self.page())

        self.assertEqual(Contract.objects.count(), 0)
        self.assertEqual(ContractItem.objects.count(), 0)

    def test_cancelling_after_one_contract_leaves_that_one(self) -> None:
        self.create()

        self.page()

        self.assertEqual(Contract.objects.count(), 1)


class ChoosableApplicationTests(ContractEntryTestCase):
    """REQ-ROLE-007: which applications a contract may be formed against."""

    def offered(self) -> list[str]:
        response = self.client.get(reverse("kelishinlingan"))
        field = response.context["form"].fields["application"]

        return [
            application.ariza_raqami for application in field.queryset
        ]

    def test_an_assigned_application_is_offered(self) -> None:
        self.assertIn(self.application.ariza_raqami, self.offered())

    def test_an_offered_application_can_be_told_from_another(self) -> None:
        # Application.__str__ is the number, and the number is the one thing
        # about a request the person choosing did not pick it by. The review
        # of #52 found three of them in a drop-down with nothing else on them.
        response = self.client.get(reverse("kelishinlingan"))
        field = response.context["form"].fields["application"]

        label = field.label_from_instance(self.application)

        self.assertIn(self.application.ariza_raqami, label)
        self.assertIn("Texnik bolim", label)
        self.assertIn("Bolt M12", label)

    def test_a_multi_line_application_says_how_many_more(self) -> None:
        many = Application.raise_application(
            items=[
                {
                    "mahsulot_turi": self.category,
                    "buyurtma_nomi": f"Bolt M{index}",
                    "buyurtma_soni": 10,
                    "olchov_birligi": "ta",
                }
                for index in range(3)
            ],
            department=self.department,
        )
        many.accept(self.buyer)
        many.assign(self.buyer, self.specialist)

        response = self.client.get(reverse("kelishinlingan"))
        field = response.context["form"].fields["application"]

        self.assertIn("+2", field.label_from_instance(many))

    def test_an_undecided_application_is_not_offered(self) -> None:
        waiting = self.an_application()

        self.assertNotIn(waiting.ariza_raqami, self.offered())

    def test_an_undecided_application_is_refused_when_posted(self) -> None:
        # The drop-down is a suggestion; this is the rule.
        waiting = self.an_application()

        response = self.create(application=waiting.pk)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Contract.objects.count(), 0)

    def test_a_specialist_is_offered_only_their_own(self) -> None:
        mine = self.application
        somebody_elses = self.an_assigned_application(
            specialist=make_user(KATTA_MUTAXASIS, first_name="Bekzod")
        )
        self.client.force_login(self.specialist)

        offered = self.offered()

        self.assertIn(mine.ariza_raqami, offered)
        self.assertNotIn(somebody_elses.ariza_raqami, offered)

    def test_a_specialist_cannot_contract_against_somebody_elses(self) -> None:
        somebody_elses = self.an_assigned_application(
            specialist=make_user(KATTA_MUTAXASIS, first_name="Bekzod")
        )
        self.client.force_login(self.specialist)

        response = self.create(application=somebody_elses.pk)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Contract.objects.count(), 0)

    def test_a_manager_is_offered_every_assigned_application(self) -> None:
        somebody_elses = self.an_assigned_application(
            specialist=make_user(KATTA_MUTAXASIS, first_name="Bekzod")
        )

        offered = self.offered()

        self.assertIn(self.application.ariza_raqami, offered)
        self.assertIn(somebody_elses.ariza_raqami, offered)


class MasterDataTests(ContractEntryTestCase):
    """DEC-023 and DEC-011: what the drop-downs are made of."""

    def test_the_contract_type_comes_from_master_data(self) -> None:
        turi = ShartnomaTuri.objects.create(name="Barter")

        response = self.client.get(reverse("kelishinlingan"))
        offered = response.context["form"].fields["shartnoma_turi"].queryset

        # Import and Local are seeded examples rather than the whole list
        # (DEC-023), so a type the department adds is offered too. Asserted as
        # membership rather than as a total, which the review of #52 found:
        # a total fails the day a migration seeds a third type, which is a
        # test about something else breaking.
        self.assertIn(turi, offered)
        for seeded in ("Import", "Mahalliy (Local)"):
            with self.subTest(shartnoma_turi=seeded):
                self.assertIn(ShartnomaTuri.objects.get(name=seeded), offered)

    def test_a_retired_firm_leaves_the_drop_down(self) -> None:
        retired = Supplier.objects.create(name="Eski Firma", inn="987654321")
        retired.delete()

        response = self.client.get(reverse("kelishinlingan"))
        offered = response.context["form"].fields["supplier"].queryset

        self.assertIn(self.supplier, offered)
        self.assertNotIn(retired, offered)

    def test_the_firm_option_carries_its_inn(self) -> None:
        # REQ-SHARTNOMA-006 asks for Firma INN raqami and DEC-011 says it is
        # not typed. The option carries it so the page can show it.
        self.assertIn(f'data-inn="{self.supplier.inn}"', self.page())


class PermissionTests(ContractEntryTestCase):
    """DEC-015 decides who may enter a contract."""

    def test_the_permitted_types_may_post(self) -> None:
        for type_name in (ADMIN, BOLIM_BOSHLIGI, MENEJER):
            with self.subTest(user_type=type_name):
                Contract.objects.all().delete()
                self.client.force_login(make_user(type_name))

                self.assertRedirects(self.create(), reverse("kelishinlingan"))

    def test_the_holder_of_an_application_may_post(self) -> None:
        self.client.force_login(self.specialist)

        self.assertRedirects(self.create(), reverse("kelishinlingan"))

    def test_the_others_may_not(self) -> None:
        for type_name in (DIREKTOR, USERS):
            with self.subTest(user_type=type_name):
                self.client.force_login(make_user(type_name))

                self.assertEqual(self.create().status_code, 403)
                self.assertEqual(Contract.objects.count(), 0)

    def test_signing_in_is_required(self) -> None:
        self.client.logout()

        response = self.create()

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_the_form_is_posted_rather_than_fetched(self) -> None:
        self.assertEqual(self.client.get(self.url).status_code, 405)
