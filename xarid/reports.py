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

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from django.contrib.auth.models import AbstractBaseUser
from django.db.models import Count, DateField, Q, QuerySet, Sum
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone

from xarid.exports import ExportColumn, TableExport
from xarid.filters import DateColumn, DatePeriod, FilterColumn
from xarid.models import (
    Contract,
    ContractStatusChange,
    Department,
    MahsulotTuri,
    ShartnomaStatus,
    Supplier,
    assignable_specialists,
    money_display,
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


def whole_percent(part: Decimal | int, whole: Decimal | int) -> int:
    """`part` as a percentage of `whole`, to the nearest whole percent.

    Zero when there is nothing to measure against, rather than a division: a
    database nobody has filled in yet is not an error.

    A half rounds up, which is the arithmetic somebody checking the figure by
    hand will have done. Python's own round() would send 12.5% down to 12 and
    13.5% up to 14, which is defensible statistics and an odd thing to have to
    explain to the department. Every percentage on the dashboard comes through
    here, so there is one answer to "how does this round" rather than one per
    panel.
    """
    if not whole:
        return 0

    exact = Decimal(part) * 100 / Decimal(whole)

    return int(exact.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def as_percentage_of(count: int, supplier_count: int) -> Indicator:
    """One indicator: a count, and what it is as a percentage of the suppliers."""
    return Indicator(
        count=count,
        measured_against=supplier_count,
        percentage=whole_percent(count, supplier_count),
    )


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


# ---------------------------------------------------------------------------
# The dashboard spendings (section 2, REQ-DASH-008 and REQ-DASH-010)
# ---------------------------------------------------------------------------

# The date a contract is accounted under: the date on the contract itself,
# and where there is none the day it was raised. The entry form requires the
# contract date, but the column allows null - a contract loaded some other
# way must still be counted somewhere rather than falling out of every total.
ACCOUNTING_DATE = "hisob_sanasi"

# The period bar the dashboard offers, narrowing by that date.
SPENDINGS_PERIOD = DateColumn("Shartnoma sanasi", ACCOUNTING_DATE, carries_time=False)

NOTHING = Decimal("0")

# What money_display() puts between the soums and the tiyin.
DECIMAL_SEPARATOR = ","


def dated_contracts() -> QuerySet:
    """Every contract, carrying the date its money is accounted under."""
    return Contract.objects.annotate(
        **{
            ACCOUNTING_DATE: Coalesce(
                "shartnoma_sanasi",
                TruncDate("yaratilingan_sana"),
                output_field=DateField(),
            )
        }
    )


@dataclass(frozen=True)
class Money:
    """An amount of soums, and the two ways the dashboard prints it.

    Attributes:
        amount: the exact total, in UZS (DEC-026).
    """

    amount: Decimal

    @property
    def display(self) -> str:
        """The exact amount, grouped: 1 240 000 000,00."""
        return money_display(self.amount)

    @property
    def whole_display(self) -> str:
        """The amount to the soum, for a headline with no room for tiyin.

        The same grouping as `display`, with the tiyin removed - and removed
        by taking what money_display() put before its decimal separator, or
        the whole of it when there is none. A card whose only figure silently
        rendered as an empty string would be the one failure nobody reports.
        """
        whole = self.amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        grouped = money_display(whole)
        soums, separator, _tiyin = grouped.rpartition(DECIMAL_SEPARATOR)

        return soums if separator else grouped


@dataclass(frozen=True)
class SpendingIndicators:
    """What the department committed, in the chosen period and in the year.

    Attributes:
        period: the total inside the period the reader chose, or everything
            on file when no period was chosen.
        year: the total agreed across the current calendar year, which the
            period never narrows.
        year_number: the calendar year `year` covers, so the card can name it.
    """

    period: Money
    year: Money
    year_number: int


def total_value_of(contracts: QuerySet) -> Money:
    """What these contracts come to. An empty set is 0,00, not nothing."""
    return Money(contracts.aggregate(total=Sum("qiymati"))["total"] or NOTHING)


def spending_indicators(period: DatePeriod | None) -> SpendingIndicators:
    """The spend inside the period and the year's agreed total.

    Both are sums of Contract.qiymati, which is the value of the goods rows
    (REQ-SHARTNOMA-006) and is held in UZS (DEC-026). Every contract counts:
    nothing in this system records money as unspent, so a contract that was
    rejected is still money the department committed on paper, and the
    acceptance criterion asks for the sum of contract values in the period.

    The yearly figure ignores the period deliberately - the specification
    asks for the total agreed during the year (REQ-DASH-008) beside the
    spend of the period being looked at (REQ-DASH-010), so narrowing to one
    week must not move it.

    Args:
        period: the period chosen in the bar. None, or a refused period,
            means every contract on file.

    Returns:
        The period total, the year total and the year it covers.
    """
    contracts = dated_contracts()
    year = timezone.localdate().year

    return SpendingIndicators(
        period=total_value_of(period.apply(contracts) if period else contracts),
        year=total_value_of(
            contracts.filter(
                **{
                    f"{ACCOUNTING_DATE}__gte": date(year, 1, 1),
                    f"{ACCOUNTING_DATE}__lte": date(year, 12, 31),
                }
            )
        ),
        year_number=year,
    )


# ---------------------------------------------------------------------------
# Average processing time (section 2, REQ-DASH-012)
# ---------------------------------------------------------------------------

# The specification names four stages and no events (REQ-DASH-012); only the
# Invoice source is decided, by DEC-025. What each stage is measured between
# is therefore chosen here, printed on the page beside the figure and written
# into the README, so the department can argue with a definition it can see.
#
# Approval is measured from the contract being raised rather than from
# Contract.yuborilgan_sana, which a resend overwrites (DEC-024): a contract
# sent twice would otherwise report only the time since its last send, which
# is shorter, wrong, and invisible.

ORDER_ENTRY = "Buyurtma kiritish"
APPROVAL = "Tasdiqlash"
DELIVERY = "Yetkazib berish"
INVOICE = "Invoice"

# What each stage spans, in the words the panel prints under its name. Kept
# beside the labels so that a stage is one entry rather than a name here and
# a sentence somewhere else, and read through span_of() so a stage that was
# never given one says which stage it is.
STAGE_SPANS: dict[str, str] = {
    ORDER_ENTRY: "Ariza kelib tushgandan shartnoma kiritilgunga qadar",
    APPROVAL: "Shartnoma kiritilgandan tasdiqlangunga qadar",
    DELIVERY: "Tasdiqlangandan tugallangan holatga o`tgunga qadar",
    INVOICE: "Tugallangan holatdan invoice sanasigacha",
}


def span_of(label: str) -> str:
    """What a stage is measured between, or a stated gap when it has no entry."""
    return STAGE_SPANS.get(label, f"{label}: bosqich chegaralari ko`rsatilmagan")


@dataclass(frozen=True)
class StageAverage:
    """One stage of the processing time, and how long it takes.

    Attributes:
        label: the stage's name, as the specification lists it.
        span: what the average is measured between, for the panel to print.
        days: the mean gap in whole days, or None when nothing completed the
            stage. None rather than zero: no contract taking no time and no
            contract at all are different answers.
        measured_from: how many contracts the average is drawn from.
    """

    label: str
    span: str
    days: int | None
    measured_from: int

    @property
    def was_measured(self) -> bool:
        """Whether anything completed this stage."""
        return self.days is not None


def as_local_date(moment: datetime | date | None) -> date | None:
    """One recorded moment as the calendar day it happened on, or None.

    A stage may span a DateTimeField at one end and a DateField at the other
    - delivery ends on a recorded change, invoice on the date written on the
    supplier's paper - and "in number of days" (REQ-DASH-012) is a question
    about days, not about hours. Reducing both ends to a local day is what
    lets them be subtracted at all.
    """
    if moment is None:
        return None
    if isinstance(moment, datetime):
        return timezone.localtime(moment).date()
    return moment


def gap_in_days(start: datetime | date | None, end: datetime | date | None) -> int | None:
    """How many days from start to end, or None when either was not recorded.

    A negative gap is returned as it is rather than clamped: it means the two
    dates contradict each other, and an average that quietly hid it would
    leave nobody any way of noticing.
    """
    first, last = as_local_date(start), as_local_date(end)
    if first is None or last is None:
        return None
    return (last - first).days


def averaged(label: str, gaps: Iterable[int | None]) -> StageAverage:
    """One stage's average over the gaps that were measurable."""
    measured = [gap for gap in gaps if gap is not None]
    mean = round(sum(measured) / len(measured)) if measured else None

    return StageAverage(
        label=label,
        span=span_of(label),
        days=mean,
        measured_from=len(measured),
    )


def completed_at() -> dict[int, datetime]:
    """When each contract first entered the status marked completed.

    The first arrival, not the last: a contract moved out of the completed
    status and back again was delivered once, on the day it first got there.
    Contracts that never arrived are absent from the mapping.

    Every move is read in one query, rather than the contracts being handed
    back to the database as a list of ids - one bound variable each, which
    SQLite refuses past its own limit, on a page that would then not render
    at all.
    """
    completed = ShartnomaStatus.completed_status()
    if completed is None:
        return {}

    arrivals: dict[int, datetime] = {}
    moves = (
        ContractStatusChange.objects.filter(to_status=completed)
        .order_by("changed_at")
        .values_list("contract_id", "changed_at")
    )
    for contract_id, changed_at in moves:
        arrivals.setdefault(contract_id, changed_at)

    return arrivals


def processing_times() -> tuple[StageAverage, ...]:
    """The four stages of REQ-DASH-012, in the order the document lists them.

    Each average covers only the contracts that recorded both of its ends; a
    contract still awaiting approval is not an approval taking zero days, and
    a stage nothing has completed has no average at all.

    One consequence is worth knowing: Invoice runs from the move into the
    completed status, so an invoice recorded against a contract nobody has
    moved there has no start and is not counted. Invoices arriving before
    the status is updated would therefore leave that stage reading a dash
    while the dates pile up. It is the stage the department asked for
    (DEC-025); if it stays empty, the status is not being kept, and that is
    worth knowing too.

    Returns:
        Buyurtma kiritish, Tasdiqlash, Yetkazib berish and Invoice.
    """
    contracts = Contract.objects.values_list(
        "id",
        "application__kelib_tushgan_sana",
        "yaratilingan_sana",
        "tasdiqlangan_sana",
        "invoice_sanasi",
    )
    rows = list(contracts)
    delivered_at = completed_at()

    entry, approval, delivery, invoice = [], [], [], []
    for contract_id, arrived, raised, approved, invoiced in rows:
        delivered = delivered_at.get(contract_id)
        entry.append(gap_in_days(arrived, raised))
        approval.append(gap_in_days(raised, approved))
        delivery.append(gap_in_days(approved, delivered))
        invoice.append(gap_in_days(delivered, invoiced))

    return (
        averaged(ORDER_ENTRY, entry),
        averaged(APPROVAL, approval),
        averaged(DELIVERY, delivery),
        averaged(INVOICE, invoice),
    )


# ---------------------------------------------------------------------------
# Top suppliers (section 2 and its own page, REQ-DASH-005, REQ-DASH-006)
# ---------------------------------------------------------------------------

# How many rows the dashboard's panel shows. The page itself shows them all.
DASHBOARD_TOP_SUPPLIERS = 5

# The Daraja filter both the page and its bar use. Free text on the supplier
# record (DEC-025), so the options are whatever levels have been recorded.
BY_DARAJA = FilterColumn(
    parameter="daraja",
    label="Daraja",
    value_lookup="daraja",
    label_lookups=("daraja",),
)


@dataclass(frozen=True)
class SupplierRank:
    """One firm's place in the ranking.

    Attributes:
        place: its position in the list, counting from one.
        supplier: the firm.
        contracts: how many of its contracts fall inside the period.
        total: what those contracts come to, in UZS.
        share_of_leader: the total as a percentage of the first row's, for the
            panel's bar. One hundred for the leader; zero when nothing is
            ranked.
    """

    place: int
    supplier: Supplier
    contracts: int
    total: Money
    share_of_leader: int


def daraja_options() -> QuerySet:
    """The suppliers a Daraja drop-down draws its options from.

    Only those with a level recorded: a blank Daraja would otherwise become an
    option whose value is the empty string, which the bar already spends on
    "barchasi".
    """
    return Supplier.objects.active().exclude(daraja="")


def top_suppliers(
    period: DatePeriod | None,
    daraja: str = "",
    limit: int | None = None,
) -> tuple[SupplierRank, ...]:
    """The firms ranked by what their contracts come to (DEC-025).

    Ranked by total contract value inside the period, highest first, with the
    firm's name breaking a tie so that two equal totals do not swap places
    between one render and the next.

    A firm with no contracts in the period is not ranked. A ranking of what
    the department spent has nothing to say about a firm it spent nothing
    with, and padding the list with zeros would push the firms the page is
    read for further down it.

    A deleted firm is still ranked, unlike the dashboard's supplier count,
    which leaves it out. The two are asking different questions: the count is
    how many firms the department has, which a deleted one is not, and this
    is what the department spent, which a deletion does not unspend. Deleting
    a firma deactivates it (DEC-009), and money already paid to it stays in
    its own row rather than vanishing from the ranking's totals.

    Args:
        period: the period chosen in the bar, applied to the contract's
            accounting date exactly as the dashboard's spend is. None, or a
            refused period, means every contract on file.
        daraja: the level chosen in the bar; empty means every level.
        limit: how many rows to return, for the dashboard's panel. None means
            the whole ranking.

    Returns:
        The ranking, in order, each row carrying its place and its share of
        the leader's total.
    """
    contracts = dated_contracts()
    if period:
        contracts = period.apply(contracts)
    if daraja:
        contracts = contracts.filter(supplier__daraja=daraja)

    totalled = (
        contracts.values("supplier")
        .annotate(qiymat=Sum("qiymati"), soni=Count("pk"))
        .order_by("-qiymat", "supplier__name")
    )
    if limit is not None:
        totalled = totalled[:limit]

    counted = list(totalled)
    suppliers = Supplier.objects.in_bulk([row["supplier"] for row in counted])

    # Every row resolves: Contract.supplier is PROTECT, so a firm holding a
    # contract cannot be deleted from under it. One that somehow does not is
    # dropped here rather than raising a KeyError out of a report - and
    # dropped before the places are handed out, so the ranking cannot come
    # back numbered 1, 3, 4.
    rows = [row for row in counted if row["supplier"] in suppliers]
    leader = rows[0]["qiymat"] if rows else NOTHING

    return tuple(
        SupplierRank(
            place=place,
            supplier=suppliers[row["supplier"]],
            contracts=row["soni"],
            total=Money(row["qiymat"]),
            share_of_leader=whole_percent(row["qiymat"], leader),
        )
        for place, row in enumerate(rows, start=1)
    )


# ---------------------------------------------------------------------------
# The supplier category block (section 2, REQ-DASH-007, REQ-DASH-009)
# ---------------------------------------------------------------------------

# The ORM path from a product type to the firms that supply it: the order
# lines naming the type, the applications carrying those lines, and the
# contracts raised against them.
#
# A contract is against an application, not against one of its lines, so an
# application ordering steel and cable with a single contract credits that
# firm with both. Nothing in the data model says which line a contract
# covers; the block answers "which types is this firm involved in" rather
# than "which types did it deliver", and there is no narrower question to
# ask of these tables.
CATEGORY_SUPPLIERS = "application_items__application__contracts__supplier"

# The same path, continued to the status of those contracts, for counting the
# types that actually reached the completed state.
CATEGORY_CONTRACT_STATE = "application_items__application__contracts__status"


@dataclass(frozen=True)
class CategoryShare:
    """One product type and how much of the department's supply base it is.

    Attributes:
        category: the product type.
        firms: how many distinct firms supply it. A firm with four contracts
            for one type is one firm.
        share: that count as a percentage of every count in the table.
    """

    category: MahsulotTuri
    firms: int
    share: int


@dataclass(frozen=True)
class SupplierCategories:
    """The category block: its rows, what the shares divide by, and the total.

    Attributes:
        rows: a row per active product type, busiest first.
        placements: the sum of the rows' counts, which the shares are a share
            of. A firm supplying two types is in that sum twice, which is
            what lets the column add up to a hundred.
        delivered_types: how many product types have reached the status
            marked as completed (REQ-DASH-007). Delivered, literally: a type
            somebody has merely contracted for is not one the department has
            received. Zero while no status carries the completed marker
            (DEC-010, TASK-UZK-048).
    """

    rows: tuple[CategoryShare, ...]
    placements: int
    delivered_types: int


def supplier_categories() -> SupplierCategories:
    """How the department's firms are spread across the product types.

    A type nobody supplies is listed with zero rather than left out: the
    block is read to see where the supply base is thin, and a missing row
    answers that question with silence.

    Delivered means reached the status marked as completed (DEC-010), not
    merely contracted for: a type somebody has a contract against is not one
    the department has received. While no status carries that marker, nothing
    counts as delivered.

    The share is each type's count as a percentage of the whole table, so the
    column adds to a hundred (within rounding). REQ-DASH-009 words it as a
    percentage "relative to total firms", which is the same number only while
    every firm supplies exactly one type - a firm supplying two is counted
    under both, and against a count of firms the column would then pass a
    hundred. The page prints what the share divides by so the two readings
    cannot be confused.

    Returns:
        The rows busiest first, what the shares divide by, and how many types
        are actually supplied.
    """
    completed = ShartnomaStatus.completed_status()
    delivered = (
        Q(**{CATEGORY_CONTRACT_STATE: completed}) if completed else Q(pk__in=())
    )
    counted = (
        MahsulotTuri.objects.active()
        .annotate(
            firmalar=Count(CATEGORY_SUPPLIERS, distinct=True),
            yetkazilgan=Count(CATEGORY_SUPPLIERS, filter=delivered, distinct=True),
        )
        .order_by("-firmalar", "name")
    )
    categories = list(counted)
    placements = sum(category.firmalar for category in categories)

    return SupplierCategories(
        rows=tuple(
            CategoryShare(
                category=category,
                firms=category.firmalar,
                share=whole_percent(category.firmalar, placements),
            )
            for category in categories
        ),
        placements=placements,
        delivered_types=sum(1 for category in categories if category.yetkazilgan),
    )
