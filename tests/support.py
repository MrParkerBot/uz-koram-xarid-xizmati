"""Scaffolding shared by the test modules.

Users are created the way the application creates them, with a password
generated per run so the repository never carries a string that could be
tried against a real deployment. The PDF fixture is a genuinely parseable
document, because the approval stamp opens it and writes to it.
"""

from __future__ import annotations

import shutil
import tempfile
from datetime import date, datetime, time
from decimal import Decimal
from io import BytesIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractBaseUser
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import get_random_string
from pypdf import PdfWriter

from xarid.models import (
    ADMIN,
    BOLIM_BOSHLIGI,
    DIREKTOR,
    USERS,
    Application,
    ArizaStatus,
    Contract,
    Department,
    MahsulotTuri,
    PurchaseApplication,
    ShartnomaStatus,
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


def send_form_of(contract) -> str:
    """What marks a row's controls on Kelishinlingan in the page's HTML.

    Saqlash and Yuborish share one form per row, because they share the
    status drop-down and a select can only belong to one form. Both buttons
    name it by id, so that id is what a test asking whether the row's
    controls are drawn looks for.
    """
    return f'form="sht-qator-{contract.pk}"'


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


def arrived_on(day: date, hour: int = 12) -> Application:
    """An application whose arrival is a chosen local day, not the test run.

    The arrival timestamp is written on insert, so it is rewritten in the
    database rather than passed to the builder.
    """
    application = an_application()
    moment = timezone.make_aware(datetime.combine(day, time(hour, 0)))
    Application.objects.filter(pk=application.pk).update(kelib_tushgan_sana=moment)
    application.refresh_from_db()
    return application


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


def assigned_on(
    day: date,
    assigned_by: AbstractBaseUser,
    specialist: AbstractBaseUser,
    **fields,
) -> Application:
    """An application assigned to a specialist on a chosen local day.

    The assignment date is written by assign(), so it is rewritten in the
    database afterwards rather than passed in.
    """
    application = an_assigned_application(assigned_by, specialist, **fields)
    moment = timezone.make_aware(datetime.combine(day, time(12, 0)))
    Application.objects.filter(pk=application.pk).update(tayinlangan_sana=moment)
    application.refresh_from_db()
    return application


def a_contract(
    application: Application,
    created_by: AbstractBaseUser,
    *,
    status: ShartnomaStatus | None = None,
    supplier: Supplier | None = None,
    with_pdf: bool = False,
    **columns,
) -> Contract:
    """One contract of one priced row, raised against an application.

    Without an attachment unless one is asked for. The form has required one
    since TASK-UZK-036A, but the model does not, and the contracts entered
    before it have none - so a test about the attachment says so, and every
    other test is spared writing a file. A class asking for one needs
    TemporaryAttachmentsMixin, which is where the file goes.

    Any other column - izoh, the dates - is passed straight through.
    """
    fields = {}
    if with_pdf:
        fields["pdf"] = a_pdf("shartnoma.pdf")

    return Contract.raise_contract(
        items=[
            {
                "buyurtma_nomi": "Bolt M12x50",
                "part_number": "",
                "buyurtma_soni": Decimal("1"),
                "olchov_birligi": "ta",
                "narxi": Decimal("10"),
            }
        ],
        created_by=created_by,
        application=application,
        supplier=supplier or a_supplier(),
        status=status,
        **fields,
        **columns,
    )


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


def an_arrived_purchase_request(
    *,
    department: Department | None = None,
    category: MahsulotTuri | None = None,
    with_pdf: bool = False,
) -> PurchaseApplication:
    """A purchase request that has been the whole way along DEC-016's chain.

    Both approvals taken, so it has raised the department's own application
    and stands at the purchasing department's step - the rows Kelib Tushgan
    Arizalar holds. Its approvers are made here and given names nothing else
    uses, because what a caller cares about is the request, not the chain.
    """
    department = department or a_department()
    suffix = get_random_string(8).lower()
    requester = make_user(f"arrived.requester.{suffix}", user_type=USERS, department=department)
    head = make_user(f"arrived.head.{suffix}", user_type=BOLIM_BOSHLIGI, department=department)
    direktor = make_user(f"arrived.direktor.{suffix}", user_type=DIREKTOR)

    request = a_purchase_application(
        requester, department, category=category, with_pdf=with_pdf
    )
    request.approve(by=head)
    request.approve(by=direktor)
    request.refresh_from_db()

    return request


def raised_on(day: date, hour: int = 12, **fields) -> PurchaseApplication:
    """An arrived purchase request raised on a chosen local day, not the test run.

    yaratilingan_sana is written on insert, so it is rewritten in the database
    rather than passed to the builder.
    """
    request = an_arrived_purchase_request(**fields)
    moment = timezone.make_aware(datetime.combine(day, time(hour, 0)))
    PurchaseApplication.objects.filter(pk=request.pk).update(yaratilingan_sana=moment)
    request.refresh_from_db()
    return request


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
        Contract._meta.get_field("pdf"),
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
