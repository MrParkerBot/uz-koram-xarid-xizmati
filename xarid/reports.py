"""The counting behind the Hisobotlar pages.

A report table in the specification is the same shape every time: a row per
something (an employee, a department), a counter per contract status, and a
totals row under them (REQ-YUKLAMA-002, REQ-XARID-001). The statuses are not
a fixed list - they are master data anybody may add to (DEC-010) - so the
columns are generated from the active ShartnomaStatus rows rather than named
in the code or in a template.

Counting is done in one annotated query per report rather than one query per
status, so adding a status adds a column and not a round trip.

A purchase application may carry more than one contract: a refused one and
the contract raised to replace it. Such an application is counted under every
status it has a contract in, and once in its owner's assignment total. The
counters therefore say how much work stands in each state, which is what the
report is read for, and they may sum to more than the total.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from django.contrib.auth.models import AbstractBaseUser
from django.db.models import Count, Q

from xarid.exports import ExportColumn, TableExport
from xarid.filters import DatePeriod
from xarid.models import (
    Contract,
    Department,
    MahsulotTuri,
    ShartnomaStatus,
    Supplier,
    assignable_specialists,
)

# The ORM path from a specialist to one of their assigned applications, and
# from there to the status of a contract raised against it.
ASSIGNED_APPLICATIONS = "assigned_applications"
ASSIGNED_CONTRACT_STATUS = "assigned_applications__contracts__status"

# What the totals row is called, on the page and in a download alike.
TOTALS_LABEL = "Jami:"

# The same two paths read from a department, which owns the applications it
# raised rather than the ones it was given.
DEPARTMENT_APPLICATIONS = "applications"
DEPARTMENT_CONTRACT_STATUS = "applications__contracts__status"

# And from a product type, which is reached through the order lines that name
# it. Counting the applications rather than the lines is what makes an
# application ordering two things of one type count once.
CATEGORY_APPLICATIONS = "application_items__application"
CATEGORY_CONTRACT_STATUS = "application_items__application__contracts__status"


@dataclass(frozen=True)
class StatusColumn:
    """One generated counter column of a report.

    Attributes:
        status: the contract status this column counts.
        alias: the annotation name holding the count, unique per status.
    """

    status: ShartnomaStatus
    alias: str

    @property
    def label(self) -> str:
        """What the column header calls it."""
        return self.status.name

    @property
    def badge_class(self) -> str:
        """The CSS class of the status badge, so the header matches the data."""
        return self.status.badge_class


@dataclass(frozen=True)
class ReportRow:
    """One row of a report: what it is about, and its counters.

    Attributes:
        subject_label: what the row's first cell prints - a person's name or
            a department's.
        detail: the second cell, such as a phone number; empty when the
            report has nothing to put there.
        total: how many purchase applications the subject holds in the
            period, however far they have got.
        counters: one count per StatusColumn, in the columns' order.
        subject_id: the primary key of what the row reports on, for a page
            that links its rows somewhere. None when the row links nowhere.
    """

    subject_label: str
    detail: str
    total: int
    counters: tuple[int, ...]
    subject_id: int | None = None


@dataclass(frozen=True)
class ReportTotals:
    """The sum of every column, as the last row of a report."""

    total: int
    counters: tuple[int, ...]


@dataclass(frozen=True)
class Report:
    """A report table: its generated columns, its rows and its totals."""

    columns: tuple[StatusColumn, ...]
    rows: tuple[ReportRow, ...]
    totals: ReportTotals

    @property
    def has_rows(self) -> bool:
        """Whether there is anything to print under the header."""
        return bool(self.rows)

    @property
    def busiest(self) -> int:
        """The largest assignment total, which the page prints in colour.

        Zero when nobody holds anything, so an empty report highlights
        nothing rather than every row.
        """
        return max((row.total for row in self.rows), default=0)

    @property
    def subject_count(self) -> int:
        """How many subjects the report covers, for the page's first figure."""
        return len(self.rows)

    @property
    def export_rows(self) -> tuple[ReportRow, ...]:
        """The rows a download holds: the report's, then the totals as one more.

        The totals are the last row of the page too, and giving them the same
        shape as any other row is what stops a file's totals drifting from its
        columns - there is one way to read a counter, not two.
        """
        if not self.rows:
            return ()

        return (
            *self.rows,
            ReportRow(
                subject_label=TOTALS_LABEL,
                detail="",
                total=self.totals.total,
                counters=self.totals.counters,
            ),
        )


