"""Test scaffolding shared by the application test modules.

config/test_support.py does this for the pages; this does it for the records.
A fixture that two modules build separately is a fixture that stops agreeing
with itself, which the #33 review pointed out about the PDF: both copies were
correct, and neither would have noticed the other going stale when DEC-019's
rules moved.
"""

from __future__ import annotations

from django.core.files.uploadedfile import SimpleUploadedFile

# A PDF by name and by its first bytes, which is what validate_pdf checks.
PDF_BYTES = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\ntrailer\n%%EOF\n"


def a_pdf(name: str = "ariza.pdf") -> SimpleUploadedFile:
    """An uploaded file that passes validate_pdf."""
    return SimpleUploadedFile(name, PDF_BYTES, content_type="application/pdf")
