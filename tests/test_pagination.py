"""Every table is read a page at a time, and the reader says how long a page is.

The bar under a table carries two controls and one figure: the pages, the row
count and the total. What is tested here is that the three agree with each
other and with the table above them - that the count applies, that the total
counts the whole table rather than the page, and that paging a table somebody
narrowed does not quietly widen it again.

The pages render through Jinja2, so response.context carries nothing and the
rendered markup is what a test reads, as the rest of this suite reads it.
"""

from __future__ import annotations

import re

from django.test import SimpleTestCase, TestCase

from tests.support import (
    SignedInAdminTestCase,
    TemporaryAttachmentsMixin,
    a_contract,
    a_department,
    a_purchase_application,
    an_accepted_application,
    an_application,
    an_arrived_purchase_request,
    an_assigned_application,
    make_user,
    page,
)
from xarid.models import (
    ADMIN,
    BOLIM_BOSHLIGI,
    KATTA_MUTAXASIS,
    USERS,
    ArizaStatus,
    Department,
    Notification,
    UserSpecialty,
)
from xarid.audit import record_created
from xarid.pagination import DEFAULT_PER_PAGE, PER_PAGE_CHOICES, TablePage

TOTAL = 'Jami: <span class="count">{}</span> ta'


def records_drawn(response) -> int:
    """How many records a table drew.

    Every list row opens with data-id. A grouped table repeats it once per
    goods line, so it is the distinct ids that are the records - which is
    what a page holds a page of.
    """
    return len(set(re.findall(r'<tr data-id="(\d+)"', response.content.decode())))


class RowCountTests(SimpleTestCase):
    """The drop-down's five numbers, and what anything else means."""

    def test_it_offers_the_five_counts_the_specification_names(self) -> None:
        self.assertEqual(PER_PAGE_CHOICES, (15, 20, 30, 50, 100))

    def test_a_count_nobody_was_offered_is_the_default(self) -> None:
        """Including one that would be a denial of service if it were obeyed."""
        for asked in ("", "0", "-20", "17", "100000", "yigirma", None):
            with self.subTest(asked=asked):
                self.assertEqual(
                    TablePage(range(10), {"qatorlar": asked}).per_page, DEFAULT_PER_PAGE
                )

    def test_a_page_past_the_end_is_the_last_page(self) -> None:
        paged = TablePage(range(45), {"qatorlar": "15", "sahifa": "9"})

        self.assertEqual(paged.number, 3)
        self.assertEqual(list(paged.rows), list(range(30, 45)))

    def test_a_page_that_is_not_a_number_is_the_first(self) -> None:
        self.assertEqual(TablePage(range(45), {"sahifa": "oxirgi"}).number, 1)

    def test_the_numbers_are_elided_rather_than_printed_in_full(self) -> None:
        paged = TablePage(range(1000), {"qatorlar": "15"})

        self.assertLess(len(paged.numbers), 15)
        self.assertIn(paged.ellipsis, paged.numbers)
        self.assertEqual(paged.numbers[0], 1)

    def test_the_row_numbers_carry_on_from_page_to_page(self) -> None:
        self.assertEqual(TablePage(range(45), {"qatorlar": "15"}).start_index, 1)
        self.assertEqual(
            TablePage(range(45), {"qatorlar": "15", "sahifa": "3"}).start_index, 31
        )

    def test_the_first_page_of_an_unfiltered_table_is_the_tables_own_url(self) -> None:
        """So a reader paging back arrives where they started, not at ?sahifa=1."""
        paged = TablePage(range(45), {"qatorlar": "20"})

        self.assertEqual(paged.query_for(1), "")
        self.assertEqual(paged.query_for(2), "?sahifa=2")

    def test_every_link_carries_the_row_count_and_the_filters(self) -> None:
        paged = TablePage(range(45), {"qatorlar": "15", "sahifa": "2"}, kept={"holat": "3"})

        self.assertIn("holat=3", paged.query_for(3))
        self.assertIn("qatorlar=15", paged.query_for(3))
        self.assertIn("sahifa=3", paged.query_for(3))
        # The first page keeps them too: a filtered table's first page is not
        # the unfiltered table.
        self.assertIn("holat=3", paged.query_for(1))
        self.assertNotIn("sahifa", paged.query_for(1))

    def test_an_empty_table_draws_no_bar(self) -> None:
        self.assertFalse(TablePage([], {}).is_offered)
        self.assertTrue(TablePage([1], {}).is_offered)


