"""The Izoh drawer on Kelishinlingan and the thread behind it (TASK-UZK-066).

Three kinds of written text in one list, oldest first: the note typed on
the contract form, the reason each decision carried, and the comments
people add. Adding one tells the contract's holders and everybody already
in the conversation.
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
    BOLIM_BOSHLIGI,
    KATTA_MUTAXASIS,
    MENEJER,
    Contract,
    ContractComment,
    Notification,
)


def comment_action(contract: Contract) -> str:
    return page("shartnoma-izoh", contract.pk)


class TheIconTests(SignedInAdminTestCase):
    """What the Izoh column shows before anything is opened."""

    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        cls.specialist = make_user("izoh.specialist", user_type=KATTA_MUTAXASIS)

    def a_contract_with_a_thread(self, izoh: str = "") -> Contract:
        return a_contract(
            an_assigned_application(self.admin, self.specialist),
            self.specialist,
            izoh=izoh,
        )

    def test_the_column_offers_the_icon_and_its_drawer(self) -> None:
        contract = self.a_contract_with_a_thread()

        response = self.client.get(page("kelishinlingan"))

        self.assertContains(response, f'data-open-drawer="sht-izoh-{contract.pk}"')
        self.assertContains(response, f'id="sht-izoh-{contract.pk}-overlay"')

    def test_the_icon_counts_what_there_is_to_read(self) -> None:
        contract = self.a_contract_with_a_thread(izoh="Narx kelishildi.")
        ContractComment.objects.create(
            contract=contract, author=self.admin, matn="Muddatni tekshiring."
        )

        response = self.client.get(page("kelishinlingan"))

        # The entry note and the comment.
        self.assertContains(response, '<span class="comment-count">2</span>')

    def test_a_contract_nobody_has_written_about_carries_no_count(self) -> None:
        self.a_contract_with_a_thread()

        response = self.client.get(page("kelishinlingan"))

        self.assertNotContains(response, "comment-count")
        self.assertContains(response, "hali izoh yo'q")

    def test_the_reason_is_behind_the_icon_and_not_in_the_column(self) -> None:
        """The icon replaced the column's text rather than joining it.

        Everything written about a contract is in the drawer, so a cell
        that also printed the last rejection would be the same sentence
        twice - once cut to fit a column.
        """
        contract = self.a_contract_with_a_thread()
        contract.send_for_approval(by=self.specialist)
        self.client.post(page("tuzilgan-inkor", contract.pk), {"izoh": "Narxi baland."})

        response = self.client.get(page("kelishinlingan"))
        table = response.content.decode().split('id="kelish-tbody"')[1].split("</table>")[0]

        self.assertContains(response, "Narxi baland.")
        self.assertNotIn("Narxi baland.", table)


class TheThreadTests(SignedInAdminTestCase):
    """What the drawer lists, and in what order."""

    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        cls.specialist = make_user("thread.specialist", user_type=KATTA_MUTAXASIS)

    def a_contract_with_a_thread(self, izoh: str = "") -> Contract:
        return a_contract(
            an_assigned_application(self.admin, self.specialist),
            self.specialist,
            izoh=izoh,
        )

    def test_the_note_typed_on_the_form_is_the_first_entry(self) -> None:
        self.a_contract_with_a_thread(izoh="Yetkazib berish 30 kun.")

        response = self.client.get(page("kelishinlingan"))

        self.assertContains(response, "Yetkazib berish 30 kun.")
        self.assertContains(response, "Kiritdi")

    def test_a_rejection_carries_its_reason_and_who_gave_it(self) -> None:
        contract = self.a_contract_with_a_thread()
        contract.send_for_approval(by=self.specialist)
        self.client.post(
            page("tuzilgan-inkor", contract.pk), {"izoh": "Narxi bozordan baland."}
        )

        response = self.client.get(page("kelishinlingan"))

        self.assertContains(response, "Narxi bozordan baland.")
        self.assertContains(response, "Inkor etdi")
        self.assertContains(response, self.admin.get_full_name())

    def test_a_comment_appears_with_its_author_and_time(self) -> None:
        contract = self.a_contract_with_a_thread()
        ContractComment.objects.create(
            contract=contract, author=self.specialist, matn="Firma bilan gaplashdim."
        )

        response = self.client.get(page("kelishinlingan"))

        self.assertContains(response, "Firma bilan gaplashdim.")
        self.assertContains(response, self.specialist.get_username())
        self.assertContains(response, "comment-date")

    def panel_of(self, response, contract: Contract) -> str:
        """Just this contract's drawer, cut out of the page.

        The drawers follow one another in the table's order, which is newest
        first, so "everything after this id" is not one panel.
        """
        body = response.content.decode()
        after = body.split(f'id="sht-izoh-{contract.pk}-overlay"', 1)[1]

        return after.split('id="sht-izoh-', 1)[0]

    def test_the_thread_is_oldest_first(self) -> None:
        contract = self.a_contract_with_a_thread(izoh="Birinchi.")
        ContractComment.objects.create(
            contract=contract, author=self.admin, matn="Ikkinchi."
        )

        response = self.client.get(page("kelishinlingan"))
        body = response.content.decode()

        self.assertLess(body.index("Birinchi."), body.index("Ikkinchi."))

    def test_one_contract_s_comments_stay_on_that_contract(self) -> None:
        mine = self.a_contract_with_a_thread()
        theirs = self.a_contract_with_a_thread()
        ContractComment.objects.create(
            contract=mine, author=self.admin, matn="Faqat birinchisi haqida."
        )

        response = self.client.get(page("kelishinlingan"))

        self.assertNotIn("Faqat birinchisi haqida.", self.panel_of(response, theirs))
        self.assertIn("Faqat birinchisi haqida.", self.panel_of(response, mine))

    def test_the_page_costs_the_same_whatever_the_number_of_contracts(self) -> None:
        """Two queries for the whole thread, not two per row."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        first = self.a_contract_with_a_thread(izoh="Bir.")
        ContractComment.objects.create(contract=first, author=self.admin, matn="X")
        with CaptureQueriesContext(connection) as one:
            self.client.get(page("kelishinlingan"))

        for _ in range(4):
            more = self.a_contract_with_a_thread(izoh="Yana.")
            ContractComment.objects.create(contract=more, author=self.admin, matn="Y")
        with CaptureQueriesContext(connection) as five:
            self.client.get(page("kelishinlingan"))

        self.assertEqual(len(one), len(five))


