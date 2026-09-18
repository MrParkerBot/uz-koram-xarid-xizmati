"""Scaffolding shared by the test modules.

Users are created the way the application creates them, with a password
generated per run so the repository never carries a string that could be
tried against a real deployment. The PDF fixture is a genuinely parseable
document, because the approval stamp opens it and writes to it.
"""

from __future__ import annotations

import shutil
import tempfile
from io import BytesIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractBaseUser
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils.crypto import get_random_string
from pypdf import PdfWriter

from xarid.models import (
    ADMIN,
    Application,
    ArizaStatus,
    Department,
    MahsulotTuri,
    PurchaseApplication,
    Supplier,
    UserType,
    assign_user_type,
    profile_of,
)

PASSWORD = get_random_string(24)

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


def a_pdf(name: str = "ariza.pdf", pages: int = 1) -> SimpleUploadedFile:
    """An uploaded file that passes validate_pdf and that pypdf can read."""
    return SimpleUploadedFile(name, pdf_bytes(pages), content_type="application/pdf")


def page(name: str, *args) -> str:
    """The URL of one application page or action, by its bare page name."""
    return reverse(f"xarid:{name}", args=args)


def make_user(
    username: str,
    *,
    user_type: str | None = None,
    department: Department | None = None,
    first_name: str = "",
    last_name: str = "",
    is_staff: bool = False,
    is_superuser: bool = False,
) -> AbstractBaseUser:
    """An account with PASSWORD, optionally given a User Type and a department."""
    user = get_user_model().objects.create_user(
        username=username,
        password=PASSWORD,
        first_name=first_name,
        last_name=last_name,
        is_staff=is_staff,
        is_superuser=is_superuser,
    )
    if user_type is not None:
        assign_user_type(user, UserType.objects.get(name=user_type))
    if department is not None:
        profile = profile_of(user)
        profile.department = department
        profile.save(update_fields=["department"])
    return user


def a_department(name: str = "Texnik bo`lim") -> Department:
    department, _ = Department.objects.get_or_create(name=name)
    return department


def a_category(number: int = 100042, name: str = "Metallurgiya") -> MahsulotTuri:
    category, _ = MahsulotTuri.objects.get_or_create(
        category_number=number, defaults={"name": name}
    )
    return category


def a_supplier(name: str = "Texnoprom LLC", inn: str = "123456789") -> Supplier:
    supplier, _ = Supplier.objects.get_or_create(name=name, defaults={"inn": inn})
    return supplier


def an_application(
    *,
    department: Department | None = None,
    category: MahsulotTuri | None = None,
    with_pdf: bool = False,
    **fields,
) -> Application:
    """An incoming application with one order line."""
    if with_pdf:
        fields["pdf"] = a_pdf()
    return Application.raise_application(
        items=[
            {
                "mahsulot_turi": category or a_category(),
                "buyurtma_nomi": "Bolt M12x50",
                "buyurtma_soni": "500",
                "olchov_birligi": "ta",
            }
        ],
        department=department or a_department(),
        buyurtmachi_ismi="Bobur Toshmatov",
        **fields,
    )


def an_accepted_application(accepted_by: AbstractBaseUser, **fields) -> Application:
    application = an_application(**fields)
    application.accept(by=accepted_by)
    return application


def an_assigned_application(
    assigned_by: AbstractBaseUser, specialist: AbstractBaseUser, **fields
) -> Application:
    application = an_accepted_application(assigned_by, **fields)
    application.assign(by=assigned_by, specialist=specialist)
    return application


def a_purchase_application(
    requester: AbstractBaseUser,
    department: Department,
    *,
    category: MahsulotTuri | None = None,
    with_pdf: bool = True,
) -> PurchaseApplication:
    """A purchase application awaiting the department head."""
    fields = {}
    if with_pdf:
        fields["pdf"] = a_pdf()
    return PurchaseApplication.raise_purchase_application(
        items=[
            {
                "mahsulot_turi": category or a_category(),
                "buyurtma_nomi": "Kabel 4mm",
                "buyurtma_soni": "200",
                "olchov_birligi": "m",
            }
        ],
        department=department,
        shartnoma_nomi="Kabel xaridi",
        created_by=requester,
        status=ArizaStatus.with_code(ArizaStatus.Code.NEW),
        **fields,
    )


def formset_management(total: int = 1) -> dict[str, str]:
    """The management form fields a model formset POST must carry."""
    return {
        "form-TOTAL_FORMS": str(total),
        "form-INITIAL_FORMS": "0",
        "form-MIN_NUM_FORMS": "1",
        "form-MAX_NUM_FORMS": "1000",
    }


class TemporaryAttachmentsMixin:
    """Point every attachment field at a temporary directory for the class.

    The storages are built once at import from settings.ATTACHMENT_ROOT, so
    override_settings cannot move them; their location is replaced directly
    and restored afterwards.
    """

    attachment_fields = (
        Application._meta.get_field("pdf"),
        PurchaseApplication._meta.get_field("pdf"),
        PurchaseApplication._meta.get_field("asl_pdf"),
    )

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.attachment_root = tempfile.mkdtemp()
        cls.original_locations = []
        for field in cls.attachment_fields:
            storage = field.storage
            cls.original_locations.append((storage, storage._location))
            storage._location = cls.attachment_root
            storage.__dict__.pop("base_location", None)
            storage.__dict__.pop("location", None)

    @classmethod
    def tearDownClass(cls) -> None:
        for storage, original in cls.original_locations:
            storage._location = original
            storage.__dict__.pop("base_location", None)
            storage.__dict__.pop("location", None)
        shutil.rmtree(cls.attachment_root, ignore_errors=True)
        super().tearDownClass()


class SignedInAdminTestCase(TemporaryAttachmentsMixin, TestCase):
    """A test case whose client is signed in as an Admin.

    Admin because every page is closed to the types DEC-015 permits, and the
    tests that use this base are about pages rather than about permissions.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        cls.admin = make_user("test.admin", user_type=ADMIN, first_name="Test", last_name="Admin")

    def setUp(self) -> None:
        super().setUp()
        self.client.force_login(self.admin)
