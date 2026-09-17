"""Tests for the contract-edit lock (TASK-UZK-040, REQ-SHARTNOMA-005).

DEC-021 settles CONFLICT-001 as an exclusive lock that starts closed: at most
one person holds the Edit Permission, and granting it to somebody takes it
from whoever had it. TASK-UZK-013 built the lock and nothing ever asked it
anything; this is what asks.

The part worth being careful about is that nobody bypasses it, including
Admin. A bypass would make the exclusivity untrue for every administrator, and
exclusivity is the whole of what the decision decided - so the test that
matters most here is an Admin being refused.

The second is that three rules now guard the same two routes and they answer
three different questions: may this person open the Kelishinlingan page, are
they the one person who may edit a contract, and is this contract theirs. Each
is tested with the other two satisfied, so a test cannot pass because a
different rule refused.
"""

from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils.crypto import get_random_string

from accounts.contract_editing import (
    contract_editor,
    grant_contract_editing,
    may_edit_contracts,
    revoke_contract_editing,
)
from accounts.models import UserType
from accounts.roles import (
    ADMIN,
    BOLIM_BOSHLIGI,
    KATTA_MUTAXASIS,
    MENEJER,
    USERS,
    assign_user_type,
)
from applications.models import Application, Contract
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


class EditPermissionTestCase(TestCase):
    """A contract, a holder, and several people who are not the holder."""

    def setUp(self) -> None:
        self.department = Department.objects.create(name="Texnik bolim")
        self.category = MahsulotTuri.objects.create(
            category_number=100042, name="Metallurgiya"
        )
        self.supplier = Supplier.objects.create(
            name="Metall Savdo MCHJ", inn="123456789"
        )
        self.admin = make_user(ADMIN, first_name="Alisher")
        self.specialist = make_user(KATTA_MUTAXASIS, first_name="Dilnoza")
        self.contract = self.a_contract()

    def a_contract(self) -> Contract:
        application = Application.raise_application(
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
        application.accept(self.admin)
        application.assign(self.admin, self.specialist)

        return Contract.raise_contract(
            items=[
                {
                    "buyurtma_nomi": "Bolt M12",
                    "part_number": "PN-0001",
                    "buyurtma_soni": Decimal("500"),
                    "olchov_birligi": "ta",
                    "narxi": Decimal("250000.00"),
                }
            ],
            application=application,
            supplier=self.supplier,
            created_by=self.specialist,
            shartnoma_sanasi="2026-09-17",
            pdf=a_pdf("shartnoma.pdf"),
            status=ShartnomaStatus.objects.active().first(),
        )

    def open_the_form(self, contract: Contract | None = None):
        return self.client.get(
            reverse(
                "shartnoma-tahrirlash", args=[(contract or self.contract).pk]
            )
        )

    def save(self, contract: Contract | None = None, **overrides):
        contract = contract or self.contract
        payload = {
            "application": contract.application_id,
            "supplier": self.supplier.pk,
            "shartnoma_turi": "",
            "status": "",
            "shartnoma_sanasi": "2026-09-18",
            "tolash_muddati": "",
            "muddat_talabi": "",
            "izoh": "Tahrirlandi",
            "form-TOTAL_FORMS": "1",
            "form-INITIAL_FORMS": "1",
            "form-MIN_NUM_FORMS": "1",
            "form-MAX_NUM_FORMS": "1000",
            "form-0-id": contract.items.get().pk,
            "form-0-buyurtma_nomi": "Bolt M12",
            "form-0-part_number": "PN-0001",
            "form-0-buyurtma_soni": "500",
            "form-0-olchov_birligi": "ta",
            "form-0-narxi": "250000.00",
        }
        payload.update(overrides)

        return self.client.post(
            reverse("shartnoma-saqlash", args=[contract.pk]), payload
        )

    def table(self) -> str:
        page = self.client.get(reverse("kelishinlingan")).content.decode()

        return page.split('<tbody id="kelish-tbody">', 1)[1].split(
            "</tbody>", 1
        )[0]


class WithoutThePermissionTests(EditPermissionTestCase):
    """Nobody holds it until Admin grants it (DEC-021)."""

    def test_the_form_cannot_be_opened(self) -> None:
        self.client.force_login(self.admin)

        self.assertEqual(self.open_the_form().status_code, 403)

    def test_posting_at_the_endpoint_is_refused(self) -> None:
        # The control is not on the page for them; this is the rule.
        self.client.force_login(self.admin)

        self.assertEqual(self.save().status_code, 403)

        self.contract.refresh_from_db()
        self.assertEqual(self.contract.izoh, "")

    def test_admin_does_not_bypass_it(self) -> None:
        # The test that matters. A bypass would make DEC-021's exclusivity
        # untrue for every administrator, and exclusivity is the whole of what
        # the decision decided. An Admin who needs to edit grants themselves
        # the permission, which is the same act as taking it from the holder.
        self.client.force_login(make_user(ADMIN, "Bekzod"))

        self.assertEqual(self.open_the_form().status_code, 403)

    def test_the_holder_of_the_page_permission_is_not_enough(self) -> None:
        for type_name in (ADMIN, MENEJER, KATTA_MUTAXASIS):
            with self.subTest(user_type=type_name):
                self.client.force_login(make_user(type_name))

                self.assertEqual(self.open_the_form().status_code, 403)

    def test_the_control_says_what_is_missing(self) -> None:
        # Disabled rather than absent: a control that is simply gone looks
        # like a page that is broken.
        self.client.force_login(self.admin)

        row = self.table()

        self.assertIn("Tahrirlash ruxsati sizda emas", row)
        self.assertNotIn(
            reverse("shartnoma-tahrirlash", args=[self.contract.pk]), row
        )


class WithThePermissionTests(EditPermissionTestCase):
    """The one person who holds it."""

    def test_the_holder_can_open_the_form(self) -> None:
        grant_contract_editing(self.specialist)
        self.client.force_login(self.specialist)

        response = self.open_the_form()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["editing"], self.contract)

    def test_the_holder_can_save(self) -> None:
        grant_contract_editing(self.specialist)
        self.client.force_login(self.specialist)

        self.save()

        self.contract.refresh_from_db()
        self.assertEqual(self.contract.izoh, "Tahrirlandi")

    def test_the_control_is_offered_to_them(self) -> None:
        grant_contract_editing(self.specialist)
        self.client.force_login(self.specialist)

        row = self.table()

        self.assertIn(
            reverse("shartnoma-tahrirlash", args=[self.contract.pk]), row
        )
        self.assertNotIn("Tahrirlash ruxsati sizda emas", row)

    def test_an_admin_holder_can_edit(self) -> None:
        grant_contract_editing(self.admin)
        self.client.force_login(self.admin)

        self.save()

        self.contract.refresh_from_db()
        self.assertEqual(self.contract.izoh, "Tahrirlandi")


