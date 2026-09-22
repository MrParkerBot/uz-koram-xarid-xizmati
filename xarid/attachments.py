"""Attachments: where they live, what they may be, and how they are handed back.

DEC-019 settles all three: PDF only, 10 MB at most, kept for the life of the
record, stored on local disk outside the web root and served through a
permission check so a file cannot be fetched by guessing its URL.

The directory is ATTACHMENT_ROOT and deliberately not MEDIA_ROOT. Django does
not publish MEDIA_ROOT by itself, but MEDIA_URL is an invitation to wire it up,
and the day somebody does, every attachment becomes readable by anybody who can
guess a filename. UnaddressableStorage refuses to produce a URL at all, which
makes the permission-checked download view the only way to a file.

The approval stamp (REQ-ARIZA-019, DEC-027) lives here too: the QR page is
drawn with Pillow and merged onto the first page with pypdf.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import qrcode
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import UploadedFile
from django.db import models
from django.http import FileResponse, Http404
from pypdf import PageObject, PdfReader, PdfWriter, Transformation

MEGABYTE = 1024 * 1024
LARGEST_ATTACHMENT_BYTES = 10 * MEGABYTE

PDF_SUFFIX = ".pdf"
PDF_MAGIC = b"%PDF-"

TOO_LARGE = f"Fayl hajmi {LARGEST_ATTACHMENT_BYTES // MEGABYTE} MB dan oshmasligi kerak."
NOT_A_PDF = "Faqat PDF fayl yuklanadi."

# How the three parts of the DEC-027 payload are joined: readable to somebody
# whose scanner shows plain text, which is the point of plain text.
PAYLOAD_SEPARATOR = " | "

# The stamp's size and position in PDF points: bottom right of the first page.
STAMP_SIDE = 110
STAMP_MARGIN = 36


class UnaddressableStorage(FileSystemStorage):
    """Storage whose files have no URL at all.

    FileSystemStorage(base_url=None) falls back to settings.MEDIA_URL, which
    Django defaults to "/", so .url() would return a plausible path that would
    end up in a template one day. Raising here makes the download view the only
    way rather than the intended way.
    """

    def url(self, name: str) -> str:
        """Refuse to produce an address for an attachment.

        Raises:
            ValueError: always. Link to the download view instead.
        """
        raise ValueError(
            "An attachment has no URL (DEC-019). Link to the download view, "
            "which checks permission, rather than to the file."
        )


def attachment_storage() -> UnaddressableStorage:
    """Storage rooted outside anything the web server publishes."""
    return UnaddressableStorage(location=settings.ATTACHMENT_ROOT)


def validate_pdf(uploaded: UploadedFile) -> None:
    """Refuse anything that is not a PDF within the DEC-019 size limit.

    The name and the first bytes are both checked: the name is what the person
    typed, the bytes are what the file actually is.

    Raises:
        ValidationError: when the file is too large, is not named .pdf, or does
            not begin with the PDF marker.
    """
    if uploaded.size > LARGEST_ATTACHMENT_BYTES:
        raise ValidationError(TOO_LARGE)

    if Path(uploaded.name).suffix.lower() != PDF_SUFFIX:
        raise ValidationError(NOT_A_PDF)

    opening = uploaded.read(len(PDF_MAGIC))
    uploaded.seek(0)
    if opening != PDF_MAGIC:
        raise ValidationError(NOT_A_PDF)


def application_pdf_field() -> models.FileField:
    """The optional Ariza PDF column of section 4.1.

    Optional on the record because DEC-016 lets Admin key in an application
    that arrived on paper; the creation forms make it compulsory instead.
    """
    return models.FileField(
        "Ariza (PDF)",
        upload_to="arizalar/%Y/%m",
        storage=attachment_storage,
        blank=True,
        validators=[validate_pdf],
        help_text="PDF, eng ko`pi bilan 10 MB (DEC-019).",
    )


def contract_pdf_field() -> models.FileField:
    """The Shartnoma PDF column (REQ-SHARTNOMA-010).

    Optional on the record for the same reason the Ariza one is: a contract
    entered through the admin, or one raised before this column existed, has
    no attachment and must stay readable. The entry form makes it compulsory
    instead, which is where the rule belongs.
    """
    return models.FileField(
        "Shartnoma (PDF)",
        upload_to="shartnomalar/%Y/%m",
        storage=attachment_storage,
        blank=True,
        validators=[validate_pdf],
        help_text="PDF, eng ko`pi bilan 10 MB (DEC-019).",
    )


# What every downloaded attachment is called at the end: the word the pages
# label the column with. A folder of downloads is then readable on its own -
# the record's number says which record, and Ilova says this is the file
# somebody attached rather than the sheet the application draws.
ATTACHMENT_SUFFIX = "Ilova"


def attachment_name(number: str, *parts: str) -> str:
    """The filename an attachment of this record downloads as.

    Args:
        number: the record's own number, such as XA-2026-00001.
        parts: anything that distinguishes one attachment of a record from
            another, such as "asl" for the copy kept before the approval
            stamp. They sit between the number and the suffix.
    """
    return "-".join((number, *parts, ATTACHMENT_SUFFIX)) + PDF_SUFFIX


def attachment_response(attachment, download_name: str) -> FileResponse:
    """Hand a stored attachment back as a download.

    Args:
        attachment: the FieldFile to serve. May be empty.
        download_name: the filename the browser saves it as.

    Raises:
        Http404: when the record has no attachment, or the file it names is
            missing from disk.
    """
    if not attachment:
        raise Http404("Bu yozuvda ilova yo`q.")

    try:
        handle = attachment.open("rb")
    except FileNotFoundError as missing:
        raise Http404("Ilova fayli topilmadi.") from missing

    return FileResponse(handle, as_attachment=True, filename=download_name)


def approval_payload(number: str, approver, approved_at) -> str:
    """The plain text DEC-027 puts inside the approval QR code.

    Args:
        number: the application's own number.
        approver: the manager who approved it; their full name, or their
            username when they have none.
        approved_at: when they approved it, written in ISO 8601.
    """
    name = approver.get_full_name() or approver.username

    return PAYLOAD_SEPARATOR.join((number, name, approved_at.isoformat(timespec="seconds")))


def qr_page(payload: str) -> PageObject:
    """A one-page PDF holding nothing but the code, read back as a page."""
    page = BytesIO()
    qrcode.make(payload).save(page, format="PDF")
    page.seek(0)

    return PdfReader(page).pages[0]


def stamp_with_qr(attachment, payload: str, name: str) -> ContentFile:
    """Return a copy of the attachment with the code on its first page.

    The stored original is read and never written; the caller decides what to
    do with the copy that comes back.

    Args:
        attachment: the stored FieldFile to stamp.
        payload: what the code should carry, from approval_payload().
        name: the filename of the returned copy.

    Raises:
        Exception: whatever pypdf raises for a file it cannot read. Not caught
            here: an approval that swallowed it would mark an application
            approved with an unstamped document.
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
