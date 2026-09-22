"""One record written out as a PDF (the Ariza PDF and Shartnoma PDF columns).

exports.py writes a whole list page's table; this writes a single record as
the sheet somebody reads on its own: what was asked for, by whom, the order
lines, and how far it has got. Three records are drawn - a purchase request
with DEC-016's approval chain, the department's own application with the
handling it has been through, and an approved contract with its priced goods
and the signature that settled it.

Nothing here is uploaded. The file is drawn from the record every time it is
asked for, so it cannot fall out of step with the row the table shows - which
is the difference between this column and the Ilova PDF beside it, where the
requester's own attachment is kept exactly as it arrived (DEC-019).

The contract a status came from is deliberately never named. DEC-015 gives a
requester this page and no contract page at all, and a download must not hand
over a fact the table itself withholds.
"""

from __future__ import annotations

from html import escape
from io import BytesIO
from typing import Any

import qrcode
from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpResponse
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from xarid.attachments import approval_payload
from xarid.exports import DATETIME_OUTPUT, PDF_CONTENT_TYPE, local_date
from xarid.jinja2 import display_name
from xarid.models import (
    BOLIM_BOSHLIGI,
    DIREKTOR,
    purchasing_department,
    users_of_type,
)

# What the third step of the sheet is called. Not "Bo`lim Boshlig`i" a second
# time: the first row is the requester's own head, this one is the purchasing
# department's, and a reader comparing two identical labels would have to work
# out from the names which was which.
PURCHASING_STEP = "Xarid bo`lim boshlig`i"

# The page: portrait A4 with the same margin all round, which leaves 180mm of
# printable width for the tables below to divide up.
PAGE_MARGIN = 15 * mm
PRINTABLE_WIDTH = A4[0] - 2 * PAGE_MARGIN

# The approval code and the column it sits in, which is a little wider so the
# code keeps the quiet border a scanner needs.
QR_SIDE = 16 * mm
QR_COLUMN = 22 * mm

# An empty field prints as a dash rather than as nothing, so that a blank reads
# as "there is none" instead of as a table that failed to render. A plain
# hyphen and not the em dash the pages use: the built-in Helvetica this file is
# drawn with has no glyph for that one, and draws a blot in its place.
NOTHING = "-"

TITLE = ParagraphStyle("ariza-title", fontName="Helvetica-Bold", fontSize=15, leading=18)
SUBTITLE = ParagraphStyle(
    "ariza-subtitle", fontName="Helvetica", fontSize=9, leading=12, textColor=colors.grey
)
SECTION = ParagraphStyle(
    "ariza-section", fontName="Helvetica-Bold", fontSize=10, leading=13, spaceAfter=4
)
LABEL = ParagraphStyle("ariza-label", fontName="Helvetica-Bold", fontSize=8, leading=11)
VALUE = ParagraphStyle("ariza-value", fontName="Helvetica", fontSize=8, leading=11)


def purchase_application_response(application) -> HttpResponse:
    """The generated Ariza PDF of one purchase application, ready to download."""
    response = HttpResponse(
        purchase_application_pdf_bytes(application), content_type=PDF_CONTENT_TYPE
    )
    filename = f"{application.xarid_raqami}-ariza.pdf"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'

    return response


def purchase_application_pdf_bytes(application) -> bytes:
    """Draw one purchase application: its details, its order lines, its chain."""
    return _sheet(
        title=f"{application.xarid_raqami} - {application.shartnoma_nomi}",
        number=application.xarid_raqami,
        details=_details_table(application),
        record=application,
        approvals=_approvals_table(application),
    )


