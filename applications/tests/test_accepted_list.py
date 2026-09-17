"""Tests for the Qabul qilingan Arizalar list of TASK-UZK-025.

Two things carry the weight.

The first is that the page shows accepted applications and nothing else. It
decides that from the stage code, for the reason TASK-UZK-022 gave about the
incoming list: DEC-017 lets an administrator rename or delete any Ariza Status
row, and a list that reads a status name quietly empties the day somebody
does. There is a test that renames the accepted status and then loads the
page.

The second is the date. Qabul qilingan sana is when acceptance happened, not
when the application arrived, and the two are easy to confuse because both are
on the record. There is a test whose application has two different dates.
"""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import get_random_string

from accounts.models import UserType
from accounts.roles import (
    ADMIN,
    BOLIM_BOSHLIGI,
    DIREKTOR,
    MENEJER,
    USERS,
    assign_user_type,
)
from applications.models import Application
from reference.models import ArizaStatus, Department, MahsulotTuri


def make_user(type_name: str = ADMIN):
    user = get_user_model().objects.create_user(
        username=f"user.{get_random_string(8).lower()}",
        password=get_random_string(24),
        first_name="Test",
        last_name=type_name,
    )
    assign_user_type(user, UserType.objects.get(name=type_name))
    return user


class AcceptedListTestCase(TestCase):
    """Somebody permitted to see accepted applications."""

    def setUp(self) -> None:
        self.decider = make_user(ADMIN)
        self.client.force_login(self.decider)
        self.department = Department.objects.create(name="Texnik bolim")
        self.category = MahsulotTuri.objects.create(
            category_number=100042, name="Metallurgiya"
        )

    def raise_application(self, **overrides) -> Application:
        """One application with one order line, both taking overrides.

        The order-line fields moved onto ApplicationItem in TASK-UZK-026 and
        the callers of this helper did not: it still takes buyurtma_nomi and
        the rest as keywords and sends each to whichever record now holds it.
        """
        line = {
            "mahsulot_turi": self.category,
            "buyurtma_nomi": "Bolt M12",
            "buyurtma_soni": 500,
            "olchov_birligi": "ta",
        }
        fields = {"department": self.department}
        for name, value in overrides.items():
            if name in line:
                line[name] = value
            else:
                fields[name] = value

        return Application.raise_application(items=[line], **fields)

    def accepted_application(self, **overrides) -> Application:
        application = self.raise_application(**overrides)
        application.accept(by=self.decider)
        return application

    def page(self) -> str:
        return self.client.get(reverse("qabul-arizalar")).content.decode()

    def table(self) -> str:
        """The rows, without the page around them.

        The page can name an application outside the table - in a message, for
        instance - so a test about what is listed has to read the list.
        """
        body = self.page().split('<tbody id="qabul-tbody">', 1)[1]

        return body.split("</tbody>", 1)[0]


class ContentTests(AcceptedListTestCase):
    """Only accepted applications, and every column REQ-ARIZA-006 names."""

    def test_an_accepted_application_is_listed(self) -> None:
        application = self.accepted_application()

        self.assertIn(application.ariza_raqami, self.table())

    def test_an_incoming_application_is_not_listed(self) -> None:
        waiting = self.raise_application(buyurtma_nomi="Gayka M10")

        self.assertNotIn(waiting.ariza_raqami, self.table())

    def test_a_rejected_application_is_not_listed(self) -> None:
        refused = self.raise_application(buyurtma_nomi="Kabel 4mm")
        refused.reject(by=self.decider, comment="Byudjet yo`q.")

        self.assertNotIn(refused.ariza_raqami, self.table())

    def test_the_headings_are_the_specified_ones(self) -> None:
        page = self.page()

        for heading in (
            "Ariza",
            "Bo'lim",
            "Mahsulot Turi",
            "Buyurtma nomi",
            "Soni",
            "O'lchov",
            "PDF",
            "Qabul qilingan sana",
            "Tayinlangan xodim",
            "Amallar",
        ):
            with self.subTest(heading=heading):
                self.assertIn(heading, page)

    def test_a_row_shows_the_application(self) -> None:
        application = self.accepted_application(buyurtma_nomi="Prokat polat")
        row = self.table()

        self.assertIn(application.ariza_raqami, row)
        self.assertIn("Texnik bolim", row)
        self.assertIn("Metallurgiya", row)
        self.assertIn("Prokat polat", row)
        self.assertIn("500", row)
        self.assertIn("ta", row)

    def test_an_empty_list_says_so_rather_than_showing_nothing(self) -> None:
        self.assertIn("Hozircha qabul qilingan ariza", self.table())

    def test_the_list_is_newest_decision_first(self) -> None:
        # The order acceptances were taken in, which is what this page is
        # worked through in - not the order the applications arrived.
        #
        # Both dates are written explicitly. Accepting two applications in a
        # row and then re-stamping one of them left this deciding on two
        # timezone.now() calls microseconds apart, which collide at the
        # resolution SQLite stores - and on a tie the row that arrived later
        # wins, which is the reverse of what the test asserts. It passed on an
        # idle machine and failed on a busy one; found while fixing #29.
        earlier = self.accepted_application(buyurtma_nomi="Birinchi")
        later = self.accepted_application(buyurtma_nomi="Ikkinchi")
        decided = timezone.now()
        Application.objects.filter(pk=earlier.pk).update(
            qabul_qilingan_sana=decided - timedelta(hours=2)
        )
        Application.objects.filter(pk=later.pk).update(
            qabul_qilingan_sana=decided
        )

        row = self.table()

        self.assertLess(
            row.index(later.ariza_raqami), row.index(earlier.ariza_raqami)
        )