class ListPageTests(SignedInAdminTestCase):
    """The bar as a page renders it, over rows the page really holds."""

    def test_a_table_shows_the_default_count_and_reports_the_whole_total(self) -> None:
        for _ in range(25):
            an_arrived_purchase_request()

        response = self.client.get(page("kelib-arizalar"))

        self.assertEqual(records_drawn(response), DEFAULT_PER_PAGE)
        self.assertContains(response, TOTAL.format(25))
        self.assertContains(response, "Keyingi")

    def test_the_chosen_count_is_what_the_page_holds(self) -> None:
        for _ in range(25):
            an_arrived_purchase_request()

        for asked, expected in ((15, 15), (30, 25), (100, 25)):
            with self.subTest(qatorlar=asked):
                response = self.client.get(page("kelib-arizalar"), {"qatorlar": asked})

                self.assertEqual(records_drawn(response), expected)
                self.assertContains(response, f'<option value="{asked}" selected>')

    def test_the_second_page_holds_what_the_first_one_left(self) -> None:
        for _ in range(25):
            an_arrived_purchase_request()

        first = self.client.get(page("kelib-arizalar"))
        second = self.client.get(page("kelib-arizalar"), {"sahifa": 2})

        on_the_first = set(re.findall(r'<tr data-id="(\d+)"', first.content.decode()))
        on_the_second = set(re.findall(r'<tr data-id="(\d+)"', second.content.decode()))
        self.assertEqual(len(on_the_second), 5)
        self.assertEqual(on_the_first & on_the_second, set())
        self.assertEqual(len(on_the_first | on_the_second), 25)

    def test_the_row_numbers_count_through_the_table(self) -> None:
        """Row 21 is row 21 on page two, not row 1 again."""
        for number in range(25):
            UserSpecialty.objects.create(name=f"Mutaxassislik {number}")

        first = self.client.get(page("user-specialty"))
        second = self.client.get(page("user-specialty"), {"sahifa": 2})

        self.assertContains(first, "<td>1</td>")
        self.assertContains(first, "<td>20</td>")
        self.assertContains(second, "<td>21</td>")
        self.assertContains(second, "<td>25</td>")
        self.assertNotContains(second, "<td>1</td>")

    def test_paging_a_narrowed_table_keeps_it_narrowed(self) -> None:
        moliya = Department.objects.create(name="Moliya bo`limi")
        for _ in range(22):
            an_arrived_purchase_request(department=a_department())
        for _ in range(3):
            an_arrived_purchase_request(department=moliya)

        narrowed = self.client.get(page("kelib-arizalar"), {"bolim": moliya.pk})

        self.assertEqual(records_drawn(narrowed), 3)
        self.assertContains(narrowed, TOTAL.format(3))
        # And the bar's own form carries it, so choosing a row count does not
        # widen a table the reader narrowed.
        self.assertContains(
            narrowed, f'<input type="hidden" name="bolim" value="{moliya.pk}"/>'
        )
        # Not the page number: fifty rows a page may have no page four.
        self.assertNotContains(narrowed, '<input type="hidden" name="sahifa"')

    def test_a_page_link_of_a_narrowed_table_carries_the_filter(self) -> None:
        moliya = Department.objects.create(name="Moliya bo`limi")
        for _ in range(25):
            an_arrived_purchase_request(department=moliya)

        narrowed = self.client.get(page("kelib-arizalar"), {"bolim": moliya.pk})

        self.assertContains(narrowed, f"bolim={moliya.pk}&amp;sahifa=2")

    def test_a_master_data_page_is_paged_like_any_other(self) -> None:
        for number in range(23):
            UserSpecialty.objects.create(name=f"Mutaxassislik {number}")

        response = self.client.get(page("user-specialty"), {"qatorlar": 15})

        self.assertEqual(records_drawn(response), 15)
        self.assertContains(response, TOTAL.format(23))

    def test_a_report_pages_its_rows_and_keeps_the_reports_totals(self) -> None:
        """The totals row is the report's, so it is the same on every page."""
        for number in range(22):
            specialist = make_user(f"spec{number}", user_type=KATTA_MUTAXASIS)
            an_assigned_application(self.admin, specialist)

        first = self.client.get(page("xodimlar-yuklamasi"), {"qatorlar": 15})
        second = self.client.get(page("xodimlar-yuklamasi"), {"qatorlar": 15, "sahifa": 2})

        self.assertEqual(first.content.decode().count('class="user-avatar"'), 15)
        self.assertEqual(second.content.decode().count('class="user-avatar"'), 7)
        # One assignment each, so the report's total is every specialist on
        # both pages rather than the fifteen or the seven being read.
        for response in (first, second):
            self.assertContains(response, '<tr class="total-row" data-jami="22">')

    def test_an_export_covers_the_whole_table_and_not_the_page(self) -> None:
        for _ in range(25):
            an_arrived_purchase_request()

        paged = self.client.get(page("kelib-arizalar"), {"qatorlar": 15})
        export = self.client.get(page("kelib-arizalar-eksport", "xlsx"), {"qatorlar": 15})

        self.assertEqual(records_drawn(paged), 15)
        self.assertEqual(export.status_code, 200)
        self.assertGreater(len(export.content), 0)


