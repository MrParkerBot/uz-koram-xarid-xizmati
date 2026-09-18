"""Tests for the Excel and PDF export of the list pages (TASK-UZK-042)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import BytesIO

from django.urls import reverse
from openpyxl import load_workbook
from pypdf import PdfReader

from tests.support import (
    SignedInAdminTestCase,
    a_category,
    a_contract,
    a_department,
    a_purchase_application,
    a_supplier,
    an_application,
    an_assigned_application,
    arrived_on,
    assigned_on,
    make_user,
    page,
)
from xarid.exports import EXCEL_CONTENT_TYPE, PDF_CONTENT_TYPE
from xarid.models import (
    BOLIM_BOSHLIGI,
    DIREKTOR,
    KATTA_MUTAXASIS,
    MENEJER,
    USERS,
    Application,
    Contract,
    PurchaseApplication,
    ShartnomaStatus,
)


def workbook_rows(response) -> list[list[object]]:
    sheet = load_workbook(BytesIO(response.content)).active
    return [list(row) for row in sheet.iter_rows(values_only=True)]


def pdf_text(response) -> str:
    return "\n".join(page.extract_text() for page in PdfReader(BytesIO(response.content)).pages)


def page_width(response) -> float:
    """The width of the first page of a downloaded PDF, in points."""
    return float(PdfReader(BytesIO(response.content)).pages[0].mediabox.width)


def drawn_width(response) -> float:
    """How far right anything is actually drawn on the first page.

    Reportlab will happily draw a table wider than the paper, and the text
    still extracts, so a download can read as complete while its last columns
    are off the page. This is what says whether it is really there.
    """
    first = PdfReader(BytesIO(response.content)).pages[0]
    positions: list[float] = []
    first.extract_text(
        visitor_text=lambda text, cm, tm, font, size: (
            positions.append(tm[4]) if text.strip() else None
        )
    )
    return max(positions, default=0.0)


class ExportRouteTests(SignedInAdminTestCase):
    PAGES = ("kelib-arizalar", "qabul-arizalar", "tayinlangan", "kelishinlingan", "xarid-ariza")

    def test_every_list_page_exports_both_formats_with_the_right_headers(self) -> None:
        for page_name in self.PAGES:
            with self.subTest(page=page_name):
                excel = self.client.get(page(f"{page_name}-eksport", "xlsx"))
                pdf = self.client.get(page(f"{page_name}-eksport", "pdf"))

                self.assertEqual(excel.status_code, 200)
                self.assertEqual(excel["Content-Type"], EXCEL_CONTENT_TYPE)
                self.assertIn(f'filename="{page_name}-', excel["Content-Disposition"])
                self.assertEqual(pdf.status_code, 200)
                self.assertEqual(pdf["Content-Type"], PDF_CONTENT_TYPE)
                self.assertIn(".pdf", pdf["Content-Disposition"])

    def test_an_empty_list_exports_headers_and_no_rows(self) -> None:
        excel = self.client.get(page("kelib-arizalar-eksport", "xlsx"))
        pdf = self.client.get(page("kelib-arizalar-eksport", "pdf"))

        rows = workbook_rows(excel)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][:3], ["Ariza raqami", "Bo'lim", "Mahsulot turi"])
        self.assertIn("Ariza raqami", pdf_text(pdf))

    def test_an_unknown_format_is_a_not_found(self) -> None:
        self.assertEqual(self.client.get(page("kelib-arizalar-eksport", "csv")).status_code, 404)

    def test_the_export_answers_to_the_page_permission(self) -> None:
        self.client.logout()
        anonymous = self.client.get(page("kelib-arizalar-eksport", "xlsx"))
        self.assertEqual(anonymous.status_code, 302)
        self.assertTrue(anonymous.url.startswith(reverse("login")))

        self.client.force_login(make_user("requester", user_type=USERS))
        self.assertEqual(self.client.get(page("kelib-arizalar-eksport", "xlsx")).status_code, 403)
        self.assertEqual(self.client.get(page("xarid-ariza-eksport", "xlsx")).status_code, 200)

    def test_the_toolbar_links_carry_the_active_filters(self) -> None:
        department = a_department("Texnik bo`lim")
        an_application(department=department)

        plain = self.client.get(page("kelib-arizalar"))
        filtered = self.client.get(page("kelib-arizalar"), {"bolim": department.pk})

        self.assertContains(plain, f'href="{page("kelib-arizalar-eksport", "xlsx")}"')
        self.assertContains(
            filtered, f'href="{page("kelib-arizalar-eksport", "pdf")}?bolim={department.pk}"'
        )


class ExportContentTests(SignedInAdminTestCase):
    """The rows in the file are the rows on the page, filtered the same way."""

    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        cls.texnik = a_department("Texnik bo`lim")
        cls.moliya = a_department("Moliya bo`limi")
        cls.metal = a_category(100042, "Metallurgiya")
        cls.kimyo = a_category(200031, "Kimyoviy")
        cls.texnik_application = an_application(department=cls.texnik, category=cls.metal)
        cls.moliya_application = an_application(department=cls.moliya, category=cls.kimyo)
        # A second order line makes the export two rows for one application,
        # the way the table renders it.
        cls.moliya_application.items.create(
            mahsulot_turi=cls.metal,
            buyurtma_nomi="Prokat",
            buyurtma_soni="12.5",
            olchov_birligi="kg",
        )

    def test_exporting_with_no_filter_writes_every_table_row(self) -> None:
        excel = self.client.get(page("kelib-arizalar-eksport", "xlsx"))

        rows = workbook_rows(excel)
        self.assertEqual(len(rows), 1 + 3)
        numbers = {row[0] for row in rows[1:]}
        self.assertEqual(
            numbers,
            {self.texnik_application.ariza_raqami, self.moliya_application.ariza_raqami},
        )
        prokat = next(row for row in rows[1:] if row[3] == "Prokat")
        self.assertEqual(prokat[0], self.moliya_application.ariza_raqami)
        self.assertEqual(prokat[1], "Moliya bo`limi")
        self.assertEqual(prokat[4], Decimal("12.5"))

    def test_exporting_with_a_filter_writes_only_the_filtered_rows(self) -> None:
        excel = self.client.get(page("kelib-arizalar-eksport", "xlsx"), {"bolim": self.texnik.pk})

        rows = workbook_rows(excel)
        self.assertEqual(len(rows), 1 + 1)
        self.assertEqual(rows[1][0], self.texnik_application.ariza_raqami)

    def test_the_pdf_carries_the_same_rows_as_the_workbook(self) -> None:
        for query in ({}, {"bolim": self.moliya.pk}):
            with self.subTest(query=query):
                excel = self.client.get(page("kelib-arizalar-eksport", "xlsx"), query)
                pdf = self.client.get(page("kelib-arizalar-eksport", "pdf"), query)

                text = pdf_text(pdf)
                for row in workbook_rows(excel)[1:]:
                    self.assertIn(str(row[0]), text)
                    self.assertIn(str(row[3]), text)
                if query:
                    self.assertNotIn(self.texnik_application.ariza_raqami, text)

    def test_an_invalid_filter_value_exports_the_full_list(self) -> None:
        excel = self.client.get(page("kelib-arizalar-eksport", "xlsx"), {"bolim": "999999"})

        self.assertEqual(len(workbook_rows(excel)), 1 + 3)

    def test_the_assigned_export_is_limited_to_a_specialist_s_own_work(self) -> None:
        specialist = make_user("spec", user_type=KATTA_MUTAXASIS)
        other = make_user("spec2", user_type=KATTA_MUTAXASIS)
        mine = an_assigned_application(self.admin, specialist)
        an_assigned_application(self.admin, other)

        self.client.force_login(specialist)
        rows = workbook_rows(self.client.get(page("tayinlangan-eksport", "xlsx")))

        self.assertEqual(len(rows), 1 + 1)
        self.assertEqual(rows[1][0], mine.ariza_raqami)
        self.assertNotIn("Tayinlangan xodim", rows[0])

        self.client.force_login(self.admin)
        rows = workbook_rows(self.client.get(page("tayinlangan-eksport", "xlsx")))
        self.assertEqual(len(rows), 1 + 2)
        self.assertIn("Tayinlangan xodim", rows[0])

    def test_the_contracts_export_writes_one_row_per_goods_line_with_prices(self) -> None:
        specialist = make_user("spec", user_type=KATTA_MUTAXASIS)
        application = an_assigned_application(self.admin, specialist)
        contract = Contract.raise_contract(
            items=[
                {
                    "buyurtma_nomi": "Bolt",
                    "part_number": "PN-1",
                    "buyurtma_soni": Decimal("2"),
                    "olchov_birligi": "ta",
                    "narxi": Decimal("1000.50"),
                },
                {
                    "buyurtma_nomi": "Gayka",
                    "part_number": "",
                    "buyurtma_soni": Decimal("3"),
                    "olchov_birligi": "ta",
                    "narxi": Decimal("1"),
                },
            ],
            created_by=self.admin,
            application=application,
            supplier=a_supplier(),
        )

        rows = workbook_rows(self.client.get(page("kelishinlingan-eksport", "xlsx")))

        self.assertEqual(len(rows), 1 + 2)
        bolt = next(row for row in rows[1:] if row[2] == "Bolt")
        self.assertEqual(bolt[0], contract.shartnoma_raqami)
        self.assertEqual(bolt[7], Decimal("2001.00"))
        self.assertEqual(bolt[9], "Texnoprom LLC")
        self.assertIn(
            contract.shartnoma_raqami,
            pdf_text(self.client.get(page("kelishinlingan-eksport", "pdf"))),
        )

    def test_the_purchase_export_follows_its_category_filter(self) -> None:
        requester = make_user("requester", user_type=USERS, department=self.texnik)
        kimyo = a_purchase_application(requester, self.texnik, category=self.kimyo, with_pdf=False)
        a_purchase_application(requester, self.texnik, category=self.metal, with_pdf=False)

        rows = workbook_rows(
            self.client.get(page("xarid-ariza-eksport", "xlsx"), {"mahsulot": self.kimyo.pk})
        )

        self.assertEqual(len(rows), 1 + 1)
        self.assertEqual(rows[1][0], kimyo.xarid_raqami)


class ExportPeriodTests(SignedInAdminTestCase):
    """A download carries the period and the ordering of the page (TASK-UZK-043)."""

    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        cls.january = arrived_on(date(2026, 1, 10))
        cls.february = arrived_on(date(2026, 2, 20))
        cls.march = arrived_on(date(2026, 3, 5))

    def exported_numbers(self, chosen: dict[str, str]) -> list[str]:
        response = self.client.get(page("kelib-arizalar-eksport", "xlsx"), chosen)
        return [str(row[0]) for row in workbook_rows(response)[1:]]

    def test_a_download_holds_only_the_rows_inside_the_period(self) -> None:
        numbers = self.exported_numbers({"dan": "2026-02-01", "gacha": "2026-02-28"})

        self.assertEqual(numbers, [self.february.ariza_raqami])

    def test_a_download_follows_the_chosen_order(self) -> None:
        descending = self.exported_numbers({})
        ascending = self.exported_numbers({"tartib": "osish"})

        self.assertEqual(descending, list(reversed(ascending)))
        self.assertEqual(ascending[0], self.january.ariza_raqami)

    def test_a_download_ignores_an_inverted_period_as_the_page_does(self) -> None:
        numbers = self.exported_numbers({"dan": "2026-03-01", "gacha": "2026-01-01"})

        self.assertEqual(len(numbers), 3)

    def test_the_toolbar_links_carry_the_period_and_the_order(self) -> None:
        response = self.client.get(
            page("kelib-arizalar"), {"dan": "2026-02-01", "tartib": "osish"}
        )

        self.assertContains(response, "dan=2026-02-01")
        self.assertContains(response, "tartib=osish")


class PurchaseStatusExportTests(SignedInAdminTestCase):
    """The Xarid Arizasi download holds the status the page shows (TASK-UZK-033)."""

    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        cls.texnik = a_department("Texnik bo`lim")
        cls.head = make_user("exp.head", user_type=BOLIM_BOSHLIGI, department=cls.texnik)
        cls.direktor = make_user("exp.direktor", user_type=DIREKTOR)
        cls.specialist = make_user("exp.specialist", user_type=KATTA_MUTAXASIS)
        cls.requester = make_user("exp.requester", user_type=USERS, department=cls.texnik)

    def a_contracted_request(self, status):
        request = a_purchase_application(self.requester, self.texnik, with_pdf=False)
        request.approve(by=self.head)
        request.refresh_from_db()
        request.approve(by=self.direktor)
        request.refresh_from_db()
        application = request.raised_application
        application.accept(by=self.admin)
        application.refresh_from_db()
        application.assign(by=self.admin, specialist=self.specialist)
        a_contract(application, self.specialist, status=status)
        return PurchaseApplication.objects.get(pk=request.pk)

    def exported(self) -> list[list[object]]:
        return workbook_rows(self.client.get(page("xarid-ariza-eksport", "xlsx")))

    def test_the_file_holds_the_contract_status_the_page_shows(self) -> None:
        status = ShartnomaStatus.objects.active().first()
        self.a_contracted_request(status)

        rows = self.exported()

        holat = rows[0].index("Holati")
        self.assertEqual(rows[1][holat], status.name)

    def test_the_file_says_which_status_it_is(self) -> None:
        status = ShartnomaStatus.objects.active().first()
        self.a_contracted_request(status)

        rows = self.exported()

        manba = rows[0].index("Holat manbasi")
        self.assertEqual(rows[1][manba], "Shartnoma")

    def test_a_request_with_no_contract_exports_its_own_status(self) -> None:
        request = a_purchase_application(self.requester, self.texnik, with_pdf=False)

        rows = self.exported()

        holat = rows[0].index("Holati")
        manba = rows[0].index("Holat manbasi")
        self.assertEqual(rows[1][holat], request.status.name)
        self.assertEqual(rows[1][manba], "Ariza")


class ReportExportTests(SignedInAdminTestCase):
    """The reports download what the page shows (TASK-UZK-065).

    REQ-YUKLAMA-001 and REQ-XARID-001 both end with a download button for all
    and filtered data in Excel and PDF.
    """

    REPORTS = ("xodimlar-yuklamasi", "bolimlar", "mahsulot-tur")

    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        cls.specialist = make_user(
            "export.specialist",
            user_type=KATTA_MUTAXASIS,
            first_name="Dilnoza",
            last_name="Yusupova",
        )
        cls.texnik = a_department("Texnik bo`lim")
        cls.statuses = tuple(ShartnomaStatus.objects.active())

    def test_both_reports_download_in_both_formats(self) -> None:
        for report in self.REPORTS:
            with self.subTest(report=report):
                excel = self.client.get(page(f"{report}-eksport", "xlsx"))
                pdf = self.client.get(page(f"{report}-eksport", "pdf"))

                self.assertEqual(excel.status_code, 200)
                self.assertEqual(excel["Content-Type"], EXCEL_CONTENT_TYPE)
                self.assertEqual(pdf.status_code, 200)
                self.assertEqual(pdf["Content-Type"], PDF_CONTENT_TYPE)

    def test_the_headers_are_the_active_statuses_in_their_order(self) -> None:
        rows = workbook_rows(self.client.get(page("xodimlar-yuklamasi-eksport", "xlsx")))

        expected = ["#", "Xodim", "Telefon", "Xarid topshiriqlari"]
        expected += [status.name for status in ShartnomaStatus.objects.active()]
        self.assertEqual(rows[0], expected)

    def test_a_new_status_adds_a_column_to_the_file(self) -> None:
        before = workbook_rows(self.client.get(page("bolimlar-eksport", "xlsx")))[0]

        ShartnomaStatus.objects.create(name="Tekshiruvda", badge_colour="blue")

        after = workbook_rows(self.client.get(page("bolimlar-eksport", "xlsx")))[0]
        self.assertEqual(len(after), len(before) + 1)
        self.assertIn("Tekshiruvda", after)

    def test_the_workload_file_holds_a_row_per_specialist_and_the_totals(self) -> None:
        a_contract(
            an_assigned_application(self.admin, self.specialist),
            self.admin,
            status=self.statuses[0],
        )

        rows = workbook_rows(self.client.get(page("xodimlar-yuklamasi-eksport", "xlsx")))

        self.assertEqual(rows[1][1], "Dilnoza Yusupova")
        self.assertEqual(rows[1][3], 1)
        self.assertEqual(rows[-1][1], "Jami:")
        # The totals row has no ordinal; an empty cell reads back as None.
        self.assertIsNone(rows[-1][0])

    def test_the_totals_row_is_the_sum_of_each_column(self) -> None:
        for _ in range(2):
            a_contract(
                an_assigned_application(self.admin, self.specialist),
                self.admin,
                status=self.statuses[0],
            )

        rows = workbook_rows(self.client.get(page("xodimlar-yuklamasi-eksport", "xlsx")))

        body, totals = rows[1:-1], rows[-1]
        for column in range(3, len(rows[0])):
            with self.subTest(column=rows[0][column]):
                self.assertEqual(totals[column], sum(row[column] for row in body))
        self.assertEqual(totals[3], 2)

    def test_a_download_holds_only_the_rows_inside_the_period(self) -> None:
        assigned_on(date(2026, 2, 10), self.admin, self.specialist)
        assigned_on(date(2026, 5, 10), self.admin, self.specialist)

        rows = workbook_rows(
            self.client.get(
                page("xodimlar-yuklamasi-eksport", "xlsx"),
                {"dan": "2026-02-01", "gacha": "2026-02-28"},
            )
        )

        self.assertEqual(rows[-1][3], 1)

    def test_a_download_narrowed_to_one_department_holds_that_row_only(self) -> None:
        moliya = a_department("Moliya bo" + chr(96) + "limi")
        an_application(department=self.texnik)
        an_application(department=moliya)

        rows = workbook_rows(
            self.client.get(page("bolimlar-eksport", "xlsx"), {"bolim": moliya.pk})
        )

        names = [row[1] for row in rows[1:-1]]
        self.assertEqual(names, ["Moliya bo" + chr(96) + "limi"])
        self.assertEqual(rows[-1][2], 1)

    def test_a_report_with_no_rows_still_downloads_its_headers(self) -> None:
        Application.objects.all().delete()
        self.texnik.is_active = False
        self.texnik.save(update_fields=["is_active"])

        response = self.client.get(page("bolimlar-eksport", "xlsx"))
        rows = workbook_rows(response)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(rows[0][0], "#")
        self.assertNotIn("Jami:", [row[1] for row in rows[1:]])

    def test_the_pdf_holds_the_rows_too(self) -> None:
        an_application(department=self.texnik)

        text = pdf_text(self.client.get(page("bolimlar-eksport", "pdf")))

        self.assertIn("Jami:", text)

    def test_a_report_wider_than_the_page_is_narrowed_to_fit_it(self) -> None:
        """DEC-010 lets anybody add a status, and a PDF cannot scroll.

        Asserting the text is present is not enough: reportlab draws a table
        at its natural width and pypdf reads that text back happily, off the
        page and all. What matters is where it was drawn.
        """
        an_application(department=self.texnik)
        for number in range(25):
            ShartnomaStatus.objects.create(name=f"Holat {number}", badge_colour="blue")

        response = self.client.get(page("bolimlar-eksport", "pdf"))

        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(drawn_width(response), page_width(response))

    def test_a_report_that_fits_is_not_narrowed(self) -> None:
        an_application(department=self.texnik)

        response = self.client.get(page("bolimlar-eksport", "pdf"))

        self.assertLessEqual(drawn_width(response), page_width(response))
        self.assertIn("Jami:", pdf_text(response))


    def test_the_type_report_downloads_its_rows_and_totals(self) -> None:
        category = a_category(100042, "Metallurgiya")
        an_application(category=category)

        rows = workbook_rows(self.client.get(page("mahsulot-tur-eksport", "xlsx")))

        self.assertEqual(rows[0][:4], ["#", "Mahsulot Turi", "Kodi", "Xarid topshiriqlari"])
        self.assertIn("Metallurgiya", [row[1] for row in rows])
        self.assertEqual(rows[-1][1], "Jami:")
        self.assertEqual(rows[-1][3], 1)

    def test_a_type_the_matrix_refuses_cannot_download_either(self) -> None:
        manager = make_user("export.manager", user_type=MENEJER)
        self.client.force_login(manager)

        for report in self.REPORTS:
            with self.subTest(report=report):
                response = self.client.get(page(f"{report}-eksport", "xlsx"))

                self.assertEqual(response.status_code, 403)

    def test_the_page_offers_the_download_links(self) -> None:
        for report in self.REPORTS:
            with self.subTest(report=report):
                response = self.client.get(page(report))

                self.assertContains(response, page(f"{report}-eksport", "xlsx"))
                self.assertContains(response, page(f"{report}-eksport", "pdf"))
