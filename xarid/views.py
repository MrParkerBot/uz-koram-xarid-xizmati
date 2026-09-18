"""Every view of the purchasing department's pages.

Every page view is wrapped in urls.py by require_page_permission(), which
applies Django's login_required and then the DEC-015 page matrix. The views
here decide what a page shows and what an action does; which rows a signed-in
person may touch is decided per view where the page alone cannot say.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import AbstractBaseUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F, Prefetch, QuerySet
from django.http import (
    FileResponse,
    Http404,
    HttpRequest,
    HttpResponse,
    HttpResponseForbidden,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from xarid.attachments import attachment_response
from xarid.exports import ExportColumn, TableExport, export_response, lines_of, local_date
from xarid.filters import (
    DateColumn,
    FilterColumn,
    TableFilter,
    newest_and_oldest_first,
    report_invalid_filters,
)
from xarid.forms import (
    SUGGESTED_UNITS,
    ApplicationForm,
    ApplicationItemFormSet,
    ArizaStatusForm,
    ContractForm,
    ContractItemFormSet,
    DepartmentForm,
    MahsulotTuriForm,
    MasterDataForm,
    PurchaseApplicationForm,
    PurchaseApplicationItemFormSet,
    ShartnomaStatusForm,
    ShartnomaTuriForm,
    SupplierForm,
    UserAdministrationForm,
    UserSpecialtyForm,
    UserTypeForm,
)
from xarid.jinja2 import display_name
from xarid.models import (
    BOLIM_BOSHLIGI,
    DIREKTOR,
    Application,
    ApplicationItem,
    ArizaStatus,
    Contract,
    ContractItem,
    Department,
    MahsulotTuri,
    MasterDataRecord,
    Notification,
    PurchaseApplication,
    PurchaseApplicationItem,
    ShartnomaStatus,
    ShartnomaTuri,
    Supplier,
    UserProfile,
    UserSpecialty,
    UserType,
    assignable_specialists,
    deactivate,
    department_of,
    has_user_type,
)
from xarid.permissions import (
    acts_on_own_work_only,
    contract_editor,
    first_page_for,
    grant_contract_editing,
    may_open,
    revoke_contract_editing,
)
from xarid.reports import department_purchasing, staff_workload

USERS_TEMPLATE = "xarid/pages/users.html"
INCOMING_TEMPLATE = "xarid/pages/kelib-arizalar.html"
ACCEPTED_TEMPLATE = "xarid/pages/qabul-arizalar.html"
ASSIGNED_TEMPLATE = "xarid/pages/tayinlangan.html"
AGREED_CONTRACTS_TEMPLATE = "xarid/pages/kelishinlingan.html"
PURCHASE_TEMPLATE = "xarid/pages/xarid-ariza.html"

# The pages that are still the supplied prototype: reports, the drafted
# contracts list and the two system pages. Each is a template with no data
# behind it yet, served under its own permission. The dashboard is index.html.
PROTOTYPE_PAGE_TEMPLATES: dict[str, str] = {
    "dashboard": "xarid/index.html",
    "tuzilgan": "xarid/pages/tuzilgan.html",
    "mahsulot-tur": "xarid/pages/mahsulot-tur.html",
    "mahsulotlar": "xarid/pages/mahsulotlar.html",
    "integration": "xarid/pages/integration.html",
    "logs": "xarid/pages/logs.html",
}


def prototype_page(page_name: str) -> Callable[..., HttpResponse]:
    """A view rendering one prototype page by its page name."""
    return TemplateView.as_view(template_name=PROTOTYPE_PAGE_TEMPLATES[page_name])


@login_required
def landing_page(request: HttpRequest) -> HttpResponse:
    """Send a signed-in user to the first page their type may open.

    Not the dashboard: three of the six types may not open it (DEC-015), so
    signing in correctly would answer 403.

    Raises:
        PermissionDenied: when the account has no User Type and so may open
            nothing.
    """
    page_name = first_page_for(request.user)
    if page_name is None:
        raise PermissionDenied("Hisobingizga User Type belgilanmagan. Admin bilan bog'laning.")

    return redirect(f"xarid:{page_name}")


# ---------------------------------------------------------------------------
# Master data pages: a table beside a form (sections 3.2, 3.5-3.8)
# ---------------------------------------------------------------------------


class MasterDataPage:
    """The four views one master data page needs, built from what differs.

    Save adds a row and redirects, an invalid Save re-renders the page with
    the errors still on the form, Edit fills the form in from ?edit=, and
    Delete deactivates after the confirmation the template asks for.
    """

    def __init__(
        self,
        *,
        model: type[MasterDataRecord],
        form_class: type[MasterDataForm],
        template_name: str,
        page_name: str,
        context_object_name: str,
    ) -> None:
        """Describe one page.

        Args:
            model: the master data table this page maintains.
            form_class: the form that captures one row.
            template_name: the template to render.
            page_name: the URL name of the list, used for redirects.
            context_object_name: what the template calls the list of rows.
        """
        self.model = model
        self.form_class = form_class
        self.template_name = template_name
        self.page_name = page_name
        self.context_object_name = context_object_name

        self.list_records: Callable[..., HttpResponse] = self._list_records
        self.create_record: Callable[..., HttpResponse] = require_POST(self._create_record)
        self.update_record: Callable[..., HttpResponse] = require_POST(self._update_record)
        self.delete_record: Callable[..., HttpResponse] = require_POST(self._delete_record)

    def _render_page(
        self,
        request: HttpRequest,
        form: MasterDataForm,
        edited_record: MasterDataRecord | None = None,
    ) -> HttpResponse:
        return render(
            request,
            self.template_name,
            {
                self.context_object_name: self.model.objects.active(),
                "form": form,
                "edited_record": edited_record,
            },
        )

    def _active_record(self, pk: int | str) -> MasterDataRecord:
        """One row that has not been deleted, or a 404.

        pk arrives as a raw string from ?edit=, so a value that is not a
        number is a 404 rather than a ValueError.
        """
        try:
            return get_object_or_404(self.model, pk=pk, is_active=True)
        except (ValueError, ValidationError) as not_a_pk:
            raise Http404(
                f"{pk!r} is not the id of a {self.model._meta.verbose_name}."
            ) from not_a_pk

    def _list_records(self, request: HttpRequest) -> HttpResponse:
        edit_id = request.GET.get("edit")
        if edit_id:
            edited = self._active_record(edit_id)
            return self._render_page(request, self.form_class(instance=edited), edited)

        return self._render_page(request, self.form_class())

    def _create_record(self, request: HttpRequest) -> HttpResponse:
        form = self.form_class(request.POST)
        if not form.is_valid():
            return self._render_page(request, form)

        form.save()
        return redirect(f"xarid:{self.page_name}")

    def _update_record(self, request: HttpRequest, pk: int) -> HttpResponse:
        edited = self._active_record(pk)

        form = self.form_class(request.POST, instance=edited)
        if not form.is_valid():
            return self._render_page(request, form, edited)

        form.save()
        return redirect(f"xarid:{self.page_name}")

    def _delete_record(self, request: HttpRequest, pk: int) -> HttpResponse:
        deactivate(self._active_record(pk))

        return redirect(f"xarid:{self.page_name}")


class UserTypePage(MasterDataPage):
    """The User Types page, where the six system roles cannot be renamed or deleted."""

    def _update_record(self, request: HttpRequest, pk: int) -> HttpResponse:
        edited = self._active_record(pk)

        # A rename of a system role is refused rather than quietly dropped by
        # the disabled field: a save that reports success while discarding
        # what was typed is the worst of the answers.
        submitted_name = request.POST.get("name", edited.name)
        if edited.is_system_role and submitted_name != edited.name:
            raise PermissionDenied(f"{edited.name} - tizim roli, nomini o'zgartirib bo'lmaydi.")

        return super()._update_record(request, pk)

    def _delete_record(self, request: HttpRequest, pk: int) -> HttpResponse:
        deleted = self._active_record(pk)

        if deleted.is_system_role:
            # A deactivated type is no type at all, so deleting Admin would
            # take every administrator's access with it.
            raise PermissionDenied(f"{deleted.name} - tizim roli, o'chirib bo'lmaydi.")

        deactivate(deleted)
        return redirect(f"xarid:{self.page_name}")


specialty_page = MasterDataPage(
    model=UserSpecialty,
    form_class=UserSpecialtyForm,
    template_name="xarid/pages/user-specialty.html",
    page_name="user-specialty",
    context_object_name="specialties",
)

user_type_page = UserTypePage(
    model=UserType,
    form_class=UserTypeForm,
    template_name="xarid/pages/user-types.html",
    page_name="user-types",
    context_object_name="user_types",
)

ariza_status_page = MasterDataPage(
    model=ArizaStatus,
    form_class=ArizaStatusForm,
    template_name="xarid/pages/ariza-status.html",
    page_name="ariza-status",
    context_object_name="statuses",
)

shartnoma_status_page = MasterDataPage(
    model=ShartnomaStatus,
    form_class=ShartnomaStatusForm,
    template_name="xarid/pages/shartnoma-status.html",
    page_name="shartnoma-status",
    context_object_name="statuses",
)

mahsulot_turi_page = MasterDataPage(
    model=MahsulotTuri,
    form_class=MahsulotTuriForm,
    template_name="xarid/pages/mahsulot-turlari.html",
    page_name="mahsulot-turlari",
    context_object_name="categories",
)

shartnoma_turi_page = MasterDataPage(
    model=ShartnomaTuri,
    form_class=ShartnomaTuriForm,
    template_name="xarid/pages/shartnoma-turi.html",
    page_name="shartnoma-turi",
    context_object_name="contract_types",
)

department_page = MasterDataPage(
    model=Department,
    form_class=DepartmentForm,
    template_name="xarid/pages/bolim-royhati.html",
    page_name="bolim-royhati",
    context_object_name="departments",
)

supplier_page = MasterDataPage(
    model=Supplier,
    form_class=SupplierForm,
    template_name="xarid/pages/firmalar.html",
    page_name="firmalar",
    context_object_name="suppliers",
)


# ---------------------------------------------------------------------------
# The Users page (section 3.3)
# ---------------------------------------------------------------------------


def listed_users() -> QuerySet:
    """The active users the page shows, with their profiles joined."""
    return (
        get_user_model()
        .objects.filter(is_active=True)
        .select_related("profile", "profile__user_type", "profile__department")
        .order_by("first_name", "last_name", "id")
    )


def render_users_page(
    request: HttpRequest,
    form: UserAdministrationForm,
    edited_user_id: int | None = None,
) -> HttpResponse:
    return render(
        request,
        USERS_TEMPLATE,
        {
            "users": listed_users(),
            "contract_editor": contract_editor(),
            "form": form,
            "edited_user_id": edited_user_id,
            # The modal opens by itself when a submission failed or an edit
            # was requested.
            "open_form": bool(form.errors) or edited_user_id is not None,
        },
    )


def user_list(request: HttpRequest) -> HttpResponse:
    """The Users page, optionally with one user open for editing."""
    edit_user_id = request.GET.get("edit")
    if edit_user_id:
        edited_user = get_object_or_404(get_user_model(), pk=edit_user_id, is_active=True)
        return render_users_page(
            request, UserAdministrationForm.for_user(edited_user), edited_user.pk
        )

    return render_users_page(request, UserAdministrationForm())


@require_POST
def user_create(request: HttpRequest) -> HttpResponse:
    """Add a user."""
    form = UserAdministrationForm(request.POST)
    if not form.is_valid():
        return render_users_page(request, form)

    form.save()
    return redirect("xarid:users")


@require_POST
def user_update(request: HttpRequest, pk: int) -> HttpResponse:
    """Change a user's details, and their password when one was supplied."""
    edited_user = get_object_or_404(get_user_model(), pk=pk, is_active=True)

    form = UserAdministrationForm(request.POST, edited_user=edited_user)
    if not form.is_valid():
        return render_users_page(request, form, edited_user.pk)

    form.save()
    return redirect("xarid:users")


