"""Yuklab olish: a list page's table as an Excel workbook or a PDF (REQ-ARIZA-002).

A page describes its table once - the header labels and how each cell is read
from a row - and the same description is written to both formats, so the two
files always carry the same rows. The rows are the ones the page shows, after
its filters, mirrored one-per-order-line exactly as the table renders them.

Styling and branding are out of scope: plain headers, a grid, and the data.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from html import escape
from io import BytesIO
from typing import Any

from django.http import Http404, HttpResponse
from django.utils import timezone
from openpyxl import Workbook
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle

# Day first, matching what the tables on the pages print. strftime spellings;
# xarid.jinja2 carries the Django-format equivalents the templates use.
DATE_OUTPUT = "%d/%m/%Y"
DATETIME_OUTPUT = "%d/%m/%Y %H:%M"

EXCEL_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PDF_CONTENT_TYPE = "application/pdf"

# Anything wider than this is clipped in the PDF so a long comment cannot push
# the table off the page; the Excel cell keeps the full text.
PDF_CELL_CHARACTERS = 40

# Header cells of a table too wide for the page are drawn as paragraphs so
# that a long status name wraps inside its column instead of running over
# the next one.
_HEADER_CELL = ParagraphStyle("export-header", fontName="Helvetica", fontSize=7, leading=8)

# What a column of a narrowed table costs before it holds any content, and
# the least it may be given.
NARROW_COLUMN_PADDING = 2
NARROW_COLUMN_MINIMUM = 10


@dataclass(frozen=True)
class ExportColumn:
    """One column of the exported table.

    Attributes:
        label: the header the column is written under.
        value_of: reads the cell from an export row, which is the record the
            table row belongs to and the order line it renders (None when the
            record has no lines).
    """

    label: str
    value_of: Callable[[Any, Any], object]


@dataclass(frozen=True)
class TableExport:
    """A table ready to be written: what to call it, its columns and its rows."""

    filename_stem: str
    columns: Sequence[ExportColumn]
    rows: Sequence[tuple[Any, Any]]

    @property
    def headers(self) -> list[str]:
        return [column.label for column in self.columns]

    def cell_rows(self) -> list[list[object]]:
        """Every data row, cell by cell, with None written as an empty cell."""
        return [
            [self._cell(column.value_of(record, line)) for column in self.columns]
            for record, line in self.rows
        ]

    def filename(self, extension: str) -> str:
        return f"{self.filename_stem}-{timezone.localdate().isoformat()}.{extension}"

    @staticmethod
    def _cell(value: object) -> object:
        if value is None:
            return ""
        if isinstance(value, datetime):
            return timezone.localtime(value).strftime(DATETIME_OUTPUT)
        if isinstance(value, date):
            return value.strftime(DATE_OUTPUT)
        return value


def lines_of(records: Iterable[Any]) -> list[tuple[Any, Any]]:
    """One export row per order line, the way the tables render their rows.

    A record with no lines renders no table row, so it exports none either.
    """
    return [(record, line) for record in records for line in record.items.all()]


def local_date(value: datetime | date | None) -> str:
    """A date column as the tables print it, empty when the record has none."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return timezone.localtime(value).strftime(DATE_OUTPUT)
    return value.strftime(DATE_OUTPUT)


