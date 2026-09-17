"""Where an attachment lives, what it may be, and how it is handed back.

DEC-019 settles all three: PDF only, 10 MB at most, kept for the life of the
record, stored on local disk outside the web root and served through a
permission check so it cannot be fetched by guessing its URL.

The last part is the one that needs care, and it is easy to get wrong in a way
that looks right. Django does not publish MEDIA_ROOT by itself, but MEDIA_URL
is an invitation to wire it up, and the day somebody does, every attachment
under MEDIA_ROOT becomes readable by anybody who can guess a filename. So the
directory is ATTACHMENT_ROOT and is not MEDIA_ROOT.

MEDIA_URL cannot simply be left unset: Django defaults it to "/". Building the
storage with base_url=None does not help either, because it falls back to that
default, so .url() would return a plausible-looking path that somebody would
eventually put in a template. UnaddressableStorage refuses instead, which makes
the permission-checked download view the only way to a file rather than the
intended one.

TASK-UZK-026 and TASK-UZK-036 attach their own documents and reuse this.
TASK-UZK-036 is the third, and the first whose column is required.
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.storage import FileSystemStorage
from django.db import models
from django.http import FileResponse, Http404

# DEC-019. Written in bytes rather than as 10 * 1024 * 1024 at the point of
# use, so the limit is one number somebody can change.
MEGABYTE = 1024 * 1024
LARGEST_ATTACHMENT_BYTES = 10 * MEGABYTE

PDF_SUFFIX = ".pdf"
PDF_MAGIC = b"%PDF-"

TOO_LARGE = (
    f"Fayl hajmi {LARGEST_ATTACHMENT_BYTES // MEGABYTE} MB dan oshmasligi kerak."
)
NOT_A_PDF = "Faqat PDF fayl yuklanadi."


class UnaddressableStorage(FileSystemStorage):
    """Storage whose files have no URL at all.

    FileSystemStorage(base_url=None) is not enough, which is worth stating
    because it looks like it should be: with no base_url it falls back to
    settings.MEDIA_URL, which Django defaults to "/", so .url() cheerfully
    returns /arizalar/2026/03/ariza.pdf. Nothing serves that path today, but
    the value would end up in a template the moment somebody wrote
    {{ application.pdf.url }}, and it would look like a working link.

    DEC-019 says an attachment is reached through a permission check. Raising
    here makes that the only way rather than the intended way.
    """

    def url(self, name: str) -> str:
        """Refuse to produce an address for an attachment.

        Raises:
            ValueError: always. Use the download view, which asks the
                permission matrix first.
        """
        raise ValueError(
            "An attachment has no URL (DEC-019). Link to the download view, "
            "which checks permission, rather than to the file."
        )


def attachment_storage() -> UnaddressableStorage:
    """Storage rooted outside anything the web server publishes."""
    return UnaddressableStorage(location=settings.ATTACHMENT_ROOT)


def validate_pdf(uploaded) -> None:
    """Refuse anything that is not a PDF within the DEC-019 size limit.

    The name and the first bytes are both checked. A name alone is what the
    person typed; the first bytes are what the file actually is, and the two
    disagreeing is the interesting case rather than an edge one.

    Raises:
        ValidationError: when the file is too large, is not named .pdf, or
            does not begin with the PDF marker.
    """
    if uploaded.size > LARGEST_ATTACHMENT_BYTES:
        raise ValidationError(TOO_LARGE)

    if not Path(uploaded.name).suffix.lower() == PDF_SUFFIX:
        raise ValidationError(NOT_A_PDF)

    opening = uploaded.read(len(PDF_MAGIC))
    uploaded.seek(0)
    if opening != PDF_MAGIC:
        raise ValidationError(NOT_A_PDF)


def application_pdf_field() -> models.FileField:
    """The Ariza PDF column of section 4.1.

    Optional: the column is described as downloadable, which reads as always
    present, but DEC-016 lets Admin key in an application that arrived on
    paper. The list says so when there is nothing to download.
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
    """The Shartnoma PDF of section 4.8 (REQ-SHARTNOMA-003).

    Required, which is where it differs from the application's. DEC-016 gave
    that one an exception - Admin keying in something that arrived on paper,
    with no file to attach - and REQ-SHARTNOMA-003 gives this one none: it
    says every created contract must carry an attachment when it is entered
    and when it is edited. A contract without its signed document is not
    evidence of anything.

    Everything else is shared with the other two: the same storage, which
    refuses to hand out a URL, and the same validator, which checks the size,
    the name and the first bytes.
    """
    return models.FileField(
        "Shartnoma (PDF)",
        upload_to="shartnomalar/%Y/%m",
        storage=attachment_storage,
        validators=[validate_pdf],
        help_text="PDF, eng ko`pi bilan 10 MB (DEC-019).",
    )


def attachment_response(attachment, download_name: str) -> FileResponse:
    """Hand the file back as a download, or answer 404 when it is not there.

    as_attachment, so a PDF a person did not ask to view opens in whatever
    they use for files rather than inside the page. The name is the record's
    own rather than the stored one, which carries a directory and whatever
    suffix the upload machinery added to keep it unique.

    Raises:
        Http404: when the record has no attachment, or the file it names is
            missing from disk - which is a gone file, not a server fault.
    """
    if not attachment:
        raise Http404("Bu yozuvda ilova yo`q.")

    try:
        handle = attachment.open("rb")
    except FileNotFoundError as missing:
        raise Http404("Ilova fayli topilmadi.") from missing

    return FileResponse(handle, as_attachment=True, filename=download_name)