class AcceptanceDateTests(AcceptedListTestCase):
    """Qabul qilingan sana is when it was accepted, not when it arrived."""

    def test_the_date_shown_is_the_acceptance_date(self) -> None:
        # The dates are compared in the timezone the template renders in.
        # TIME_ZONE is Asia/Tashkent and USE_TZ is on, so a stored instant
        # between 19:00 and midnight UTC is already the next day on the page,
        # and comparing against the raw UTC date made this test fail for five
        # hours a day. It was written in TASK-UZK-025 and found by the
        # TASK-UZK-032 validation run, which happened to be inside that
        # window; nothing about either task caused it.
        application = self.accepted_application()
        arrived = timezone.now() - timedelta(days=9)
        decided = timezone.now() - timedelta(days=2)
        Application.objects.filter(pk=application.pk).update(
            kelib_tushgan_sana=arrived, qabul_qilingan_sana=decided
        )

        row = self.table()

        self.assertIn(timezone.localdate(decided).isoformat(), row)
        self.assertNotIn(timezone.localdate(arrived).isoformat(), row)


class StageNotStatusTests(AcceptedListTestCase):
    """The list reads the stage, which an administrator cannot rename."""

    def test_renaming_the_accepted_status_does_not_empty_the_list(self) -> None:
        application = self.accepted_application()
        accepted = ArizaStatus.objects.get(code=ArizaStatus.Code.ACCEPTED)
        accepted.name = "Bo`lim qabul qildi"
        accepted.save(update_fields=["name"])

        self.assertIn(application.ariza_raqami, self.table())

    def test_deleting_every_status_does_not_empty_the_list(self) -> None:
        application = self.accepted_application()
        ArizaStatus.objects.update(is_active=False)

        self.assertIn(application.ariza_raqami, self.table())


class AssignmentControlsTests(AcceptedListTestCase):
    """The controls REQ-ARIZA-006 names, wired by TASK-UZK-027."""

    def test_every_row_offers_the_controls(self) -> None:
        self.accepted_application()
        row = self.table()

        self.assertIn("Tayinlash", row)
        self.assertIn("<select", row)

    def test_they_work_rather_than_naming_the_task_that_will_wire_them(
        self,
    ) -> None:
        # They were rendered disabled with a title naming TASK-UZK-027 until
        # TASK-UZK-027 arrived. Counted per row rather than as a fixed number,
        # for the reason the #29 review gave: an exact count over the whole
        # table body passes only while the case has exactly one application
        # in it.
        rows = 3
        for index in range(rows):
            self.accepted_application(buyurtma_nomi=f"Ariza {index}")

        table = self.table()

        self.assertNotIn("TASK-UZK-027", table)
        self.assertEqual(table.count('action="/qabul-arizalar/'), rows)

    def test_the_creation_form_is_back_and_posts(self) -> None:
        # TASK-UZK-025 removed the prototype's modal because it posted
        # nowhere, and said TASK-UZK-026 owned it. It does: the form is here
        # and its action is the create route, which is the difference between
        # a feature and a placeholder.
        page = self.page()

        self.assertIn("create-modal", page)
        self.assertIn("Ariza Yaratish", page)
        self.assertIn(reverse("ariza-yaratish"), page)

    def test_the_creation_form_starts_closed(self) -> None:
        # Nobody opening the list asked to create anything.
        self.assertIn('id="create-modal" class="modal-overlay hidden"', self.page())


class AttachmentTests(AcceptedListTestCase):
    """The pairing PAGE_SHOWING_STAGE promised and nothing could test.

    TASK-UZK-022 made an application's PDF answer to the permission of the
    page the application is currently on, and mapped the accepted stage to
    this page - which did not exist. Now it does, so the promise can be
    checked: somebody who may open this page may fetch the attachment of a row
    on it, and somebody who may not, may not.
    """

    def test_somebody_who_may_open_this_page_may_fetch_the_attachment(self):
        application = self.accepted_application()
        self.client.force_login(make_user(MENEJER))

        response = self.client.get(
            reverse("ariza-pdf", args=[application.pk])
        )

        # 404 because this application has no file, not 403: the permission
        # question was answered yes and the file is what is missing.
        self.assertEqual(response.status_code, 404)

    def test_somebody_who_may_not_open_this_page_may_not(self) -> None:
        # DEC-015 gives Direktor the incoming page and not this one, so an
        # application's attachment stops being reachable by them at the moment
        # it is accepted. That is the whole point of following the record.
        application = self.accepted_application()
        self.client.force_login(make_user(DIREKTOR))

        response = self.client.get(
            reverse("ariza-pdf", args=[application.pk])
        )

        self.assertEqual(response.status_code, 403)


