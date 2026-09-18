"""Per-column filtering for the list pages (REQ-ARIZA-001, REQ-GLOBAL-001).

Every table in the specification has a drop-down per column and a Search
button. This is that mechanism, once: a page declares which columns it
filters by, the options of each drop-down are derived from the data actually
in that column, the chosen values come from the query string, and the same
object renders the bar and narrows the rows.

Options come from the queryset the page already shows rather than from the
whole table, so a specialist who sees only their own work is offered only the
departments and statuses of that work. A value that is not among the options
is invalid: it is reported, and that filter is not applied, rather than being
dropped silently.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from urllib.parse import urlencode

from django.db.models import QuerySet


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


class TableFilter:
    """The filter bar of one list page, and the rows it narrows.

    Args:
        columns: the columns the page filters by, in the order they render.
        rows: the queryset the page shows before filtering. Options are
            derived from it, so it must already be narrowed to what the
            current user may see.
        chosen: the request's query parameters. A parameter that is absent
            or empty means "barchasi" for that column.
    """

    def __init__(
        self,
        columns: Sequence[FilterColumn],
        rows: QuerySet,
        chosen: Mapping[str, str] | None = None,
    ) -> None:
        self.rows = rows
        self._invalid_labels: list[str] = []
        chosen = chosen or {}
        self.fields: tuple[FilterField, ...] = tuple(
            self._field(column, (chosen.get(column.parameter) or "").strip()) for column in columns
        )

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
        """The labels of the columns whose requested value is not an option."""
        return tuple(self._invalid_labels)

    @property
    def is_active(self) -> bool:
        """Whether at least one valid filter is chosen."""
        return any(field.is_active for field in self.fields)

    @property
    def selections(self) -> dict[str, str]:
        """The valid choices, by query parameter."""
        return {field.column.parameter: field.selected for field in self.fields if field.is_active}

    @property
    def query_string(self) -> str:
        """The valid choices as a query string, without a leading '?'."""
        return urlencode(self.selections)

    def apply(self) -> QuerySet:
        """The rows narrowed by every valid choice."""
        narrowed = self.rows
        distinct = False
        for field in self.fields:
            if not field.is_active:
                continue
            narrowed = narrowed.filter(**{field.column.value_lookup: field.selected})
            distinct = distinct or field.column.multi_valued

        return narrowed.distinct() if distinct else narrowed


def report_invalid_filters(request, table_filter: TableFilter) -> None:
    """Tell the person which filter value was refused (never silently dropped)."""
    from django.contrib import messages

    for label in table_filter.invalid:
        messages.error(
            request,
            f"Noma'lum filtr qiymati: {label}. Bu filtr qo'llanilmadi.",
        )