def _sheet(*, title: str, number: str, details: Table, record, approvals: Table) -> bytes:
    """The one sheet both records are drawn on.

    A purchase request and the department's own application are two rows of
    the same story, and somebody holding both printouts should not have to
    work out that they are looking at one request twice. So the heading, the
    three sections and their order are fixed here, and what differs between
    the two is only what goes inside them.
    """
    content = BytesIO()
    document = SimpleDocTemplate(
        content,
        pagesize=A4,
        leftMargin=PAGE_MARGIN,
        rightMargin=PAGE_MARGIN,
        topMargin=PAGE_MARGIN,
        bottomMargin=PAGE_MARGIN,
        title=title,
    )
    document.build(
        [
            Paragraph("XARID ARIZASI", TITLE),
            Paragraph(_text(number), SUBTITLE),
            Spacer(1, 10),
            details,
            Spacer(1, 14),
            KeepTogether(
                [Paragraph("Buyurtma qatorlari", SECTION), _order_lines_table(record)]
            ),
            Spacer(1, 14),
            KeepTogether([Paragraph("Tasdiqlash", SECTION), approvals]),
        ]
    )

    return content.getvalue()


def application_response(application) -> HttpResponse:
    """The generated Ariza PDF of one application, ready to download."""
    response = HttpResponse(application_pdf_bytes(application), content_type=PDF_CONTENT_TYPE)
    filename = f"{application.ariza_raqami}-ariza.pdf"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'

    return response


def application_pdf_bytes(application) -> bytes:
    """Draw one application on the same sheet as the request that raised it.

    Almost every application is one: DEC-016's chain ends by raising it, so
    the request holds the name, the deadline and the two signatures, and the
    honest sheet for the application is the request's own with the purchasing
    department's acceptance added to the chain. Drawing it from the request
    rather than copying its fields across is also what keeps the two
    downloads from ever disagreeing.

    An application keyed in directly has no request behind it, so it is drawn
    from its own record instead - the same sheet, with a dash standing in for
    the two fields only a request carries.
    """
    request = _raising_request(application)
    if request is not None:
        return purchase_application_pdf_bytes(request)

    return _sheet(
        title=f"{application.ariza_raqami} - {application.department.name}",
        number=application.ariza_raqami,
        details=_application_details_table(application),
        record=application,
        approvals=_application_approvals_table(application),
    )


def contract_response(contract) -> HttpResponse:
    """The generated Shartnoma PDF of one contract, ready to download."""
    response = HttpResponse(contract_pdf_bytes(contract), content_type=PDF_CONTENT_TYPE)
    filename = f"{contract.shartnoma_raqami}-shartnoma.pdf"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'

    return response


def contract_pdf_bytes(contract) -> bytes:
    """Draw one contract: its terms, its priced goods, and who signed it.

    The same sheet as the application's in its bones - a heading, a table of
    what was ordered, and the signature that settled it - because somebody
    holding the request and the contract it became should not have to learn
    two layouts to read one purchase.

    Drawn from the record rather than from anything uploaded: the Shartnoma
    Ilova beside it is the department's own document, kept exactly as it
    arrived (DEC-019), and this is what the application knows about it.
    """
    content = BytesIO()
    document = SimpleDocTemplate(
        content,
        pagesize=A4,
        leftMargin=PAGE_MARGIN,
        rightMargin=PAGE_MARGIN,
        topMargin=PAGE_MARGIN,
        bottomMargin=PAGE_MARGIN,
        title=f"{contract.shartnoma_raqami} - {contract.supplier.name}",
    )
    document.build(
        [
            Paragraph("SHARTNOMA", TITLE),
            Paragraph(_text(contract.shartnoma_raqami), SUBTITLE),
            Spacer(1, 10),
            _contract_details_table(contract),
            Spacer(1, 14),
            KeepTogether(
                [Paragraph("Shartnoma qatorlari", SECTION), _contract_lines_table(contract)]
            ),
            Spacer(1, 14),
            KeepTogether(
                [Paragraph("Tasdiqlash", SECTION), _contract_approval_table(contract)]
            ),
        ]
    )

    return content.getvalue()


