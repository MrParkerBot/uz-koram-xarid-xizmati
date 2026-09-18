"""Tests for moving a contract through its statuses (TASK-UZK-037).

What is enforced is narrower than "permitted transitions" sounds, because
DEC-010 makes the statuses extensible master data with no code column: a
status must be in use, the contract must still be its specialist's to change,
and moving to the status it already has is not a move. No order between two
statuses in use is enforced, and none is asserted here - a test asserting an
invented order would make the open question look answered.
"""

from __future__ import annotations

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from tests.support import (
    SignedInAdminTestCase,
    a_contract,
    an_assigned_application,
    make_user,
    page,
)
from xarid.models import (
    ADMIN,
    KATTA_MUTAXASIS,
    Contract,
    ContractStatusChange,
    ShartnomaStatus,
)
from xarid.permissions import held_contract


class SetStatusTests(TestCase):
    """The rule itself, without a page around it."""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.head = make_user("status.head", user_type=ADMIN)
        cls.specialist = make_user("status.specialist", user_type=KATTA_MUTAXASIS)
        cls.first, cls.second = tuple(ShartnomaStatus.objects.active())[:2]

    def a_held_contract(self, status=None) -> Contract:
        application = an_assigned_application(self.head, self.specialist)
        return a_contract(application, self.specialist, status=status)

    def test_a_move_changes_the_status_and_records_who_and_when(self) -> None:
        contract = self.a_held_contract(status=self.first)

        moved = contract.set_status(self.second, by=self.specialist)

        contract.refresh_from_db()
        self.assertTrue(moved)
        self.assertEqual(contract.status, self.second)
        change = ContractStatusChange.objects.get(contract=contract)
        self.assertEqual(change.from_status, self.first)
        self.assertEqual(change.to_status, self.second)
        self.assertEqual(change.changed_by, self.specialist)
        self.assertIsNotNone(change.changed_at)

    def test_the_first_move_of_a_contract_with_no_status_records_no_previous(self) -> None:
        contract = self.a_held_contract(status=None)

        self.assertTrue(contract.set_status(self.first, by=self.specialist))

        change = ContractStatusChange.objects.get(contract=contract)
        self.assertIsNone(change.from_status)
        self.assertEqual(change.to_status, self.first)

    def test_moving_to_the_status_it_already_has_is_not_a_move(self) -> None:
        contract = self.a_held_contract(status=self.first)

        moved = contract.set_status(self.first, by=self.specialist)

        self.assertFalse(moved)
        self.assertEqual(ContractStatusChange.objects.count(), 0)

    def test_no_status_at_all_is_refused(self) -> None:
        contract = self.a_held_contract(status=self.first)

        with self.assertRaises(ValueError):
            contract.set_status(None, by=self.specialist)

        contract.refresh_from_db()
        self.assertEqual(contract.status, self.first)

    def test_a_status_that_is_not_in_use_is_refused(self) -> None:
        retired = ShartnomaStatus.objects.create(name="Eskirgan", badge_colour="grey")
        retired.is_active = False
        retired.save(update_fields=["is_active"])
        contract = self.a_held_contract(status=self.first)

        with self.assertRaises(ValueError):
            contract.set_status(retired, by=self.specialist)

        contract.refresh_from_db()
        self.assertEqual(contract.status, self.first)
        self.assertEqual(ContractStatusChange.objects.count(), 0)

    def test_a_contract_awaiting_a_decision_is_refused(self) -> None:
        """SENT is the stage that refuses, not SIGNED.

        Until TASK-UZK-039 this test used SIGNED, because one constant
        answered both "may the terms change" and "may the progress be
        reported". Those are different questions: a contract must not change
        underneath the person deciding on it, and a signed one is still
        delivered afterwards.
        """
        contract = self.a_held_contract(status=self.first)
        Contract.objects.filter(pk=contract.pk).update(stage=Contract.Stage.SENT)

        with self.assertRaises(ValueError):
            contract.set_status(self.second, by=self.specialist)

        contract.refresh_from_db()
        self.assertEqual(contract.status, self.first)
        self.assertEqual(ContractStatusChange.objects.count(), 0)

    def test_a_signed_contract_still_moves(self) -> None:
        """DEC-010 seeds a delivered status, which happens after signing.

        Sharing EDITABLE_STAGES froze an approved contract's status forever,
        so that status was unreachable and DEC-028's "continues through its
        status chain" was impossible.
        """
        contract = self.a_held_contract(status=self.first)
        Contract.objects.filter(pk=contract.pk).update(stage=Contract.Stage.SIGNED)
        contract.refresh_from_db()

        self.assertTrue(contract.set_status(self.second, by=self.specialist))

        contract.refresh_from_db()
        self.assertEqual(contract.status, self.second)

    def test_two_moves_racing_produce_one_move_and_one_history_row(self) -> None:
        """The second caller read the old status before the first one wrote.

        Reaching in between the read and the write rather than asserting the
        shape of the code: both objects were loaded when the status was still
        the first one, which is exactly what two clicks landing together do.
        """
        contract = self.a_held_contract(status=self.first)
        one = Contract.objects.get(pk=contract.pk)
        two = Contract.objects.get(pk=contract.pk)

        self.assertTrue(one.set_status(self.second, by=self.specialist))
        self.assertFalse(two.set_status(self.second, by=self.specialist))

        self.assertEqual(ContractStatusChange.objects.filter(contract=contract).count(), 1)

    def test_the_last_change_is_the_most_recent_one(self) -> None:
        contract = self.a_held_contract(status=self.first)

        contract.set_status(self.second, by=self.specialist)

        self.assertEqual(contract.last_status_change.to_status, self.second)

    def test_a_contract_that_has_never_moved_has_no_last_change(self) -> None:
        self.assertIsNone(self.a_held_contract(status=self.first).last_status_change)


