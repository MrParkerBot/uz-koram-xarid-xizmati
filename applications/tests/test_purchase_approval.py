"""Tests for DEC-016's approval chain (TASK-UZK-031).

The order is the requirement, so most of this is about what cannot happen. An
application reaching Direktor without the requester's own department head is
the failure the chain exists to prevent, and a department head approving
another department's spending is the other one. Both are tested from the wrong
direction rather than only from the right one.

The end of the chain is the interesting part. Direktor approving is what
creates the department's own application - the moment DEC-016 describes, when
a request stops being one department asking and becomes work in the purchasing
department's queue. It is asserted through the Kelib tushgan Arizalar page
rather than through the record, because that page is what the decision is for.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils.crypto import get_random_string

from accounts.models import UserProfile, UserType
from accounts.roles import (
    ADMIN,
    BOLIM_BOSHLIGI,
    DIREKTOR,
    KATTA_MUTAXASIS,
    USERS,
    assign_user_type,
)
from applications.models import Application, PurchaseApplication
from applications.notifications import Notification
from applications.tests.test_support import a_pdf
from reference.models import ArizaStatus, Department, MahsulotTuri


def make_user(type_name: str, department: Department | None = None):
    user = get_user_model().objects.create_user(
        username=f"user.{get_random_string(8).lower()}",
        password=get_random_string(24),
        first_name="Test",
        last_name=type_name,
    )
    assign_user_type(user, UserType.objects.get(name=type_name))
    if department is not None:
        UserProfile.objects.filter(user=user).update(department=department)
    return user


class ApprovalTestCase(TestCase):
    """A request, its department's head, another department's, and Direktor."""

    def setUp(self) -> None:
        self.department = Department.objects.create(name="Texnik bolim")
        self.other_department = Department.objects.create(name="Logistika")
        self.category = MahsulotTuri.objects.create(
            category_number=100042, name="Metallurgiya"
        )
        self.requester = make_user(USERS, self.department)
        self.head = make_user(BOLIM_BOSHLIGI, self.department)
        self.other_head = make_user(BOLIM_BOSHLIGI, self.other_department)
        self.direktor = make_user(DIREKTOR, self.department)
        self.application = self.raise_request()

    def raise_request(self, lines: int = 1) -> PurchaseApplication:
        return PurchaseApplication.raise_purchase_application(
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
            shartnoma_nomi="Bolt yetkazib berish shartnomasi",
            izoh="Shoshilinch",
            pdf=a_pdf(),
            created_by=self.requester,
            status=ArizaStatus.objects.filter(
                code=ArizaStatus.Code.NEW
            ).first(),
        )

    def approve_as(self, user, application=None):
        self.client.force_login(user)
        return self.client.post(
            reverse(
                "xarid-ariza-tasdiqlash",
                args=[(application or self.application).pk],
            )
        )

    def reject_as(self, user, comment="Byudjet yo`q.", application=None):
        self.client.force_login(user)
        return self.client.post(
            reverse(
                "xarid-ariza-inkor",
                args=[(application or self.application).pk],
            ),
            {"inkor_izohi": comment},
        )

    def told(self) -> str:
        """What the page said after the last redirect, as one string."""
        page = self.client.get(reverse("xarid-ariza"))

        return " ".join(str(message) for message in page.context["messages"])

    def queue_of(self, user) -> str:
        self.client.force_login(user)
        page = self.client.get(reverse("xarid-ariza")).content.decode()
        if '<tbody id="xa-approvals-tbody">' not in page:
            return ""

        return page.split('<tbody id="xa-approvals-tbody">', 1)[1].split(
            "</tbody>", 1
        )[0]


class QueueTests(ApprovalTestCase):
    """Whose decision it is, at each step."""

    def test_a_new_request_waits_for_its_own_department_head(self) -> None:
        self.assertEqual(
            self.application.stage, PurchaseApplication.Stage.AWAITING_HEAD
        )
        self.assertIn(self.application.xarid_raqami, self.queue_of(self.head))

    def test_another_departments_head_does_not_see_it(self) -> None:
        # The failure the chain exists to prevent, in its second form: a
        # department head approving somebody else's spending.
        self.assertNotIn(
            self.application.xarid_raqami, self.queue_of(self.other_head)
        )

    def test_direktor_does_not_see_it_yet(self) -> None:
        self.assertNotIn(
            self.application.xarid_raqami, self.queue_of(self.direktor)
        )

    def test_the_requester_never_sees_a_queue(self) -> None:
        self.assertEqual(self.queue_of(self.requester), "")

    def test_somebody_with_neither_role_sees_no_queue(self) -> None:
        self.assertEqual(
            self.queue_of(make_user(KATTA_MUTAXASIS, self.department)), ""
        )

    def test_a_head_with_no_department_sees_nothing(self) -> None:
        self.assertEqual(self.queue_of(make_user(BOLIM_BOSHLIGI)), "")

    def test_after_the_head_approves_it_moves_to_direktor(self) -> None:
        self.approve_as(self.head)

        self.assertNotIn(
            self.application.xarid_raqami, self.queue_of(self.head)
        )
        self.assertIn(
            self.application.xarid_raqami, self.queue_of(self.direktor)
        )


class SequenceTests(ApprovalTestCase):
    """The order, which is the requirement."""

    def test_the_head_approving_moves_it_one_step(self) -> None:
        self.approve_as(self.head)

        self.application.refresh_from_db()
        self.assertEqual(
            self.application.stage,
            PurchaseApplication.Stage.AWAITING_DIREKTOR,
        )
        self.assertEqual(
            self.application.tasdiqlagan_bolim_boshligi, self.head
        )

    def test_direktor_cannot_approve_one_still_waiting_for_the_head(
        self,
    ) -> None:
        response = self.approve_as(self.direktor)

        self.application.refresh_from_db()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            self.application.stage, PurchaseApplication.Stage.AWAITING_HEAD
        )

    def test_the_head_cannot_approve_twice(self) -> None:
        # Not a Forbidden page. The #44 review found this answering 403: they
        # had the permission they needed and what changed is the record, which
        # is the distinction the #26 review settled for accept_application.
        self.approve_as(self.head)

        response = self.approve_as(self.head)

        self.application.refresh_from_db()
        self.assertRedirects(response, reverse("xarid-ariza"))
        self.assertEqual(
            self.application.stage,
            PurchaseApplication.Stage.AWAITING_DIREKTOR,
        )

    def test_a_colleague_clicking_a_stale_button_is_told_rather_than_denied(
        self,
    ) -> None:
        second_head = make_user(BOLIM_BOSHLIGI, self.department)
        self.approve_as(self.head)

        response = self.approve_as(second_head)

        # told() before anything else fetches the page: following the
        # redirect is what consumes the message.
        self.assertEqual(response.status_code, 302)
        self.assertIn("allaqachon", self.told())
        self.application.refresh_from_db()
        self.assertEqual(
            self.application.stage,
            PurchaseApplication.Stage.AWAITING_DIREKTOR,
        )

    def test_a_stale_rejection_is_told_rather_than_denied(self) -> None:
        second_head = make_user(BOLIM_BOSHLIGI, self.department)
        self.approve_as(self.head)

        response = self.reject_as(second_head)

        self.application.refresh_from_db()
        self.assertRedirects(response, reverse("xarid-ariza"))
        self.assertNotEqual(
            self.application.stage, PurchaseApplication.Stage.REJECTED
        )

    def test_somebody_who_could_never_decide_is_still_denied(self) -> None:
        # The distinction has to cut both ways, or it is just a weaker check.
        for who in (
            self.other_head,
            self.requester,
            make_user(KATTA_MUTAXASIS, self.department),
        ):
            with self.subTest(who=who.last_name):
                response = self.approve_as(who)

                self.assertEqual(response.status_code, 403)

    def test_another_departments_head_cannot_approve_it(self) -> None:
        response = self.approve_as(self.other_head)

        self.application.refresh_from_db()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            self.application.stage, PurchaseApplication.Stage.AWAITING_HEAD
        )

    def test_a_requester_cannot_approve_their_own_request(self) -> None:
        response = self.approve_as(self.requester)

        self.application.refresh_from_db()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            self.application.stage, PurchaseApplication.Stage.AWAITING_HEAD
        )

    def test_get_is_refused(self) -> None:
        self.client.force_login(self.head)

        self.assertEqual(
            self.client.get(
                reverse("xarid-ariza-tasdiqlash", args=[self.application.pk])
            ).status_code,
            405,
        )


class FinalApprovalTests(ApprovalTestCase):
    """What Direktor's approval creates - the DEC-016 moment."""

    def approve_fully(self) -> None:
        self.approve_as(self.head)
        self.approve_as(self.direktor)
        self.application.refresh_from_db()

    def test_it_is_approved(self) -> None:
        self.approve_fully()

        self.assertEqual(
            self.application.stage, PurchaseApplication.Stage.APPROVED
        )
        self.assertEqual(self.application.tasdiqlagan_direktor, self.direktor)

    def test_it_creates_the_departments_application(self) -> None:
        self.approve_fully()

        raised = self.application.raised_application
        self.assertIsNotNone(raised)
        self.assertEqual(raised.stage, Application.Stage.INCOMING)
        self.assertEqual(raised.department, self.department)
        self.assertEqual(raised.sender, self.requester)
        self.assertEqual(raised.izoh, "Shoshilinch")

    def test_the_lines_are_carried_across(self) -> None:
        self.application = self.raise_request(lines=3)
        self.approve_fully()

        self.assertEqual(
            [
                line.buyurtma_nomi
                for line in self.application.raised_application.items.all()
            ],
            ["Bolt M1", "Bolt M2", "Bolt M3"],
        )

    def test_it_appears_on_kelib_tushgan_arizalar(self) -> None:
        # The point of the whole chain, asserted through the page the
        # decision is for rather than through the record.
        self.approve_fully()
        self.client.force_login(make_user(ADMIN, self.department))

        page = self.client.get(reverse("kelib-arizalar")).content.decode()

        self.assertIn(
            self.application.raised_application.ariza_raqami, page
        )

    def test_nothing_is_created_before_the_final_approval(self) -> None:
        self.approve_as(self.head)

        self.assertFalse(Application.objects.exists())

    def test_it_leaves_every_queue(self) -> None:
        self.approve_fully()

        self.assertEqual(self.queue_of(self.direktor), "")
        self.assertNotIn(
            self.application.xarid_raqami, self.queue_of(self.head)
        )