@require_POST
def user_delete(request: HttpRequest, pk: int) -> HttpResponse:
    """Deactivate a user (DEC-009): they leave the list and cannot sign in."""
    deleted_user = get_object_or_404(get_user_model(), pk=pk, is_active=True)

    if deleted_user.pk == request.user.pk:
        return HttpResponseForbidden("O'z hisobingizni o'chira olmaysiz.")

    deleted_user.is_active = False
    deleted_user.save(update_fields=["is_active"])

    return redirect("xarid:users")


@require_POST
def user_contract_editing(request: HttpRequest, pk: int) -> HttpResponse:
    """Grant or revoke the contract-edit permission for one user.

    The submitted state is what the switch now shows: a checked box is a
    grant and an unchecked one is a revocation.
    """
    subject = get_object_or_404(get_user_model(), pk=pk, is_active=True)

    if request.POST.get("may_edit_contracts") == "on":
        grant_contract_editing(subject)
    else:
        revoke_contract_editing(subject)

    return redirect("xarid:users")


# ---------------------------------------------------------------------------
# Applications (sections 4.1, 4.2): incoming, accepted, assigned
# ---------------------------------------------------------------------------

# Which page shows an application at each stage. The attachment follows the
# record rather than the route: a PDF is downloadable by whoever may open the
# page the application is currently on. A rejected application is on no page,
# so its attachment stops being reachable.
PAGE_SHOWING_STAGE: dict[str, str] = {
    Application.Stage.INCOMING: "kelib-arizalar",
    Application.Stage.ACCEPTED: "qabul-arizalar",
    Application.Stage.ASSIGNED: "tayinlangan",
}

