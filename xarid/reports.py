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

from dataclasses import dataclass

from django.contrib.auth.models import AbstractBaseUser
from django.db.models import Count, Q

from xarid.filters import DatePeriod
from xarid.models import Department, ShartnomaStatus, assignable_specialists

# The ORM path from a specialist to one of their assigned applications, and
# from there to the status of a contract raised against it.
ASSIGNED_APPLICATIONS = "assigned_applications"
ASSIGNED_CONTRACT_STATUS = "assigned_applications__contracts__status"

# The same two paths read from a department, which owns the applications it
# raised rather than the ones it was given.
DEPARTMENT_APPLICATIONS = "applications"
DEPARTMENT_CONTRACT_STATUS = "applications__contracts__status"


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
