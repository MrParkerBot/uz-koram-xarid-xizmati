"""Tests for Send and Re-Send (TASK-UZK-038, REQ-SHARTNOMA-005, DEC-024).

Two things are worth saying.

Sending a contract takes it off the page that sent it. The Kelishinlingan list
is the contracts still the specialist's to work on, and a sent one is not - so
the test that matters is not only that the stage moved, it is that the row is
gone and the person was told where it went.

And the rejected state does not exist yet. TASK-UZK-039 builds the department
head's Accept and Reject, so the tests here write a rejection the way that task
will produce it - the stage and the comment together - rather than the way that
is convenient. TASK-UZK-034 wrote its Izoh test the same way and the review of
#48 found the half of it that had been done for convenience.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
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


class SendingTestCase(TestCase):
    """A contract in its specialist's hands, ready to go."""

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
        self.client.force_login(self.specialist)

    def an_assigned_application(self, specialist=None) -> Application:
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
        application.accept(self.buyer)
        application.assign(self.buyer, specialist or self.specialist)

        return application

    def a_contract(self, **overrides) -> Contract:
        fields = {
            "application": overrides.pop("application", None)
            or self.an_assigned_application(),
            "supplier": self.supplier,
            "created_by": self.specialist,
            "shartnoma_sanasi": "2026-09-17",
            "pdf": a_pdf("shartnoma.pdf"),
            "status": ShartnomaStatus.objects.active().first(),
        }
        fields.update(overrides)

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
            **fields,
        )

    def a_rejected_contract(self, comment: str = "Narx juda baland.") -> Contract:
        """A contract the department head sent back.

        Written directly because TASK-UZK-039 is what rejects one, and written
        as that task will produce it - the stage and the comment together,
        because a comment on a contract still at the agreed stage is a state
        the workflow never makes.
        """
        contract = self.a_contract()
        Contract.objects.filter(pk=contract.pk).update(
            stage=Contract.Stage.REJECTED, inkor_izohi=comment
        )
        contract.refresh_from_db()

        return contract

    def send(self, contract: Contract):
        return self.client.post(
            reverse("shartnoma-yuborish", args=[contract.pk])
        )

    def table(self) -> str:
        page = self.client.get(reverse("kelishinlingan")).content.decode()

        return page.split('<tbody id="kelish-tbody">', 1)[1].split(
            "</tbody>", 1
        )[0]


class SendTests(SendingTestCase):
    """REQ-SHARTNOMA-005: Send submits the contract for approval."""

    def test_sending_moves_it_to_awaiting_approval(self) -> None:
        contract = self.a_contract()

        response = self.send(contract)

        self.assertRedirects(response, reverse("kelishinlingan"))
        contract.refresh_from_db()
        self.assertEqual(contract.stage, Contract.Stage.SENT)
        self.assertTrue(contract.is_sent)

    def test_sending_records_when_and_by_whom(self) -> None:
        contract = self.a_contract()

        self.send(contract)

        contract.refresh_from_db()
        self.assertEqual(contract.yuborgan, self.specialist)
        self.assertIsNotNone(contract.yuborilgan_sana)

    def test_a_sent_contract_leaves_the_list(self) -> None:
        # The Kelishinlingan list is the contracts still the specialist's to
        # work on, so a sent one is not on it.
        contract = self.a_contract()
        self.assertIn(contract.shartnoma_raqami, self.table())

        self.send(contract)

        self.assertNotIn(contract.shartnoma_raqami, self.table())

    def test_the_person_is_told_where_it_went(self) -> None:
        # A row disappearing with no explanation is how somebody concludes
        # they deleted something.
        contract = self.a_contract()

        response = self.client.post(
            reverse("shartnoma-yuborish", args=[contract.pk]), follow=True
        )

        self.assertContains(response, "Tuzilgan Shartnomalar")

    def test_send_for_approval_says_whether_it_sent(self) -> None:
        contract = self.a_contract()

        self.assertTrue(contract.send_for_approval(self.specialist))