def _contract_details_table(contract) -> Table:
    """The heading of the contract sheet: one label and one value to a row."""
    rows = (
        ("Shartnoma raqami", contract.shartnoma_raqami),
        ("Ariza raqami", contract.application.ariza_raqami),
        ("Bo`lim nomi", contract.application.department.name),
        ("Firma", contract.supplier.name),
        ("Firma INN", contract.supplier.inn or NOTHING),
        ("Kim tuzdi", display_name(contract.created_by)),
        ("Yaratilgan sana", _moment(contract.yaratilingan_sana)),
        ("Tasdiqlashga yuborilgan", _moment(contract.yuborilgan_sana)),
        ("Shartnoma qiymati", contract.qiymati_display),
        ("Holati", contract.status.name if contract.status else NOTHING),
        ("Bosqichi", contract.get_stage_display()),
        ("Izoh", contract.inkor_izohi or NOTHING),
    )
    table = Table(
        [
            [Paragraph(_text(label), LABEL), Paragraph(_text(value), VALUE)]
            for label, value in rows
        ],
        colWidths=(45 * mm, PRINTABLE_WIDTH - 45 * mm),
    )
    table.setStyle(_grid_style())

    return table


def _contract_lines_table(contract) -> Table:
    """What the contract buys, one row per goods line, priced as the page prices it.

    A totals row closes it: the value in the heading is the sum of these
    lines, and a sheet that states a total its own rows do not add up to is
    the one thing a priced document must not do.
    """
    header = ("#", "Buyurtma nomi", "Part Number", "Soni", "O`lchov", "Narxi", "Umumiy narx")
    body = [
        (
            str(number),
            line.buyurtma_nomi,
            line.part_number or NOTHING,
            str(line.soni_display),
            line.olchov_birligi,
            line.narxi_display,
            line.umumiy_narx_display,
        )
        for number, line in enumerate(contract.items.all(), start=1)
    ]
    if not body:
        body = [("", "Shartnoma qatori yo`q.", "", "", "", "", "")]
    else:
        body.append(("", "Jami", "", "", "", "", contract.qiymati_display))

    return _paragraph_table(
        header,
        body,
        widths=(8 * mm, 46 * mm, 26 * mm, 18 * mm, 20 * mm, 28 * mm, PRINTABLE_WIDTH - 146 * mm),
    )


def _contract_approval_table(contract) -> Table:
    """Who settled the contract, when, and the code that verifies it.

    The same four columns and the same QR payload as an application's chain,
    so a reader who has scanned one knows what this one is. A contract is
    drawn only once it has been approved, so the row is always a signed one -
    the layout still carries the refusal row, because a contract that was
    sent back and approved on the second attempt keeps what was said the
    first time.
    """
    body: list[tuple[object, str, str, str, str]] = []

    if contract.tasdiqlangan_sana is not None:
        payload = approval_payload(
            contract.shartnoma_raqami, contract.tasdiqlagan, contract.tasdiqlangan_sana
        )
        body.append(
            (
                _qr_cell(payload),
                "Tasdiqlangan",
                display_name(contract.tasdiqlagan),
                _moment(contract.tasdiqlangan_sana),
                "",
            )
        )

    if contract.inkor_izohi:
        body.append(("", "Oldingi inkor", NOTHING, NOTHING, contract.inkor_izohi))

    return _approvals_layout(body)


def _raising_request(application):
    """The purchase request this application was raised from, or None.

    The reverse of a nullable one-to-one raises rather than answering None,
    and an application typed in by hand is an ordinary case and not a fault.
    """
    try:
        return application.raised_from
    except ObjectDoesNotExist:
        return None


def _application_details_table(application) -> Table:
    """The heading of the sheet for an application with no request behind it.

    The same eight rows a request is drawn with, so the two sheets read
    alike. Two of them are a request's to hold: an application has no name of
    its own and no deadline, and a dash says so rather than the row going
    missing and the sheet looking like a different document.
    """
    rows = (
        ("Ariza nomi", NOTHING),
        ("Bo`lim nomi", application.department.name),
        ("Buyurtmachi", application.buyurtmachi_ismi or display_name(application.sender)),
        ("Yaratilgan sana", _moment(application.kelib_tushgan_sana)),
        ("Muddat talabi", NOTHING),
        ("Holati", application.status.name if application.status is not None else NOTHING),
        ("Bosqichi", application.get_stage_display()),
        ("Izoh", application.izoh or NOTHING),
    )
    table = Table(
        [
            [Paragraph(_text(label), LABEL), Paragraph(_text(value), VALUE)]
            for label, value in rows
        ],
        colWidths=(45 * mm, PRINTABLE_WIDTH - 45 * mm),
    )
    table.setStyle(_grid_style())

    return table


