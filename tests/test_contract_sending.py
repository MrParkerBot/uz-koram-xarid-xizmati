"""Tests for sending a contract for approval (TASK-UZK-038, TASK-UZK-062).

Sending takes the contract out of its specialist's hands, which takes it off
the Kelishinlingan page. The two refusals - awaiting approval, and already
approved - are different sentences on purpose: the first attempt's review
found one sentence for both, and the test that covered it read the stage and
not the message, which is how it passed.

Since TASK-UZK-062 the same click also saves the status chosen in the Status
column and tells Xarid Bo`limi's Bo`lim Boshlig`i and Menejer that a contract
now waits for them.
"""

from __future__ import annotations

from django.test import TestCase

from tests.support import (
    SignedInAdminTestCase,
    a_contract,
    a_department,
    an_assigned_application,
    make_user,
    page,
    send_form_of,
)
from xarid.models import (
    ADMIN,
    BOLIM_BOSHLIGI,
    KATTA_MUTAXASIS,
    MENEJER,
    Contract,
    ContractStatusChange,
    Notification,
    ShartnomaStatus,
)


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
        self.assertNotContains(response, send_form_of(contract))

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

        # The row's form is what the controls act through, so its presence is
        # the one question: a disabled button naming an action it has no form
        # for submits nothing.
        self.assertContains(response, f'id="sht-qator-{mine.pk}"')
        self.assertNotContains(response, f'id="sht-qator-{theirs.pk}"')
        self.assertContains(response, page("kelishinlingan-yuborish", mine.pk))

    def test_the_action_refuses_a_get(self) -> None:
        contract = self.a_contract_on_the_page()

        response = self.client.get(page("kelishinlingan-yuborish", contract.pk))

        self.assertEqual(response.status_code, 405)


