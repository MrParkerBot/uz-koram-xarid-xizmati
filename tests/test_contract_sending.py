"""Tests for sending a contract for approval (TASK-UZK-038).

Sending takes the contract out of its specialist's hands, which takes it off
the Kelishinlingan page. The two refusals - awaiting approval, and already
approved - are different sentences on purpose: the first attempt's review
found one sentence for both, and the test that covered it read the stage and
not the message, which is how it passed.
"""

from __future__ import annotations

from django.test import TestCase

from tests.support import (
    SignedInAdminTestCase,
    a_contract,
    an_assigned_application,
    make_user,
    page,
)
from xarid.models import ADMIN, KATTA_MUTAXASIS, Contract


class SendForApprovalTests(TestCase):
    """The rule itself."""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.head = make_user("send.head", user_type=ADMIN)
        cls.specialist = make_user("send.specialist", user_type=KATTA_MUTAXASIS)

    def a_contract_to_send(self) -> Contract:
        return a_contract(an_assigned_application(self.head, self.specialist), self.specialist)

    def test_sending_moves_it_to_awaiting_approval_and_records_the_send(self) -> None:
        contract = self.a_contract_to_send()

        sent = contract.send_for_approval(by=self.specialist)

        contract.refresh_from_db()
        self.assertTrue(sent)
        self.assertEqual(contract.stage, Contract.Stage.SENT)
        self.assertTrue(contract.is_sent)
        self.assertEqual(contract.yuborgan, self.specialist)
        self.assertIsNotNone(contract.yuborilgan_sana)
        self.assertEqual(contract.yuborishlar_soni, 1)

    def test_a_contract_awaiting_approval_cannot_be_sent_again(self) -> None:
        contract = self.a_contract_to_send()
        contract.send_for_approval(by=self.specialist)

        with self.assertRaises(ValueError) as refused:
            contract.send_for_approval(by=self.specialist)

        self.assertIn("tasdiqlashga yuborilgan", str(refused.exception))
        contract.refresh_from_db()
        self.assertEqual(contract.yuborishlar_soni, 1)

    def test_an_approved_contract_is_refused_with_a_different_sentence(self) -> None:
        """Being told the wrong one sends whoever reads it looking for a queue."""
        contract = self.a_contract_to_send()
        Contract.objects.filter(pk=contract.pk).update(stage=Contract.Stage.SIGNED)

        with self.assertRaises(ValueError) as refused:
            contract.send_for_approval(by=self.specialist)

        self.assertIn("tasdiqlangan", str(refused.exception))
        self.assertNotIn("tasdiqlashga yuborilgan", str(refused.exception))

    def test_a_rejected_contract_can_be_resent_and_the_count_reaches_two(self) -> None:
        contract = self.a_contract_to_send()
        contract.send_for_approval(by=self.specialist)
        Contract.objects.filter(pk=contract.pk).update(
            stage=Contract.Stage.REJECTED, inkor_izohi="Narxi baland."
        )
        contract.refresh_from_db()

        self.assertTrue(contract.send_for_approval(by=self.specialist))

        contract.refresh_from_db()
        self.assertEqual(contract.stage, Contract.Stage.SENT)
        self.assertEqual(contract.yuborishlar_soni, 2)

    def test_a_resend_keeps_the_rejection_comment(self) -> None:
        """The approver looking at it again is who the comment is for."""
        contract = self.a_contract_to_send()
        Contract.objects.filter(pk=contract.pk).update(
            stage=Contract.Stage.REJECTED, inkor_izohi="Narxi baland."
        )
        contract.refresh_from_db()

        contract.send_for_approval(by=self.specialist)

        contract.refresh_from_db()
        self.assertEqual(contract.inkor_izohi, "Narxi baland.")

    def test_the_control_reads_re_send_only_after_a_rejection(self) -> None:
        contract = self.a_contract_to_send()

        self.assertEqual(contract.send_label, "Yuborish")

        Contract.objects.filter(pk=contract.pk).update(stage=Contract.Stage.REJECTED)
        contract.refresh_from_db()

        self.assertEqual(contract.send_label, "Re-Send")

    def test_two_sends_racing_send_it_once_and_count_one(self) -> None:
        """Reach in between the read and the write, not around it.

        send_for_approval re-reads the contract first, so a second caller in
        the same thread simply sees it sent and is refused - which is the
        previous test, not this one. A real race is a caller that read before
        the first write landed, so the re-read is suppressed here and the
        caller arrives at the conditional update holding stale state. That
        update is what has to refuse it.
        """
        contract = self.a_contract_to_send()
        one = Contract.objects.get(pk=contract.pk)
        two = Contract.objects.get(pk=contract.pk)
        two.refresh_from_db = lambda *args, **kwargs: None

        self.assertTrue(one.send_for_approval(by=self.specialist))
        self.assertFalse(two.send_for_approval(by=self.specialist))

        contract.refresh_from_db()
        self.assertEqual(contract.yuborishlar_soni, 1)
        self.assertEqual(contract.yuborgan, self.specialist)