def _application_approvals_table(application) -> Table:
    """The chain of an application nobody raised: acceptance, and refusal.

    DEC-016's two approvals are a request's, and this application never was
    one, so the sheet shows the one step it did go through rather than two
    rows waiting for signatures that are not coming.
    """
    body = [
        row
        for row in (
            _acceptance_row(application, application.ariza_raqami),
            _refusal_row(
                application.rejected_by,
                application.inkor_qilingan_sana,
                application.inkor_izohi,
            ),
        )
        if row is not None
    ]

    return _approvals_layout(body)


def _details_table(application) -> Table:
    """The heading of the sheet: one label and one value to a row."""
    status = application.shown_status
    rows = (
        ("Ariza nomi", application.shartnoma_nomi),
        ("Bo`lim nomi", application.department.name),
        ("Buyurtmachi", display_name(application.created_by)),
        ("Yaratilgan sana", _moment(application.yaratilingan_sana)),
        ("Muddat talabi", local_date(application.muddat_talabi) or NOTHING),
        ("Holati", status.name if status is not None else NOTHING),
        ("Bosqichi", application.get_stage_display()),
        ("Izoh", application.izoh or NOTHING),
    )
    table = Table(
        [
            [Paragraph(_text(label), LABEL), Paragraph(_text(value), VALUE)]
            for label, value in rows
        ],
        colWidths=(45 * mm, PRINTABLE_WIDTH - 45 * mm),
    )
    table.setStyle(_grid_style())

    return table


def _order_lines_table(application) -> Table:
    """What the request asks for, one row per line, as the page lists them."""
    header = ("#", "Buyurtma nomi", "Mahsulot turi", "Soni", "O`lchov birligi")
    body = [
        (
            str(number),
            line.buyurtma_nomi,
            f"{line.mahsulot_turi.category_number} - {line.mahsulot_turi.name}",
            str(line.soni_display),
            line.olchov_birligi,
        )
        for number, line in enumerate(application.items.all(), start=1)
    ]
    if not body:
        body = [("", "Buyurtma qatori yo`q.", "", "", "")]

    return _paragraph_table(header, body, widths=(10 * mm, 60 * mm, 55 * mm, 25 * mm, 30 * mm))


def _approvals_table(application) -> Table:
    """The signature sheet: who has signed DEC-016's chain and who is still to.

    A step that has been taken shows the approver, when they took it, and the
    same QR code the approval stamped onto the attachment, so the sheet and
    the document verify alike. A step nobody has taken names everybody who
    may take it instead - one row each, with the QR cell left blank for the
    code that will be there once they sign.

    A refusal ends the chain and gets its own row, with the reason: the row a
    reader of a refused request is looking for. It carries no code, because
    DEC-027 stamps approvals and nothing else, and a code that says only
    "number, name, time" beside a refusal would read as the opposite.

    A third step follows DEC-016's two: the purchasing department taking the
    approved request up as its own application. It is the step that tells a
    requester their request has actually been picked up rather than merely
    let through, so it is signed like the others.
    """
    decided = {
        BOLIM_BOSHLIGI: (
            application.tasdiqlagan_bolim_boshligi,
            application.bolim_boshligi_sanasi,
        ),
        DIREKTOR: (application.tasdiqlagan_direktor, application.direktor_sanasi),
    }
    refused = application.inkor_qilgan_id is not None

    body: list[tuple[object, str, str, str, str]] = []
    for step, may_take_it in application.approval_chain():
        approver, at = decided[step]
        if approver is not None:
            body.append(
                (
                    _qr_cell(approval_payload(application.xarid_raqami, approver, at)),
                    step,
                    display_name(approver),
                    _moment(at),
                    "Tasdiqlangan",
                )
            )
        elif not refused:
            body.extend(
                ("", step, display_name(person), "", "Kutilmoqda") for person in may_take_it
            )
            if not may_take_it:
                body.append(("", step, "Tayinlanmagan", "", "Kutilmoqda"))

    if not refused:
        body.extend(_purchasing_step(application))

    refusal = _refusal_row(
        application.inkor_qilgan, application.inkor_sanasi, application.inkor_izohi
    )
    if refusal is not None:
        body.append(refusal)

    return _approvals_layout(body)