def excel_response(export: TableExport) -> HttpResponse:
    """The table as an .xlsx workbook: headers on the first row, one row per line."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = export.filename_stem[:31]
    sheet.append(export.headers)
    for row in export.cell_rows():
        sheet.append(row)

    content = BytesIO()
    workbook.save(content)

    return _attachment(content.getvalue(), EXCEL_CONTENT_TYPE, export.filename("xlsx"))


def pdf_response(export: TableExport) -> HttpResponse:
    """The table as a landscape A4 PDF with the header row repeated on each page."""
    header = [str(label) for label in export.headers]
    body = [[_clipped(cell) for cell in row] for row in export.cell_rows()]

    content = BytesIO()
    document = SimpleDocTemplate(
        content,
        pagesize=landscape(A4),
        leftMargin=10 * mm,
        rightMargin=10 * mm,
        topMargin=10 * mm,
        bottomMargin=10 * mm,
        title=export.filename_stem,
    )
    document.build([_fitted_table(header, body, document.width)])

    return _attachment(content.getvalue(), PDF_CONTENT_TYPE, export.filename("pdf"))


def _table_style(padding: float = 6) -> TableStyle:
    """How every exported table is drawn.

    A table narrowed to the page asks for tighter padding, because reportlab's
    default 6pt on each side is most of a column once there are thirty of them.
    """
    return TableStyle(
        [
            ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), padding),
            ("RIGHTPADDING", (0, 0), (-1, -1), padding),
        ]
    )


def _fitted_table(header: list[str], body: list[list[str]], available: float) -> Table:
    """The table, narrowed to the page when it would otherwise run off it.

    A report generates one column per contract status and anybody may add one
    (DEC-010), so a table can be wider than the paper. Reportlab draws a table
    at its natural width without complaining, which puts the last columns off
    the right edge of the page: the file looks whole and is not.

    A table that already fits - every list page today - is built exactly as it
    was, so those downloads are unchanged. A table that does not gets column
    widths in proportion to its content that add up to the page, and its
    headers wrapped so the long ones stack instead of overlapping their
    neighbours.

    Args:
        header: the header row.
        body: the data rows.
        available: the printable width of the page.

    Returns:
        A table that fits within `available`.
    """
    rows = [header, *body]
    natural = Table(rows, repeatRows=1)
    natural.setStyle(_table_style())
    if natural.wrap(available, 0)[0] <= available:
        return natural

    widths = _proportional_widths(rows, available, NARROW_COLUMN_MINIMUM)
    wrapped_header = [Paragraph(f"<b>{escape(cell)}</b>", _HEADER_CELL) for cell in header]
    narrowed = Table([wrapped_header, *body], colWidths=widths, repeatRows=1)
    narrowed.setStyle(_table_style(padding=NARROW_COLUMN_PADDING))
    return narrowed


def _proportional_widths(
    rows: list[list[str]], available: float, minimum: float
) -> list[float]:
    """Column widths that keep their relative size and add up to the page.

    No column may fall below `minimum`: a column narrower than its own padding
    leaves negative room for its content, which reportlab refuses outright. The
    width that lifting the narrow columns costs is taken back from the columns
    that have room to give.
    """
    longest = [max(len(str(row[index])) for row in rows) for index in range(len(rows[0]))]
    total = sum(longest) or len(longest)
    widths = [max(minimum, available * width / total) for width in longest]

    overshoot = sum(widths) - available
    if overshoot <= 0:
        return widths

    spare = [width - minimum for width in widths]
    givable = sum(spare)
    if givable <= 0:
        # More columns than the page can hold even at the minimum. Nothing
        # here can fix that; the Excel file is the one to read.
        return widths
    return [
        width - overshoot * (room / givable)
        for width, room in zip(widths, spare, strict=True)
    ]


FORMAT_WRITERS: dict[str, Callable[[TableExport], HttpResponse]] = {
    "xlsx": excel_response,
    "pdf": pdf_response,
}


def export_response(export: TableExport, file_format: str) -> HttpResponse:
    """The table in the requested format.

    Raises:
        Http404: when file_format is neither "xlsx" nor "pdf".
    """
    writer = FORMAT_WRITERS.get(file_format)
    if writer is None:
        raise Http404(f"{file_format!r} is not an export format.")

    return writer(export)


def _clipped(cell: object) -> str:
    text = str(cell)
    if len(text) > PDF_CELL_CHARACTERS:
        return text[: PDF_CELL_CHARACTERS - 1] + "…"
    return text


def _attachment(content: bytes, content_type: str, filename: str) -> HttpResponse:
    response = HttpResponse(content, content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