class WritingOneTests(SignedInAdminTestCase):
    """Posting to the thread."""

    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        cls.specialist = make_user("write.specialist", user_type=KATTA_MUTAXASIS)

    def a_contract(self) -> Contract:
        return a_contract(
            an_assigned_application(self.admin, self.specialist), self.specialist
        )

    def test_a_comment_is_saved_against_its_author(self) -> None:
        contract = self.a_contract()

        self.client.post(comment_action(contract), {"matn": "Invoice kutilmoqda."})

        comment = ContractComment.objects.get()
        self.assertEqual(comment.contract, contract)
        self.assertEqual(comment.author, self.admin)
        self.assertEqual(comment.matn, "Invoice kutilmoqda.")

    def test_it_comes_back_with_that_drawer_open(self) -> None:
        """Writing a comment must not lose the reader's place in the table."""
        contract = self.a_contract()

        response = self.client.post(
            comment_action(contract), {"matn": "Shoshilinch."}, follow=True
        )

        self.assertContains(
            response, f'id="sht-izoh-{contract.pk}-overlay" class="drawer-overlay"'
        )

    def test_an_empty_comment_is_refused(self) -> None:
        contract = self.a_contract()

        response = self.client.post(comment_action(contract), {"matn": "   "}, follow=True)

        self.assertFalse(ContractComment.objects.exists())
        self.assertContains(response, "matn bo`sh")

    def test_the_text_is_escaped_rather_than_rendered(self) -> None:
        """A comment is text nobody has vetted."""
        contract = self.a_contract()
        self.client.post(comment_action(contract), {"matn": "<script>alert(1)</script>"})

        response = self.client.get(page("kelishinlingan"))

        self.assertNotContains(response, "<script>alert(1)</script>")
        self.assertContains(response, "&lt;script&gt;")

    def test_somebody_elses_contract_may_still_be_commented_on(self) -> None:
        """Commenting is not acting on the contract."""
        other = make_user("write.other", user_type=KATTA_MUTAXASIS)
        theirs = a_contract(an_assigned_application(self.admin, other), other)
        self.client.force_login(self.specialist)

        self.client.post(comment_action(theirs), {"matn": "Savol bor."})

        self.assertTrue(ContractComment.objects.filter(contract=theirs).exists())

    def test_the_action_refuses_a_get(self) -> None:
        contract = self.a_contract()

        response = self.client.get(comment_action(contract))

        self.assertEqual(response.status_code, 405)

    def test_a_type_that_may_not_open_the_page_may_not_write(self) -> None:
        contract = self.a_contract()
        self.client.force_login(make_user("write.outsider"))

        response = self.client.post(comment_action(contract), {"matn": "Yozaman."})

        self.assertEqual(response.status_code, 403)
        self.assertFalse(ContractComment.objects.exists())


