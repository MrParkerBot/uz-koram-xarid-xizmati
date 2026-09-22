"""Qabul, Inkor and Bekor Qilish on Tuzilgan (TASK-UZK-067).

The decision widens from Admin to Xarid Bo`limi's own Bo`lim Boshlig`i and
Menejer, both ways of deciding tell whoever the contract belongs to, and an
approval can be taken back. Everybody else on the page reads the same three
states as a status.
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
)
from xarid.models import (
    ADMIN,
    BOLIM_BOSHLIGI,
    DIREKTOR,
    KATTA_MUTAXASIS,
    MENEJER,
    Contract,
    Notification,
)
from xarid.permissions import decides_on_contracts


class ADepartmentThatDecides(SignedInAdminTestCase):
    """A staffed purchasing department, and a contract awaiting a decision."""

    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        cls.purchasing = a_department("Xarid bo`limi")
        cls.purchasing.is_purchasing = True
        cls.purchasing.save(update_fields=["is_purchasing"])
        cls.head = make_user(
            "dec.head", user_type=BOLIM_BOSHLIGI, department=cls.purchasing
        )
        cls.menejer = make_user(
            "dec.menejer", user_type=MENEJER, department=cls.purchasing
        )
        cls.specialist = make_user(
            "dec.specialist", user_type=KATTA_MUTAXASIS, department=cls.purchasing
        )

    def a_sent_contract(self, entered_by=None) -> Contract:
        contract = a_contract(
            an_assigned_application(self.admin, self.specialist),
            entered_by or self.specialist,
        )
        contract.send_for_approval(by=self.specialist)
        return contract

    def told(self, contract: Contract, kind: str):
        return [
            note.recipient
            for note in Notification.objects.filter(
                kind=kind, application=contract.application
            )
        ]


class WhoDecidesTests(ADepartmentThatDecides):
    """The rule itself."""

    def test_the_departments_head_and_menejer_decide(self) -> None:
        for person in (self.head, self.menejer):
            with self.subTest(user=person.get_username()):
                self.assertTrue(decides_on_contracts(person))

    def test_an_admin_still_does(self) -> None:
        self.assertTrue(decides_on_contracts(self.admin))

    def test_the_specialist_who_sent_it_does_not(self) -> None:
        self.assertFalse(decides_on_contracts(self.specialist))

    def test_the_same_roles_in_another_department_do_not(self) -> None:
        elsewhere = a_department("Buxgalteriya")
        for user_type in (BOLIM_BOSHLIGI, MENEJER):
            with self.subTest(user_type=user_type):
                outsider = make_user(
                    f"dec.out.{user_type[:6]}", user_type=user_type, department=elsewhere
                )

                self.assertFalse(decides_on_contracts(outsider))

    def test_a_direktor_does_not(self) -> None:
        self.assertFalse(decides_on_contracts(make_user("dec.dir", user_type=DIREKTOR)))

    def test_while_no_department_is_named_the_decision_stays_with_admin(self) -> None:
        """This one falls closed where the arrived queue falls open.

        A queue opening to everybody who may see it costs a muddle; the
        approval opening to them commits the company.
        """
        self.purchasing.is_purchasing = False
        self.purchasing.save(update_fields=["is_purchasing"])

        self.assertFalse(decides_on_contracts(self.menejer))
        self.assertTrue(decides_on_contracts(self.admin))


class TheButtonsTests(ADepartmentThatDecides):
    """What the Amallar column draws, for whom."""

    def test_a_menejer_is_offered_qabul_and_inkor(self) -> None:
        contract = self.a_sent_contract()
        self.client.force_login(self.menejer)

        response = self.client.get(page("tuzilgan"))

        self.assertContains(response, page("tuzilgan-tasdiqlash", contract.pk))
        self.assertContains(response, page("tuzilgan-inkor", contract.pk))
        self.assertContains(response, "Qabul")
        self.assertContains(response, "Inkor")

    def test_the_head_is_offered_them_too(self) -> None:
        contract = self.a_sent_contract()
        self.client.force_login(self.head)

        response = self.client.get(page("tuzilgan"))

        self.assertContains(response, page("tuzilgan-tasdiqlash", contract.pk))

    def test_the_specialist_is_offered_a_status_instead(self) -> None:
        contract = self.a_sent_contract()
        self.client.force_login(self.specialist)

        response = self.client.get(page("tuzilgan"))

        self.assertNotContains(response, page("tuzilgan-tasdiqlash", contract.pk))
        self.assertContains(response, "Tasdiqlash kutilmoqda")

    def test_the_specialist_reads_the_decision_and_who_made_it(self) -> None:
        contract = self.a_sent_contract()
        contract.accept(by=self.menejer)
        self.client.force_login(self.specialist)

        response = self.client.get(page("tuzilgan"))

        self.assertContains(response, "Tasdiqlangan")
        self.assertContains(response, self.menejer.get_username())
        # Theirs to read, not to undo.
        self.assertNotContains(response, page("tuzilgan-bekor", contract.pk))


class QabulTells(ADepartmentThatDecides):
    """Approving tells whoever the contract belongs to."""

    def test_the_holder_is_told(self) -> None:
        contract = self.a_sent_contract()
        self.client.force_login(self.menejer)

        self.client.post(page("tuzilgan-tasdiqlash", contract.pk))

        self.assertCountEqual(
            self.told(contract, Notification.Kind.CONTRACT_APPROVED), [self.specialist]
        )

    def test_both_holders_are_told_when_they_differ(self) -> None:
        contract = self.a_sent_contract(entered_by=self.head)
        self.client.force_login(self.menejer)

        self.client.post(page("tuzilgan-tasdiqlash", contract.pk))

        self.assertCountEqual(
            self.told(contract, Notification.Kind.CONTRACT_APPROVED),
            [self.specialist, self.head],
        )

    def test_a_decider_who_is_also_a_holder_is_not_told(self) -> None:
        contract = self.a_sent_contract(entered_by=self.menejer)
        self.client.force_login(self.menejer)

        self.client.post(page("tuzilgan-tasdiqlash", contract.pk))

        self.assertCountEqual(
            self.told(contract, Notification.Kind.CONTRACT_APPROVED), [self.specialist]
        )

    def test_a_refused_approval_tells_nobody(self) -> None:
        contract = self.a_sent_contract()
        contract.accept(by=self.admin)
        Notification.objects.all().delete()
        self.client.force_login(self.menejer)

        self.client.post(page("tuzilgan-tasdiqlash", contract.pk))

        self.assertFalse(
            self.told(contract, Notification.Kind.CONTRACT_APPROVED)
        )

    def test_it_reaches_the_panel(self) -> None:
        contract = self.a_sent_contract()
        self.client.force_login(self.menejer)
        self.client.post(page("tuzilgan-tasdiqlash", contract.pk))
        self.client.force_login(self.specialist)

        response = self.client.get(page("notifications"))

        self.assertContains(response, "Shartnomangiz tasdiqlandi")


class InkorTells(ADepartmentThatDecides):
    """Rejecting sends it back with its reason, and says so."""

    def reject(self, contract: Contract, comment: str = "Narxi baland."):
        return self.client.post(
            page("tuzilgan-inkor", contract.pk), {"izoh": comment}, follow=True
        )

    def test_it_goes_back_to_the_holders_page(self) -> None:
        contract = self.a_sent_contract()
        self.client.force_login(self.menejer)

        self.reject(contract)

        contract.refresh_from_db()
        self.assertEqual(contract.stage, Contract.Stage.REJECTED)
        self.client.force_login(self.specialist)
        self.assertContains(
            self.client.get(page("kelishinlingan")), contract.shartnoma_raqami
        )

    def test_it_leaves_the_deciders_list(self) -> None:
        contract = self.a_sent_contract()
        self.client.force_login(self.menejer)

        self.reject(contract)

        response = self.client.get(page("tuzilgan"))
        self.assertNotContains(response, page("tuzilgan-tasdiqlash", contract.pk))

    def test_the_holder_is_told_with_the_reason(self) -> None:
        contract = self.a_sent_contract()
        self.client.force_login(self.menejer)

        self.reject(contract, "Muddat juda uzoq.")

        note = Notification.objects.get(kind=Notification.Kind.CONTRACT_RETURNED)
        self.assertEqual(note.recipient, self.specialist)
        self.assertIn("Muddat juda uzoq.", note.izoh)

    def test_the_comment_is_on_the_holders_page(self) -> None:
        contract = self.a_sent_contract()
        self.client.force_login(self.menejer)

        self.reject(contract, "Muddat juda uzoq.")

        self.client.force_login(self.specialist)
        self.assertContains(self.client.get(page("kelishinlingan")), "Muddat juda uzoq.")


class BekorQilishTests(ADepartmentThatDecides):
    """Taking an approval back."""

    def an_approved_contract(self) -> Contract:
        contract = self.a_sent_contract()
        contract.accept(by=self.menejer)
        return contract

    def test_the_button_is_offered_beside_the_badge(self) -> None:
        contract = self.an_approved_contract()
        self.client.force_login(self.menejer)

        response = self.client.get(page("tuzilgan"))

        self.assertContains(response, "Tasdiqlangan")
        self.assertContains(response, page("tuzilgan-bekor", contract.pk))
        self.assertContains(response, "Bekor Qilish")

    def test_it_leaves_the_contract_awaiting_a_decision(self) -> None:
        contract = self.an_approved_contract()
        self.client.force_login(self.head)

        self.client.post(page("tuzilgan-bekor", contract.pk))

        contract.refresh_from_db()
        self.assertEqual(contract.stage, Contract.Stage.SENT)
        self.assertIsNone(contract.tasdiqlagan)
        self.assertIsNone(contract.tasdiqlangan_sana)

    def test_the_contract_can_then_be_decided_again(self) -> None:
        contract = self.an_approved_contract()
        self.client.force_login(self.head)
        self.client.post(page("tuzilgan-bekor", contract.pk))

        response = self.client.get(page("tuzilgan"))

        self.assertContains(response, page("tuzilgan-tasdiqlash", contract.pk))
        self.assertContains(response, page("tuzilgan-inkor", contract.pk))

    def test_the_send_is_not_undone_with_it(self) -> None:
        """Sending is the specialist's act, not the approver's."""
        contract = self.an_approved_contract()
        was_sent_at = contract.yuborilgan_sana
        self.client.force_login(self.head)

        self.client.post(page("tuzilgan-bekor", contract.pk))

        contract.refresh_from_db()
        self.assertEqual(contract.yuborilgan_sana, was_sent_at)
        self.assertEqual(contract.yuborishlar_soni, 1)

    def test_the_holders_are_told_the_approval_no_longer_stands(self) -> None:
        contract = self.an_approved_contract()
        self.client.force_login(self.head)

        self.client.post(page("tuzilgan-bekor", contract.pk))

        self.assertCountEqual(
            self.told(contract, Notification.Kind.CONTRACT_APPROVAL_UNDONE),
            [self.specialist],
        )

    def test_a_contract_that_was_not_approved_is_a_message(self) -> None:
        contract = self.a_sent_contract()
        self.client.force_login(self.menejer)

        response = self.client.post(page("tuzilgan-bekor", contract.pk), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "tasdiqlanmagan edi")

    def test_somebody_who_may_not_decide_may_not_undo(self) -> None:
        contract = self.an_approved_contract()
        self.client.force_login(self.specialist)

        response = self.client.post(page("tuzilgan-bekor", contract.pk))

        self.assertEqual(response.status_code, 403)
        contract.refresh_from_db()
        self.assertEqual(contract.stage, Contract.Stage.SIGNED)

    def test_the_action_refuses_a_get(self) -> None:
        contract = self.an_approved_contract()
        self.client.force_login(self.menejer)

        response = self.client.get(page("tuzilgan-bekor", contract.pk))

        self.assertEqual(response.status_code, 405)


class TheLogTests(ADepartmentThatDecides):
    """The decisions reach the log whoever made them."""

    def test_an_approval_by_a_menejer_is_recorded(self) -> None:
        from xarid.audit import decisions_for

        contract = self.a_sent_contract()
        self.client.force_login(self.menejer)

        self.client.post(page("tuzilgan-tasdiqlash", contract.pk))

        decision = decisions_for([contract])[contract.pk][0]
        self.assertEqual(decision.by, self.menejer)
        self.assertTrue(decision.approved)