class WhoMayMoveTests(TestCase):
    """The row-level rule: a specialist moves their own work."""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.head = make_user("who.head", user_type=ADMIN)
        cls.mine = make_user("who.mine", user_type=KATTA_MUTAXASIS)
        cls.theirs = make_user("who.theirs", user_type=KATTA_MUTAXASIS)
        cls.status = ShartnomaStatus.objects.active().first()

    def test_a_specialist_may_move_a_contract_for_their_own_application(self) -> None:
        contract = a_contract(an_assigned_application(self.head, self.mine), self.mine)

        self.assertTrue(held_contract(self.mine, contract))

    def test_a_specialist_may_not_move_one_assigned_to_somebody_else(self) -> None:
        contract = a_contract(an_assigned_application(self.head, self.theirs), self.theirs)

        self.assertFalse(held_contract(self.mine, contract))

    def test_the_rule_follows_the_assignment_rather_than_who_created_it(self) -> None:
        """DEC-024 lets an Admin re-assign at any time, and the work moves with it."""
        application = an_assigned_application(self.head, self.mine)
        contract = a_contract(application, self.mine)
        application.assign(by=self.head, specialist=self.theirs)

        self.assertFalse(held_contract(self.mine, Contract.objects.get(pk=contract.pk)))
        self.assertTrue(held_contract(self.theirs, Contract.objects.get(pk=contract.pk)))

    def test_somebody_who_hands_work_out_may_move_any_of_it(self) -> None:
        contract = a_contract(an_assigned_application(self.head, self.mine), self.mine)

        self.assertTrue(held_contract(self.head, contract))


