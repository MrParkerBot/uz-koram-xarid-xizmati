"""Tests for the Ariza Yaratish form of TASK-UZK-026.

Three rules carry most of this task, and each is worth a test that fails
loudly if somebody relaxes it:

- an application orders at least one line, and may order several
  (REQ-ARIZA-010),
- it cannot be created without its PDF (REQ-ARIZA-009),
- a submission that is refused leaves nothing behind - no record, no line and
  no file - which is what Cancel means when nothing was written in the first
  place (REQ-ARIZA-011).

The last one is the reason creation is a single transaction, and the reason
there is a test that breaks a line after the header has already validated.
"""

from __future__ import annotations

from datetime import date

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils.crypto import get_random_string

from accounts.models import UserType
from accounts.roles import ADMIN, DIREKTOR, assign_user_type
from applications.models import SMALLEST_QUANTITY, Application, ApplicationItem
from applications.tests.test_support import a_pdf
from reference.models import ArizaStatus, Department, MahsulotTuri


def make_user(type_name: str = ADMIN):
    user = get_user_model().objects.create_user(
        username=f"user.{get_random_string(8).lower()}",
        password=get_random_string(24),
        first_name="Test",
        last_name=type_name,
    )
    assign_user_type(user, UserType.objects.get(name=type_name))
    return user


