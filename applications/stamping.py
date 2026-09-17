"""Putting an approval onto the document rather than only into the record.

REQ-ARIZA-019 wants the approving manager's name and the approval date
attached to the PDF, and DEC-027 says as plain text inside a QR code, along
with the application number. The record has known all three since
TASK-UZK-031; this is what makes the paper know them too, so a printed
application can be checked without the system in front of you.

The QR page is built through PIL rather than through a PDF toolkit. Pillow is
already here because Django needs it, and it saves an image straight to a
one-page PDF that pypdf can merge onto the attachment. reportlab is the usual
answer and would be a third dependency for what amounts to placing a square.

Nothing here reads a QR code. The application writes them and never scans one,
which is why the decoder the tests use is a development dependency rather than
a runtime one.
"""

from __future__ import annotations

from io import BytesIO

import qrcode
from django.core.files.base import ContentFile
from pypdf import PdfReader, PdfWriter, Transformation

# How the three parts of DEC-027 are joined. A separator with spaces around it
# so the payload stays readable to somebody whose scanner shows plain text,
# which is the whole point of putting plain text in it.
PAYLOAD_SEPARATOR = " | "

# The stamp's size and where it sits, in PDF points. Bottom right of the first
# page: nothing says where, and that is where a stamp goes on a document
# nobody designed for one.
STAMP_SIDE = 110
STAMP_MARGIN = 36


def approval_payload(number: str, approver, approved_at) -> str:
    """The text DEC-027 puts inside the code.

    Args:
        number: the application's own number.
        approver: the manager who approved it. Their full name is used, or
            their username when they have not been given one - a stamp naming
            nobody is worse than a stamp naming an account.
        approved_at: when. In ISO 8601, because a stamp is read by whoever
            finds the document and a local format would need them to know
            which locale wrote it.

    Returns:
        One line of plain text.
    """
    name = approver.get_full_name() or approver.username

    return PAYLOAD_SEPARATOR.join(
        (number, name, approved_at.isoformat(timespec="seconds"))
    )


def qr_page(payload: str):
    """A one-page PDF holding nothing but the code.

    Pillow writes the image as a PDF and pypdf reads it back as a page, which
    is how this avoids a PDF drawing library for a single square.
    """
    page = BytesIO()
    qrcode.make(payload).save(page, format="PDF")
    page.seek(0)

    return PdfReader(page).pages[0]


def stamp_with_qr(attachment, payload: str, name: str) -> ContentFile:
    """Return the attachment with the code stamped on its first page.

    The original is not touched. The caller decides what to do with what comes
    back, which is what lets the approval keep both copies.

    Args:
        attachment: the stored file to stamp. Read, never written.
        payload: what the code should carry, from approval_payload().
        name: what to call the file that comes back.

    Returns:
        The stamped PDF, ready to assign to a FileField.

    Raises:
        Exception: whatever pypdf raises for a file it cannot read. Deliberately
            not caught here: the caller is an approval, and an approval that
            swallowed this would mark an application approved with an
            unstamped document.
    """
    attachment.open("rb")
    try:
        source = PdfReader(BytesIO(attachment.read()))
    finally:
        attachment.close()

    stamp = qr_page(payload)
    scale = STAMP_SIDE / float(stamp.mediabox.width)

    writer = PdfWriter()
    for index, page in enumerate(source.pages):
        if index == 0:
            # The first page only. A stamp on every page of a long attachment
            # is noise, and the first page is the one somebody looks at.
            page.merge_transformed_page(
                stamp,
                Transformation()
                .scale(scale)
                .translate(
                    float(page.mediabox.width) - STAMP_SIDE - STAMP_MARGIN,
                    STAMP_MARGIN,
                ),
            )
        writer.add_page(page)

    stamped = BytesIO()
    writer.write(stamped)

    return ContentFile(stamped.getvalue(), name=name)
