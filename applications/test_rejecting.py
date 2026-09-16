"""Tests for rejecting an incoming application (TASK-UZK-024).

The comment is the requirement, not a decoration on it. REQ-ARIZA-005 exists
so that the sender is told why, so a rejection carrying no reason is not a
rejection this application performs - and the refusal has to leave the record
exactly as it was, because a half-applied rejection is worse than none.

The other weight is where the reason is enforced. The textarea is marked
required, which a browser honours and a POST does not have to, so the model
refuses it too and there is a test that posts around the form.
"""

from __future__ import annotations

import re

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils.crypto import get_random_string

from accounts.models import UserType
from accounts.roles import ADMIN, MENEJER, USERS, assign_user_type
from applications.models import Application
from reference.models import ArizaStatus, Department, MahsulotTuri

REASON = "Byudjet ajratilmagan."


def make_user(type_name: str = ADMIN):
    user = get_user_model().objects.create_user(
        username=f"user.{get_random_string(8).lower()}",
        password=get_random_string(24),
        first_name="Test",
        last_name=type_name,
    )
    assign_user_type(user, UserType.objects.get(name=type_name))
    return user


class RejectionTestCase(TestCase):
    """One incoming application and somebody who may decide it."""

    def setUp(self) -> None:
        self.decider = make_user(ADMIN)
        self.client.force_login(self.decider)
        self.application = Application.raise_application(
            department=Department.objects.create(name="Texnik bolim"),
            mahsulot_turi=MahsulotTuri.objects.create(
                category_number=100042, name="Metallurgiya"
            ),
            buyurtma_nomi="Bolt M12",
            buyurtma_soni=500,
            olchov_birligi="ta",
        )
        self.url = reverse("ariza-inkor", args=[self.application.pk])

    def reject(self, comment: str = REASON):
        return self.client.post(self.url, {"inkor_izohi": comment})

    def reload(self) -> Application:
        self.application.refresh_from_db()
        return self.application

    def table(self) -> str:
        """The rows of the incoming list, without the page around them."""
        page = self.client.get(reverse("kelib-arizalar")).content.decode()
        body = page.split('<tbody id="ariza-tbody">', 1)[1]

        return body.split("</tbody>", 1)[0]


class CommentIsRequiredTests(RejectionTestCase):
    """Without a reason there is no rejection, and nothing changes."""

    def test_rejecting_with_no_comment_is_refused(self) -> None:
        self.reject(comment="")

        self.assertEqual(self.reload().stage, Application.Stage.INCOMING)

    def test_a_comment_of_only_whitespace_is_no_comment(self) -> None:
        self.reject(comment="   \n\t ")

        self.assertEqual(self.reload().stage, Application.Stage.INCOMING)

    def test_a_missing_field_is_refused_rather_than_crashing(self) -> None:
        # A browser honours the required attribute. A POST need not.
        response = self.client.post(self.url, {})

        self.assertRedirects(response, reverse("kelib-arizalar"))
        self.assertEqual(self.reload().stage, Application.Stage.INCOMING)

    def test_a_refused_rejection_stores_nothing(self) -> None:
        self.reject(comment="")
        refused = self.reload()

        self.assertEqual(refused.inkor_izohi, "")
        self.assertIsNone(refused.inkor_qilingan_sana)
        self.assertIsNone(refused.rejected_by)

    def test_a_refused_rejection_leaves_it_on_the_list(self) -> None:
        self.reject(comment="")

        self.assertIn(self.application.ariza_raqami, self.table())

    def test_the_page_says_why_it_was_refused(self) -> None:
        page = self.client.post(
            self.url, {"inkor_izohi": ""}, follow=True
        ).content.decode()

        self.assertIn("izoh kiritilishi shart", page)

    def test_the_model_refuses_it_too(self) -> None:
        with self.assertRaises(ValueError):
            self.application.reject(by=self.decider, comment="  ")