class EveryListPageDrawsTheBarTests(SignedInAdminTestCase):
    """The guard: a page added later without a bar fails here, not in use."""

    PAGES = (
        "kelib-arizalar",
        "qabul-arizalar",
        "tayinlangan",
        "kelishinlingan",
        "tuzilgan",
        "ochirilgan-shartnomalar",
        "xarid-ariza",
        "mahsulotlar",
        "xodimlar-yuklamasi",
        "bolimlar",
        "mahsulot-tur",
        "top-suppliers",
        "logs",
        "users",
        "notifications",
        "user-specialty",
        "user-types",
        "ariza-status",
        "shartnoma-status",
        "mahsulot-turlari",
        "shartnoma-turi",
        "bolim-royhati",
        "firmalar",
    )

    def test_every_list_page_draws_the_row_count_and_the_total(self) -> None:
        """Each of them holds a row already, from the seeds or from this.

        An empty table draws no bar by design, so a page with nothing on it
        would pass this test without drawing anything - which is why the row
        each page needs is made first.
        """
        specialist = make_user("spec", user_type=KATTA_MUTAXASIS)
        assigned = an_assigned_application(self.admin, specialist)
        an_arrived_purchase_request()
        UserSpecialty.objects.create(name="Metallurg")
        # A notification is about exactly one record, so it is given one.
        Notification.objects.create(
            recipient=self.admin,
            kind=Notification.Kind.APPLICATION_ACCEPTED,
            application=an_application(),
        )
        # A contract for the three contract pages and the supplier ranking,
        # one of them sent for a decision and one deleted.
        a_contract(assigned, self.admin)
        sent = a_contract(an_assigned_application(self.admin, specialist), self.admin)
        sent.send_for_approval(by=self.admin)
        a_contract(an_assigned_application(self.admin, specialist), self.admin).soft_delete(
            by=self.admin
        )
        # And one entry for the log, which only an action through a view writes.
        record_created(self.admin, assigned)

        for page_name in self.PAGES:
            with self.subTest(page=page_name):
                rendered = self.client.get(page(page_name)).content.decode()

                self.assertIn("Qatorlar:", rendered)
                self.assertIn("Jami:", rendered)
                self.assertIn('name="qatorlar"', rendered)
                for choice in PER_PAGE_CHOICES:
                    self.assertIn(f'<option value="{choice}"', rendered)


class ApprovalsPageTests(TemporaryAttachmentsMixin, TestCase):
    """Tasdiqlangan Arizalar: one page name that an admin never sees.

    A head outside the purchasing department reads their own approvals under
    this name, so the guard above - which signs in as an Admin - cannot reach
    the template. It is paged like the rest, and this is where that is said.
    """

    def test_a_heads_own_approvals_are_paged(self) -> None:
        purchasing = a_department("Xarid bo`limi")
        purchasing.is_purchasing = True
        purchasing.save(update_fields=["is_purchasing"])
        elsewhere = a_department("Ishlab chiqarish")
        head = make_user("own.head", user_type=BOLIM_BOSHLIGI, department=elsewhere)
        requester = make_user("own.requester", user_type=USERS, department=elsewhere)
        for _ in range(23):
            request = a_purchase_application(requester, elsewhere, with_pdf=False)
            request.approve(by=head)
        self.client.force_login(head)

        response = self.client.get(page("qabul-arizalar"), {"qatorlar": 15})

        self.assertContains(response, "Tasdiqlangan Arizalar")
        self.assertEqual(records_drawn(response), 15)
        self.assertContains(response, TOTAL.format(23))


class NotificationPagingTests(TestCase):
    """Marking read is about every notification, not the page being read."""

    def test_the_page_shows_one_page_and_marks_them_all_read(self) -> None:
        reader = make_user("reader", user_type=ADMIN)
        for number in range(25):
            Notification.objects.create(
                recipient=reader,
                kind=Notification.Kind.APPLICATION_ACCEPTED,
                application=an_application(),
                izoh=f"Xabar {number}",
            )
        self.client.force_login(reader)

        response = self.client.get(page("notifications"))

        self.assertEqual(response.content.decode().count("mini-list-item"), DEFAULT_PER_PAGE)
        self.assertContains(response, TOTAL.format(25))
        self.assertEqual(
            Notification.objects.filter(recipient=reader, read_at__isnull=True).count(), 0
        )


class StatusFilterAndPagingTests(SignedInAdminTestCase):
    """A paged table is still a filtered one (the Tayinlangan Holat column)."""

    def test_the_status_filter_and_the_row_count_hold_together(self) -> None:
        specialist = make_user("spec", user_type=KATTA_MUTAXASIS)
        accepted = ArizaStatus.objects.get(name="Qabul qilingan")
        for _ in range(18):
            an_assigned_application(self.admin, specialist)
        moved = an_assigned_application(self.admin, specialist)
        moved.set_status(accepted)

        response = self.client.get(page("tayinlangan"), {"holat": accepted.pk, "qatorlar": 15})

        self.assertEqual(records_drawn(response), 1)
        self.assertContains(response, TOTAL.format(1))
