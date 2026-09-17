"""Tests for the Kelishinlingan Shartnoma list of TASK-UZK-034.

Two things are worth saying about this task.

It is the first reader of three master data tables. Supplier, ShartnomaStatus
and ShartnomaTuri were built by TASK-UZK-017, TASK-UZK-019 and TASK-UZK-021 and
nothing has ever pointed at them, so deleting one has been free. A contract
makes that PROTECTed in fact rather than in principle, and there is a test
that tries.

And the Izoh column has nothing in it. REQ-SHARTNOMA-004 gives the rejection
comment a column, and nothing rejects a contract until TASK-UZK-038 - so the
test writes one directly, because a column that has never held anything is a
column nobody has checked renders.

TASK-UZK-035 gave a contract goods rows of its own, so the fixture here now
prices them and the contract value falls out of them rather than being typed
into the fixture. The list shows those rows rather than the application's,
which is why the row assertions read the same and mean something different.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection
from django.db.models import ProtectedError
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
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
from applications.models import Application, Contract, next_ariza_raqami
from applications.test_support import a_pdf
from reference.models import (
    Department,
    MahsulotTuri,
    ShartnomaStatus,
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


class ContractTestCase(TestCase):
    """An application, a supplier, and somebody to agree a contract."""

    def setUp(self) -> None:
        self.department = Department.objects.create(name="Texnik bolim")
        self.category = MahsulotTuri.objects.create(
            category_number=100042, name="Metallurgiya"
        )
        self.supplier = Supplier.objects.create(
            name="Metall Savdo MCHJ", inn="123456789"
        )
        self.buyer = make_user(ADMIN, first_name="Alisher")
        self.client.force_login(self.buyer)

    def an_application(self, lines: int = 1) -> Application:
        return Application.raise_application(
            items=[
                {
                    "mahsulot_turi": self.category,
                    "buyurtma_nomi": f"Bolt M{index + 1}",
                    "buyurtma_soni": 500,
                    "olchov_birligi": "ta",
                }
                for index in range(lines)
            ],
            department=self.department,
        )

    def a_contract(self, lines: int = 1, **overrides) -> Contract:
        """A contract with one priced row per line.

        Five hundred at 250 000 comes to 125 000 000 a row, which is the
        figure the value-formatting tests below read - written here rather
        than passed in, because TASK-UZK-035 made the contract value the sum
        of the rows and a fixture that could set it directly would be a
        fixture able to disagree with them.
        """
        items = overrides.pop(
            "items",
            [
                {
                    "buyurtma_nomi": f"Bolt M{index + 1}",
                    "part_number": f"PN-000{index + 1}",
                    "buyurtma_soni": Decimal("500"),
                    "olchov_birligi": "ta",
                    "narxi": Decimal("250000.00"),
                }
                for index in range(lines)
            ],
        )
        fields = {
            "application": overrides.pop("application", None)
            or self.an_application(lines),
            "supplier": self.supplier,
            "created_by": self.buyer,
            "status": ShartnomaStatus.objects.filter(is_active=True).first(),
            # TASK-UZK-036 made the document a rule about the contract rather
            # than about the form, so every fixture carries one.
            "pdf": a_pdf("shartnoma.pdf"),
        }
        fields.update(overrides)
        return Contract.raise_contract(items=items, **fields)

    def page(self) -> str:
        return self.client.get(reverse("kelishinlingan")).content.decode()

    def table(self) -> str:
        body = self.page().split('<tbody id="kelish-tbody">', 1)[1]

        return body.split("</tbody>", 1)[0]


class ValueFormatTests(ContractTestCase):
    """A contract value a person can read."""

    def test_the_value_is_grouped(self) -> None:
        contract = self.a_contract()

        self.assertEqual(
            contract.qiymati_display, "125 000 000,00"
        )

    def test_a_small_value_is_not_grouped(self) -> None:
        contract = self.a_contract(
            items=[
                {
                    "buyurtma_nomi": "Vint",
                    "buyurtma_soni": Decimal("1"),
                    "olchov_birligi": "ta",
                    "narxi": Decimal("950.50"),
                }
            ]
        )

        self.assertEqual(contract.qiymati_display, "950,50")


class NumberingTests(ContractTestCase):
    """DEC-022's third sequence."""

    def test_a_contract_is_numbered(self) -> None:
        contract = self.a_contract()

        self.assertEqual(
            contract.shartnoma_raqami, f"SHT-{date.today().year}-00001"
        )

    def test_the_next_one_takes_the_next_number(self) -> None:
        self.a_contract()
        second = self.a_contract()

        self.assertEqual(
            second.shartnoma_raqami, f"SHT-{date.today().year}-00002"
        )

    def test_the_sequence_is_independent_of_the_application_one(self) -> None:
        self.a_contract()

        # One application exists, made by the contract fixture, so the next
        # ARZ number is the second - not the third, which is what a shared
        # counter would give.
        self.assertEqual(
            next_ariza_raqami(), f"ARZ-{date.today().year}-00002"
        )