# The four columns one order line is made of, named once so the creation
# views and the line models cannot drift apart.
ORDER_LINE_FIELDS = ("mahsulot_turi", "buyurtma_nomi", "buyurtma_soni", "olchov_birligi")

CONTRACT_LINE_FIELDS = ("buyurtma_nomi", "part_number", "buyurtma_soni", "olchov_birligi", "narxi")

# The columns each list page filters by (REQ-ARIZA-001). Options are derived
# from the rows the page already shows, so nothing outside a user's view is
# offered.
BY_DEPARTMENT = FilterColumn("bolim", "Bo'lim", "department_id", ("department__name",))
BY_ORDERED_CATEGORY = FilterColumn(
    "mahsulot",
    "Mahsulot turi",
    "items__mahsulot_turi_id",
    ("items__mahsulot_turi__name",),
    multi_valued=True,
)
BY_SPECIALIST = FilterColumn(
    "xodim",
    "Tayinlangan xodim",
    "assigned_to_id",
    ("assigned_to__first_name", "assigned_to__last_name"),
    label_fallback_lookup="assigned_to__username",
)
BY_STATUS = FilterColumn("holat", "Holati", "status_id", ("status__name",))
BY_SUPPLIER = FilterColumn("firma", "Firma", "supplier_id", ("supplier__name",))

# The period each list page narrows by and the ordering its drop-down offers
# (REQ-YUKLAMA-001). Each page names the date it already shows in a column,
# and orders by that same date so the drop-down reorders what is on screen.
INCOMING_PERIOD = DateColumn("Kelib tushgan sana", "kelib_tushgan_sana")
INCOMING_SORTS = newest_and_oldest_first(INCOMING_PERIOD.lookup)
ACCEPTED_PERIOD = DateColumn("Qabul qilingan sana", "qabul_qilingan_sana")
ACCEPTED_SORTS = newest_and_oldest_first(ACCEPTED_PERIOD.lookup)
ASSIGNED_PERIOD = DateColumn("Tayinlangan sana", "tayinlangan_sana")
ASSIGNED_SORTS = newest_and_oldest_first(ASSIGNED_PERIOD.lookup)
CONTRACT_PERIOD = DateColumn("Yaratilgan sana", "yaratilingan_sana")
CONTRACT_SORTS = newest_and_oldest_first(CONTRACT_PERIOD.lookup)
PURCHASE_PERIOD = DateColumn("Yaratilgan sana", "yaratilingan_sana")
PURCHASE_SORTS = newest_and_oldest_first(PURCHASE_PERIOD.lookup)

INCOMING_FILTERS = (BY_DEPARTMENT, BY_ORDERED_CATEGORY)
ACCEPTED_FILTERS = (BY_DEPARTMENT, BY_SPECIALIST)
ASSIGNED_FILTERS = (BY_DEPARTMENT, BY_STATUS)
CONTRACT_FILTERS = (BY_SUPPLIER,)
PURCHASE_FILTERS = (BY_ORDERED_CATEGORY,)


def filled_in_rows(formset, fields: tuple[str, ...]) -> list[dict[str, object]]:
    """The rows somebody actually filled in, in the order they gave.

    A formset always carries at least one spare row; a spare nobody typed into
    comes back with empty cleaned_data and is dropped. Only the named fields
    are taken, never the hidden id a model formset adds.
    """
    return [
        {field: row.cleaned_data[field] for field in fields}
        for row in formset.forms
        if row.cleaned_data
    ]


def application_lines() -> Prefetch:
    """The order lines of an application, with the category each names."""
    return Prefetch("items", queryset=ApplicationItem.objects.select_related("mahsulot_turi"))


def incoming_applications() -> QuerySet[Application]:
    """The applications still waiting to be accepted or rejected."""
    return (
        Application.objects.filter(stage=Application.Stage.INCOMING)
        .select_related("department")
        .prefetch_related(application_lines())
    )


def accepted_applications() -> QuerySet[Application]:
    """The applications on the Qabul qilingan page: accepted, and assigned.

    Assigned ones stay because re-assignment is offered on this row. Ordered
    by when they were accepted, newest first.
    """
    return (
        Application.objects.filter(
            stage__in=(Application.Stage.ACCEPTED, Application.Stage.ASSIGNED)
        )
        .select_related("department", "assigned_to")
        .prefetch_related(application_lines())
        .order_by(
            F("qabul_qilingan_sana").desc(nulls_last=True),
            "-kelib_tushgan_sana",
            "-id",
        )
    )


def assigned_applications(specialist: AbstractBaseUser) -> QuerySet[Application]:
    """The applications one specialist has been given (REQ-ARIZA-007)."""
    return (
        Application.objects.filter(stage=Application.Stage.ASSIGNED, assigned_to=specialist)
        .select_related("department", "status")
        .prefetch_related(application_lines())
        .order_by(F("tayinlangan_sana").desc(nulls_last=True), "-id")
    )


def all_assigned_applications() -> QuerySet[Application]:
    """Every application somebody is working on, whoever that is."""
    return (
        Application.objects.filter(stage=Application.Stage.ASSIGNED)
        .select_related("department", "assigned_to", "status")
        .prefetch_related(application_lines())
        .order_by(F("tayinlangan_sana").desc(nulls_last=True), "-id")
    )


def incoming_list(request: HttpRequest) -> HttpResponse:
    """The table of applications that have arrived and not been decided."""
    table_filter = TableFilter(
        INCOMING_FILTERS,
        incoming_applications(),
        request.GET,
        date_column=INCOMING_PERIOD,
        sort_choices=INCOMING_SORTS,
    )
    report_invalid_filters(request, table_filter)

    return render(
        request,
        INCOMING_TEMPLATE,
        {"applications": table_filter.apply(), "table_filter": table_filter},
    )