class CreateApplicationTests(TestCase):
    """Somebody permitted to open Qabul qilingan Arizalar, creating one."""

    def setUp(self) -> None:
        self.department = Department.objects.create(name="Texnik bolim")
        self.category = MahsulotTuri.objects.create(
            category_number=100042, name="Metallurgiya"
        )
        self.creator = make_user(ADMIN)
        self.client.force_login(self.creator)
        self.url = reverse("ariza-yaratish")

    def payload(self, lines: int = 1, **overrides) -> dict:
        """A submission with the given number of order lines filled in."""
        form = {
            "department": self.department.pk,
            "buyurtmachi_ismi": "Alisher Karimov",
            "izoh": "Zanglamaydigan",
            "form-TOTAL_FORMS": str(lines),
            "form-INITIAL_FORMS": "0",
            "form-MIN_NUM_FORMS": "1",
            "form-MAX_NUM_FORMS": "1000",
        }
        for index in range(lines):
            form |= {
                f"form-{index}-mahsulot_turi": self.category.pk,
                f"form-{index}-buyurtma_nomi": f"Bolt M{index + 1}",
                f"form-{index}-buyurtma_soni": "500",
                f"form-{index}-olchov_birligi": "ta",
            }
        form.update(overrides)
        return form

    def create(self, lines: int = 1, pdf=None, **overrides):
        """Submit the form with an attachment: the given one, or a valid one."""
        payload = self.payload(lines, **overrides)
        payload["pdf"] = pdf if pdf is not None else a_pdf()

        return self.client.post(self.url, payload)

    def create_without_pdf(self, lines: int = 1, **overrides):
        """Submit the form with no attachment at all (REQ-ARIZA-009)."""
        return self.client.post(self.url, self.payload(lines, **overrides))

    def test_one_line_creates_one_application(self) -> None:
        response = self.create()

        self.assertRedirects(response, reverse("qabul-arizalar"))
        application = Application.objects.get()
        self.assertEqual(application.items.count(), 1)
        self.assertEqual(application.buyurtmachi_ismi, "Alisher Karimov")

    def test_the_number_follows_dec_022(self) -> None:
        self.create()

        application = Application.objects.get()
        self.assertEqual(
            application.ariza_raqami, f"ARZ-{date.today().year}-00001"
        )

    def test_a_second_application_takes_the_next_number(self) -> None:
        self.create()
        self.create()

        self.assertEqual(
            list(
                Application.objects.order_by("ariza_raqami").values_list(
                    "ariza_raqami", flat=True
                )
            ),
            [
                f"ARZ-{date.today().year}-00001",
                f"ARZ-{date.today().year}-00002",
            ],
        )

    def test_the_plus_button_records_several_lines(self) -> None:
        self.create(lines=3)

        application = Application.objects.get()
        self.assertEqual(
            [line.buyurtma_nomi for line in application.items.all()],
            ["Bolt M1", "Bolt M2", "Bolt M3"],
        )

    def test_the_lines_keep_the_order_they_were_entered_in(self) -> None:
        self.create(
            lines=2,
            **{
                "form-0-buyurtma_nomi": "Birinchi",
                "form-1-buyurtma_nomi": "Ikkinchi",
            },
        )

        application = Application.objects.get()
        self.assertEqual(
            [line.buyurtma_nomi for line in application.items.all()],
            ["Birinchi", "Ikkinchi"],
        )

    def test_it_is_created_already_accepted(self) -> None:
        """The form is on the accepted page, so what it makes is accepted.

        Recorded in the plan as the reading to challenge. The test is here so
        that overturning it is a decision somebody takes rather than a change
        that slips through.
        """
        self.create()

        application = Application.objects.get()
        self.assertEqual(application.stage, Application.Stage.ACCEPTED)
        self.assertIsNotNone(application.qabul_qilingan_sana)
        self.assertEqual(application.accepted_by, self.creator)

    def test_the_status_is_the_accepted_row(self) -> None:
        self.create()

        self.assertEqual(
            Application.objects.get().status.code, ArizaStatus.Code.ACCEPTED
        )

    def test_it_appears_on_the_accepted_page(self) -> None:
        self.create()

        page = self.client.get(reverse("qabul-arizalar")).content.decode()
        self.assertIn(Application.objects.get().ariza_raqami, page)

    def test_without_the_pdf_nothing_is_created(self) -> None:
        response = self.create_without_pdf()

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Application.objects.exists())
        self.assertFalse(ApplicationItem.objects.exists())

    def test_the_refusal_says_the_pdf_is_missing(self) -> None:
        response = self.create_without_pdf()

        self.assertContains(response, "PDF ilova yuklanishi shart")

    def test_something_that_is_not_a_pdf_is_refused(self) -> None:
        response = self.create(
            pdf=SimpleUploadedFile("ariza.pdf", b"GIF89a", "application/pdf")
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Application.objects.exists())

    def test_a_negative_quantity_is_refused(self) -> None:
        """The #33 review found this stored as an order for minus five."""
        response = self.create(**{"form-0-buyurtma_soni": "-5"})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Application.objects.exists())
        self.assertFalse(ApplicationItem.objects.exists())

    def test_a_zero_quantity_is_refused(self) -> None:
        """An order for none of something is a line somebody meant to delete."""
        response = self.create(**{"form-0-buyurtma_soni": "0"})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Application.objects.exists())

    def test_the_smallest_order_the_column_stores_is_allowed(self) -> None:
        # The floor is the smallest storable quantity, not a round number, so
        # the boundary itself has to be accepted rather than refused by one
        # thousandth.
        self.create(**{"form-0-buyurtma_soni": str(SMALLEST_QUANTITY)})

        self.assertEqual(
            Application.objects.get().items.get().buyurtma_soni,
            SMALLEST_QUANTITY,
        )

    def test_without_a_line_nothing_is_created(self) -> None:
        response = self.create(lines=0, **{"form-TOTAL_FORMS": "0"})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Application.objects.exists())

    def test_a_broken_line_leaves_no_application(self) -> None:
        """The header validates, the second line does not, and nothing lands.

        This is the transaction, tested from the outside: without it the
        application and its first line would already be written by the time
        the second failed.
        """
        response = self.create(lines=2, **{"form-1-buyurtma_soni": ""})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Application.objects.exists())
        self.assertFalse(ApplicationItem.objects.exists())

    def test_a_refused_submission_comes_back_with_what_was_typed(self) -> None:
        response = self.create_without_pdf(buyurtmachi_ismi="Dilnoza Yusupova")

        self.assertContains(response, "Dilnoza Yusupova")

    def test_the_form_reopens_when_it_is_refused(self) -> None:
        response = self.create_without_pdf()

        self.assertContains(response, 'id="create-modal" class="modal-overlay"')

    def test_get_is_refused(self) -> None:
        self.assertEqual(self.client.get(self.url).status_code, 405)