def status_columns() -> tuple[StatusColumn, ...]:
    """One column per active contract status, in the configured order.

    The order is ShartnomaStatus's own - its position, then its name - so the
    report reads left to right the way the status list is maintained
    (DEC-010). A deactivated status keeps its history but stops being a
    column.
    """
    return tuple(
        StatusColumn(status=status, alias=f"holat_{status.pk}")
        for status in ShartnomaStatus.objects.active()
    )


def status_counters(
    columns: tuple[StatusColumn, ...],
    counted: str,
    status_lookup: str,
    inside_period: Q,
) -> dict[str, Count]:
    """One distinct count per column, narrowed to the period.

    Args:
        columns: the generated status columns.
        counted: the ORM path of the rows being counted, such as
            "assigned_applications".
        status_lookup: the ORM path from the counted rows to the contract
            status they stand in.
        inside_period: the period condition, empty when no period is chosen.

    Returns:
        The annotations, by alias. Distinct, so an application carrying two
        contracts in the same status is one application, not two.
    """
    return {
        column.alias: Count(
            counted,
            filter=Q(**{status_lookup: column.status}) & inside_period,
            distinct=True,
        )
        for column in columns
    }


def totals_of(columns: tuple[StatusColumn, ...], rows: tuple[ReportRow, ...]) -> ReportTotals:
    """The sum of each column across the rows."""
    return ReportTotals(
        total=sum(row.total for row in rows),
        counters=tuple(sum(row.counters[index] for row in rows) for index in range(len(columns))),
    )


def name_of(person: AbstractBaseUser) -> str:
    """The person's name as a report prints it, falling back to the username."""
    return person.get_full_name().strip() or person.get_username()


def phone_of(person: AbstractBaseUser) -> str:
    """The phone number on the person's profile, or an empty string."""
    profile = getattr(person, "profile", None)
    return profile.phone_number if profile else ""


def staff_workload(period: DatePeriod | None) -> Report:
    """The Xodimlar yuklamasi report (REQ-YUKLAMA-002).

    A row per account that may be assigned purchase work, whether or not it
    holds any: an employee with nothing to do is what the department head is
    reading the report for, not an omission.

    The busiest specialist comes first, as the departments report puts the
    busiest department first: both pages are read to find where the load is,
    and they should answer that the same way. A tie breaks by name, so two
    requests agree on the order.

    Args:
        period: the period chosen in the filter bar, which narrows by the
            date an application was assigned. None, or a period that was
            refused, means all time.

    Returns:
        The generated columns, a row per specialist and the totals row.
    """
    inside_period = period.as_condition(f"{ASSIGNED_APPLICATIONS}__") if period else Q()
    columns = status_columns()
    specialists = (
        assignable_specialists()
        .select_related("profile")
        .annotate(
            topshiriqlar=Count(ASSIGNED_APPLICATIONS, filter=inside_period, distinct=True),
            **status_counters(
                columns, ASSIGNED_APPLICATIONS, ASSIGNED_CONTRACT_STATUS, inside_period
            ),
        )
        .order_by("-topshiriqlar", "first_name", "last_name", "username")
    )

    rows = tuple(
        ReportRow(
            subject_label=name_of(specialist),
            detail=phone_of(specialist),
            total=specialist.topshiriqlar,
            counters=tuple(getattr(specialist, column.alias) for column in columns),
        )
        for specialist in specialists
    )
    return Report(columns=columns, rows=rows, totals=totals_of(columns, rows))