def accepted_page(
    chosen_filters: Mapping[str, str] | None = None,
    form: ApplicationForm | None = None,
    items: ApplicationItemFormSet | None = None,
) -> dict[str, object]:
    """Everything the Qabul qilingan page renders.

    Args:
        chosen_filters: the request's query parameters, for the filter bar.
        form: a bound application form to re-render with its errors.
        items: the bound order lines, likewise.
    """
    table_filter = TableFilter(
        ACCEPTED_FILTERS,
        accepted_applications(),
        chosen_filters,
        date_column=ACCEPTED_PERIOD,
        sort_choices=ACCEPTED_SORTS,
    )
    return {
        "applications": table_filter.apply(),
        "table_filter": table_filter,
        "form": form if form is not None else ApplicationForm(),
        "item_formset": (
            items
            if items is not None
            else ApplicationItemFormSet(queryset=ApplicationItem.objects.none())
        ),
        "open_form": form is not None,
        "specialists": assignable_specialists(),
    }


def accepted_list(request: HttpRequest) -> HttpResponse:
    """The Qabul qilingan Arizalar table and the creation form (REQ-ARIZA-006)."""
    page_context = accepted_page(request.GET)
    report_invalid_filters(request, page_context["table_filter"])

    return render(request, ACCEPTED_TEMPLATE, page_context)


@require_POST
def application_create(request: HttpRequest) -> HttpResponse:
    """Create an application and its order lines (REQ-ARIZA-008 to 011).

    The application is created already accepted: the form is on the Qabul
    qilingan page and its button is Yaratish va Tayinlash.
    """
    form = ApplicationForm(request.POST, request.FILES)
    items = ApplicationItemFormSet(request.POST, queryset=ApplicationItem.objects.none())

    if not (form.is_valid() and items.is_valid()):
        messages.error(request, "Ariza yaratilmadi: formani tekshiring.")
        return render(request, ACCEPTED_TEMPLATE, accepted_page(form=form, items=items))

    with transaction.atomic():
        application = Application.raise_application(
            items=filled_in_rows(items, ORDER_LINE_FIELDS),
            department=form.cleaned_data["department"],
            buyurtmachi_ismi=form.cleaned_data["buyurtmachi_ismi"],
            izoh=form.cleaned_data["izoh"],
            pdf=form.cleaned_data["pdf"],
            stage=Application.Stage.ACCEPTED,
            qabul_qilingan_sana=timezone.now(),
            accepted_by=request.user,
            status=ArizaStatus.with_code(ArizaStatus.Code.ACCEPTED),
        )

    messages.success(request, f"{application.ariza_raqami} yaratildi.")

    return redirect("xarid:qabul-arizalar")


def assigned_list(request: HttpRequest) -> HttpResponse:
    """The Tayinlangan Arizalar page (REQ-ARIZA-012).

    A Katta Mutaxasis sees the applications assigned to them and nobody
    else's; everybody else DEC-015 lets in hands work out and sees all of it.
    """
    own_work_only = acts_on_own_work_only(request.user)
    visible = assigned_applications(request.user) if own_work_only else all_assigned_applications()
    table_filter = TableFilter(
        ASSIGNED_FILTERS,
        visible,
        request.GET,
        date_column=ASSIGNED_PERIOD,
        sort_choices=ASSIGNED_SORTS,
    )
    report_invalid_filters(request, table_filter)

    return render(
        request,
        ASSIGNED_TEMPLATE,
        {
            "applications": table_filter.apply(),
            "table_filter": table_filter,
            "shows_the_holder": not own_work_only,
            "statuses": ArizaStatus.objects.active(),
        },
    )


def held_application(request: HttpRequest, pk: int) -> Application:
    """The application this request may act on, or a refusal.

    Raises:
        PermissionDenied: when a specialist reaches for work that is not
            theirs.
        Http404: when there is no such application.
    """
    application = get_object_or_404(Application, pk=pk)

    if acts_on_own_work_only(request.user) and application.assigned_to_id != request.user.pk:
        raise PermissionDenied(f"{request.user} does not hold {application.ariza_raqami}.")

    return application


@require_POST
def accept_assigned_application(request: HttpRequest, pk: int) -> HttpResponse:
    """The holder takes the work assigned to them (REQ-ARIZA-013).

    Recorded against the holder rather than whoever pressed the button, and
    Admin is told inside the same transaction.
    """
    application = held_application(request, pk)

    try:
        with transaction.atomic():
            taken = application.accept_as_specialist(by=application.assigned_to)
            if taken:
                Notification.tell_admins_of_acceptance(application)
    except ValueError:
        messages.error(
            request, f"{application.ariza_raqami} qabul qilinmadi: ariza tayinlanmagan."
        )
        return redirect("xarid:tayinlangan")

    if taken:
        messages.success(request, f"{application.ariza_raqami} qabul qilindi.")
    else:
        messages.info(request, f"{application.ariza_raqami} allaqachon qabul qilingan.")

    return redirect("xarid:tayinlangan")


@require_POST
def set_application_status(request: HttpRequest, pk: int) -> HttpResponse:
    """Mark the state an assigned application is currently in (REQ-ARIZA-013)."""
    application = held_application(request, pk)
    chosen = request.POST.get("status")
    status = (
        ArizaStatus.objects.filter(pk=int(chosen), is_active=True).first()
        if chosen and chosen.isdigit()
        else None
    )

    try:
        changed = application.set_status(status)
    except ValueError:
        if application.stage != Application.Stage.ASSIGNED:
            messages.error(
                request,
                f"{application.ariza_raqami} holati o`zgartirilmadi: ariza tayinlanmagan.",
            )
        else:
            messages.error(
                request,
                f"{application.ariza_raqami} holati o`zgartirilmadi: holat tanlanishi shart.",
            )

        return redirect("xarid:tayinlangan")

    if changed:
        messages.success(request, f"{application.ariza_raqami} holati: {status.name}.")
    else:
        messages.info(request, f"{application.ariza_raqami} allaqachon shu holatda.")

    return redirect("xarid:tayinlangan")


@login_required
def application_pdf(request: HttpRequest, pk: int) -> FileResponse:
    """Download one application's PDF (DEC-019).

    Asks the permission matrix about the page that currently shows the
    application, so the attachment stops being reachable at the same moment
    the row stops being visible.

    Raises:
        PermissionDenied: when the caller may not open the page this
            application is on, or the application is at a stage no page shows.
        Http404: when the application does not exist or has no attachment.
    """
    application = get_object_or_404(Application, pk=pk)

    page_name = PAGE_SHOWING_STAGE.get(application.stage)
    if page_name is None or not may_open(request.user, page_name):
        raise PermissionDenied(f"{request.user} may not see {application.ariza_raqami}.")

    return attachment_response(application.pdf, f"{application.ariza_raqami}.pdf")