class CreatePermissionTests(TestCase):
    """The form answers to the permission of the page that offers it."""

    def setUp(self) -> None:
        self.department = Department.objects.create(name="Texnik bolim")
        self.category = MahsulotTuri.objects.create(
            category_number=100042, name="Metallurgiya"
        )
        self.url = reverse("ariza-yaratish")

    def test_somebody_who_may_not_open_the_page_may_not_create(self) -> None:
        """DEC-015 keeps Direktor off Qabul qilingan, so off this too."""
        self.client.force_login(make_user(DIREKTOR))

        response = self.client.post(self.url, {})

        self.assertEqual(response.status_code, 403)
        self.assertFalse(Application.objects.exists())

    def test_signing_in_is_required(self) -> None:
        response = self.client.post(self.url, {})

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])
        self.assertFalse(Application.objects.exists())


class RaiseApplicationTests(TestCase):
    """The creation door itself, beside the form that knocks on it."""

    def setUp(self) -> None:
        self.department = Department.objects.create(name="Texnik bolim")
        self.category = MahsulotTuri.objects.create(
            category_number=100042, name="Metallurgiya"
        )

    def test_an_application_without_a_line_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            Application.raise_application(
                items=[], department=self.department
            )

    def test_nothing_is_written_when_it_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            Application.raise_application(
                items=[], department=self.department
            )

        self.assertFalse(Application.objects.exists())

    def test_the_quantity_renders_without_its_trailing_zeros(self) -> None:
        """The reason soni_display exists, moved onto the line with it."""
        application = Application.raise_application(
            items=[
                {
                    "mahsulot_turi": self.category,
                    "buyurtma_nomi": "Asetilen gazi",
                    "buyurtma_soni": "2.500",
                    "olchov_birligi": "kg",
                }
            ],
            department=self.department,
        )

        self.assertEqual(str(application.items.get().soni_display), "2.5")

    def test_a_whole_quantity_does_not_become_scientific(self) -> None:
        application = Application.raise_application(
            items=[
                {
                    "mahsulot_turi": self.category,
                    "buyurtma_nomi": "Bolt M12",
                    "buyurtma_soni": "500",
                    "olchov_birligi": "ta",
                }
            ],
            department=self.department,
        )

        self.assertEqual(str(application.items.get().soni_display), "500")

    def test_deleting_an_application_takes_its_lines(self) -> None:
        """CASCADE: a line has no meaning without the application."""
        application = Application.raise_application(
            items=[
                {
                    "mahsulot_turi": self.category,
                    "buyurtma_nomi": "Bolt M12",
                    "buyurtma_soni": 1,
                    "olchov_birligi": "ta",
                }
            ],
            department=self.department,
        )

        application.delete()

        self.assertFalse(ApplicationItem.objects.exists())

    def test_a_negative_quantity_is_refused_by_the_database_too(self) -> None:
        """The form is not the only way in, so the rule is not only on it.

        raise_application() bulk_creates, which runs no validator at all - so
        without the constraint the #33 finding would be fixed on the page and
        open from code.
        """
        from django.db.utils import IntegrityError

        with self.assertRaises(IntegrityError):
            Application.raise_application(
                items=[
                    {
                        "mahsulot_turi": self.category,
                        "buyurtma_nomi": "Bolt M12",
                        "buyurtma_soni": -5,
                        "olchov_birligi": "ta",
                    }
                ],
                department=self.department,
            )

    def test_a_category_in_use_on_a_line_cannot_be_deleted(self) -> None:
        """PROTECT: master data somebody else maintains, as before the move."""
        from django.db.models import ProtectedError

        Application.raise_application(
            items=[
                {
                    "mahsulot_turi": self.category,
                    "buyurtma_nomi": "Bolt M12",
                    "buyurtma_soni": 1,
                    "olchov_birligi": "ta",
                }
            ],
            department=self.department,
        )

        with self.assertRaises(ProtectedError):
            self.category.delete()