class RejectionTests(RejectionTestCase):
    """A rejection with a reason cancels the application and records it."""

    def test_rejecting_moves_it_to_the_rejected_stage(self) -> None:
        self.reject()

        self.assertEqual(self.reload().stage, Application.Stage.REJECTED)

    def test_the_comment_is_stored(self) -> None:
        self.reject()

        self.assertEqual(self.reload().inkor_izohi, REASON)

    def test_the_comment_is_stored_without_its_surrounding_whitespace(self):
        self.reject(comment=f"\n  {REASON}  \n")

        self.assertEqual(self.reload().inkor_izohi, REASON)

    def test_rejecting_stamps_the_date_and_records_who_decided(self) -> None:
        self.reject()
        rejected = self.reload()

        self.assertIsNotNone(rejected.inkor_qilingan_sana)
        self.assertEqual(rejected.rejected_by, self.decider)

    def test_a_rejected_application_leaves_the_incoming_list(self) -> None:
        self.reject()

        self.assertNotIn(self.application.ariza_raqami, self.table())

    def test_rejecting_redirects_back_to_the_page(self) -> None:
        self.assertRedirects(self.reject(), reverse("kelib-arizalar"))

    def test_the_page_says_it_was_rejected(self) -> None:
        page = self.client.post(
            self.url, {"inkor_izohi": REASON}, follow=True
        ).content.decode()

        self.assertIn(f"{self.application.ariza_raqami} inkor etildi.", page)


class StatusTests(RejectionTestCase):
    """The cancelled status is found by code, and its absence blocks nothing."""

    def test_rejecting_attaches_the_cancelled_status(self) -> None:
        self.reject()

        self.assertEqual(
            self.reload().status.code, ArizaStatus.Code.CANCELLED
        )

    def test_the_status_is_found_after_it_has_been_renamed(self) -> None:
        cancelled = ArizaStatus.objects.get(code=ArizaStatus.Code.CANCELLED)
        cancelled.name = "Rad etildi"
        cancelled.save(update_fields=["name"])

        self.reject()

        self.assertEqual(self.reload().status, cancelled)

    def test_the_application_is_still_rejected_with_no_status_at_all(self):
        # A master data page must not be able to stop the workflow.
        ArizaStatus.objects.update(is_active=False)

        self.reject()

        self.assertEqual(self.reload().stage, Application.Stage.REJECTED)
        self.assertIsNone(self.reload().status)


class RejectingTwiceTests(RejectionTestCase):
    """The second click of a double click is not an error."""

    def test_the_second_rejection_leaves_the_first_decision_alone(self) -> None:
        self.reject()
        first = self.reload()

        self.client.force_login(make_user(MENEJER))
        self.reject(comment="Boshqa sabab.")

        again = self.reload()
        self.assertEqual(again.inkor_izohi, first.inkor_izohi)
        self.assertEqual(again.inkor_qilingan_sana, first.inkor_qilingan_sana)
        self.assertEqual(again.rejected_by, first.rejected_by)

    def test_the_second_rejection_is_not_an_error(self) -> None:
        self.reject()

        self.assertRedirects(self.reject(), reverse("kelib-arizalar"))

    def test_reject_returns_whether_it_did_anything(self) -> None:
        self.assertTrue(self.application.reject(self.decider, REASON))
        self.assertFalse(self.application.reject(self.decider, REASON))

    def test_rejecting_an_accepted_application_is_refused(self) -> None:
        self.application.accept(by=self.decider)

        with self.assertRaises(ValueError):
            self.application.reject(by=self.decider, comment=REASON)

    def test_a_stale_page_is_told_what_happened_rather_than_forbidden(self):
        # The #26 review settled this shape for accept, and reject follows it:
        # whoever clicks Inkor on a row a colleague accepted while the page
        # sat open had the permission they needed. What changed is the
        # application.
        self.application.accept(by=self.decider)

        page = self.client.post(
            self.url, {"inkor_izohi": REASON}, follow=True
        ).content.decode()

        self.assertIn("allaqachon hal qilingan", page)
        self.assertEqual(self.reload().stage, Application.Stage.ACCEPTED)