def _purchasing_step(application) -> list[tuple[object, str, str, str, str]]:
    """Xarid bo`limi's own step: accepting what DEC-016's chain let through.

    Taken once the department's head accepts the application the approval
    raised, so the fact lives on that application rather than on the request.
    Until then the row names who it is waiting for, as the two steps above it
    do - and names nobody at all while no department is marked as the
    purchasing one, because a head of some other department is not who this
    is waiting for.
    """
    raised = application.raised_application
    if raised is not None and raised.accepted_by is not None:
        return [_acceptance_row(raised, application.xarid_raqami)]

    heads = (
        users_of_type(BOLIM_BOSHLIGI, department=purchasing_department())
        if purchasing_department() is not None
        else ()
    )
    waiting = [
        ("", PURCHASING_STEP, display_name(person), "", "Kutilmoqda") for person in heads
    ]

    return waiting or [("", PURCHASING_STEP, "Tayinlanmagan", "", "Kutilmoqda")]


def _acceptance_row(application, number: str) -> tuple[object, str, str, str, str] | None:
    """The purchasing department's signature, once its head has accepted."""
    if application.accepted_by is None:
        return None

    at = application.qabul_qilingan_sana

    return (
        _qr_cell(approval_payload(number, application.accepted_by, at)),
        PURCHASING_STEP,
        display_name(application.accepted_by),
        _moment(at),
        "Qabul qilingan",
    )


def _refusal_row(refused_by, at, izoh: str) -> tuple[object, str, str, str, str] | None:
    """The row a reader of a refused record is looking for, with the reason."""
    if refused_by is None:
        return None

    return ("", "Inkor", display_name(refused_by), _moment(at), izoh or NOTHING)


def _approvals_layout(body: list[tuple[object, str, str, str, str]]) -> Table:
    """The Tasdiqlash table's own columns, shared so both sheets line up."""
    return _paragraph_table(
        ("QR", "Bosqich", "Kim", "Sana", "Izoh"),
        body,
        widths=(QR_COLUMN, 32 * mm, 45 * mm, 28 * mm, PRINTABLE_WIDTH - QR_COLUMN - 105 * mm),
    )


def _qr_cell(payload: str) -> Image:
    """The DEC-027 approval code, drawn small enough to sit in a table cell."""
    drawn = BytesIO()
    qrcode.make(payload).save(drawn, format="PNG")
    drawn.seek(0)

    return Image(drawn, width=QR_SIDE, height=QR_SIDE)


def _paragraph_table(
    header: tuple[str, ...], body: list[tuple[str, ...]], widths: tuple[float, ...]
) -> Table:
    """A fixed-width table whose cells wrap instead of running over the page."""
    rows = [
        [Paragraph(_text(cell), LABEL) for cell in header],
        *([_body_cell(cell) for cell in row] for row in body),
    ]
    table = Table(rows, colWidths=widths, repeatRows=1)
    table.setStyle(_grid_style(header_background=True))

    return table


def _grid_style(header_background: bool = False) -> TableStyle:
    """How both tables on the sheet are drawn: a thin grid and tight padding."""
    commands: list[tuple[Any, ...]] = [
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if header_background:
        commands.append(("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke))

    return TableStyle(commands)


def _body_cell(value: object) -> Image | Paragraph:
    """One cell of a data row: a drawn code as it is, anything else as text."""
    if isinstance(value, Image):
        return value

    return Paragraph(_text(value), VALUE)


def _moment(value) -> str:
    """A timestamp as the pages print it, or a dash when there is none yet."""
    if value is None:
        return NOTHING

    return timezone.localtime(value).strftime(DATETIME_OUTPUT)


def _text(value: object) -> str:
    """A cell as Paragraph markup, escaped: a comment may well hold a "<"."""
    return escape(str(value))