@require_POST
def accept_application(request: HttpRequest, pk: int) -> HttpResponse:
    """Accept one incoming application (REQ-ARIZA-004).

    A stale page - the application was decided by somebody else meanwhile -
    is reported as a message rather than a 403: the caller had the permission
    they needed, and what changed is the application.
    """
    application = get_object_or_404(Application, pk=pk)

    try:
        accepted = application.accept(by=request.user)
    except ValueError:
        messages.error(
            request,
            f"{application.ariza_raqami} qabul qilinmadi: ariza allaqachon hal qilingan.",
        )
        return redirect("xarid:kelib-arizalar")

    if accepted:
        messages.success(request, f"{application.ariza_raqami} qabul qilindi.")
    else:
        messages.info(request, f"{application.ariza_raqami} allaqachon qabul qilingan.")

    return redirect("xarid:kelib-arizalar")


@require_POST
def reject_application(request: HttpRequest, pk: int) -> HttpResponse:
    """Reject one incoming application, with a reason (REQ-ARIZA-005)."""
    application = get_object_or_404(Application, pk=pk)

    try:
        rejected = application.reject(by=request.user, comment=request.POST.get("inkor_izohi", ""))
    except ValueError:
        if not application.is_incoming:
            messages.error(
                request,
                f"{application.ariza_raqami} inkor etilmadi: ariza allaqachon hal qilingan.",
            )
        else:
            messages.error(
                request,
                f"{application.ariza_raqami} inkor etilmadi: izoh kiritilishi shart.",
            )

        return redirect("xarid:kelib-arizalar")

    if rejected:
        messages.success(request, f"{application.ariza_raqami} inkor etildi.")
    else:
        messages.info(request, f"{application.ariza_raqami} allaqachon inkor etilgan.")

    return redirect("xarid:kelib-arizalar")


def chosen_specialist(chosen: str | None) -> AbstractBaseUser | None:
    """The assignable specialist a submitted choice names, or None.

    Anything that is not a number is nobody, and so is a number naming an
    account the chooser would never have offered.
    """
    if not chosen or not chosen.isdigit():
        return None

    return assignable_specialists().filter(pk=int(chosen)).first()


@require_POST
def assign_application(request: HttpRequest, pk: int) -> HttpResponse:
    """Give one accepted application to a specialist, or move it (REQ-ARIZA-007)."""
    application = get_object_or_404(Application, pk=pk)
    specialist = chosen_specialist(request.POST.get("xodim"))

    try:
        assigned = application.assign(by=request.user, specialist=specialist)
    except ValueError:
        if specialist is None:
            messages.error(
                request,
                f"{application.ariza_raqami} tayinlanmadi: Katta Mutaxasis tanlanishi shart.",
            )
        else:
            messages.error(
                request,
                f"{application.ariza_raqami} tayinlanmadi: ariza qabul qilinmagan.",
            )

        return redirect("xarid:qabul-arizalar")

    if assigned:
        name = specialist.get_full_name() or specialist.username
        messages.success(request, f"{application.ariza_raqami} {name}ga tayinlandi.")
    else:
        messages.info(request, f"{application.ariza_raqami} allaqachon shu xodimga tayinlangan.")

    return redirect("xarid:qabul-arizalar")


# ---------------------------------------------------------------------------
# Contracts (sections 4.6, 4.8)
# ---------------------------------------------------------------------------


def agreed_contracts() -> QuerySet[Contract]:
    """The contracts on the Kelishinlingan page: agreed ones and rejected ones.

    A rejected contract belongs here because it is corrected and resent, and
    this is the page carrying its rejection comment as a column.
    """
    return (
        Contract.objects.filter(stage__in=(Contract.Stage.AGREED, Contract.Stage.REJECTED))
        .select_related(
            "application", "application__department", "supplier", "status", "created_by"
        )
        .prefetch_related(Prefetch("items", queryset=ContractItem.objects.all()))
    )


def contractable_applications(user: AbstractBaseUser) -> QuerySet[Application]:
    """The assigned applications this person may agree a contract against.

    A Katta Mutaxasis forms a contract on the basis of the application
    assigned to them (REQ-ROLE-007); everybody else sees all assigned ones.
    """
    applications = (
        Application.objects.filter(stage=Application.Stage.ASSIGNED)
        .select_related("department")
        .prefetch_related("items")
    )

    if acts_on_own_work_only(user):
        return applications.filter(assigned_to=user)

    return applications


def contract_page(
    user: AbstractBaseUser,
    chosen_filters: Mapping[str, str] | None = None,
    form: ContractForm | None = None,
    items: ContractItemFormSet | None = None,
) -> dict[str, object]:
    """Everything the Kelishinlingan Shartnoma page renders."""
    table_filter = TableFilter(
        CONTRACT_FILTERS,
        agreed_contracts(),
        chosen_filters,
        date_column=CONTRACT_PERIOD,
        sort_choices=CONTRACT_SORTS,
    )
    return {
        "contracts": table_filter.apply(),
        "table_filter": table_filter,
        "form": (
            form
            if form is not None
            else ContractForm(applications=contractable_applications(user))
        ),
        "item_formset": (
            items
            if items is not None
            else ContractItemFormSet(queryset=ContractItem.objects.none())
        ),
        "open_form": form is not None,
        "suggested_units": SUGGESTED_UNITS,
    }


def agreed_contracts_list(request: HttpRequest) -> HttpResponse:
    """The Kelishinlingan Shartnoma table and the form that adds to it."""
    page_context = contract_page(request.user, request.GET)
    report_invalid_filters(request, page_context["table_filter"])

    return render(request, AGREED_CONTRACTS_TEMPLATE, page_context)


@require_POST
def contract_create(request: HttpRequest) -> HttpResponse:
    """Enter a contract and its goods rows (REQ-SHARTNOMA-006).

    The contract value is never read from the form: raise_contract() computes
    it from the rows.
    """
    applications = contractable_applications(request.user)
    form = ContractForm(request.POST, applications=applications)
    items = ContractItemFormSet(request.POST, queryset=ContractItem.objects.none())

    if not (form.is_valid() and items.is_valid()):
        messages.error(request, "Shartnoma yaratilmadi: formani tekshiring.")
        return render(
            request,
            AGREED_CONTRACTS_TEMPLATE,
            contract_page(request.user, form=form, items=items),
        )

    with transaction.atomic():
        contract = Contract.raise_contract(
            items=filled_in_rows(items, CONTRACT_LINE_FIELDS),
            created_by=request.user,
            application=form.cleaned_data["application"],
            supplier=form.cleaned_data["supplier"],
            shartnoma_turi=form.cleaned_data["shartnoma_turi"],
            status=form.cleaned_data["status"],
            shartnoma_sanasi=form.cleaned_data["shartnoma_sanasi"],
            tolash_muddati=form.cleaned_data["tolash_muddati"],
            muddat_talabi=form.cleaned_data["muddat_talabi"],
            izoh=form.cleaned_data["izoh"],
        )

    messages.success(
        request,
        f"{contract.shartnoma_raqami} yaratildi. "
        f"Shartnoma qiymati: {contract.qiymati_display} UZS.",
    )

    return redirect("xarid:kelishinlingan")