class TellingTheThreadTests(SignedInAdminTestCase):
    """Who hears about a new comment."""

    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        cls.purchasing = a_department("Xarid bo`limi")
        cls.purchasing.is_purchasing = True
        cls.purchasing.save(update_fields=["is_purchasing"])
        cls.specialist = make_user(
            "tell.specialist", user_type=KATTA_MUTAXASIS, department=cls.purchasing
        )
        cls.menejer = make_user(
            "tell.menejer", user_type=MENEJER, department=cls.purchasing
        )
        cls.head = make_user(
            "tell.head", user_type=BOLIM_BOSHLIGI, department=cls.purchasing
        )

    def a_contract(self, entered_by=None) -> Contract:
        return a_contract(
            an_assigned_application(self.admin, self.specialist),
            entered_by or self.specialist,
        )

    def told(self, contract: Contract):
        return [
            note.recipient
            for note in Notification.objects.filter(
                kind=Notification.Kind.CONTRACT_COMMENTED,
                application=contract.application,
            )
        ]

    def test_the_holder_is_told(self) -> None:
        contract = self.a_contract()

        self.client.post(comment_action(contract), {"matn": "Savol."})

        self.assertCountEqual(self.told(contract), [self.specialist])

    def test_both_holders_are_told_when_they_differ(self) -> None:
        """Assigned to one person, entered by another: it is both of theirs."""
        contract = self.a_contract(entered_by=self.menejer)

        self.client.post(comment_action(contract), {"matn": "Savol."})

        self.assertCountEqual(self.told(contract), [self.specialist, self.menejer])

    def test_everybody_already_in_the_thread_is_told(self) -> None:
        contract = self.a_contract()
        self.client.force_login(self.head)
        self.client.post(comment_action(contract), {"matn": "Birinchi savol."})
        # What the first comment produced is not what this test is about,
        # and notifications come back newest first, so slicing would be
        # reading the wrong end of the list.
        Notification.objects.all().delete()
        self.client.force_login(self.menejer)

        self.client.post(comment_action(contract), {"matn": "Men ham."})

        self.assertCountEqual(self.told(contract), [self.specialist, self.head])

    def test_the_author_is_never_told_of_their_own(self) -> None:
        contract = self.a_contract()
        self.client.force_login(self.specialist)

        self.client.post(comment_action(contract), {"matn": "O`zim yozdim."})

        self.assertEqual(self.told(contract), [])

    def test_nobody_is_told_twice(self) -> None:
        """A holder who has already written is one person, not two."""
        contract = self.a_contract()
        self.client.force_login(self.specialist)
        self.client.post(comment_action(contract), {"matn": "Birinchi."})
        self.client.force_login(self.admin)

        self.client.post(comment_action(contract), {"matn": "Javob."})

        self.assertEqual(self.told(contract), [self.specialist])

    def test_the_notification_carries_what_was_said(self) -> None:
        contract = self.a_contract()

        self.client.post(comment_action(contract), {"matn": "Invoice qachon?"})

        note = Notification.objects.get(kind=Notification.Kind.CONTRACT_COMMENTED)
        self.assertIn(contract.shartnoma_raqami, note.izoh)
        self.assertIn("Invoice qachon?", note.izoh)

    def test_it_reaches_the_panel(self) -> None:
        contract = self.a_contract()
        self.client.post(comment_action(contract), {"matn": "Ko`rib chiqing."})
        self.client.force_login(self.specialist)

        response = self.client.get(page("notifications"))

        self.assertContains(response, "Shartnoma bo`yicha yangi izoh")
        self.assertContains(response, "Ko`rib chiqing.")