class ExclusivityTests(EditPermissionTestCase):
    """At most one person holds it, and granting it takes it away."""

    def test_granting_it_to_somebody_else_takes_it_from_the_holder(
        self,
    ) -> None:
        grant_contract_editing(self.specialist)
        self.client.force_login(self.specialist)
        self.assertEqual(self.open_the_form().status_code, 200)

        grant_contract_editing(self.admin)

        self.assertEqual(self.open_the_form().status_code, 403)

    def test_revoking_it_leaves_nobody_able_to_edit(self) -> None:
        grant_contract_editing(self.specialist)
        revoke_contract_editing(self.specialist)
        self.client.force_login(self.specialist)

        self.assertEqual(self.open_the_form().status_code, 403)

    def test_a_deactivated_holder_does_not_hold_it(self) -> None:
        # DEC-009 leaves the row in place when somebody is deleted, and a
        # deleted person must not still be the one person allowed to change a
        # contract. contract_editing.py says so, and this asserts it there:
        # the route never gets the chance, because a deactivated account is
        # signed out by authentication before any permission is asked.
        grant_contract_editing(self.specialist)
        self.client.force_login(self.specialist)
        self.specialist.is_active = False
        self.specialist.save(update_fields=["is_active"])

        self.assertFalse(may_edit_contracts(self.specialist))
        self.assertIsNone(contract_editor())

        response = self.open_the_form()
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])


class ThreeRulesTests(EditPermissionTestCase):
    """The lock, the page and the row are three different questions."""

    def test_the_holder_still_may_not_edit_somebody_elses_contract(
        self,
    ) -> None:
        # The lock says who may edit at all; held_contract() says whose
        # contract this is. Nothing says either replaces the other.
        somebody_else = make_user(KATTA_MUTAXASIS, "Bekzod")
        grant_contract_editing(somebody_else)
        self.client.force_login(somebody_else)

        self.assertEqual(self.open_the_form().status_code, 403)

    def test_a_holder_who_hands_work_out_may_edit_anybodys(self) -> None:
        # The row rule narrows a Katta Mutaxasis to their own work and nobody
        # else, on this route as on every other. Bo`lim Boshlig`i may open
        # Kelishinlingan, so a holder of that type edits any contract on it.
        head = make_user(BOLIM_BOSHLIGI, "Gulnora")
        grant_contract_editing(head)
        self.client.force_login(head)

        self.assertEqual(self.open_the_form().status_code, 200)

    def test_a_holder_who_may_not_open_the_page_may_not_edit(self) -> None:
        # DEC-015 gives Users the Xarid Arizasi page and nothing else. Holding
        # the lock does not open a page they were never given.
        requester = make_user(USERS, "Sardor")
        grant_contract_editing(requester)
        self.client.force_login(requester)

        self.assertEqual(
            self.client.get(reverse("kelishinlingan")).status_code, 403
        )
        self.assertEqual(self.open_the_form().status_code, 403)

    def test_the_lock_does_not_touch_creating_a_contract(self) -> None:
        # REQ-ROLE-007 is who forms a contract and REQ-USERS-002 is who edits
        # an entered one. Only the second is a lock.
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("shartnoma-yaratish"),
            {
                "application": self.contract.application_id,
                "supplier": self.supplier.pk,
                "shartnoma_turi": "",
                "status": "",
                "shartnoma_sanasi": "2026-09-17",
                "tolash_muddati": "",
                "muddat_talabi": "",
                "izoh": "",
                "pdf": a_pdf("ikkinchi.pdf"),
                "form-TOTAL_FORMS": "1",
                "form-INITIAL_FORMS": "0",
                "form-MIN_NUM_FORMS": "1",
                "form-MAX_NUM_FORMS": "1000",
                "form-0-buyurtma_nomi": "Vint",
                "form-0-part_number": "PN-0002",
                "form-0-buyurtma_soni": "10",
                "form-0-olchov_birligi": "ta",
                "form-0-narxi": "1000.00",
            },
        )

        self.assertRedirects(response, reverse("kelishinlingan"))
        self.assertEqual(Contract.objects.count(), 2)

    def test_the_lock_does_not_touch_moving_the_status(self) -> None:
        # REQ-ROLE-008 is who reports a contract's progress, which is not the
        # same permission and is not exclusive.
        self.client.force_login(self.admin)
        moved_to = ShartnomaStatus.objects.active()[1]

        self.client.post(
            reverse("shartnoma-holat", args=[self.contract.pk]),
            {"status": str(moved_to.pk)},
        )

        self.contract.refresh_from_db()
        self.assertEqual(self.contract.status, moved_to)