# ---------------------------------------------------------------------------
# Purchase applications (section 4.9) and DEC-016's approval chain
# ---------------------------------------------------------------------------


def purchase_lines() -> Prefetch:
    """The order lines of a purchase application, with their categories."""
    return Prefetch(
        "items",
        queryset=PurchaseApplicationItem.objects.select_related("mahsulot_turi"),
    )


def purchase_applications() -> QuerySet[PurchaseApplication]:
    """Every purchase application, newest first (REQ-ARIZA-014)."""
    return (
        PurchaseApplication.objects.select_related("department", "status")
        .prefetch_related(purchase_lines())
        .all()
    )


def approvals_for(user: AbstractBaseUser) -> QuerySet[PurchaseApplication]:
    """The purchase requests waiting for this person to decide (DEC-016).

    A Bo`lim Boshlig`i sees the first step from their own department only; a
    Direktor sees the second step from anywhere; everybody else sees none.
    """
    waiting = PurchaseApplication.objects.select_related(
        "department", "status", "created_by"
    ).prefetch_related(purchase_lines())

    if has_user_type(user, (BOLIM_BOSHLIGI,)):
        department = department_of(user)
        if department is None:
            return waiting.none()

        return waiting.filter(stage=PurchaseApplication.Stage.AWAITING_HEAD, department=department)

    if has_user_type(user, (DIREKTOR,)):
        return waiting.filter(stage=PurchaseApplication.Stage.AWAITING_DIREKTOR)

    return waiting.none()


def awaiting_approval(request: HttpRequest, pk: int) -> PurchaseApplication:
    """The request this person may decide, or a refusal.

    Somebody who could never decide this request is denied; somebody for whom
    it has simply moved on is handed the record so the view can say so.

    Raises:
        PermissionDenied: when this person could not decide this request at
            any step.
        Http404: when there is no such request.
    """
    application = get_object_or_404(PurchaseApplication, pk=pk)

    if not (application.awaits(request.user) or application.moved_past(request.user)):
        raise PermissionDenied(f"{application.xarid_raqami} is not {request.user} to decide.")

    return application


@require_POST
def approve_purchase_application(request: HttpRequest, pk: int) -> HttpResponse:
    """Take one request a step along the chain (REQ-ARIZA-016)."""
    application = awaiting_approval(request, pk)

    try:
        approved = application.approve(by=request.user)
    except ValueError:
        messages.info(request, f"{application.xarid_raqami} allaqachon hal qilingan.")
        return redirect("xarid:xarid-ariza")

    if approved and application.stage == PurchaseApplication.Stage.APPROVED:
        messages.success(
            request,
            f"{application.xarid_raqami} tasdiqlandi va "
            f"{application.raised_application.ariza_raqami} yaratildi.",
        )
    elif approved:
        messages.success(
            request, f"{application.xarid_raqami} tasdiqlandi va direktorga yuborildi."
        )
    else:
        messages.info(request, f"{application.xarid_raqami} allaqachon tasdiqlangan.")

    return redirect("xarid:xarid-ariza")


@require_POST
def reject_purchase_application(request: HttpRequest, pk: int) -> HttpResponse:
    """Refuse one request, with a reason (REQ-ARIZA-020)."""
    application = awaiting_approval(request, pk)

    try:
        rejected = application.reject(by=request.user, comment=request.POST.get("inkor_izohi", ""))
    except ValueError:
        if not application.awaits(request.user):
            messages.info(request, f"{application.xarid_raqami} allaqachon hal qilingan.")
        else:
            messages.error(
                request,
                f"{application.xarid_raqami} inkor etilmadi: izoh kiritilishi shart.",
            )

        return redirect("xarid:xarid-ariza")

    if rejected:
        messages.success(request, f"{application.xarid_raqami} inkor etildi.")
    else:
        messages.info(request, f"{application.xarid_raqami} allaqachon inkor etilgan.")

    return redirect("xarid:xarid-ariza")


def purchase_page(
    signed_in_department: Department | None = None,
    approvals: QuerySet[PurchaseApplication] | None = None,
    chosen_filters: Mapping[str, str] | None = None,
    form: PurchaseApplicationForm | None = None,
    items: PurchaseApplicationItemFormSet | None = None,
) -> dict[str, object]:
    """Everything the Xarid Arizasi page renders."""
    table_filter = TableFilter(
        PURCHASE_FILTERS,
        purchase_applications(),
        chosen_filters,
        date_column=PURCHASE_PERIOD,
        sort_choices=PURCHASE_SORTS,
    )
    return {
        "applications": table_filter.apply(),
        "table_filter": table_filter,
        "signed_in_department": signed_in_department,
        "approvals": approvals,
        "form": form if form is not None else PurchaseApplicationForm(),
        "item_formset": (
            items
            if items is not None
            else PurchaseApplicationItemFormSet(queryset=PurchaseApplicationItem.objects.none())
        ),
        "open_form": form is not None,
        "suggested_units": SUGGESTED_UNITS,
    }


def purchase_application_list(request: HttpRequest) -> HttpResponse:
    """The Xarid Arizasi table, the approval queue and the creation form."""
    page_context = purchase_page(
        signed_in_department=department_of(request.user),
        approvals=approvals_for(request.user),
        chosen_filters=request.GET,
    )
    report_invalid_filters(request, page_context["table_filter"])

    return render(request, PURCHASE_TEMPLATE, page_context)


def why_no_department(user: AbstractBaseUser) -> str:
    """Which of the two ways a requester can have no department to use.

    Never assigned one, or assigned one an administrator has since retired:
    the remedies differ, and the requester cannot apply either.
    """
    profile = UserProfile.objects.filter(user=user).select_related("department").first()
    retired = profile is not None and profile.department is not None

    if retired:
        return (
            f"Xarid arizasi yaratilmadi: bo`limingiz ({profile.department.name}) "
            "faol emas. Administratorga murojaat qiling."
        )

    return (
        "Xarid arizasi yaratilmadi: hisobingizga bo`lim biriktirilmagan. "
        "Administratorga murojaat qiling."
    )