def department_purchasing(period: DatePeriod | None, chosen_department: str = "") -> Report:
    """The Korhona xaridi | Bo`limlar report (REQ-XARID-001).

    A row per active department: how many purchase applications it raised,
    and how many of them stand in each contract status. A department that
    raised nothing still has a row of zeros - the department head is reading
    the report to compare departments, and a missing one is not a comparison.

    The busiest department comes first, because which department consumes the
    most purchasing effort is the question the page answers; a tie breaks by
    name so two requests agree on the order.

    Args:
        period: the period chosen in the filter bar, which narrows by the
            date an application arrived. None, or a period that was refused,
            means all time.
        chosen_department: the department chosen in the bar, as its primary
            key; empty means every department.

    Returns:
        The generated columns, a row per department and the totals row.
    """
    inside_period = period.as_condition(f"{DEPARTMENT_APPLICATIONS}__") if period else Q()
    columns = status_columns()
    departments = Department.objects.active()
    if chosen_department:
        departments = departments.filter(pk=chosen_department)

    counted = departments.annotate(
        arizalar=Count(DEPARTMENT_APPLICATIONS, filter=inside_period, distinct=True),
        **status_counters(
            columns, DEPARTMENT_APPLICATIONS, DEPARTMENT_CONTRACT_STATUS, inside_period
        ),
    ).order_by("-arizalar", "name")

    rows = tuple(
        ReportRow(
            subject_label=department.name,
            detail="",
            total=department.arizalar,
            counters=tuple(getattr(department, column.alias) for column in columns),
            subject_id=department.pk,
        )
        for department in counted
    )
    return Report(columns=columns, rows=rows, totals=totals_of(columns, rows))


def report_export(
    report: Report,
    filename_stem: str,
    subject_label: str,
    total_label: str,
    detail_label: str | None = None,
) -> TableExport:
    """One report as a downloadable table (REQ-YUKLAMA-001, REQ-XARID-001).

    The columns are built per request rather than declared once, because a
    report's counter columns are the active contract statuses and anybody may
    add one (DEC-010). The leading columns differ per report - the workload
    report names a phone number where the departments report has nothing - so
    each page says what to call its own.

    Each export row is a pair of the report row and its ordinal, which is what
    the # column prints; a list page puts an order line in that second slot
    instead. The totals row carries a blank ordinal, as the page gives it a
    colspan rather than a number.

    Args:
        report: the report as the page renders it, already narrowed.
        filename_stem: what the downloaded file is called, before the date.
        subject_label: the header of the first named column, such as "Xodim".
        total_label: the header of the count column, such as
            "Xarid topshiriqlari".
        detail_label: the header of the column between them, when the report
            has one; None leaves that column out entirely.

    Returns:
        The table, ready for excel_response or pdf_response.
    """
    columns = [
        ExportColumn("#", lambda _row, ordinal: ordinal),
        ExportColumn(subject_label, lambda row, _ordinal: row.subject_label),
    ]
    if detail_label is not None:
        columns.append(ExportColumn(detail_label, lambda row, _ordinal: row.detail))
    columns.append(ExportColumn(total_label, lambda row, _ordinal: row.total))
    columns.extend(
        ExportColumn(column.label, _counter_at(index))
        for index, column in enumerate(report.columns)
    )

    rows = [
        (row, "" if row.subject_label == TOTALS_LABEL else ordinal)
        for ordinal, row in enumerate(report.export_rows, start=1)
    ]
    return TableExport(filename_stem, tuple(columns), rows)


def _counter_at(index: int) -> Callable[[ReportRow, object], int]:
    """Reads one generated column's counter, by its place in the columns.

    The export columns and the row counters come from the same
    status_columns() call inside one request, so the index means the same
    thing on both sides.
    """
    return lambda row, _ordinal: row.counters[index]