class ConcurrentRejectionTests(RejectionTestCase):
    """Two people deciding the same application at the same moment.

    reject() mirrors accept(), including the fix the #26 review produced: the
    stage comparison is part of the write, so the loser of a race cannot
    overwrite the winner's decision. The interleaving is reproduced by holding
    a stale instance across somebody else's decision, which is what a second
    request that loaded the row a moment earlier actually has.
    """

    def stale_copy(self) -> Application:
        return Application.objects.get(pk=self.application.pk)

    def test_only_one_of_two_simultaneous_callers_rejects_it(self) -> None:
        first, second = self.stale_copy(), self.stale_copy()

        self.assertTrue(first.reject(self.decider, REASON))
        self.assertFalse(second.reject(make_user(MENEJER), "Boshqa sabab."))

    def test_the_loser_does_not_overwrite_the_winners_reason(self) -> None:
        first, second = self.stale_copy(), self.stale_copy()

        first.reject(self.decider, REASON)
        second.reject(make_user(MENEJER), "Boshqa sabab.")

        settled = self.reload()
        self.assertEqual(settled.inkor_izohi, REASON)
        self.assertEqual(settled.rejected_by, self.decider)

    def test_the_loser_ends_up_holding_the_truth(self) -> None:
        first, second = self.stale_copy(), self.stale_copy()

        first.reject(self.decider, REASON)
        second.reject(make_user(MENEJER), "Boshqa sabab.")

        self.assertEqual(second.stage, Application.Stage.REJECTED)
        self.assertEqual(second.inkor_izohi, REASON)

    def test_a_stale_incoming_row_that_was_accepted_is_refused(self) -> None:
        stale = self.stale_copy()
        self.application.accept(by=self.decider)

        with self.assertRaises(ValueError):
            stale.reject(by=self.decider, comment=REASON)

        self.assertEqual(self.reload().stage, Application.Stage.ACCEPTED)

    def test_the_comment_is_still_required_before_anything_is_read(self):
        # The comment check comes before the row is re-read, so a rejection
        # with no reason costs no query and refuses whatever the stage is.
        self.application.accept(by=self.decider)

        with self.assertRaises(ValueError):
            self.application.reject(by=self.decider, comment="")


class AccessTests(RejectionTestCase):
    """The action answers to the page that offers it."""

    def test_the_route_refuses_a_get(self) -> None:
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 405)
        self.assertEqual(self.reload().stage, Application.Stage.INCOMING)

    def test_somebody_who_may_not_open_the_page_may_not_reject(self) -> None:
        self.client.force_login(make_user(USERS))

        self.assertEqual(self.reject().status_code, 403)
        self.assertEqual(self.reload().stage, Application.Stage.INCOMING)

    def test_an_anonymous_visitor_is_redirected(self) -> None:
        self.client.logout()

        self.assertEqual(self.reject().status_code, 302)
        self.assertEqual(self.reload().stage, Application.Stage.INCOMING)


class CommentWindowTests(RejectionTestCase):
    """REQ-ARIZA-005 asks for a window, and it is on the page."""

    def page(self) -> str:
        return self.client.get(reverse("kelib-arizalar")).content.decode()

    def test_the_page_carries_the_comment_window(self) -> None:
        page = self.page()

        self.assertIn('id="reject-modal"', page)
        self.assertIn('name="inkor_izohi"', page)

    def test_the_comment_is_required_in_the_browser_as_well(self) -> None:
        # Matched on the element rather than on a fixed run of attributes, so
        # that adding a placeholder to the textarea does not fail this.
        textarea = re.search(
            r"<textarea[^>]*\bname=\"inkor_izohi\"[^>]*>", self.page()
        )

        self.assertIsNotNone(textarea)
        self.assertIn("required", textarea.group())

    def test_the_row_carries_its_own_reject_url(self) -> None:
        self.assertIn(f'data-reject-url="{self.url}"', self.page())


class RejectedAttachmentTests(RejectionTestCase):
    """A rejected application is off every page, and so is its PDF.

    Nothing in the specification lists rejected applications, so there is no
    page to ask about one, and applications.views.PAGE_SHOWING_STAGE has no
    entry for the stage. This test records that as the current answer rather
    than leaving it to be discovered: whichever task adds a rejected list has
    to change this deliberately.
    """

    def test_a_rejected_applications_pdf_is_reachable_by_nobody(self) -> None:
        self.reject()

        response = self.client.get(
            reverse("ariza-pdf", args=[self.application.pk])
        )

        self.assertEqual(response.status_code, 403)