class SendSavesTheStatusTests(SignedInAdminTestCase):
    """One click saves the chosen status and sends (TASK-UZK-062).

    The page has no Saqlash of its own any more: the drop-down rides with
    Yuborish. Sending is the step that cannot be taken back - the contract
    leaves the page - so a status that will not save has to stop the send
    rather than let the contract go with the wrong one.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        cls.specialist = make_user("save.sender", user_type=KATTA_MUTAXASIS)
        cls.first, cls.second = tuple(ShartnomaStatus.objects.active())[:2]

    def a_contract_on_the_page(self) -> Contract:
        return a_contract(
            an_assigned_application(self.admin, self.specialist),
            self.specialist,
            status=self.first,
        )

    def test_the_chosen_status_is_saved_and_the_contract_is_sent(self) -> None:
        contract = self.a_contract_on_the_page()

        response = self.client.post(
            page("kelishinlingan-yuborish", contract.pk),
            {"holat": self.second.pk},
            follow=True,
        )

        contract.refresh_from_db()
        self.assertEqual(contract.status, self.second)
        self.assertEqual(contract.stage, Contract.Stage.SENT)
        self.assertContains(response, "tasdiqlashga yuborildi")

    def test_the_move_is_written_to_the_history(self) -> None:
        """The status route records who moved it; sending must not skip that."""
        contract = self.a_contract_on_the_page()

        self.client.post(
            page("kelishinlingan-yuborish", contract.pk), {"holat": self.second.pk}
        )

        move = ContractStatusChange.objects.get(contract=contract)
        self.assertEqual(move.to_status, self.second)
        self.assertEqual(move.changed_by, self.admin)

    def test_sending_without_choosing_leaves_the_status_alone(self) -> None:
        """A contract with no status yet offers a blank first option.

        Choosing nothing there means send it as it is, not clear it -
        set_status refuses None, and that refusal is not a reason to hold
        back a send nobody asked to change the status on.
        """
        contract = a_contract(
            an_assigned_application(self.admin, self.specialist), self.specialist
        )

        self.client.post(page("kelishinlingan-yuborish", contract.pk), {"holat": ""})

        contract.refresh_from_db()
        self.assertIsNone(contract.status)
        self.assertEqual(contract.stage, Contract.Stage.SENT)

    def test_a_status_that_will_not_save_stops_the_send(self) -> None:
        retired = ShartnomaStatus.objects.create(name="Eskirgan", badge_colour="grey")
        retired.is_active = False
        retired.save(update_fields=["is_active"])
        contract = self.a_contract_on_the_page()

        response = self.client.post(
            page("kelishinlingan-yuborish", contract.pk),
            {"holat": retired.pk},
            follow=True,
        )

        contract.refresh_from_db()
        self.assertEqual(contract.status, self.first)
        self.assertEqual(contract.stage, Contract.Stage.AGREED)
        self.assertContains(response, "Shartnoma yuborilmadi")

    def test_an_unknown_status_stops_the_send_too(self) -> None:
        """A hand-made request, since the drop-down always posts a real id."""
        contract = self.a_contract_on_the_page()

        response = self.client.post(
            page("kelishinlingan-yuborish", contract.pk),
            {"holat": "999999"},
            follow=True,
        )

        contract.refresh_from_db()
        self.assertEqual(contract.stage, Contract.Stage.AGREED)
        self.assertContains(response, "Shartnoma yuborilmadi")


class SendTellsTheDepartmentTests(SignedInAdminTestCase):
    """A sent contract tells the people it now waits for (TASK-UZK-062)."""

    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        cls.purchasing = a_department("Xarid bo`limi")
        cls.purchasing.is_purchasing = True
        cls.purchasing.save(update_fields=["is_purchasing"])
        cls.xarid_head = make_user(
            "send.xarid.head", user_type=BOLIM_BOSHLIGI, department=cls.purchasing
        )
        cls.xarid_menejer = make_user(
            "send.xarid.menejer", user_type=MENEJER, department=cls.purchasing
        )
        cls.outsider = make_user(
            "send.other.head",
            user_type=BOLIM_BOSHLIGI,
            department=a_department("Buxgalteriya"),
        )
        cls.specialist = make_user(
            "send.told.specialist", user_type=KATTA_MUTAXASIS, department=cls.purchasing
        )

    def a_contract_on_the_page(self) -> Contract:
        return a_contract(
            an_assigned_application(self.admin, self.specialist), self.specialist
        )

    def told_about(self, contract: Contract):
        return Notification.objects.filter(
            kind=Notification.Kind.CONTRACT_SENT, application=contract.application
        )

    def test_both_roles_are_told_and_nobody_else(self) -> None:
        contract = self.a_contract_on_the_page()

        self.client.post(page("kelishinlingan-yuborish", contract.pk))

        self.assertCountEqual(
            [note.recipient for note in self.told_about(contract)],
            [self.xarid_head, self.xarid_menejer],
        )

    def test_the_message_names_the_contract_not_only_its_ariza(self) -> None:
        """It hangs off the application, so without the line nobody knows which."""
        contract = self.a_contract_on_the_page()

        self.client.post(page("kelishinlingan-yuborish", contract.pk))

        note = self.told_about(contract).first()
        self.assertIn(contract.shartnoma_raqami, note.izoh)
        self.assertIn(contract.supplier.name, note.izoh)

    def test_the_sender_is_not_told_about_their_own_send(self) -> None:
        """The Menejer sends one of their own, so only the head hears.

        A Menejer is never the assigned specialist - only a Katta Mutaxasis
        is - but they may enter a contract, and since TASK-UZK-064 what they
        entered is what they may act on. Somebody does not need telling that
        the thing they just did is waiting for them.
        """
        contract = a_contract(
            an_assigned_application(self.admin, self.specialist), self.xarid_menejer
        )
        self.client.force_login(self.xarid_menejer)

        self.client.post(page("kelishinlingan-yuborish", contract.pk))

        self.assertCountEqual(
            [note.recipient for note in self.told_about(contract)], [self.xarid_head]
        )

    def test_a_refused_send_tells_nobody(self) -> None:
        contract = self.a_contract_on_the_page()
        contract.send_for_approval(by=self.admin)

        self.client.post(page("kelishinlingan-yuborish", contract.pk))

        self.assertFalse(self.told_about(contract).exists())

    def test_the_notification_reaches_the_panel(self) -> None:
        contract = self.a_contract_on_the_page()
        self.client.post(page("kelishinlingan-yuborish", contract.pk))
        self.client.force_login(self.xarid_head)

        response = self.client.get(page("notifications"))

        self.assertContains(response, "Shartnoma tasdiqlashga yuborildi")
        self.assertContains(response, contract.shartnoma_raqami)