class ListTests(ContractTestCase):
    """Every column REQ-SHARTNOMA-004 names."""

    def test_the_headings_are_the_specified_ones(self) -> None:
        page = self.page()

        for heading in (
            "Ariza",
            "Bo'lim",
            "Buyurtma nomi",
            "Shartnoma",
            "Firma",
            "Kim tuzdi",
            "Yaratilgan",
            "Qiymati",
            "Ko'rish",
            "Yuborish",
            "Izoh",
        ):
            with self.subTest(heading=heading):
                self.assertIn(heading, page)

    def test_a_row_shows_the_contract(self) -> None:
        contract = self.a_contract()
        row = self.table()

        self.assertIn(contract.shartnoma_raqami, row)
        self.assertIn(contract.application.ariza_raqami, row)
        self.assertIn("Texnik bolim", row)
        self.assertIn("Bolt M1", row)
        self.assertIn("Metall Savdo MCHJ", row)
        self.assertIn("Alisher", row)
        self.assertIn(contract.qiymati_display, row)

    def test_the_creation_date_appears_without_being_given(self) -> None:
        # REQ-SHARTNOMA-004 says it appears automatically, and nothing in the
        # fixture sets it.
        contract = self.a_contract()

        # localdate, not .date(): the template renders in Asia/Tashkent and
        # the stored instant is UTC, which is the bug TASK-UZK-032 found in a
        # TASK-UZK-025 test. Writing it correctly here rather than repeating
        # it and waiting for the clock to expose it.
        self.assertIsNotNone(contract.yaratilingan_sana)
        self.assertIn(
            timezone.localdate(contract.yaratilingan_sana).isoformat(),
            self.table(),
        )

    def test_a_multi_row_contract_renders_a_row_per_row(self) -> None:
        self.a_contract(lines=3)
        row = self.table()

        for nomi in ("Bolt M1", "Bolt M2", "Bolt M3"):
            with self.subTest(line=nomi):
                self.assertIn(nomi, row)
        # Fourteen cells span the rows: every column except Buyurtma nomi,
        # which is the one there is a row of. TASK-UZK-036 added Ilova and
        # Tahrir, and TASK-UZK-037 added Holati.
        self.assertEqual(row.count('rowspan="3"'), 14)

    def test_an_empty_list_says_so_rather_than_showing_nothing(self) -> None:
        self.assertIn("Hozircha kelishinlingan shartnoma", self.table())

    def test_a_contract_that_has_moved_on_is_not_listed(self) -> None:
        # Sent and signed contracts belong to the pages that follow this one.
        # Rejected ones do not move on - DEC-024 brings them back here.
        agreed = self.a_contract()
        for stage in (Contract.Stage.SENT, Contract.Stage.SIGNED):
            with self.subTest(stage=stage):
                gone = self.a_contract()
                Contract.objects.filter(pk=gone.pk).update(stage=stage)

                row = self.table()
                self.assertIn(agreed.shartnoma_raqami, row)
                self.assertNotIn(gone.shartnoma_raqami, row)


