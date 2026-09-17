"""Test scaffolding shared by the application test modules.

core/tests/test_support.py does this for the pages; this does it for the records.
A fixture that two modules build separately is a fixture that stops agreeing
with itself, which the #33 review pointed out about the PDF: both copies were
correct, and neither would have noticed the other going stale when DEC-019's
rules moved.

The PDF is a real one. It used to be a handful of bytes beginning with the
right marker, which was enough while nothing did more than check the marker -
and stopped being enough the moment TASK-UZK-032 had to open one and write to
it. A fixture that claims to be a PDF and is not passes every test until one
of them means it.
"""

from __future__ import annotations

from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from pypdf import PdfWriter

# A4 in points, which is what the department prints on.
PAGE_WIDTH = 595
PAGE_HEIGHT = 842


def pdf_bytes(pages: int = 1) -> bytes:
    """A genuinely parseable PDF of the given length."""
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)

    document = BytesIO()
    writer.write(document)

    return document.getvalue()


PDF_BYTES = pdf_bytes()


def a_pdf(name: str = "ariza.pdf", pages: int = 1) -> SimpleUploadedFile:
    """An uploaded file that passes validate_pdf and that pypdf can read."""
    content = PDF_BYTES if pages == 1 else pdf_bytes(pages)

    return SimpleUploadedFile(name, content, content_type="application/pdf")