@require_POST
def purchase_application_create(request: HttpRequest) -> HttpResponse:
    """Raise a purchase application (REQ-ARIZA-015).

    The department comes from the requester's own account (DEC-018) and is
    never read from the form.
    """
    form = PurchaseApplicationForm(request.POST, request.FILES)
    items = PurchaseApplicationItemFormSet(
        request.POST, queryset=PurchaseApplicationItem.objects.none()
    )
    department = department_of(request.user)

    if department is None:
        messages.error(request, why_no_department(request.user))
        return render(
            request,
            PURCHASE_TEMPLATE,
            purchase_page(department, approvals_for(request.user), form=form, items=items),
        )

    if not (form.is_valid() and items.is_valid()):
        messages.error(request, "Xarid arizasi yaratilmadi: formani tekshiring.")
        return render(
            request,
            PURCHASE_TEMPLATE,
            purchase_page(department, approvals_for(request.user), form=form, items=items),
        )

    with transaction.atomic():
        application = PurchaseApplication.raise_purchase_application(
            items=filled_in_rows(items, ORDER_LINE_FIELDS),
            department=department,
            shartnoma_nomi=form.cleaned_data["shartnoma_nomi"],
            muddat_talabi=form.cleaned_data["muddat_talabi"],
            izoh=form.cleaned_data["izoh"],
            pdf=form.cleaned_data["pdf"],
            created_by=request.user,
            status=ArizaStatus.with_code(ArizaStatus.Code.NEW),
        )

    messages.success(request, f"{application.xarid_raqami} yaratildi.")

    return redirect("xarid:xarid-ariza")


def purchase_application_pdf(request: HttpRequest, pk: int) -> FileResponse:
    """Download one purchase application's PDF (DEC-019).

    The permission is on the route: a purchase application is on one page for
    its whole life.
    """
    application = get_object_or_404(PurchaseApplication, pk=pk)

    return attachment_response(application.pdf, f"{application.xarid_raqami}.pdf")


def purchase_application_original_pdf(request: HttpRequest, pk: int) -> FileResponse:
    """Download the attachment as it was uploaded, before any stamp.

    Raises:
        Http404: when there is no such application, or it has no original -
            every application that has not been approved, since until then
            pdf is the original.
    """
    application = get_object_or_404(PurchaseApplication, pk=pk)

    return attachment_response(application.asl_pdf, f"{application.xarid_raqami}-asl.pdf")


# ---------------------------------------------------------------------------
# Yuklab olish: each list page's table as Excel or PDF (REQ-ARIZA-002)
# ---------------------------------------------------------------------------

# The columns mirror the tables, one row per order line, so the file holds
# what the page shows. Each value_of reads (record, line).


def category_label(line) -> str:
    return f"{line.mahsulot_turi.category_number} - {line.mahsulot_turi.name}"


def holder_name(application: Application) -> str:
    return display_name(application.assigned_to) if application.assigned_to else ""


ORDER_LINE_EXPORT_COLUMNS = (
    ExportColumn("Mahsulot turi", lambda record, line: category_label(line)),
    ExportColumn("Buyurtma nomi", lambda record, line: line.buyurtma_nomi),
    ExportColumn("Soni", lambda record, line: line.soni_display),
    ExportColumn("O'lchov", lambda record, line: line.olchov_birligi),
)

INCOMING_EXPORT_COLUMNS = (
    ExportColumn("Ariza raqami", lambda ariza, line: ariza.ariza_raqami),
    ExportColumn("Bo'lim", lambda ariza, line: ariza.department.name),
    *ORDER_LINE_EXPORT_COLUMNS,
    ExportColumn("Izoh", lambda ariza, line: ariza.izoh),
    ExportColumn("Kelib tushgan", lambda ariza, line: local_date(ariza.kelib_tushgan_sana)),
)

ACCEPTED_EXPORT_COLUMNS = (
    ExportColumn("Ariza raqami", lambda ariza, line: ariza.ariza_raqami),
    ExportColumn("Bo'lim", lambda ariza, line: ariza.department.name),
    *ORDER_LINE_EXPORT_COLUMNS,
    ExportColumn("Qabul qilingan sana", lambda ariza, line: local_date(ariza.qabul_qilingan_sana)),
    ExportColumn("Tayinlangan xodim", lambda ariza, line: holder_name(ariza)),
)

ASSIGNED_EXPORT_COLUMNS = (
    ExportColumn("Ariza raqami", lambda ariza, line: ariza.ariza_raqami),
    ExportColumn("Bo'lim", lambda ariza, line: ariza.department.name),
    *ORDER_LINE_EXPORT_COLUMNS,
    ExportColumn("Izoh", lambda ariza, line: ariza.izoh),
    ExportColumn("Qabul qilingan sana", lambda ariza, line: local_date(ariza.qabul_qilingan_sana)),
)
ASSIGNED_HOLDER_COLUMN = ExportColumn("Tayinlangan xodim", lambda ariza, line: holder_name(ariza))
ASSIGNED_PROGRESS_COLUMNS = (
    ExportColumn(
        "Xodim qabul qilgan sana", lambda ariza, line: local_date(ariza.xodim_qabul_qilgan_sana)
    ),
    ExportColumn("Holat", lambda ariza, line: ariza.status.name if ariza.status else ""),
)

CONTRACT_EXPORT_COLUMNS = (
    ExportColumn("Shartnoma raqami", lambda shartnoma, line: shartnoma.shartnoma_raqami),
    ExportColumn("Ariza raqami", lambda shartnoma, line: shartnoma.application.ariza_raqami),
    ExportColumn("Buyurtma nomi", lambda shartnoma, line: line.buyurtma_nomi),
    ExportColumn("Part Number", lambda shartnoma, line: line.part_number),
    ExportColumn("Miqdori", lambda shartnoma, line: line.soni_display),
    ExportColumn("Birligi", lambda shartnoma, line: line.olchov_birligi),
    ExportColumn("Narxi", lambda shartnoma, line: line.narxi),
    ExportColumn("Umumiy narx", lambda shartnoma, line: line.umumiy_narx),
    ExportColumn("Bo'lim", lambda shartnoma, line: shartnoma.application.department.name),
    ExportColumn("Firma", lambda shartnoma, line: shartnoma.supplier.name),
    ExportColumn("Kim tuzdi", lambda shartnoma, line: display_name(shartnoma.created_by)),
    ExportColumn("Yaratilgan", lambda shartnoma, line: local_date(shartnoma.yaratilingan_sana)),
    ExportColumn("Shartnoma qiymati", lambda shartnoma, line: shartnoma.qiymati),
    ExportColumn("Izoh", lambda shartnoma, line: shartnoma.inkor_izohi),
)