class SecondSendTests(SendingTestCase):
    """A contract awaiting approval cannot be sent again."""

    def test_sending_twice_is_refused(self) -> None:
        contract = self.a_contract()
        self.send(contract)
        first_sent_at = Contract.objects.get(pk=contract.pk).yuborilgan_sana

        self.send(contract)

        contract.refresh_from_db()
        self.assertEqual(contract.stage, Contract.Stage.SENT)
        self.assertEqual(contract.yuborilgan_sana, first_sent_at)

    def test_the_second_send_says_why(self) -> None:
        contract = self.a_contract()
        self.send(contract)

        response = self.client.post(
            reverse("shartnoma-yuborish", args=[contract.pk]), follow=True
        )

        self.assertContains(response, "allaqachon tasdiqlashga yuborilgan")

    def test_an_approved_contract_cannot_be_sent(self) -> None:
        contract = self.a_contract()
        Contract.objects.filter(pk=contract.pk).update(
            stage=Contract.Stage.SIGNED
        )

        self.send(contract)

        contract.refresh_from_db()
        self.assertEqual(contract.stage, Contract.Stage.SIGNED)

    def test_an_approved_contract_is_told_it_was_approved(self) -> None:
        # Two stages refuse a send and they are different facts. This test
        # read the stage and not the message, which is how the review of #60
        # found both refusals saying the contract was awaiting approval.
        contract = self.a_contract()
        Contract.objects.filter(pk=contract.pk).update(
            stage=Contract.Stage.SIGNED
        )

        response = self.client.post(
            reverse("shartnoma-yuborish", args=[contract.pk]), follow=True
        )

        self.assertContains(response, "allaqachon tasdiqlangan")
        self.assertNotContains(response, "allaqachon tasdiqlashga yuborilgan")

    def test_send_for_approval_refuses_a_sent_contract(self) -> None:
        contract = self.a_contract()
        contract.send_for_approval(self.specialist)

        with self.assertRaises(ValueError):
            contract.send_for_approval(self.specialist)

    def test_the_send_that_lands_second_changes_nothing(self) -> None:
        # Two clicks arriving at once. The stage check is a read, and the
        # update after it is conditional on the stage so only one of them
        # moves the contract - the guard set_status() carries.
        contract = self.a_contract()
        reading = Contract.refresh_from_db

        def somebody_else_gets_there_first(instance, *args, **kwargs):
            reading(instance, *args, **kwargs)
            Contract.objects.filter(pk=instance.pk).update(
                stage=Contract.Stage.SENT
            )

        with patch.object(
            Contract, "refresh_from_db", somebody_else_gets_there_first
        ):
            sent = contract.send_for_approval(self.specialist)

        self.assertFalse(sent)
        contract.refresh_from_db()
        self.assertIsNone(contract.yuborgan)


class SendCountTests(SendingTestCase):
    """How many times a contract has gone for approval (the review of #60)."""

    def test_a_new_contract_has_never_been_sent(self) -> None:
        self.assertEqual(self.a_contract().yuborishlar_soni, 0)

    def test_sending_counts_once(self) -> None:
        contract = self.a_contract()

        self.send(contract)

        contract.refresh_from_db()
        self.assertEqual(contract.yuborishlar_soni, 1)

    def test_a_resend_counts_again(self) -> None:
        # The question the department will ask is how many times a contract
        # came back, and the two columns beside this one are overwritten by
        # each resend - so a log built later could not reconstruct it.
        contract = self.a_rejected_contract()
        contract.send_for_approval(self.specialist)
        Contract.objects.filter(pk=contract.pk).update(
            stage=Contract.Stage.REJECTED
        )
        contract.refresh_from_db()

        contract.send_for_approval(self.specialist)

        contract.refresh_from_db()
        self.assertEqual(contract.yuborishlar_soni, 2)

    def test_a_refused_send_does_not_count(self) -> None:
        contract = self.a_contract()
        self.send(contract)

        self.send(contract)

        contract.refresh_from_db()
        self.assertEqual(contract.yuborishlar_soni, 1)