def category_purchasing(period: DatePeriod | None, chosen_category: str = "") -> Report:
    """The Korhona xaridi | Mahsulot Turi report (REQ-XARID-002).

    A row per active product type: how many purchase applications ordered
    something of that type, and how many of those stand in each contract
    status. A type nothing has ordered still has a row of zeros, for the same
    reason a quiet department does - the page is read to compare types.

    A type is reached through the order lines that name it, so the counts are
    distinct: an application ordering two things of one type counts once for
    that type, and an application ordering two different types counts once
    under each.

    Args:
        period: the period chosen in the filter bar, which narrows by the
            date an application arrived. None, or a refused period, means all
            time.
        chosen_category: the type chosen in the bar, as its primary key;
            empty means every type.

    Returns:
        The generated columns, a row per type and the totals row.
    """
    # No prefix here, unlike the other two reports: this report's period is
    # declared with the path from a product type already in it, so that the
    # page's filter bar can apply the same period to its own rows.
    inside_period = period.as_condition() if period else Q()
    columns = status_columns()
    categories = MahsulotTuri.objects.active()
    if chosen_category:
        categories = categories.filter(pk=chosen_category)

    counted = categories.annotate(
        arizalar=Count(CATEGORY_APPLICATIONS, filter=inside_period, distinct=True),
        **status_counters(
            columns, CATEGORY_APPLICATIONS, CATEGORY_CONTRACT_STATUS, inside_period
        ),
    ).order_by("-arizalar", "name")

    rows = tuple(
        ReportRow(
            subject_label=category.name,
            detail=str(category.category_number),
            total=category.arizalar,
            counters=tuple(getattr(category, column.alias) for column in columns),
            subject_id=category.pk,
        )
        for category in counted
    )
    return Report(columns=columns, rows=rows, totals=totals_of(columns, rows))


# ---------------------------------------------------------------------------
# The dashboard indicators (section 2, REQ-DASH-001 to REQ-DASH-004)
# ---------------------------------------------------------------------------

# How many percent make a full progress bar. A supplier may hold more than one
# contract, so a percentage above this is possible and is reported as it is;
# only the bar stops at its own end.
FULL_BAR = 100


@dataclass(frozen=True)
class Indicator:
    """One counted figure and what it comes to against the supplier count.

    Attributes:
        count: how many contracts were counted.
        measured_against: what they were measured against - the supplier
            count.
        percentage: count as a percentage of measured_against, to the nearest
            whole percent, and zero when there is nothing to measure against.
    """

    count: int
    measured_against: int
    percentage: int

    @property
    def bar_width(self) -> int:
        """How much of the card's progress bar to fill, which cannot overflow."""
        return min(self.percentage, FULL_BAR)


@dataclass(frozen=True)
class DashboardIndicators:
    """The three contract indicators the dashboard opens with."""

    supplier_count: int
    created: Indicator
    completed: Indicator


def as_percentage_of(count: int, supplier_count: int) -> Indicator:
    """One indicator: a count, and what it is as a percentage of the suppliers.

    A department with no suppliers on file is not an error - it is a database
    nobody has filled in yet - so the percentage is zero rather than a
    division.
    """
    percentage = round(count * 100 / supplier_count) if supplier_count else 0
    return Indicator(count=count, measured_against=supplier_count, percentage=percentage)


def dashboard_indicators() -> DashboardIndicators:
    """How many suppliers there are, and how much of that has contracts.

    The specification asks for the created and the completed contracts as
    percentages of the supplier count (REQ-DASH-003, REQ-DASH-004), which is
    a ratio rather than a share: one supplier may hold several contracts, so
    a figure above 100% means exactly that and is not clamped.

    Deleted suppliers are left out. DEC-009 deletes a master data row by
    deactivating it, so an active row is a supplier the department still has.

    Completed means the status marked as the completed state on the Shartnoma
    Status page; when no status is marked, nothing counts as completed.

    Returns:
        The supplier count and the two indicators measured against it.
    """
    supplier_count = Supplier.objects.active().count()
    completed_status = ShartnomaStatus.completed_status()
    contracts = Contract.objects.all()
    completed_count = contracts.filter(status=completed_status).count() if completed_status else 0

    return DashboardIndicators(
        supplier_count=supplier_count,
        created=as_percentage_of(contracts.count(), supplier_count),
        completed=as_percentage_of(completed_count, supplier_count),
    )