class AccessTests(AcceptedListTestCase):
    """DEC-015 decides who opens this page, as it does for every page."""

    def test_a_permitted_type_opens_it(self) -> None:
        for type_name in (ADMIN, MENEJER, BOLIM_BOSHLIGI):
            with self.subTest(user_type=type_name):
                self.client.force_login(make_user(type_name))

                response = self.client.get(reverse("qabul-arizalar"))

                self.assertEqual(response.status_code, 200)

    def test_an_excluded_type_is_refused(self) -> None:
        for type_name in (DIREKTOR, USERS):
            with self.subTest(user_type=type_name):
                self.client.force_login(make_user(type_name))

                response = self.client.get(reverse("qabul-arizalar"))

                self.assertEqual(response.status_code, 403)

    def test_an_anonymous_visitor_is_redirected(self) -> None:
        self.client.logout()

        response = self.client.get(reverse("qabul-arizalar"))

        self.assertEqual(response.status_code, 302)


class OrderingTests(AcceptedListTestCase):
    """Where an accepted row with no acceptance date lands.

    It should not exist: accept() is the only thing that writes this stage and
    it always stamps the date. The #29 review objected to the docstring
    claiming a fallback the query did not have, and the answer chosen was to
    give it one rather than to delete the sentence - a silent ordering that
    differs by database is the thing worth removing, not the comment.
    """

    def undated(self) -> Application:
        """An accepted application with no acceptance date.

        Written straight to the column, because nothing in the application
        can produce this and that is the point of the test.
        """
        application = self.accepted_application(buyurtma_nomi="Sanasiz")
        Application.objects.filter(pk=application.pk).update(
            qabul_qilingan_sana=None
        )
        return application

    def test_it_sorts_below_everything_with_a_real_date(self) -> None:
        # Not above, which is where SQLite puts a null under DESC.
        dated = self.accepted_application(buyurtma_nomi="Sanali")
        undated = self.undated()

        table = self.table()

        self.assertLess(
            table.index(dated.ariza_raqami),
            table.index(undated.ariza_raqami),
        )

    def test_it_is_still_listed(self) -> None:
        # Sorted last, not dropped: the row is a real accepted application
        # whatever is wrong with its date.
        undated = self.undated()

        self.assertIn(undated.ariza_raqami, self.table())

    def test_two_undated_rows_fall_back_to_the_arrival_date(self) -> None:
        older = self.undated()
        newer = self.undated()
        arrived = timezone.now()
        Application.objects.filter(pk=older.pk).update(
            kelib_tushgan_sana=arrived - timedelta(days=3)
        )
        Application.objects.filter(pk=newer.pk).update(
            kelib_tushgan_sana=arrived
        )

        table = self.table()

        self.assertLess(
            table.index(newer.ariza_raqami), table.index(older.ariza_raqami)
        )


class QueryTests(AcceptedListTestCase):
    """What the page fetches, and what it does not."""

    def test_only_the_name_the_page_renders_is_joined(self) -> None:
        # The #29 review found this query joining auth_user for the acceptor,
        # whom nothing on the page renders - a password hash fetched per row
        # for a column that does not exist. TASK-UZK-027 renders one name,
        # the assigned specialist, so there is one join now rather than none.
        # Asserting on the count rather than on the table name is what keeps
        # the original finding pinned: a second join means somebody selected
        # a person the page does not show.
        from applications.views import accepted_applications

        sql = str(accepted_applications().query)

        self.assertEqual(sql.count('INNER JOIN "auth_user"'), 0)
        self.assertEqual(sql.count('LEFT OUTER JOIN "auth_user"'), 1)

    def test_the_department_is_joined(self) -> None:
        # Rendered on every row, so it must not be a query each.
        from applications.views import accepted_applications

        self.assertIn("reference_department", str(accepted_applications().query))

    def test_the_lines_and_their_categories_are_fetched_in_two_queries(
        self,
    ) -> None:
        # The category moved onto the line in TASK-UZK-026, so it is no longer
        # a join on this query - it is a join on the prefetch. What matters is
        # unchanged: rendering the page must not cost a query per row.
        from applications.views import accepted_applications

        for nomi in ("Birinchi", "Ikkinchi", "Uchinchi"):
            self.accepted_application(buyurtma_nomi=nomi)

        with self.assertNumQueries(2):
            for application in accepted_applications():
                for line in application.items.all():
                    str(line.mahsulot_turi.name)