class RejectionTests(ApprovalTestCase):
    """REQ-ARIZA-020: refused, with a reason, and the requester is told."""

    def test_the_head_can_refuse_it(self) -> None:
        self.reject_as(self.head)

        self.application.refresh_from_db()
        self.assertEqual(
            self.application.stage, PurchaseApplication.Stage.REJECTED
        )
        self.assertEqual(self.application.inkor_izohi, "Byudjet yo`q.")
        self.assertEqual(self.application.inkor_qilgan, self.head)

    def test_direktor_can_refuse_it_at_the_second_step(self) -> None:
        self.approve_as(self.head)

        self.reject_as(self.direktor, comment="Narx juda baland.")

        self.application.refresh_from_db()
        self.assertEqual(
            self.application.stage, PurchaseApplication.Stage.REJECTED
        )
        self.assertEqual(self.application.inkor_qilgan, self.direktor)

    def test_refusing_cancels_it(self) -> None:
        self.reject_as(self.head)

        self.application.refresh_from_db()
        self.assertEqual(
            self.application.status.code, ArizaStatus.Code.CANCELLED
        )

    def test_the_requester_is_notified(self) -> None:
        self.reject_as(self.head)

        notification = Notification.objects.get()
        self.assertEqual(notification.recipient, self.requester)
        self.assertEqual(
            notification.purchase_application, self.application
        )
        self.assertEqual(
            notification.kind, Notification.Kind.PURCHASE_REJECTED
        )

    def test_an_empty_comment_is_refused(self) -> None:
        self.reject_as(self.head, comment="")

        self.application.refresh_from_db()
        self.assertEqual(
            self.application.stage, PurchaseApplication.Stage.AWAITING_HEAD
        )
        self.assertFalse(Notification.objects.exists())

    def test_a_whitespace_comment_is_refused(self) -> None:
        self.reject_as(self.head, comment="   ")

        self.application.refresh_from_db()
        self.assertEqual(
            self.application.stage, PurchaseApplication.Stage.AWAITING_HEAD
        )

    def test_a_refused_request_creates_no_department_application(
        self,
    ) -> None:
        self.reject_as(self.head)

        self.assertFalse(Application.objects.exists())

    def test_it_leaves_the_queue(self) -> None:
        self.reject_as(self.head)

        self.assertNotIn(
            self.application.xarid_raqami, self.queue_of(self.head)
        )

    def test_another_departments_head_cannot_refuse_it(self) -> None:
        response = self.reject_as(self.other_head)

        self.application.refresh_from_db()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            self.application.stage, PurchaseApplication.Stage.AWAITING_HEAD
        )

    def test_get_is_refused(self) -> None:
        self.client.force_login(self.head)

        self.assertEqual(
            self.client.get(
                reverse("xarid-ariza-inkor", args=[self.application.pk])
            ).status_code,
            405,
        )