class SendFromThePageTests(SignedInAdminTestCase):
    """The control and the action behind it."""

    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        cls.specialist = make_user("page.sender", user_type=KATTA_MUTAXASIS)

    def a_contract_on_the_page(self) -> Contract:
        return a_contract(an_assigned_application(self.admin, self.specialist), self.specialist)

    def test_the_page_offers_the_control(self) -> None:
        contract = self.a_contract_on_the_page()

        response = self.client.get(page("kelishinlingan"))

        self.assertContains(response, page("kelishinlingan-yuborish", contract.pk))
        self.assertContains(response, "Yuborish")

    def test_sending_takes_it_off_the_page_and_says_where_it_went(self) -> None:
        contract = self.a_contract_on_the_page()

        response = self.client.post(
            page("kelishinlingan-yuborish", contract.pk), follow=True
        )

        # The success message names the contract, which is the point of it -
        # so the assertion is that the row and its control are gone.
        self.assertNotContains(response, page("kelishinlingan-yuborish", contract.pk))
        self.assertContains(response, "Tuzilgan Shartnomalar")

    def test_the_status_control_goes_with_it(self) -> None:
        """Both ask the same stage rule, so they disappear together."""
        contract = self.a_contract_on_the_page()

        self.client.post(page("kelishinlingan-yuborish", contract.pk))

        response = self.client.get(page("kelishinlingan"))
        self.assertNotContains(response, page("kelishinlingan-holat", contract.pk))

    def test_a_second_send_from_the_page_is_a_message(self) -> None:
        contract = self.a_contract_on_the_page()
        contract.send_for_approval(by=self.admin)

        response = self.client.post(
            page("kelishinlingan-yuborish", contract.pk), follow=True
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "tasdiqlashga yuborilgan")

    def test_a_specialist_may_not_send_somebody_elses_contract(self) -> None:
        other = make_user("page.other.sender", user_type=KATTA_MUTAXASIS)
        contract = a_contract(an_assigned_application(self.admin, other), other)
        self.client.force_login(self.specialist)

        response = self.client.post(
            page("kelishinlingan-yuborish", contract.pk), follow=True
        )

        contract.refresh_from_db()
        self.assertEqual(contract.stage, Contract.Stage.AGREED)
        self.assertContains(response, "sizning ishingizga tegishli emas")

    def test_both_controls_ask_the_same_rule(self) -> None:
        """The status drop-down and the send control are one question.

        TASK-UZK-040 will restrict editing to the Edit Permission holder while
        sending stays with the specialist, so the day they diverge this test
        is what says the template was asking on purpose.
        """
        other = make_user("controls.other", user_type=KATTA_MUTAXASIS)
        mine = self.a_contract_on_the_page()
        theirs = a_contract(an_assigned_application(self.admin, other), other)
        self.client.force_login(self.specialist)

        response = self.client.get(page("kelishinlingan"))

        for route in ("kelishinlingan-holat", "kelishinlingan-yuborish"):
            with self.subTest(route=route):
                self.assertContains(response, page(route, mine.pk))
                self.assertNotContains(response, page(route, theirs.pk))

    def test_the_action_refuses_a_get(self) -> None:
        contract = self.a_contract_on_the_page()

        response = self.client.get(page("kelishinlingan-yuborish", contract.pk))

        self.assertEqual(response.status_code, 405)
