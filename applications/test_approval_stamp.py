"""Tests for the approval stamp of TASK-UZK-032.

The test that matters decodes the code rather than trusting it. A test that
only checked the file had changed, or that a QR-shaped thing was present,
would pass on a blank square - and a blank square is exactly what a broken
stamp looks like from the outside.

So these read the image back out of the stamped page and decode it, and
compare the result to the three things DEC-027 names. The decoder is a
development dependency: the application writes QR codes and never scans one.
"""

from __future__ import annotations

from io import BytesIO

import cv2
import numpy
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils.crypto import get_random_string
from PIL import Image
from pypdf import PdfReader

from accounts.models import UserProfile, UserType
from accounts.roles import BOLIM_BOSHLIGI, DIREKTOR, USERS, assign_user_type
from applications.models import PurchaseApplication
from applications.stamping import PAYLOAD_SEPARATOR, approval_payload
from applications.test_support import a_pdf
from reference.models import ArizaStatus, Department, MahsulotTuri


def make_user(type_name: str, department=None, first_name="Test", last_name=""):
    user = get_user_model().objects.create_user(
        username=f"user.{get_random_string(8).lower()}",
        password=get_random_string(24),
        first_name=first_name,
        last_name=last_name or type_name,
    )
    assign_user_type(user, UserType.objects.get(name=type_name))
    if department is not None:
        UserProfile.objects.filter(user=user).update(department=department)
    return user


def decode_the_stamp(attachment) -> str | None:
    """Read the QR code back out of a stored PDF, or None when there is none.

    Goes through the page's embedded images rather than through anything the
    stamping module exports, so the test reads the document the way somebody
    with a scanner would rather than the way it was written.
    """
    attachment.open("rb")
    try:
        page = PdfReader(BytesIO(attachment.read())).pages[0]
    finally:
        attachment.close()

    for embedded in page.images:
        frame = numpy.array(Image.open(BytesIO(embedded.data)).convert("RGB"))
        text, *_ = cv2.QRCodeDetector().detectAndDecode(frame)
        if text:
            return text

    return None


class StampTestCase(TestCase):
    """A purchase application on its way through the approval chain."""

    def setUp(self) -> None:
        self.department = Department.objects.create(name="Texnik bolim")
        self.category = MahsulotTuri.objects.create(
            category_number=100042, name="Metallurgiya"
        )
        self.requester = make_user(USERS, self.department)
        self.head = make_user(
            BOLIM_BOSHLIGI, self.department, first_name="Bobur"
        )
        self.direktor = make_user(
            DIREKTOR, self.department, first_name="Alisher", last_name="Karimov"
        )
        self.application = self.raise_request()

    def raise_request(self, pdf=None) -> PurchaseApplication:
        return PurchaseApplication.raise_purchase_application(
            items=[
                {
                    "mahsulot_turi": self.category,
                    "buyurtma_nomi": "Bolt M12",
                    "buyurtma_soni": 500,
                    "olchov_birligi": "ta",
                }
            ],
            department=self.department,
            shartnoma_nomi="Bolt yetkazib berish shartnomasi",
            izoh="Shoshilinch",
            pdf=a_pdf() if pdf is None else pdf,
            created_by=self.requester,
            status=ArizaStatus.objects.filter(
                code=ArizaStatus.Code.NEW
            ).first(),
        )

    def approve_fully(self, application=None) -> PurchaseApplication:
        application = application or self.application
        application.approve(by=self.head)
        application.approve(by=self.direktor)
        application.refresh_from_db()
        return application


class DecodedStampTests(StampTestCase):
    """What the code actually carries (DEC-027)."""

    def test_the_stamp_decodes(self) -> None:
        self.approve_fully()

        self.assertIsNotNone(decode_the_stamp(self.application.pdf))

    def test_it_carries_the_three_things_dec_027_names(self) -> None:
        self.approve_fully()

        decoded = decode_the_stamp(self.application.pdf)
        number, name, approved_at = decoded.split(PAYLOAD_SEPARATOR)

        self.assertEqual(number, self.application.xarid_raqami)
        self.assertEqual(name, "Alisher Karimov")
        self.assertEqual(
            approved_at,
            self.application.direktor_sanasi.isoformat(timespec="seconds"),
        )

    def test_the_name_is_the_approvers_not_the_first_steps(self) -> None:
        # Two people approve. REQ-ARIZA-019 names the approving manager, and
        # the department head passed it on rather than approving it.
        self.approve_fully()

        self.assertNotIn("Bobur", decode_the_stamp(self.application.pdf))

    def test_an_approver_with_no_full_name_is_named_by_their_username(
        self,
    ) -> None:
        # A stamp naming nobody is worse than one naming an account.
        nameless = make_user(DIREKTOR, self.department, first_name="")
        nameless.last_name = ""
        nameless.save(update_fields=["last_name"])
        self.application.approve(by=self.head)

        self.application.approve(by=nameless)
        self.application.refresh_from_db()

        self.assertIn(
            nameless.username, decode_the_stamp(self.application.pdf)
        )

    def test_the_payload_builder_and_the_stamp_agree(self) -> None:
        self.approve_fully()

        self.assertEqual(
            decode_the_stamp(self.application.pdf),
            approval_payload(
                self.application.xarid_raqami,
                self.direktor,
                self.application.direktor_sanasi,
            ),
        )