class ContractStatusPageTests(SignedInAdminTestCase):
    """The Holati column and the action behind it."""

    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        cls.specialist = make_user("page.specialist", user_type=KATTA_MUTAXASIS)
        cls.first, cls.second = tuple(ShartnomaStatus.objects.active())[:2]

    def a_contract_on_the_page(self, status=None) -> Contract:
        application = an_assigned_application(self.admin, self.specialist)
        return a_contract(application, self.specialist, status=status or self.first)

    def test_the_page_shows_the_status_and_the_drop_down(self) -> None:
        contract = self.a_contract_on_the_page()

        response = self.client.get(page("kelishinlingan"))

        self.assertContains(response, "Holati")
        self.assertContains(response, self.first.name)
        self.assertContains(response, page("kelishinlingan-holat", contract.pk))

    def test_the_drop_down_offers_only_statuses_in_use(self) -> None:
        retired = ShartnomaStatus.objects.create(name="Eskirgan", badge_colour="grey")
        retired.is_active = False
        retired.save(update_fields=["is_active"])
        self.a_contract_on_the_page()

        response = self.client.get(page("kelishinlingan"))

        self.assertNotContains(response, "Eskirgan")

    def test_moving_from_the_page_changes_the_status_and_says_so(self) -> None:
        contract = self.a_contract_on_the_page()

        response = self.client.post(
            page("kelishinlingan-holat", contract.pk), {"holat": self.second.pk}, follow=True
        )

        contract.refresh_from_db()
        self.assertEqual(contract.status, self.second)
        self.assertContains(response, self.second.name)

    def test_the_page_prints_who_moved_it_and_when(self) -> None:
        contract = self.a_contract_on_the_page()
        contract.set_status(self.second, by=self.specialist)

        response = self.client.get(page("kelishinlingan"))

        self.assertContains(response, self.specialist.get_username())

    def test_a_refusal_is_a_message_and_not_a_404(self) -> None:
        contract = self.a_contract_on_the_page()
        # SENT, not SIGNED: since TASK-UZK-039 a signed contract still moves.
        Contract.objects.filter(pk=contract.pk).update(stage=Contract.Stage.SENT)

        response = self.client.post(
            page("kelishinlingan-holat", contract.pk), {"holat": self.second.pk}, follow=True
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "tasdiqlashda turibdi")

    def test_a_specialist_is_refused_somebody_elses_contract(self) -> None:
        other = make_user("page.other", user_type=KATTA_MUTAXASIS)
        contract = a_contract(an_assigned_application(self.admin, other), other)
        self.client.force_login(self.specialist)

        response = self.client.post(
            page("kelishinlingan-holat", contract.pk), {"holat": self.second.pk}, follow=True
        )

        contract.refresh_from_db()
        self.assertEqual(contract.status, None)
        self.assertContains(response, "sizning ishingizga tegishli emas")

    def test_a_status_id_that_is_not_a_number_is_a_message_not_a_crash(self) -> None:
        """The drop-down always posts a real id, so this is a hand-made request.

        Every other refusal on this page is a message; before the fix an empty
        value or a word raised out of the field conversion and answered 500.
        """
        contract = self.a_contract_on_the_page()

        for value in ("", "abc", "1; drop table"):
            with self.subTest(holat=value):
                response = self.client.post(
                    page("kelishinlingan-holat", contract.pk), {"holat": value}, follow=True
                )

                self.assertEqual(response.status_code, 200)
                contract.refresh_from_db()
                self.assertEqual(contract.status, self.first)

    def test_an_unknown_status_id_is_refused_the_same_way(self) -> None:
        contract = self.a_contract_on_the_page()

        response = self.client.post(
            page("kelishinlingan-holat", contract.pk), {"holat": "999999"}, follow=True
        )

        self.assertEqual(response.status_code, 200)
        contract.refresh_from_db()
        self.assertEqual(contract.status, self.first)

    def test_the_action_refuses_a_get(self) -> None:
        contract = self.a_contract_on_the_page()

        response = self.client.get(page("kelishinlingan-holat", contract.pk))

        self.assertEqual(response.status_code, 405)

    def test_the_page_costs_the_same_whatever_the_number_of_contracts(self) -> None:
        """last_status_change reads the prefetched list, or this grows per row."""
        first = self.a_contract_on_the_page()
        first.set_status(self.second, by=self.specialist)
        with CaptureQueriesContext(connection) as one:
            self.client.get(page("kelishinlingan"))

        for _ in range(4):
            more = self.a_contract_on_the_page()
            more.set_status(self.second, by=self.specialist)
        with CaptureQueriesContext(connection) as five:
            self.client.get(page("kelishinlingan"))

        self.assertEqual(len(five), len(one))


class StatusCountersTests(SignedInAdminTestCase):
    """What this task exists to make possible: the reports can count."""

    def test_a_moved_contract_is_counted_by_the_departments_report(self) -> None:
        from xarid.reports import department_purchasing

        specialist = make_user("counted.specialist", user_type=KATTA_MUTAXASIS)
        status = ShartnomaStatus.objects.active().first()
        contract = a_contract(
            an_assigned_application(self.admin, specialist), specialist, status=None
        )
        contract.set_status(status, by=specialist)

        report = department_purchasing(None)

        counted = [row for row in report.rows if row.total]
        self.assertTrue(counted, "the department should have a row")
        self.assertEqual(counted[0].counters[0], 1)