class RejectionCommentTests(ContractTestCase):
    """REQ-SHARTNOMA-004's Izoh column, which nothing fills yet."""

    def test_an_unrejected_contract_shows_nothing_in_it(self) -> None:
        self.a_contract()

        self.assertNotIn("Byudjet", self.table())

    def test_a_rejected_contract_is_listed_with_its_comment(self) -> None:
        # The stage is set as well as the comment, which is what the #48
        # review found missing: writing the comment onto a contract still at
        # the agreed stage tested a state the workflow never produces, and
        # hid the fact that a rejected contract was not on this page at all.
        #
        # Written directly rather than through a transition because
        # TASK-UZK-038 is what rejects a contract, and this page has to be
        # ready for one before that arrives - DEC-024 has it corrected and
        # resent from here.
        contract = self.a_contract()
        Contract.objects.filter(pk=contract.pk).update(
            stage=Contract.Stage.REJECTED, inkor_izohi="Narx juda baland."
        )

        row = self.table()
        self.assertIn(contract.shartnoma_raqami, row)
        self.assertIn("Narx juda baland.", row)


class MasterDataProtectionTests(ContractTestCase):
    """The first time deleting this master data has been refused."""

    def test_a_supplier_in_use_cannot_be_deleted(self) -> None:
        self.a_contract()

        with self.assertRaises(ProtectedError):
            self.supplier.delete()

    def test_a_status_in_use_cannot_be_deleted(self) -> None:
        contract = self.a_contract()

        with self.assertRaises(ProtectedError):
            contract.status.delete()

    def test_an_application_under_contract_cannot_be_deleted(self) -> None:
        # PROTECT rather than CASCADE: a contract is an agreement with a
        # supplier, and deleting the request behind it should not take it.
        contract = self.a_contract()

        with self.assertRaises(ProtectedError):
            contract.application.delete()


class WaitingControlTests(ContractTestCase):
    """What belongs to the tasks after this one."""

    def test_the_controls_name_the_tasks_that_will_build_them(self) -> None:
        # No row action is waiting any more. TASK-UZK-035 built Shartnoma
        # Kiritish, TASK-UZK-037 built Ko'rish and TASK-UZK-038 built
        # Yuborish, and each took its own number off a control with it. What
        # is left disabled is the filter bar and the exports, which
        # TASK-UZK-041 and TASK-UZK-042 build for every table at once.
        #
        # Asserted on the disabled control rather than on the task number
        # alone, because the template's own comments name the tasks that
        # built it and a bare search cannot tell those apart from a control
        # that is still waiting.
        self.a_contract()
        page = self.page()

        self.assertIn('disabled title="TASK-UZK-041', page)
        self.assertIn('disabled title="TASK-UZK-042', page)
        for built in ("035", "037", "038"):
            with self.subTest(task=built):
                self.assertNotIn(f'disabled title="TASK-UZK-{built}', page)


class QueryTests(ContractTestCase):
    """The cost of the page, which the #38 review made a habit of checking."""

    def cost_of_the_page(self) -> int:
        with CaptureQueriesContext(connection) as captured:
            self.client.get(reverse("kelishinlingan"))

        return len(captured.captured_queries)

    def test_the_page_does_not_cost_a_query_per_row(self) -> None:
        self.a_contract()
        with_one = self.cost_of_the_page()

        for _ in range(4):
            self.a_contract()

        self.assertEqual(self.cost_of_the_page(), with_one)


class PermissionTests(ContractTestCase):
    """DEC-015 decides who may open this page."""

    def test_the_permitted_types_may_open_it(self) -> None:
        for type_name in (ADMIN, BOLIM_BOSHLIGI, MENEJER, KATTA_MUTAXASIS):
            with self.subTest(user_type=type_name):
                self.client.force_login(make_user(type_name))
                self.assertEqual(
                    self.client.get(reverse("kelishinlingan")).status_code, 200
                )

    def test_the_others_may_not(self) -> None:
        for type_name in (DIREKTOR, USERS):
            with self.subTest(user_type=type_name):
                self.client.force_login(make_user(type_name))
                self.assertEqual(
                    self.client.get(reverse("kelishinlingan")).status_code, 403
                )

    def test_signing_in_is_required(self) -> None:
        self.client.logout()

        response = self.client.get(reverse("kelishinlingan"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])