class ResendTests(SendingTestCase):
    """DEC-024: after a rejection the control reads Re-Send."""

    def test_a_rejected_contract_is_back_on_the_list_with_its_comment(
        self,
    ) -> None:
        contract = self.a_rejected_contract()

        row = self.table()

        self.assertIn(contract.shartnoma_raqami, row)
        self.assertIn("Narx juda baland.", row)

    def test_the_control_reads_re_send(self) -> None:
        self.a_rejected_contract()

        self.assertIn("Re-Send", self.table())

    def test_an_unrejected_contract_reads_yuborish(self) -> None:
        self.a_contract()

        row = self.table()

        self.assertIn("Yuborish", row)
        self.assertNotIn("Re-Send", row)

    def test_the_label_is_decided_by_the_record(self) -> None:
        self.assertEqual(self.a_contract().send_label, "Yuborish")
        self.assertEqual(self.a_rejected_contract().send_label, "Re-Send")

    def test_a_rejected_contract_can_be_resent(self) -> None:
        contract = self.a_rejected_contract()

        self.send(contract)

        contract.refresh_from_db()
        self.assertEqual(contract.stage, Contract.Stage.SENT)
        self.assertEqual(contract.yuborgan, self.specialist)

    def test_a_resend_records_the_new_send(self) -> None:
        contract = self.a_rejected_contract()
        somebody_else = make_user(KATTA_MUTAXASIS, "Bekzod")
        contract.application.assign(self.buyer, somebody_else)
        self.client.force_login(somebody_else)

        self.send(contract)

        contract.refresh_from_db()
        self.assertEqual(contract.yuborgan, somebody_else)

    def test_the_comment_survives_the_resend(self) -> None:
        # REQ-SHARTNOMA-004 gives the comment a column, and the approver about
        # to look at this contract again is the person most helped by seeing
        # why it came back. DEC-024 says nothing either way.
        contract = self.a_rejected_contract()

        self.send(contract)

        contract.refresh_from_db()
        self.assertEqual(contract.inkor_izohi, "Narx juda baland.")

    def test_a_rejected_contract_can_be_corrected_first(self) -> None:
        # The whole of DEC-024: corrected, then resent, and the correction is
        # what goes.
        contract = self.a_rejected_contract()

        self.client.post(
            reverse("shartnoma-saqlash", args=[contract.pk]),
            {
                "application": contract.application_id,
                "supplier": self.supplier.pk,
                "shartnoma_turi": "",
                "status": "",
                "shartnoma_sanasi": "2026-09-18",
                "tolash_muddati": "",
                "muddat_talabi": "",
                "izoh": "Narx qayta kelishildi",
                "form-TOTAL_FORMS": "1",
                "form-INITIAL_FORMS": "1",
                "form-MIN_NUM_FORMS": "1",
                "form-MAX_NUM_FORMS": "1000",
                "form-0-id": contract.items.get().pk,
                "form-0-buyurtma_nomi": "Bolt M12",
                "form-0-part_number": "PN-0001",
                "form-0-buyurtma_soni": "500",
                "form-0-olchov_birligi": "ta",
                "form-0-narxi": "200000.00",
            },
        )
        self.send(contract)

        contract.refresh_from_db()
        self.assertEqual(contract.stage, Contract.Stage.SENT)
        self.assertEqual(contract.izoh, "Narx qayta kelishildi")
        self.assertEqual(contract.qiymati, Decimal("100000000.00"))


class PermissionTests(SendingTestCase):
    """Whose contract, and whose page."""

    def test_a_specialist_cannot_send_somebody_elses(self) -> None:
        contract = self.a_contract(
            application=self.an_assigned_application(
                specialist=make_user(KATTA_MUTAXASIS, "Bekzod")
            )
        )

        self.assertEqual(self.send(contract).status_code, 403)
        contract.refresh_from_db()
        self.assertEqual(contract.stage, Contract.Stage.AGREED)

    def test_the_types_that_hand_work_out_may_send_any(self) -> None:
        for type_name in (ADMIN, BOLIM_BOSHLIGI, MENEJER):
            with self.subTest(user_type=type_name):
                contract = self.a_contract()
                self.client.force_login(make_user(type_name))

                self.send(contract)

                contract.refresh_from_db()
                self.assertEqual(contract.stage, Contract.Stage.SENT)

    def test_the_others_may_not(self) -> None:
        contract = self.a_contract()

        for type_name in (DIREKTOR, USERS):
            with self.subTest(user_type=type_name):
                self.client.force_login(make_user(type_name))

                self.assertEqual(self.send(contract).status_code, 403)

        contract.refresh_from_db()
        self.assertEqual(contract.stage, Contract.Stage.AGREED)

    def test_the_send_is_a_post(self) -> None:
        contract = self.a_contract()

        self.assertEqual(
            self.client.get(
                reverse("shartnoma-yuborish", args=[contract.pk])
            ).status_code,
            405,
        )