PURCHASE_EXPORT_COLUMNS = (
    ExportColumn("Ariza raqami", lambda ariza, line: ariza.xarid_raqami),
    ExportColumn("Shartnoma nomi", lambda ariza, line: ariza.shartnoma_nomi),
    ExportColumn("Bo'lim", lambda ariza, line: ariza.department.name),
    ExportColumn("Buyurtma nomi", lambda ariza, line: line.buyurtma_nomi),
    ExportColumn("Soni", lambda ariza, line: line.soni_display),
    ExportColumn("O'lchov", lambda ariza, line: line.olchov_birligi),
    ExportColumn("Holati", lambda ariza, line: ariza.status.name if ariza.status else ""),
    ExportColumn("Mahsulot turi", lambda ariza, line: category_label(line)),
    ExportColumn("Izoh", lambda ariza, line: ariza.izoh),
    ExportColumn("Yaratilgan", lambda ariza, line: local_date(ariza.yaratilingan_sana)),
)


def incoming_export(request: HttpRequest, file_format: str) -> HttpResponse:
    """Download the Kelib tushgan table, filtered as the page is."""
    table_filter = TableFilter(
        INCOMING_FILTERS,
        incoming_applications(),
        request.GET,
        date_column=INCOMING_PERIOD,
        sort_choices=INCOMING_SORTS,
    )
    export = TableExport("kelib-arizalar", INCOMING_EXPORT_COLUMNS, lines_of(table_filter.apply()))
    return export_response(export, file_format)


def accepted_export(request: HttpRequest, file_format: str) -> HttpResponse:
    """Download the Qabul qilingan table, filtered as the page is."""
    table_filter = TableFilter(
        ACCEPTED_FILTERS,
        accepted_applications(),
        request.GET,
        date_column=ACCEPTED_PERIOD,
        sort_choices=ACCEPTED_SORTS,
    )
    export = TableExport("qabul-arizalar", ACCEPTED_EXPORT_COLUMNS, lines_of(table_filter.apply()))
    return export_response(export, file_format)


def assigned_export(request: HttpRequest, file_format: str) -> HttpResponse:
    """Download the Tayinlangan table as this person sees it."""
    own_work_only = acts_on_own_work_only(request.user)
    visible = assigned_applications(request.user) if own_work_only else all_assigned_applications()
    table_filter = TableFilter(
        ASSIGNED_FILTERS,
        visible,
        request.GET,
        date_column=ASSIGNED_PERIOD,
        sort_choices=ASSIGNED_SORTS,
    )
    columns = (
        *ASSIGNED_EXPORT_COLUMNS,
        *(() if own_work_only else (ASSIGNED_HOLDER_COLUMN,)),
        *ASSIGNED_PROGRESS_COLUMNS,
    )
    export = TableExport("tayinlangan", columns, lines_of(table_filter.apply()))
    return export_response(export, file_format)


def contracts_export(request: HttpRequest, file_format: str) -> HttpResponse:
    """Download the Kelishinlingan table, filtered as the page is."""
    table_filter = TableFilter(
        CONTRACT_FILTERS,
        agreed_contracts(),
        request.GET,
        date_column=CONTRACT_PERIOD,
        sort_choices=CONTRACT_SORTS,
    )
    export = TableExport("kelishinlingan", CONTRACT_EXPORT_COLUMNS, lines_of(table_filter.apply()))
    return export_response(export, file_format)


def purchase_export(request: HttpRequest, file_format: str) -> HttpResponse:
    """Download the Xarid Arizasi table, filtered as the page is."""
    table_filter = TableFilter(
        PURCHASE_FILTERS,
        purchase_applications(),
        request.GET,
        date_column=PURCHASE_PERIOD,
        sort_choices=PURCHASE_SORTS,
    )
    export = TableExport("xarid-ariza", PURCHASE_EXPORT_COLUMNS, lines_of(table_filter.apply()))
    return export_response(export, file_format)


# ---------------------------------------------------------------------------
# Hisobotlar
# ---------------------------------------------------------------------------
WORKLOAD_TEMPLATE = "xarid/pages/xodimlar-yuklamasi.html"

# The report counts an assignment on the day it was made, so the period is
# the one the Tayinlangan page filters by (REQ-YUKLAMA-001).
WORKLOAD_PERIOD = DateColumn("Tayinlangan sana", "tayinlangan_sana")


def assigned_work() -> QuerySet[Application]:
    """Every application somebody holds, however far it has got.

    Not the Tayinlangan list, which is the work still in hand: a specialist
    whose contract was signed did that work, and the report's counters exist
    to say so. The report counts this set, and the bar is built over the same
    one so the page holds a single definition of an assignment.
    """
    return Application.objects.filter(assigned_to__isnull=False)


def staff_workload_report(request: HttpRequest) -> HttpResponse:
    """Xodimlar yuklamasi: what each specialist is carrying (REQ-YUKLAMA-002).

    The bar offers the period and nothing else: there is one row per
    specialist already, so there is no column to narrow by.
    """
    table_filter = TableFilter(
        (),
        assigned_work(),
        request.GET,
        date_column=WORKLOAD_PERIOD,
    )
    report_invalid_filters(request, table_filter)

    return render(
        request,
        WORKLOAD_TEMPLATE,
        {"report": staff_workload(table_filter.period), "table_filter": table_filter},
    )


DEPARTMENTS_REPORT_TEMPLATE = "xarid/pages/bolimlar.html"

# A department's purchasing is counted from the day its application arrived,
# which is the only date every application has (REQ-XARID-001).
DEPARTMENT_REPORT_PERIOD = DateColumn("Kelib tushgan sana", "kelib_tushgan_sana")


def reported_applications() -> QuerySet[Application]:
    """The applications the departments report counts.

    Active departments only, because those are the rows the report has. The
    bar's options are derived from this, so the drop-down and the table agree
    on which departments exist.
    """
    return Application.objects.filter(department__is_active=True)


def department_purchasing_report(request: HttpRequest) -> HttpResponse:
    """Korhona xaridi | Bo`limlar: what each department is buying.

    The bar offers the department drop-down the prototype promised and the
    period. Its options come from the applications of departments the report
    has a row for, so it cannot offer a department that would empty the
    table: a deactivated department keeps its history but is not reported on.
    """
    table_filter = TableFilter(
        (BY_DEPARTMENT,),
        reported_applications(),
        request.GET,
        date_column=DEPARTMENT_REPORT_PERIOD,
    )
    report_invalid_filters(request, table_filter)
    chosen_department = table_filter.fields[0].selected

    return render(
        request,
        DEPARTMENTS_REPORT_TEMPLATE,
        {
            "report": department_purchasing(table_filter.period, chosen_department),
            "table_filter": table_filter,
        },
    )