class WhenItStampsTests(StampTestCase):
    """Which approval does it, and what it leaves alone."""

    def test_the_first_approval_does_not_stamp(self) -> None:
        self.application.approve(by=self.head)
        self.application.refresh_from_db()

        self.assertIsNone(decode_the_stamp(self.application.pdf))

    def test_a_rejected_application_is_never_stamped(self) -> None:
        self.application.reject(by=self.head, comment="Byudjet yo`q.")
        self.application.refresh_from_db()

        self.assertIsNone(decode_the_stamp(self.application.pdf))

    def test_the_original_is_kept(self) -> None:
        before = self.application.pdf.name

        self.approve_fully()

        self.assertEqual(self.application.asl_pdf.name, before)
        self.assertNotEqual(self.application.pdf.name, before)

    def test_the_original_still_opens_and_has_no_stamp(self) -> None:
        self.approve_fully()

        self.assertIsNone(decode_the_stamp(self.application.asl_pdf))

    def test_the_page_count_is_unchanged(self) -> None:
        self.approve_fully()

        self.application.pdf.open("rb")
        try:
            pages = len(PdfReader(BytesIO(self.application.pdf.read())).pages)
        finally:
            self.application.pdf.close()

        self.assertEqual(pages, 1)

    def test_only_the_first_page_of_a_long_attachment_is_stamped(
        self,
    ) -> None:
        # An explicit branch in stamp_with_qr, and nothing pinned it - the
        # #46 review found it correct and untested, which is the kind of
        # thing that survives until somebody simplifies the loop.
        application = self.raise_request(pdf=a_pdf(pages=3))

        self.approve_fully(application)

        application.pdf.open("rb")
        try:
            pages = PdfReader(BytesIO(application.pdf.read())).pages
            images_per_page = [len(list(page.images)) for page in pages]
        finally:
            application.pdf.close()

        self.assertEqual(len(pages), 3)
        self.assertEqual(images_per_page, [1, 0, 0])

    def test_the_department_application_carries_the_stamped_document(
        self,
    ) -> None:
        # The point of stamping before the record is created: what the
        # purchasing department receives is the approved document.
        self.approve_fully()

        self.assertEqual(
            self.application.raised_application.pdf.name,
            self.application.pdf.name,
        )
        self.assertIsNotNone(
            decode_the_stamp(self.application.raised_application.pdf)
        )

    def test_an_application_with_no_attachment_is_still_approved(self) -> None:
        # DEC-016 lets a paper application through, and refusing an approval
        # here would make the attachment compulsory where nothing says it is.
        paperless = self.raise_request(pdf="")

        self.approve_fully(paperless)

        self.assertEqual(
            paperless.stage, PurchaseApplication.Stage.APPROVED
        )
        self.assertIsNotNone(paperless.raised_application)


class OriginalDownloadTests(StampTestCase):
    """The original is kept so it can be produced, so it has to be reachable."""

    def test_the_original_can_be_downloaded_after_approval(self) -> None:
        # The #46 review found it retained where nothing could produce it.
        # DEC-019 makes the download view the only way to a file, so a file
        # with no view is a file nobody has.
        self.approve_fully()
        self.client.force_login(self.direktor)

        response = self.client.get(
            reverse("xarid-ariza-asl-pdf", args=[self.application.pk])
        )

        self.assertEqual(response.status_code, 200)

    def test_what_comes_back_is_unstamped(self) -> None:
        self.approve_fully()
        self.client.force_login(self.direktor)

        response = self.client.get(
            reverse("xarid-ariza-asl-pdf", args=[self.application.pk])
        )
        downloaded = BytesIO(b"".join(response.streaming_content))

        page = PdfReader(downloaded).pages[0]
        self.assertEqual(len(list(page.images)), 0)

    def test_an_unapproved_application_has_no_original_to_download(
        self,
    ) -> None:
        # Until an approval stamps it, pdf is the original - there is no
        # second file, and saying so with a 404 is truer than serving the
        # same bytes from two addresses.
        self.client.force_login(self.direktor)

        response = self.client.get(
            reverse("xarid-ariza-asl-pdf", args=[self.application.pk])
        )

        self.assertEqual(response.status_code, 404)

    def test_somebody_who_may_not_open_the_page_may_not_download_it(
        self,
    ) -> None:
        self.approve_fully()
        self.client.logout()

        response = self.client.get(
            reverse("xarid-ariza-asl-pdf", args=[self.application.pk])
        )

        self.assertEqual(response.status_code, 302)


class StampFailureTests(StampTestCase):
    """A failure to stamp must not leave an approved application."""

    def test_an_unreadable_attachment_fails_the_approval(self) -> None:
        # pypdf raises PdfReadError for a file that is not a PDF. Named rather
        # than caught as Exception, so this test cannot pass on some unrelated
        # failure that happens to be raised from the same call.
        from django.core.files.base import ContentFile
        from pypdf.errors import PdfReadError

        self.application.approve(by=self.head)
        self.application.pdf.save(
            "broken.pdf", ContentFile(b"%PDF-1.7 not really"), save=True
        )

        with self.assertRaises(PdfReadError):
            self.application.approve(by=self.direktor)

        self.application.refresh_from_db()
        self.assertEqual(
            self.application.stage,
            PurchaseApplication.Stage.AWAITING_DIREKTOR,
        )
        self.assertIsNone(self.application.raised_application)


class ApprovalPageTests(StampTestCase):
    """The stamp happens through the page, not only through the model."""

    def test_approving_from_the_page_stamps(self) -> None:
        self.client.force_login(self.head)
        self.client.post(
            reverse("xarid-ariza-tasdiqlash", args=[self.application.pk])
        )
        self.client.force_login(self.direktor)

        self.client.post(
            reverse("xarid-ariza-tasdiqlash", args=[self.application.pk])
        )

        self.application.refresh_from_db()
        self.assertIsNotNone(decode_the_stamp(self.application.pdf))
