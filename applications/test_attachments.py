"""Tests for the application PDF of TASK-UZK-022, against DEC-019.

DEC-019 says four things: PDF only, 10 MB at most, stored outside the web root,
and served through a permission check so an attachment cannot be fetched by
guessing its URL. The first two are validation. The last two are the ones worth
being careful about, because getting them wrong is silent - an attachment that
is publicly readable looks exactly like one that is not until somebody tries.

So there are tests here that assert where the file is not, as well as what the
download does.
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils.crypto import get_random_string

from accounts.models import UserType
from accounts.roles import ADMIN, MENEJER, USERS, assign_user_type
from applications.attachments import (
    LARGEST_ATTACHMENT_BYTES,
    attachment_storage,
    validate_pdf,
)
from applications.models import Application
from reference.models import Department, MahsulotTuri

PDF_BYTES = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\ntrailer\n%%EOF\n"


def a_pdf(name: str = "ariza.pdf") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, PDF_BYTES, content_type="application/pdf")


def make_user(type_name: str = ADMIN):
    user = get_user_model().objects.create_user(
        username=f"user.{get_random_string(8).lower()}",
        password=get_random_string(24),
        first_name="Test",
        last_name=type_name,
    )
    assign_user_type(user, UserType.objects.get(name=type_name))
    return user


class ValidationTests(TestCase):
    """PDF only, 10 MB at most (DEC-019)."""

    def test_a_pdf_is_accepted(self) -> None:
        validate_pdf(a_pdf())

    def test_something_that_is_not_named_pdf_is_refused(self) -> None:
        with self.assertRaises(ValidationError):
            validate_pdf(SimpleUploadedFile("ariza.docx", PDF_BYTES))

    def test_something_named_pdf_that_is_not_one_is_refused(self) -> None:
        # The name is what the person typed; the first bytes are what the file
        # actually is, and the two disagreeing is the interesting case.
        with self.assertRaises(ValidationError):
            validate_pdf(SimpleUploadedFile("ariza.pdf", b"PK\x03\x04 zip"))

    def test_a_file_over_the_limit_is_refused(self) -> None:
        too_big = SimpleUploadedFile(
            "ariza.pdf", PDF_BYTES + b"0" * LARGEST_ATTACHMENT_BYTES
        )

        with self.assertRaises(ValidationError):
            validate_pdf(too_big)

    def test_the_limit_is_ten_megabytes(self) -> None:
        self.assertEqual(LARGEST_ATTACHMENT_BYTES, 10 * 1024 * 1024)


class StorageLocationTests(TestCase):
    """Outside the web root, which is the part that fails silently."""

    def test_the_attachment_root_is_not_inside_the_published_directories(self):
        attachments = Path(settings.ATTACHMENT_ROOT).resolve()

        published = [Path(settings.STATIC_ROOT).resolve()]
        published += [Path(each).resolve() for each in settings.STATICFILES_DIRS]

        for directory in published:
            with self.subTest(published=str(directory)):
                self.assertFalse(
                    attachments == directory
                    or directory in attachments.parents,
                    f"{attachments} is inside {directory}, so collectstatic "
                    "would publish every attachment in the system.",
                )

    def test_the_attachment_root_is_not_the_media_root(self) -> None:
        # MEDIA_ROOT is what Django serves when somebody wires up media
        # serving. The attachments are not there, so wiring it up would not
        # publish them. MEDIA_URL is deliberately not asserted on: Django
        # defaults it to "/", so its presence says nothing either way.
        self.assertNotEqual(str(settings.MEDIA_ROOT), str(settings.ATTACHMENT_ROOT))
        self.assertEqual(settings.MEDIA_ROOT, "")

    def test_a_stored_attachment_has_no_url(self) -> None:
        # Not because base_url is unset - that falls back to MEDIA_URL, which
        # Django defaults to "/", and .url() would return a plausible-looking
        # path. The storage refuses outright, so the only way to a file is the
        # download view that checks permission first (DEC-019).
        with self.assertRaises(ValueError):
            attachment_storage().url("arizalar/2026/03/ariza.pdf")


@override_settings(ATTACHMENT_ROOT=None)
class DownloadTestCase(TestCase):
    """The download route, which is the only way to a stored file."""

    def setUp(self) -> None:
        import tempfile

        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.settings_override = self.settings(ATTACHMENT_ROOT=self.directory.name)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)

        self.application = Application.raise_application(
            department=Department.objects.create(name="Texnik bolim"),
            mahsulot_turi=MahsulotTuri.objects.create(
                category_number=100042, name="Metallurgiya"
            ),
            buyurtma_nomi="Bolt M12",
            buyurtma_soni=500,
            olchov_birligi="ta",
            pdf=a_pdf(),
        )
        self.url = reverse("ariza-pdf", args=[self.application.pk])

    def test_the_file_downloads(self) -> None:
        self.client.force_login(make_user(ADMIN))

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), PDF_BYTES)

    def test_it_is_offered_as_a_download_under_the_application_number(self):
        self.client.force_login(make_user(ADMIN))

        response = self.client.get(self.url)

        self.assertIn("attachment", response["Content-Disposition"])
        self.assertIn(
            f"{self.application.ariza_raqami}.pdf",
            response["Content-Disposition"],
        )

    def test_the_row_links_to_it(self) -> None:
        self.client.force_login(make_user(ADMIN))

        page = self.client.get(reverse("kelib-arizalar")).content.decode()

        self.assertIn(self.url, page)

    def test_a_row_without_an_attachment_offers_no_link(self) -> None:
        self.client.force_login(make_user(ADMIN))
        self.application.pdf = ""
        self.application.save(update_fields=["pdf"])

        page = self.client.get(reverse("kelib-arizalar")).content.decode()

        self.assertNotIn(self.url, page)

    def test_asking_for_an_attachment_that_is_not_there_is_a_not_found(self):
        self.client.force_login(make_user(ADMIN))
        self.application.pdf = ""
        self.application.save(update_fields=["pdf"])

        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_somebody_who_may_open_the_page_may_download(self) -> None:
        self.client.force_login(make_user(MENEJER))

        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_somebody_who_may_not_open_the_page_may_not_download(self) -> None:
        # The whole point of DEC-019's permission check: the attachment is
        # not a back door into a page somebody may not open.
        self.client.force_login(make_user(USERS))

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)

    def test_an_anonymous_visitor_may_not_download(self) -> None:
        self.assertEqual(self.client.get(self.url).status_code, 302)
