"""Tests for the list-page filter bar: columns, a period and an ordering.

The per-column mechanism is TASK-UZK-041; the period and the ordering the
report pages need are TASK-UZK-043 (REQ-YUKLAMA-001).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.test import TestCase

from tests.support import (
    SignedInAdminTestCase,
    a_category,
    a_department,
    a_purchase_application,
    a_supplier,
    an_accepted_application,
    an_application,
    an_assigned_application,
    arrived_on,
    make_user,
    page,
)
from xarid.filters import (
    DateColumn,
    FilterColumn,
    TableFilter,
    newest_and_oldest_first,
)
from xarid.models import KATTA_MUTAXASIS, USERS, Application, ArizaStatus, Contract

BY_DEPARTMENT = FilterColumn("bolim", "Bo'lim", "department_id", ("department__name",))
BY_CATEGORY = FilterColumn(
    "mahsulot",
    "Mahsulot turi",
    "items__mahsulot_turi_id",
    ("items__mahsulot_turi__name",),
    multi_valued=True,
)
COLUMNS = (BY_DEPARTMENT, BY_CATEGORY)

REFUSED_DEPARTMENT = "Noma&#39;lum filtr qiymati: Bo&#39;lim"


class TableFilterTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.texnik = a_department("Texnik bo`lim")
        cls.moliya = a_department("Moliya bo`limi")
        cls.metal = a_category(100042, "Metallurgiya")
        cls.kimyo = a_category(200031, "Kimyoviy")
        cls.texnik_metal = an_application(department=cls.texnik, category=cls.metal)
        cls.texnik_kimyo = an_application(department=cls.texnik, category=cls.kimyo)
        cls.moliya_metal = an_application(department=cls.moliya, category=cls.metal)
        # One application ordering two categories, to be counted once.
        cls.moliya_both = an_application(department=cls.moliya, category=cls.metal)
        cls.moliya_both.items.create(
            mahsulot_turi=cls.kimyo, buyurtma_nomi="Kislota", buyurtma_soni="1", olchov_birligi="l"
        )

    def rows(self):
        return Application.objects.all()

    def test_options_come_from_the_data_without_duplicates(self) -> None:
        table_filter = TableFilter(COLUMNS, self.rows())

        departments, categories = table_filter.fields
        self.assertEqual(
            [option.label for option in departments.options], ["Moliya bo`limi", "Texnik bo`lim"]
        )
        self.assertEqual(
            [option.label for option in categories.options], ["Kimyoviy", "Metallurgiya"]
        )
        self.assertEqual(departments.options[1].value, str(self.texnik.pk))

    def test_options_reflect_only_the_rows_the_page_shows(self) -> None:
        table_filter = TableFilter(COLUMNS, self.rows().filter(department=self.moliya))

        self.assertEqual(
            [option.label for option in table_filter.fields[0].options], ["Moliya bo`limi"]
        )

    def test_no_parameters_returns_every_row(self) -> None:
        table_filter = TableFilter(COLUMNS, self.rows(), {})

        self.assertFalse(table_filter.is_active)
        self.assertEqual(table_filter.apply().count(), 4)
        self.assertEqual(table_filter.query_string, "")

    def test_one_filter_narrows_the_rows(self) -> None:
        table_filter = TableFilter(COLUMNS, self.rows(), {"bolim": str(self.texnik.pk)})

        self.assertCountEqual(table_filter.apply(), [self.texnik_metal, self.texnik_kimyo])
        self.assertTrue(table_filter.is_active)

    def test_two_filters_narrow_by_both(self) -> None:
        table_filter = TableFilter(
            COLUMNS, self.rows(), {"bolim": str(self.moliya.pk), "mahsulot": str(self.kimyo.pk)}
        )

        self.assertCountEqual(table_filter.apply(), [self.moliya_both])

    def test_a_row_matching_through_two_lines_is_listed_once(self) -> None:
        table_filter = TableFilter(COLUMNS, self.rows(), {"mahsulot": str(self.metal.pk)})

        listed = list(table_filter.apply())
        self.assertEqual(len(listed), 3)
        self.assertIn(self.moliya_both, listed)

    def test_an_empty_value_means_all(self) -> None:
        table_filter = TableFilter(COLUMNS, self.rows(), {"bolim": "", "mahsulot": "  "})

        self.assertFalse(table_filter.is_active)
        self.assertEqual(table_filter.apply().count(), 4)

    def test_an_unknown_value_is_reported_and_not_applied(self) -> None:
        table_filter = TableFilter(
            COLUMNS, self.rows(), {"bolim": "999999", "mahsulot": str(self.kimyo.pk)}
        )

        self.assertEqual(table_filter.invalid, ("Bo'lim",))
        self.assertEqual(table_filter.fields[0].selected, "")
        self.assertCountEqual(table_filter.apply(), [self.texnik_kimyo, self.moliya_both])
        self.assertEqual(table_filter.query_string, f"mahsulot={self.kimyo.pk}")

    def test_a_value_outside_the_visible_rows_is_unknown(self) -> None:
        table_filter = TableFilter(
            COLUMNS, self.rows().filter(department=self.moliya), {"bolim": str(self.texnik.pk)}
        )

        self.assertEqual(table_filter.invalid, ("Bo'lim",))
        self.assertEqual(table_filter.apply().count(), 2)

    def test_a_label_falls_back_when_the_named_parts_are_empty(self) -> None:
        nameless = make_user("nameless")
        named = make_user("named", first_name="Dilnoza", last_name="Yusupova")
        self.texnik_metal.accepted_by = nameless
        self.texnik_metal.save(update_fields=["accepted_by"])
        self.moliya_metal.accepted_by = named
        self.moliya_metal.save(update_fields=["accepted_by"])
        by_acceptor = FilterColumn(
            "qabul",
            "Qabul qilgan",
            "accepted_by_id",
            ("accepted_by__first_name", "accepted_by__last_name"),
            label_fallback_lookup="accepted_by__username",
        )

        table_filter = TableFilter((by_acceptor,), self.rows())

        self.assertEqual(
            [option.label for option in table_filter.fields[0].options],
            ["Dilnoza Yusupova", "nameless"],
        )


class FilterBarPageTests(SignedInAdminTestCase):
    """The filter bar as each list page renders and applies it."""

    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        cls.texnik = a_department("Texnik bo`lim")
        cls.moliya = a_department("Moliya bo`limi")
        cls.metal = a_category(100042, "Metallurgiya")
        cls.kimyo = a_category(200031, "Kimyoviy")
        cls.specialist = make_user(
            "spec", user_type=KATTA_MUTAXASIS, first_name="Dilnoza", last_name="Yusupova"
        )
        cls.other_specialist = make_user("spec2", user_type=KATTA_MUTAXASIS)

    def test_the_incoming_page_filters_by_department_and_category(self) -> None:
        texnik = an_application(department=self.texnik, category=self.metal)
        moliya = an_application(department=self.moliya, category=self.kimyo)

        unfiltered = self.client.get(page("kelib-arizalar"))
        self.assertContains(unfiltered, texnik.ariza_raqami)
        self.assertContains(unfiltered, moliya.ariza_raqami)
        self.assertContains(unfiltered, '<form method="get" action="/kelib-arizalar/"')
        self.assertContains(unfiltered, "Moliya bo`limi</option>")
        self.assertNotContains(unfiltered, "Tozalash")

        by_department = self.client.get(page("kelib-arizalar"), {"bolim": self.texnik.pk})
        self.assertContains(by_department, texnik.ariza_raqami)
        self.assertNotContains(by_department, moliya.ariza_raqami)
        self.assertContains(by_department, f'<option value="{self.texnik.pk}" selected>')
        self.assertContains(by_department, "Tozalash")

        by_both = self.client.get(
            page("kelib-arizalar"), {"bolim": self.texnik.pk, "mahsulot": self.kimyo.pk}
        )
        self.assertNotContains(by_both, texnik.ariza_raqami)
        self.assertNotContains(by_both, moliya.ariza_raqami)
        self.assertContains(by_both, "Hozircha kelib tushgan ariza yo'q.")

    def test_an_unknown_value_is_refused_with_a_message_and_the_full_list(self) -> None:
        application = an_application(department=self.texnik)

        response = self.client.get(page("kelib-arizalar"), {"bolim": "999999"})

        self.assertContains(response, REFUSED_DEPARTMENT)
        self.assertContains(response, application.ariza_raqami)

    def test_the_accepted_page_filters_by_specialist(self) -> None:
        mine = an_assigned_application(self.admin, self.specialist, department=self.texnik)
        theirs = an_assigned_application(self.admin, self.other_specialist, department=self.texnik)

        response = self.client.get(page("qabul-arizalar"), {"xodim": self.specialist.pk})

        self.assertContains(response, mine.ariza_raqami)
        self.assertNotContains(response, theirs.ariza_raqami)
        self.assertContains(response, "Dilnoza Yusupova</option>")
        self.assertContains(response, "spec2</option>")

    def test_the_assigned_page_offers_a_specialist_only_their_own_departments(self) -> None:
        an_assigned_application(self.admin, self.specialist, department=self.texnik)
        an_assigned_application(self.admin, self.other_specialist, department=self.moliya)
        self.client.force_login(self.specialist)

        response = self.client.get(page("tayinlangan"))
        self.assertContains(response, "Texnik bo`lim</option>")
        self.assertNotContains(response, "Moliya bo`limi</option>")

        refused = self.client.get(page("tayinlangan"), {"bolim": self.moliya.pk})
        self.assertContains(refused, REFUSED_DEPARTMENT)

    def test_the_assigned_page_filters_by_status(self) -> None:
        moving = an_assigned_application(self.admin, self.specialist)
        waiting = an_assigned_application(self.admin, self.specialist)
        status = ArizaStatus.with_code(ArizaStatus.Code.ASSIGNED)
        moving.set_status(status)

        response = self.client.get(page("tayinlangan"), {"holat": status.pk})

        self.assertContains(response, moving.ariza_raqami)
        self.assertNotContains(response, waiting.ariza_raqami)

    def test_the_contracts_page_filters_by_supplier(self) -> None:
        application = an_assigned_application(self.admin, self.specialist)
        first_supplier = a_supplier("Texnoprom LLC", inn="123456789")
        second_supplier = a_supplier("GazTrade", inn="987654321")
        rows = [
            {
                "buyurtma_nomi": "Bolt",
                "part_number": "",
                "buyurtma_soni": Decimal("1"),
                "olchov_birligi": "ta",
                "narxi": Decimal("10"),
            }
        ]
        first = Contract.raise_contract(
            items=rows, created_by=self.admin, application=application, supplier=first_supplier
        )
        second = Contract.raise_contract(
            items=rows, created_by=self.admin, application=application, supplier=second_supplier
        )

        response = self.client.get(page("kelishinlingan"), {"firma": first_supplier.pk})

        self.assertContains(response, first.shartnoma_raqami)
        self.assertNotContains(response, second.shartnoma_raqami)

    def test_the_purchase_page_filters_by_category(self) -> None:
        requester = make_user("requester", user_type=USERS, department=self.texnik)
        metal = a_purchase_application(requester, self.texnik, category=self.metal, with_pdf=False)
        kimyo = a_purchase_application(requester, self.texnik, category=self.kimyo, with_pdf=False)

        response = self.client.get(page("xarid-ariza"), {"mahsulot": self.kimyo.pk})

        self.assertContains(response, kimyo.xarid_raqami)
        self.assertNotContains(response, metal.xarid_raqami)

    def test_a_refused_creation_still_renders_the_filter_bar(self) -> None:
        an_accepted_application(self.admin)

        response = self.client.post(page("ariza-yaratish"), {})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Bo&#39;lim: barchasi")


ARRIVAL_PERIOD = DateColumn("Kelib tushgan sana", "kelib_tushgan_sana")
ARRIVAL_SORTS = newest_and_oldest_first("kelib_tushgan_sana")

REFUSED_INVERTED_PERIOD = "Davr boshlanishi tugashidan keyin"
REFUSED_UNREADABLE_PERIOD = "Sana noto&#39;g&#39;ri kiritilgan"


class DatePeriodTests(TestCase):
    """The period a page narrows by (REQ-YUKLAMA-001)."""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.january = arrived_on(date(2026, 1, 10))
        cls.february = arrived_on(date(2026, 2, 20))
        cls.march = arrived_on(date(2026, 3, 5))

    def narrowed(self, chosen: dict[str, str]) -> TableFilter:
        return TableFilter((), Application.objects.all(), chosen, date_column=ARRIVAL_PERIOD)

    def test_a_period_returns_only_the_rows_dated_inside_it(self) -> None:
        table_filter = self.narrowed({"dan": "2026-01-01", "gacha": "2026-02-28"})

        self.assertCountEqual(table_filter.apply(), [self.january, self.february])
        self.assertTrue(table_filter.is_active)
        self.assertEqual(table_filter.query_string, "dan=2026-01-01&gacha=2026-02-28")

    def test_both_bounds_are_inclusive(self) -> None:
        table_filter = self.narrowed({"dan": "2026-01-10", "gacha": "2026-02-20"})

        self.assertCountEqual(table_filter.apply(), [self.january, self.february])

    def test_the_last_day_of_a_period_is_included_whole(self) -> None:
        late = arrived_on(date(2026, 2, 20), hour=23)

        table_filter = self.narrowed({"gacha": "2026-02-20"})

        self.assertIn(late, table_filter.apply())

    def test_a_start_without_an_end_leaves_the_period_open(self) -> None:
        table_filter = self.narrowed({"dan": "2026-02-01"})

        self.assertCountEqual(table_filter.apply(), [self.february, self.march])
        self.assertEqual(table_filter.query_string, "dan=2026-02-01")

    def test_an_end_without_a_start_leaves_the_period_open(self) -> None:
        table_filter = self.narrowed({"gacha": "2026-02-01"})

        self.assertCountEqual(table_filter.apply(), [self.january])

    def test_neither_bound_narrows_nothing(self) -> None:
        table_filter = self.narrowed({"dan": "", "gacha": "  "})

        self.assertEqual(table_filter.apply().count(), 3)
        self.assertFalse(table_filter.is_active)
        self.assertEqual(table_filter.query_string, "")

    def test_a_start_later_than_the_end_is_refused_and_not_applied(self) -> None:
        table_filter = self.narrowed({"dan": "2026-03-01", "gacha": "2026-01-01"})

        self.assertIn("Davr boshlanishi tugashidan keyin", table_filter.period.refusal)
        self.assertEqual(table_filter.apply().count(), 3)
        self.assertFalse(table_filter.is_active)
        self.assertEqual(table_filter.query_string, "")

    def test_a_bound_that_is_not_a_date_is_refused_and_not_applied(self) -> None:
        table_filter = self.narrowed({"dan": "kecha", "gacha": "2026-03-31"})

        self.assertIn("Sana noto'g'ri kiritilgan", table_filter.period.refusal)
        self.assertEqual(table_filter.apply().count(), 3)
        self.assertFalse(table_filter.is_active)

    def test_a_row_without_that_date_is_outside_every_period(self) -> None:
        acceptance = DateColumn("Qabul qilingan sana", "qabul_qilingan_sana")

        table_filter = TableFilter(
            (), Application.objects.all(), {"dan": "2020-01-01"}, date_column=acceptance
        )

        self.assertEqual(table_filter.apply().count(), 0)

    def test_a_period_narrows_what_a_column_filter_left(self) -> None:
        moliya = a_department("Moliya bo`limi")
        Application.objects.filter(pk=self.march.pk).update(department=moliya)

        table_filter = TableFilter(
            (BY_DEPARTMENT,),
            Application.objects.all(),
            {"bolim": str(moliya.pk), "gacha": "2026-01-31"},
            date_column=ARRIVAL_PERIOD,
        )

        self.assertEqual(table_filter.apply().count(), 0)


class TableSortTests(TestCase):
    """The ordering drop-down of a list page (REQ-YUKLAMA-001)."""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.oldest = arrived_on(date(2026, 1, 10))
        cls.middle = arrived_on(date(2026, 2, 20))
        cls.newest = arrived_on(date(2026, 3, 5))

    def ordered(self, chosen: dict[str, str]) -> list[Application]:
        table_filter = TableFilter(
            (), Application.objects.all(), chosen, sort_choices=ARRIVAL_SORTS
        )
        return list(table_filter.apply())

    def test_the_first_choice_is_the_default_and_is_not_in_the_query_string(self) -> None:
        table_filter = TableFilter((), Application.objects.all(), {}, sort_choices=ARRIVAL_SORTS)

        self.assertEqual(table_filter.sort.selected, "kamayish")
        self.assertFalse(table_filter.is_active)
        self.assertEqual(table_filter.query_string, "")

    def test_ascending_and_descending_are_the_reverse_of_each_other(self) -> None:
        descending = self.ordered({"tartib": "kamayish"})
        ascending = self.ordered({"tartib": "osish"})

        self.assertEqual(descending, [self.newest, self.middle, self.oldest])
        self.assertEqual(ascending, list(reversed(descending)))

    def test_a_chosen_order_travels_in_the_query_string(self) -> None:
        table_filter = TableFilter(
            (), Application.objects.all(), {"tartib": "osish"}, sort_choices=ARRIVAL_SORTS
        )

        self.assertTrue(table_filter.is_active)
        self.assertEqual(table_filter.query_string, "tartib=osish")

    def test_an_unknown_order_is_reported_and_the_default_is_kept(self) -> None:
        table_filter = TableFilter(
            (), Application.objects.all(), {"tartib": "yuqoriga"}, sort_choices=ARRIVAL_SORTS
        )

        self.assertEqual(table_filter.invalid, ("Tartib",))
        self.assertEqual(table_filter.sort.selected, "kamayish")

    def test_a_page_offering_no_ordering_keeps_the_order_of_its_queryset(self) -> None:
        table_filter = TableFilter((), Application.objects.order_by("id"))

        self.assertFalse(table_filter.sort.is_offered)
        self.assertEqual(list(table_filter.apply()), [self.oldest, self.middle, self.newest])


class PeriodAndOrderPageTests(SignedInAdminTestCase):
    """The period and the ordering as a list page renders and applies them."""

    def test_the_incoming_page_narrows_to_the_chosen_period(self) -> None:
        inside = arrived_on(date(2026, 2, 20))
        outside = arrived_on(date(2026, 4, 1))

        response = self.client.get(
            page("kelib-arizalar"), {"dan": "2026-02-01", "gacha": "2026-02-28"}
        )

        self.assertContains(response, inside.ariza_raqami)
        self.assertNotContains(response, outside.ariza_raqami)
        self.assertContains(response, 'value="2026-02-01"')
        self.assertContains(response, "Tozalash")

    def test_a_refused_period_can_still_be_cleared(self) -> None:
        arrived_on(date(2026, 2, 20))

        response = self.client.get(
            page("kelib-arizalar"), {"dan": "2026-03-01", "gacha": "2026-01-01"}
        )

        self.assertContains(response, REFUSED_INVERTED_PERIOD)
        self.assertContains(response, "Tozalash")

    def test_an_unreadable_date_can_still_be_cleared(self) -> None:
        arrived_on(date(2026, 2, 20))

        response = self.client.get(page("kelib-arizalar"), {"dan": "kecha"})

        self.assertContains(response, REFUSED_UNREADABLE_PERIOD)
        self.assertContains(response, "Tozalash")

    def test_an_untouched_page_offers_nothing_to_clear(self) -> None:
        arrived_on(date(2026, 2, 20))

        response = self.client.get(page("kelib-arizalar"))

        self.assertNotContains(response, "Tozalash")

    def test_the_date_inputs_are_named_after_the_page_bounds(self) -> None:
        response = self.client.get(page("kelib-arizalar"))

        self.assertContains(response, 'name="dan" id="f-dan"')
        self.assertContains(response, 'name="gacha" id="f-gacha"')

    def test_the_incoming_page_refuses_an_inverted_period_with_a_message(self) -> None:
        application = arrived_on(date(2026, 2, 20))

        response = self.client.get(
            page("kelib-arizalar"), {"dan": "2026-03-01", "gacha": "2026-01-01"}
        )

        self.assertContains(response, REFUSED_INVERTED_PERIOD)
        self.assertContains(response, application.ariza_raqami)

    def test_the_incoming_page_refuses_an_unreadable_date_with_a_message(self) -> None:
        application = arrived_on(date(2026, 2, 20))

        response = self.client.get(page("kelib-arizalar"), {"dan": "kecha"})

        self.assertContains(response, REFUSED_UNREADABLE_PERIOD)
        self.assertContains(response, application.ariza_raqami)

    def test_the_incoming_page_reverses_its_rows_on_request(self) -> None:
        older = arrived_on(date(2026, 1, 10))
        newer = arrived_on(date(2026, 3, 5))

        descending = self.client.get(page("kelib-arizalar")).content.decode()
        ascending = self.client.get(page("kelib-arizalar"), {"tartib": "osish"}).content.decode()

        self.assertLess(descending.index(newer.ariza_raqami), descending.index(older.ariza_raqami))
        self.assertLess(ascending.index(older.ariza_raqami), ascending.index(newer.ariza_raqami))

    def test_every_list_page_renders_the_period_and_the_ordering(self) -> None:
        for page_name in (
            "kelib-arizalar",
            "qabul-arizalar",
            "tayinlangan",
            "kelishinlingan",
            "xarid-ariza",
        ):
            with self.subTest(page=page_name):
                response = self.client.get(page(page_name))

                self.assertContains(response, 'name="dan"')
                self.assertContains(response, 'name="gacha"')
                self.assertContains(response, "Tartib: kamayish")
