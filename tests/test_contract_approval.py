"""Tests for the department head's decision on a contract (TASK-UZK-039).

Where a rejection lands is the half worth testing: "returned back" is not a
stage of its own, it is the contract on the Kelishinlingan page again with its
comment and a Re-Send control. That is asserted from the specialist's seat.
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
from xarid.models import ADMIN, KATTA_MUTAXASIS, MENEJER, Contract, ShartnomaStatus


class AcceptTests(TestCase):
    """Approving a contract."""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.head = make_user("approve.head", user_type=ADMIN)
        cls.specialist = make_user("approve.specialist", user_type=KATTA_MUTAXASIS)

    def a_sent_contract(self) -> Contract:
        contract = a_contract(
            an_assigned_application(self.head, self.specialist), self.specialist
        )
        contract.send_for_approval(by=self.specialist)
        return contract

    def test_accepting_approves_it_and_records_who_and_when(self) -> None:
        contract = self.a_sent_contract()

        self.assertTrue(contract.accept(by=self.head))

        contract.refresh_from_db()
        self.assertEqual(contract.stage, Contract.Stage.SIGNED)
        self.assertTrue(contract.is_signed)
        self.assertEqual(contract.tasdiqlagan, self.head)
        self.assertIsNotNone(contract.tasdiqlangan_sana)

    def test_accepting_twice_is_not_an_error_and_decides_once(self) -> None:
        contract = self.a_sent_contract()
        contract.accept(by=self.head)
        decided_at = Contract.objects.get(pk=contract.pk).tasdiqlangan_sana

        self.assertFalse(contract.accept(by=self.head))

        self.assertEqual(Contract.objects.get(pk=contract.pk).tasdiqlangan_sana, decided_at)

    def test_a_contract_not_awaiting_approval_is_refused(self) -> None:
        contract = a_contract(
            an_assigned_application(self.head, self.specialist), self.specialist
        )

        with self.assertRaises(ValueError):
            contract.accept(by=self.head)

        contract.refresh_from_db()
        self.assertEqual(contract.stage, Contract.Stage.AGREED)

    def test_an_approved_contract_still_moves_through_its_statuses(self) -> None:
        """DEC-028: it continues through its chain, and delivery follows signing."""
        first, second = tuple(ShartnomaStatus.objects.active())[:2]
        contract = self.a_sent_contract()
        contract.accept(by=self.head)
        contract.refresh_from_db()

        self.assertTrue(contract.set_status(second, by=self.specialist))

        contract.refresh_from_db()
        self.assertEqual(contract.status, second)
        self.assertEqual(contract.stage, Contract.Stage.SIGNED)


class RejectTests(TestCase):
    """Sending a contract back, and where it lands."""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.head = make_user("reject.head", user_type=ADMIN)
        cls.specialist = make_user("reject.specialist", user_type=KATTA_MUTAXASIS)

    def a_sent_contract(self) -> Contract:
        contract = a_contract(
            an_assigned_application(self.head, self.specialist), self.specialist
        )
        contract.send_for_approval(by=self.specialist)
        return contract

    def test_rejecting_returns_it_with_the_comment_and_the_decider(self) -> None:
        contract = self.a_sent_contract()

        self.assertTrue(contract.reject(by=self.head, comment="Narxi baland."))

        contract.refresh_from_db()
        self.assertEqual(contract.stage, Contract.Stage.REJECTED)
        self.assertEqual(contract.inkor_izohi, "Narxi baland.")
        self.assertEqual(contract.inkor_qilgan, self.head)
        self.assertIsNotNone(contract.inkor_sanasi)

    def test_an_empty_comment_is_refused(self) -> None:
        contract = self.a_sent_contract()

        with self.assertRaises(ValueError):
            contract.reject(by=self.head, comment="")

        contract.refresh_from_db()
        self.assertEqual(contract.stage, Contract.Stage.SENT)

    def test_a_whitespace_comment_is_refused(self) -> None:
        """A page is one way in; the rule belongs on the model."""
        contract = self.a_sent_contract()

        with self.assertRaises(ValueError):
            contract.reject(by=self.head, comment="   ")

        contract.refresh_from_db()
        self.assertEqual(contract.stage, Contract.Stage.SENT)

    def test_a_rejected_contract_is_back_with_its_specialist(self) -> None:
        """Returned back is not a stage: it is the Kelishinlingan page again.

        Rejected through the route rather than the model, because the reason
        reaches the specialist through the Izoh drawer, which reads the
        decision log - and only the route writes to it.
        """
        contract = self.a_sent_contract()
        self.client.force_login(self.head)
        self.client.post(page("tuzilgan-inkor", contract.pk), {"izoh": "Narxi baland."})

        self.client.force_login(self.specialist)
        response = self.client.get(page("kelishinlingan"))

        self.assertContains(response, contract.shartnoma_raqami)
        self.assertContains(response, "Narxi baland.")
        self.assertContains(response, "Re-Send")


class TuzilganPageTests(SignedInAdminTestCase):
    """The page, and who may decide on it."""

    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        cls.specialist = make_user("tuzilgan.specialist", user_type=KATTA_MUTAXASIS)

    def a_sent_contract(self) -> Contract:
        contract = a_contract(
            an_assigned_application(self.admin, self.specialist), self.specialist
        )
        contract.send_for_approval(by=self.specialist)
        return contract

    def test_the_page_answers_with_nothing_waiting(self) -> None:
        response = self.client.get(page("tuzilgan"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Tuzilgan Shartnomalar")

    def test_a_sent_contract_arrives_here_with_its_goods(self) -> None:
        contract = self.a_sent_contract()

        response = self.client.get(page("tuzilgan"))

        self.assertContains(response, contract.shartnoma_raqami)
        self.assertContains(response, contract.application.ariza_raqami)
        self.assertContains(response, contract.supplier.name)
        self.assertContains(response, contract.items.first().buyurtma_nomi)

    def test_the_head_is_offered_both_decisions(self) -> None:
        contract = self.a_sent_contract()

        response = self.client.get(page("tuzilgan"))

        self.assertContains(response, page("tuzilgan-tasdiqlash", contract.pk))
        self.assertContains(response, page("tuzilgan-inkor", contract.pk))

    def test_accepting_from_the_page_approves_it(self) -> None:
        contract = self.a_sent_contract()

        response = self.client.post(page("tuzilgan-tasdiqlash", contract.pk), follow=True)

        contract.refresh_from_db()
        self.assertEqual(contract.stage, Contract.Stage.SIGNED)
        self.assertContains(response, "qabul qilindi")

    def test_rejecting_from_the_page_returns_it_with_the_comment(self) -> None:
        contract = self.a_sent_contract()

        response = self.client.post(
            page("tuzilgan-inkor", contract.pk), {"izoh": "Muddat uzoq."}, follow=True
        )

        contract.refresh_from_db()
        self.assertEqual(contract.stage, Contract.Stage.REJECTED)
        self.assertEqual(contract.inkor_izohi, "Muddat uzoq.")
        self.assertContains(response, "inkor qilindi")

    def test_rejecting_without_a_comment_is_refused_on_the_page_too(self) -> None:
        contract = self.a_sent_contract()

        response = self.client.post(
            page("tuzilgan-inkor", contract.pk), {"izoh": " "}, follow=True
        )

        contract.refresh_from_db()
        self.assertEqual(contract.stage, Contract.Stage.SENT)
        self.assertContains(response, "izoh majburiy")

    def test_somebody_who_is_not_the_head_sees_the_contracts_and_no_buttons(self) -> None:
        contract = self.a_sent_contract()
        manager = make_user("tuzilgan.manager", user_type=MENEJER)
        self.client.force_login(manager)

        response = self.client.get(page("tuzilgan"))

        self.assertContains(response, contract.shartnoma_raqami)
        self.assertNotContains(response, page("tuzilgan-tasdiqlash", contract.pk))

    def test_the_route_refuses_them_too(self) -> None:
        """A page-level permission alone would let a Menejer approve."""
        contract = self.a_sent_contract()
        manager = make_user("tuzilgan.manager2", user_type=MENEJER)
        self.client.force_login(manager)

        response = self.client.post(page("tuzilgan-tasdiqlash", contract.pk))

        self.assertEqual(response.status_code, 403)
        contract.refresh_from_db()
        self.assertEqual(contract.stage, Contract.Stage.SENT)

    def test_a_contract_awaiting_a_decision_offers_no_status_control(self) -> None:
        contract = self.a_sent_contract()

        response = self.client.get(page("tuzilgan"))

        self.assertNotContains(response, page("kelishinlingan-holat", contract.pk))

    def test_a_signed_contract_offers_the_status_control_here(self) -> None:
        contract = self.a_sent_contract()
        contract.accept(by=self.admin)

        response = self.client.get(page("tuzilgan"))

        self.assertContains(response, page("kelishinlingan-holat", contract.pk))

    def test_a_specialist_is_offered_no_status_control_here(self) -> None:
        """A Katta Mutaxasis reads this page (TASK-UZK-068).

        The contract is out of their hands once it is here - waiting on a
        decision, or decided - and Kelishinlingan is where they report
        progress on the ones still in them. Not even on their own, which is
        the part that changed: the control used to be drawn for those.
        """
        other = make_user("tuzilgan.other", user_type=KATTA_MUTAXASIS)
        mine = self.a_sent_contract()
        mine.accept(by=self.admin)
        theirs = a_contract(an_assigned_application(self.admin, other), other)
        theirs.send_for_approval(by=other)
        theirs.accept(by=self.admin)
        self.client.force_login(self.specialist)

        response = self.client.get(page("tuzilgan"))

        self.assertContains(response, mine.shartnoma_raqami)
        self.assertNotContains(response, page("kelishinlingan-holat", mine.pk))
        self.assertNotContains(response, page("kelishinlingan-holat", theirs.pk))
        self.assertNotContains(response, ">Saqlash</button>")

    def test_whoever_is_not_a_specialist_still_moves_it(self) -> None:
        """The control went for one user type, not for the page."""
        contract = self.a_sent_contract()
        contract.accept(by=self.admin)

        response = self.client.get(page("tuzilgan"))

        self.assertContains(response, page("kelishinlingan-holat", contract.pk))

    def test_the_status_route_returns_to_the_page_it_came_from(self) -> None:
        status = ShartnomaStatus.objects.active().last()
        contract = self.a_sent_contract()
        contract.accept(by=self.admin)

        response = self.client.post(
            page("kelishinlingan-holat", contract.pk),
            {"holat": status.pk},
            HTTP_REFERER=page("tuzilgan"),
        )

        self.assertRedirects(response, page("tuzilgan"))

    def test_the_page_shows_why_a_contract_came_back_and_how_often(self) -> None:
        contract = self.a_sent_contract()
        contract.reject(by=self.admin, comment="Narxi baland.")
        contract.refresh_from_db()
        contract.send_for_approval(by=self.specialist)

        response = self.client.get(page("tuzilgan"))

        self.assertContains(response, "Narxi baland.")
        self.assertContains(response, "2-marta")
