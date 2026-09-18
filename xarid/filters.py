"""Per-column filtering, a period and an ordering for the list pages.

Every table in the specification has a drop-down per column and a Search
button (REQ-ARIZA-001, REQ-GLOBAL-001), and the report tables add a period
and an ascending/descending order (REQ-YUKLAMA-001). This is that mechanism,
once: a page declares which columns it filters by, which date its period
narrows, and how its rows may be ordered; the chosen values come from the
query string, and the same object renders the bar and narrows the rows.

Options come from the queryset the page already shows rather than from the
whole table, so a specialist who sees only their own work is offered only the
departments and statuses of that work. A value that is not among the options,
a date that cannot be read and a period that ends before it starts are all
invalid: they are reported, and that filter is not applied, rather than being
dropped silently.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from urllib.parse import urlencode

from django.db.models import F, QuerySet

# The query string name of the ordering drop-down, which every page shares.
SORT_PARAMETER = "tartib"


@dataclass(frozen=True)
class FilterColumn:
    """One column a page may filter by.

    Attributes:
        parameter: the query string name, such as "bolim".
        label: what the drop-down calls the column, such as "Bo'lim".
        value_lookup: the ORM path of the value the query string carries,
            usually a foreign key id such as "department_id".
        label_lookups: the ORM paths whose values, joined with spaces, name
            an option, such as ("department__name",) or a first and last name.
        label_fallback_lookup: the path used when the label lookups are all
            empty, such as a username for an account without a name.
        multi_valued: whether value_lookup crosses a to-many relation, in
            which case the filtered rows are made distinct.
    """

    parameter: str
    label: str
    value_lookup: str
    label_lookups: tuple[str, ...]
    label_fallback_lookup: str | None = None
    multi_valued: bool = False


@dataclass(frozen=True)
class DateColumn:
    """The date a page's period narrows by (REQ-YUKLAMA-001).

    Attributes:
        label: what the period is called, such as "Kelib tushgan sana".
        lookup: the ORM path of the date, such as "kelib_tushgan_sana".
        carries_time: whether the field also stores a time, in which case the
            bounds compare against its calendar day in the active timezone so
            that the last day of a period is included whole.
        start_parameter: the query string name of the start bound.
        end_parameter: the query string name of the end bound.
    """

    label: str
    lookup: str
    carries_time: bool = True
    start_parameter: str = "dan"
    end_parameter: str = "gacha"

    @property
    def comparison_lookup(self) -> str:
        """The ORM path one bound of the period is compared against."""
        return f"{self.lookup}__date" if self.carries_time else self.lookup


@dataclass(frozen=True)
class SortChoice:
    """One entry of the ordering drop-down.

    Attributes:
        value: the query string value, such as "osish".
        label: what the drop-down calls it, such as "Tartib: o'sish".
        order_by: the terms handed to the queryset, as strings or expressions.
    """

    value: str
    label: str
    order_by: tuple[object, ...]


@dataclass(frozen=True)
class FilterOption:
    """One entry of a drop-down: the value posted back and the text shown."""

    value: str
    label: str


@dataclass(frozen=True)
class FilterField:
    """One drop-down as rendered: its column, its options and the chosen value."""

    column: FilterColumn
    options: tuple[FilterOption, ...]
    selected: str

    @property
    def is_active(self) -> bool:
        return bool(self.selected)


def newest_and_oldest_first(lookup: str) -> tuple[SortChoice, SortChoice]:
    """The ordering drop-down of a page ordered by one date, newest first.

    The first choice is the default, so a page keeps the order it had before
    anybody touched the drop-down. Rows without that date sort last either
    way, and the row id breaks ties so two requests agree on the order.
    """
    return (
        SortChoice("kamayish", "Tartib: kamayish", (F(lookup).desc(nulls_last=True), "-id")),
        SortChoice("osish", "Tartib: o'sish", (F(lookup).asc(nulls_last=True), "id")),
    )


class DatePeriod:
    """The period a list page shows, and the rows dated inside it.

    Both bounds are inclusive, and a bound that is absent leaves that side
    open: a start alone means "from this day onward", an end alone means "up
    to and including this day", and neither means the rows are not narrowed
    by date at all. A bound that cannot be read as a date, and a start later
    than the end, are refused - the refusal is reported and no period is
    applied, so nobody is shown a different set of rows than they asked for
    without being told why.

    Args:
        column: the date the page narrows by.
        chosen: the request's query parameters.
    """

    def __init__(self, column: DateColumn, chosen: Mapping[str, str]) -> None:
        self.column = column
        requested_start = (chosen.get(column.start_parameter) or "").strip()
        requested_end = (chosen.get(column.end_parameter) or "").strip()
        self.start = self._as_date(requested_start)
        self.end = self._as_date(requested_end)
        self.refusal = self._refusal(requested_start, requested_end)

    @staticmethod
    def _as_date(requested: str) -> date | None:
        """The requested bound, or None when it is absent or unreadable."""
        try:
            return date.fromisoformat(requested)
        except ValueError:
            return None

    def _refusal(self, requested_start: str, requested_end: str) -> str | None:
        """Why this period was not applied, or None when it was."""
        unreadable = (requested_start and self.start is None) or (
            requested_end and self.end is None
        )
        if unreadable:
            return (
                f"Sana noto'g'ri kiritilgan: {self.column.label}. "
                "Davr bo'yicha filtr qo'llanilmadi."
            )
        if self.start and self.end and self.start > self.end:
            return (
                f"Davr boshlanishi tugashidan keyin: {self.column.label}. "
                "Davr bo'yicha filtr qo'llanilmadi."
            )
        return None

    @property
    def is_active(self) -> bool:
        """Whether a usable bound was chosen."""
        return self.refusal is None and (self.start is not None or self.end is not None)

    @property
    def selections(self) -> dict[str, str]:
        """The usable bounds, by query parameter."""
        if not self.is_active:
            return {}

        bounds = {}
        if self.start is not None:
            bounds[self.column.start_parameter] = self.start.isoformat()
        if self.end is not None:
            bounds[self.column.end_parameter] = self.end.isoformat()
        return bounds

    def apply(self, rows: QuerySet) -> QuerySet:
        """The rows dated inside the period, or every row when it is not usable."""
        if not self.is_active:
            return rows

        narrowed = rows
        if self.start is not None:
            narrowed = narrowed.filter(**{f"{self.column.comparison_lookup}__gte": self.start})
        if self.end is not None:
            narrowed = narrowed.filter(**{f"{self.column.comparison_lookup}__lte": self.end})
        return narrowed


class TableSort:
    """The ordering drop-down of one list page.

    The first choice is the page default, so the drop-down always opens on the
    order the person is already looking at. A value that is not among the
    choices is refused rather than silently ignored.

    Args:
        choices: the orderings the page offers, the first being its default.
        requested: the ordering asked for in the query string.
    """

    def __init__(self, choices: Sequence[SortChoice], requested: str) -> None:
        self.choices = tuple(choices)
        offered = {choice.value for choice in self.choices}
        self.refused = bool(requested) and requested not in offered
        self.selected = requested if requested in offered else self.default

    @property
    def parameter(self) -> str:
        """The query string name of the drop-down, for the template to post back."""
        return SORT_PARAMETER

    @property
    def default(self) -> str:
        """The ordering a page renders in when none was chosen."""
        return self.choices[0].value if self.choices else ""

    @property
    def is_offered(self) -> bool:
        """Whether this page offers an ordering drop-down at all."""
        return bool(self.choices)

    @property
    def is_active(self) -> bool:
        """Whether an ordering other than the page default was chosen."""
        return bool(self.selected) and self.selected != self.default

    @property
    def selections(self) -> dict[str, str]:
        """The chosen ordering, by query parameter, when it is not the default."""
        return {SORT_PARAMETER: self.selected} if self.is_active else {}

    def apply(self, rows: QuerySet) -> QuerySet:
        """The rows in the chosen order, or untouched when no ordering is offered."""
        for choice in self.choices:
            if choice.value == self.selected:
                return rows.order_by(*choice.order_by)
        return rows


class TableFilter:
    """The filter bar of one list page, and the rows it narrows.

    Args:
        columns: the columns the page filters by, in the order they render.
        rows: the queryset the page shows before filtering. Options are
            derived from it, so it must already be narrowed to what the
            current user may see.
        chosen: the request's query parameters. A parameter that is absent
            or empty means "barchasi" for that column.
        date_column: the date the page's period narrows by, when it offers
            one.
        sort_choices: the orderings the page offers, the first being its
            default. A page that offers none keeps the order of its queryset.
    """

    def __init__(
        self,
        columns: Sequence[FilterColumn],
        rows: QuerySet,
        chosen: Mapping[str, str] | None = None,
        *,
        date_column: DateColumn | None = None,
        sort_choices: Sequence[SortChoice] = (),
    ) -> None:
        self.rows = rows
        self._invalid_labels: list[str] = []
        chosen = chosen or {}
        self.fields: tuple[FilterField, ...] = tuple(
            self._field(column, (chosen.get(column.parameter) or "").strip()) for column in columns
        )
        self.period = DatePeriod(date_column, chosen) if date_column is not None else None
        self.sort = TableSort(sort_choices, (chosen.get(SORT_PARAMETER) or "").strip())
        if self.sort.refused:
            self._invalid_labels.append("Tartib")

    def _field(self, column: FilterColumn, requested: str) -> FilterField:
        options = self._options(column)
        selected = requested if requested in {option.value for option in options} else ""
        field = FilterField(column=column, options=options, selected=selected)
        if requested and not selected:
            self._invalid_labels.append(column.label)
        return field

    def _options(self, column: FilterColumn) -> tuple[FilterOption, ...]:
        """The distinct values present in this column, labelled and sorted."""
        lookups = [column.value_lookup, *column.label_lookups]
        if column.label_fallback_lookup:
            lookups.append(column.label_fallback_lookup)

        seen: dict[str, str] = {}
        for row in self.rows.order_by().values_list(*lookups).distinct():
            value, *label_parts = row
            if value is None:
                continue
            fallback = label_parts.pop() if column.label_fallback_lookup else ""
            label = " ".join(str(part) for part in label_parts if part).strip()
            seen.setdefault(str(value), label or str(fallback) or str(value))

        return tuple(
            sorted(
                (FilterOption(value, label) for value, label in seen.items()),
                key=lambda option: option.label.casefold(),
            )
        )

    @property
    def invalid(self) -> tuple[str, ...]:
        """The labels of the controls whose requested value is not an option."""
        return tuple(self._invalid_labels)

    @property
    def is_active(self) -> bool:
        """Whether a filter, a period, or a non-default ordering is chosen."""
        return (
            any(field.is_active for field in self.fields)
            or (self.period is not None and self.period.is_active)
            or self.sort.is_active
        )

    @property
    def selections(self) -> dict[str, str]:
        """The valid choices, by query parameter."""
        chosen = {
            field.column.parameter: field.selected for field in self.fields if field.is_active
        }
        if self.period is not None:
            chosen.update(self.period.selections)
        chosen.update(self.sort.selections)
        return chosen

    @property
    def query_string(self) -> str:
        """The valid choices as a query string, without a leading '?'."""
        return urlencode(self.selections)

    def apply(self) -> QuerySet:
        """The rows narrowed by every valid choice, in the chosen order."""
        narrowed = self.rows
        distinct = False
        for field in self.fields:
            if not field.is_active:
                continue
            narrowed = narrowed.filter(**{field.column.value_lookup: field.selected})
            distinct = distinct or field.column.multi_valued

        if self.period is not None:
            narrowed = self.period.apply(narrowed)
        if distinct:
            narrowed = narrowed.distinct()
        return self.sort.apply(narrowed)


def report_invalid_filters(request, table_filter: TableFilter) -> None:
    """Tell the person which choice was refused (never silently dropped)."""
    from django.contrib import messages

    for label in table_filter.invalid:
        messages.error(
            request,
            f"Noma'lum filtr qiymati: {label}. Bu filtr qo'llanilmadi.",
        )

    if table_filter.period is not None and table_filter.period.refusal:
        messages.error(request, table_filter.period.refusal)
