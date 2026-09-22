"""Every view of the purchasing department's pages.

Every page view is wrapped in urls.py by require_page_permission(), which
applies Django's login_required and then the DEC-015 page matrix. The views
here decide what a page shows and what an action does; which rows a signed-in
person may touch is decided per view where the page alone cannot say.
"""

from __future__ import annotations

import operator
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from dataclasses import dataclass
from functools import reduce
from typing import NamedTuple

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import AbstractBaseUser
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F, Prefetch, Q, QuerySet
from django.http import (
    FileResponse,
    Http404,
    HttpRequest,
    HttpResponse,
    HttpResponseForbidden,
)
from django.shortcuts import get_object_or_404, redirect, render, resolve_url
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from xarid.attachments import attachment_name, attachment_response
from xarid.audit import (
    decisions_for,
    record_created,
    record_decision,
    record_deleted,
    record_edited,
)
from xarid.dashboard import (
    BY_DARAJA,
    DASHBOARD_TOP_SUPPLIERS,
    SPENDINGS_PERIOD,
    daraja_options,
    dashboard_indicators,
    dated_contracts,
    processing_times,
    spending_indicators,
    supplier_categories,
    top_suppliers,
)
from xarid.documents import (
    application_response,
    contract_response,
    purchase_application_response,
)
from xarid.exports import ExportColumn, TableExport, export_response, lines_of, local_date
from xarid.filters import (
    DateColumn,
    FilterColumn,
    TableFilter,
    newest_and_oldest_first,
    report_invalid_filters,
)
from xarid.pagination import TablePage
from xarid.forms import (
    ContractEditForm,
    ContractItemEditFormSet,
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
    PAGE_SHOWING_CONTRACT,
    USERS,
    Application,
    ApplicationItem,
    ArizaStatus,
    AuditEntry,
    Contract,
    ContractComment,
    ContractItem,
    ContractStatusChange,
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
from xarid.notifications import (
    tell_head_of_status_change,
    tell_holders_of_decision,
    tell_thread_of_comment,
    tell_of_contract_sent,
    tell_requester_of_progress,
    tell_sender_of_acceptance,
    tell_sender_of_refusal,
    tell_whoever_it_now_waits_for,
)
from xarid.permissions import (
    acts_on_own_work_only,
    moves_status_on_tuzilgan,
    contract_editor,
    decides_on_contracts,
    first_page_for,
    may_be_sent_to,
    grant_contract_editing,
    held_contract,
    may_open,
    own_contract_test,
    reads_own_requests_only,
    revoke_contract_editing,
    sees_own_approvals,
    works_arrived_applications,
)
from xarid.reports import (
    category_purchasing,
    department_purchasing,
    report_export,
    staff_workload,
)

USERS_TEMPLATE = "xarid/pages/users.html"
INCOMING_TEMPLATE = "xarid/pages/kelib-arizalar.html"
ACCEPTED_TEMPLATE = "xarid/pages/qabul-arizalar.html"
APPROVED_TEMPLATE = "xarid/pages/tasdiqlangan-arizalar.html"
ASSIGNED_TEMPLATE = "xarid/pages/tayinlangan.html"
AGREED_CONTRACTS_TEMPLATE = "xarid/pages/kelishinlingan.html"
PURCHASE_TEMPLATE = "xarid/pages/xarid-ariza.html"

# The page that is still the supplied prototype: the 1C integration screen,
# which stays mocked until an API specification is supplied. A template with
# no data behind it, served under its own permission.
PROTOTYPE_PAGE_TEMPLATES: dict[str, str] = {
    "integration": "xarid/pages/integration.html",
}

DASHBOARD_TEMPLATE = "xarid/index.html"
TOP_SUPPLIERS_TEMPLATE = "xarid/pages/top-suppliers.html"


def prototype_page(page_name: str) -> Callable[..., HttpResponse]:
    """A view rendering one prototype page by its page name."""
    return TemplateView.as_view(template_name=PROTOTYPE_PAGE_TEMPLATES[page_name])


def dashboard(request: HttpRequest) -> HttpResponse:
    """Asosiy Panel: the department's position at a glance (section 2).

    Counted here: the three contract indicators (REQ-DASH-001 to REQ-DASH-004),
    the spendings (REQ-DASH-008, REQ-DASH-010), the four processing-time
    averages (REQ-DASH-012) and the head of the supplier ranking
    (REQ-DASH-005). The period bar narrows the spend and the ranking, which
    are both about money inside a period, and nothing else
    - the contract indicators are the department's position now, not its
    position during a week, and an average of how long a stage takes is not a
    figure a fortnight has an answer for - which is why the cards and the
    panel say what each figure covers.

    The spendings chart and the activity list are still the supplied
    prototype's own numbers; the activity list is UZK-052's log, which has a
    page of its own.
    """
    # The bar offers no column filters and no ordering, so it is built for
    # its period and its rendering alone; spending_indicators() applies that
    # period to its own query, and nothing calls table_filter.apply().
    table_filter = TableFilter((), dated_contracts(), request.GET, date_column=SPENDINGS_PERIOD)
    report_invalid_filters(request, table_filter)
    categories = supplier_categories()

    return render(
        request,
        DASHBOARD_TEMPLATE,
        {
            "indicators": dashboard_indicators(),
            "spendings": spending_indicators(table_filter.period),
            "stages": processing_times(),
            "top_suppliers": top_suppliers(table_filter.period, limit=DASHBOARD_TOP_SUPPLIERS),
            "categories": categories,
            "category_chart": [
                {"label": row.category.name, "firms": row.firms} for row in categories.rows
            ],
            "table_filter": table_filter,
        },
    )


def top_suppliers_filter(chosen: Mapping[str, str]) -> TableFilter:
    """The Top suppliers bar: a Daraja drop-down and the contract period.

    Its options come from the suppliers that have a Daraja recorded, so the
    drop-down cannot offer a blank level beside its own "barchasi". Only the
    bar's choices are used: top_suppliers() ranks contracts, not the supplier
    rows this filter would narrow.
    """
    return TableFilter(
        (BY_DARAJA,),
        daraja_options(),
        chosen,
        date_column=SPENDINGS_PERIOD,
    )


def top_suppliers_page(request: HttpRequest) -> HttpResponse:
    """Top Yetkazib beruvchilar: the firms ranked by what they were paid.

    The page REQ-DASH-005 asks for beside the dashboard panel, ranked by
    total contract value in the period (DEC-025) and narrowed by the firm's
    level (REQ-DASH-006).
    """
    table_filter = top_suppliers_filter(request.GET)
    report_invalid_filters(request, table_filter)

    ranking = top_suppliers(table_filter.period, table_filter.fields[0].selected)
    table_page = TablePage(ranking, request.GET, kept=table_filter.selections)

    return render(
        request,
        TOP_SUPPLIERS_TEMPLATE,
        {
            "ranking": table_page.rows,
            "table_filter": table_filter,
            "table_page": table_page,
        },
    )


# ---------------------------------------------------------------------------
# The Logs page (section 10, REQ-LOG-001)
# ---------------------------------------------------------------------------

LOGS_TEMPLATE = "xarid/pages/logs.html"

# The period narrows by when the thing happened, which is the entry's own
# Sana/Soat column.
LOGS_PERIOD = DateColumn("Sana/Soat", "created_at")

# One drop-down per column REQ-LOG-001 asks to filter by. The action's
# options are labelled from the model's own choices, so the bar and the
# column under it call a value the same thing: Created, Edited, Deleted -
# the words section 10's own column header uses.
LOGS_FILTERS = (
    FilterColumn(
        parameter="foydalanuvchi",
        label="Foydalanuvchi",
        value_lookup="actor_id",
        label_lookups=("actor__first_name", "actor__last_name"),
        label_fallback_lookup="actor__username",
    ),
    FilterColumn(
        parameter="bolim",
        label="Bo`lim",
        value_lookup="actor_department_id",
        label_lookups=("actor_department__name",),
    ),
    FilterColumn(
        parameter="forma",
        label="Forma",
        value_lookup="form_name",
        label_lookups=("form_name",),
    ),
    FilterColumn(
        parameter="amal",
        label="Amal",
        value_lookup="action",
        label_lookups=("action",),
        option_labels=dict(AuditEntry.Action.choices),
    ),
)


def logged_events() -> QuerySet:
    """Every entry, newest first, with the people and departments joined."""
    return AuditEntry.objects.select_related(
        "actor", "actor_department", "approver", "approver_department"
    )


def logs_page(request: HttpRequest) -> HttpResponse:
    """The Logs page: what the application did, and who did it.

    Reads the table TASK-UZK-052 writes. Nothing on this page writes to it:
    DEC-029 keeps entries indefinitely and gives the application no way to
    edit or delete one, and no export - section 10 is the one page that does
    not ask for a download.
    """
    table_filter = TableFilter(LOGS_FILTERS, logged_events(), request.GET, date_column=LOGS_PERIOD)
    report_invalid_filters(request, table_filter)
    # The page slices what it prints and counts the rest: the count beside the
    # table is the whole filtered log, not the page of it being read.
    table_page = TablePage(table_filter.apply(), request.GET, kept=table_filter.selections)

    return render(
        request,
        LOGS_TEMPLATE,
        {
            "entries": table_page.rows,
            "entry_count": table_page.total,
            "table_filter": table_filter,
            "table_page": table_page,
        },
    )


# ---------------------------------------------------------------------------
# Notifications (REQ-ARIZA-004, REQ-ARIZA-005, DEC-012)
# ---------------------------------------------------------------------------

NOTIFICATIONS_TEMPLATE = "xarid/pages/bildirishnomalar.html"


@login_required
def notifications_page(request: HttpRequest) -> HttpResponse:
    """Everything this person has been told, newest first.

    Not in the DEC-015 matrix on purpose: it is not a page a user type may
    open, it is everybody's own, and the matrix answers the first question
    rather than the second. login_required alone is the whole rule.

    Showing a notification is what marks it read, so the bell stops counting
    what the reader has just been shown. The page says so.

    The rows are read first and marked afterwards, and the page renders what
    was read - so this once, the entries that were new still say so while the
    bell beside them is already empty. That is the point: somebody should see
    what changed before it stops being new. A reload shows them unmarked.

    The marking is one statement over this person's unread rows rather than a
    list of the ids just read: an account that has collected more
    notifications than SQLite will bind at once would otherwise lose its own
    panel.
    """
    shown = list(
        Notification.objects.filter(recipient=request.user).select_related(
            "application", "purchase_application"
        )
    )
    Notification.objects.filter(recipient=request.user, read_at__isnull=True).update(
        read_at=timezone.now()
    )

    # Every one of them is marked read, and a page of them is shown: what the
    # bell counts is what arrived, not what fitted on the first page.
    table_page = TablePage(shown, request.GET)

    return render(
        request,
        NOTIFICATIONS_TEMPLATE,
        {"notifications": table_page.rows, "table_page": table_page},
    )


class SignInView(LoginView):
    """The sign-in form, and where it lets somebody out.

    Django sends a visitor to ?next= after they sign in, which is how a person
    turned away from a page arrives back at it. The address is checked for
    being this site's, and not for being a page this account may open - so one
    person signing out of a page and another signing in on the same browser
    lands the second one on the first one's page, and that is a 403 for
    signing in correctly. That is the report this exists to answer.

    A next nobody may open is dropped rather than obeyed, and they go where a
    sign-in with no next goes: the first page their type may open.
    """

    redirect_authenticated_user = True

    def get_success_url(self) -> str:
        asked = self.get_redirect_url()
        if asked and may_be_sent_to(self.request.user, asked):
            return asked

        return resolve_url(settings.LOGIN_REDIRECT_URL)


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
        # One page of the rows, for every master data table at once: they are
        # lists an administrator adds to for as long as the application runs,
        # and a hundred product types is a page nobody reads the end of.
        table_page = TablePage(self.model.objects.active(), request.GET)

        return render(
            request,
            self.template_name,
            {
                self.context_object_name: table_page.rows,
                "table_page": table_page,
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

        record_created(request.user, form.save())
        return redirect(f"xarid:{self.page_name}")

    def _update_record(self, request: HttpRequest, pk: int) -> HttpResponse:
        edited = self._active_record(pk)

        form = self.form_class(request.POST, instance=edited)
        if not form.is_valid():
            return self._render_page(request, form, edited)

        record_edited(request.user, form.save())
        return redirect(f"xarid:{self.page_name}")

    def _delete_record(self, request: HttpRequest, pk: int) -> HttpResponse:
        deleted = self._active_record(pk)

        # Logged before the deactivation, while the record still says what it
        # said: the entry keeps its label, not a pointer to it.
        record_deleted(request.user, deleted)
        deactivate(deleted)

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
    table_page = TablePage(listed_users(), request.GET)

    return render(
        request,
        USERS_TEMPLATE,
        {
            "users": table_page.rows,
            "table_page": table_page,
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

    record_created(request.user, form.save())
    return redirect("xarid:users")


@require_POST
def user_update(request: HttpRequest, pk: int) -> HttpResponse:
    """Change a user's details, and their password when one was supplied."""
    edited_user = get_object_or_404(get_user_model(), pk=pk, is_active=True)

    form = UserAdministrationForm(request.POST, edited_user=edited_user)
    if not form.is_valid():
        return render_users_page(request, form, edited_user.pk)

    record_edited(request.user, form.save())
    return redirect("xarid:users")


@require_POST
def user_delete(request: HttpRequest, pk: int) -> HttpResponse:
    """Deactivate a user (DEC-009): they leave the list and cannot sign in."""
    deleted_user = get_object_or_404(get_user_model(), pk=pk, is_active=True)

    if deleted_user.pk == request.user.pk:
        return HttpResponseForbidden("O'z hisobingizni o'chira olmaysiz.")

    record_deleted(request.user, deleted_user)
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


def page_showing_application(
    application: Application, user: AbstractBaseUser
) -> str | None:
    """Which page shows this application to this reader, or None.

    The stage decides it, with one exception: qabul-arizalar is one page name
    and two pages. To whoever approves rather than accepts, it is Tasdiqlangan
    Arizalar - a table of purchase requests - so an accepted application is on
    no page of theirs, and holding the page name is not having seen the row.
    """
    page_name = PAGE_SHOWING_STAGE.get(application.stage)

    if page_name == PAGE_SHOWING_STAGE[Application.Stage.ACCEPTED] and sees_own_approvals(
        user
    ):
        return None

    return page_name

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

# What became of a request this head approved, and who had asked for it. The
# stage is a code rather than a name, so the drop-down is given the words the
# table prints instead of "awaiting_direktor".
BY_CHAIN_STAGE = FilterColumn(
    "bosqich",
    "Holati",
    "stage",
    ("stage",),
    option_labels=dict(PurchaseApplication.Stage.choices),
)
BY_REQUESTER = FilterColumn(
    "buyurtmachi",
    "Buyurtmachi",
    "created_by_id",
    ("created_by__first_name", "created_by__last_name"),
    label_fallback_lookup="created_by__username",
)

# The Mahsulotlar report filters rows that are order lines rather than
# applications, so the same two columns are reached by a different path. The
# parameter names are the page's contract: the Bo`limlar report already links
# here with ?bolim=<id> (TASK-UZK-045), and UZK-046's drill-down will use
# ?mahsulot=<id>.
BY_LINE_DEPARTMENT = FilterColumn(
    "bolim",
    "Bo'lim",
    "application__department_id",
    ("application__department__name",),
)
BY_LINE_CATEGORY = FilterColumn(
    "mahsulot",
    "Mahsulot turi",
    "mahsulot_turi_id",
    ("mahsulot_turi__name",),
)
BY_SUPPLIER = FilterColumn("firma", "Firma", "supplier_id", ("supplier__name",))

# Tuzilgan Shartnomalar reaches an application's department across the
# contract, and narrows by the decision the page exists to take: a contract
# here is either waiting for one or has had one, and "what is waiting for me"
# is the first question its reader asks. The stage is a code rather than a
# name, so the drop-down is given the words the page prints.
BY_CONTRACT_DEPARTMENT = FilterColumn(
    "bolim",
    "Bo'lim",
    "application__department_id",
    ("application__department__name",),
)
BY_DECISION = FilterColumn(
    "qaror",
    "Qaror",
    "stage",
    ("stage",),
    option_labels=dict(Contract.Stage.choices),
)

# The period each list page narrows by and the ordering its drop-down offers
# (REQ-YUKLAMA-001). Each page names the date it already shows in a column,
# and orders by that same date so the drop-down reorders what is on screen.
ACCEPTED_PERIOD = DateColumn("Qabul qilingan sana", "qabul_qilingan_sana")
ACCEPTED_SORTS = newest_and_oldest_first(ACCEPTED_PERIOD.lookup)
ASSIGNED_PERIOD = DateColumn("Tayinlangan sana", "tayinlangan_sana")
ASSIGNED_SORTS = newest_and_oldest_first(ASSIGNED_PERIOD.lookup)
CONTRACT_PERIOD = DateColumn("Yaratilgan sana", "yaratilingan_sana")
CONTRACT_SORTS = newest_and_oldest_first(CONTRACT_PERIOD.lookup)
# Tuzilgan shows when a contract was sent rather than when it was drawn up,
# and narrows and orders by that same date, as every page narrows by the date
# it prints.
SIGNED_PERIOD = DateColumn("Yuborilgan sana", "yuborilgan_sana")
SIGNED_SORTS = newest_and_oldest_first(SIGNED_PERIOD.lookup)
PURCHASE_PERIOD = DateColumn("Yaratilgan sana", "yaratilingan_sana")
APPROVED_PERIOD = DateColumn("Tasdiqlangan sana", "bolim_boshligi_sanasi")
# The same page read by a Direktor narrows by their own step of the chain:
# every request they approved carries the head's date too, and narrowing by
# that one would answer a question they did not ask.
DIREKTOR_APPROVED_PERIOD = DateColumn("Tasdiqlangan sana", "direktor_sanasi")
# The Mahsulotlar report narrows by the date its line's application
# arrived, the one date every line has.
PRODUCTS_PERIOD = DateColumn("Kelib tushgan sana", "application__kelib_tushgan_sana")
PURCHASE_SORTS = newest_and_oldest_first(PURCHASE_PERIOD.lookup)
APPROVED_SORTS = newest_and_oldest_first(APPROVED_PERIOD.lookup)
DIREKTOR_APPROVED_SORTS = newest_and_oldest_first(DIREKTOR_APPROVED_PERIOD.lookup)

INCOMING_FILTERS = (BY_DEPARTMENT, BY_ORDERED_CATEGORY)
ACCEPTED_FILTERS = (BY_DEPARTMENT, BY_SPECIALIST)
ASSIGNED_FILTERS = (BY_DEPARTMENT, BY_STATUS)
CONTRACT_FILTERS = (BY_SUPPLIER,)
SIGNED_FILTERS = (BY_DECISION, BY_CONTRACT_DEPARTMENT, BY_SUPPLIER, BY_STATUS)
PURCHASE_FILTERS = (BY_ORDERED_CATEGORY,)
# No Bo`lim filter: a head only ever approves their own department's.
APPROVED_FILTERS = (BY_CHAIN_STAGE, BY_REQUESTER, BY_ORDERED_CATEGORY)
# And no Holati filter for a Direktor: theirs is the chain's last approval,
# so every row of their table is approved and the choice would offer a reader
# two ways of emptying it.
DIREKTOR_APPROVED_FILTERS = (BY_REQUESTER, BY_ORDERED_CATEGORY)
PRODUCTS_FILTERS = (BY_LINE_DEPARTMENT, BY_LINE_CATEGORY)


def filled_in_rows(formset, fields: tuple[str, ...]) -> list[dict[str, object]]:
    """The rows somebody actually filled in, in the order they gave.

    A formset always carries at least one spare row; a spare nobody typed into
    comes back with empty cleaned_data and is dropped. Only the named fields
    are taken, never the hidden id a model formset adds.
    """
    return [
        {field: row.cleaned_data[field] for field in fields}
        for row in formset.forms
        # DELETE is only on the editing formset, where a row is removed by
        # being ticked rather than by being emptied. An emptied row of that
        # formset fails its required fields instead of going away, which is
        # why the tick exists.
        if row.cleaned_data and not row.cleaned_data.get("DELETE")
    ]


def application_lines() -> Prefetch:
    """The order lines of an application, with the category each names."""
    return Prefetch("items", queryset=ApplicationItem.objects.select_related("mahsulot_turi"))


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
    """One table: every purchase request standing at this person's step.

    A request moves along the chain rather than off the page - from the
    department head to the Direktor to the purchasing department - so the
    page's one table answers "what is waiting for me" whoever is asking.
    """
    table_filter = TableFilter(
        INCOMING_FILTERS,
        approvals_for(request.user),
        request.GET,
        date_column=PURCHASE_PERIOD,
        sort_choices=PURCHASE_SORTS,
    )
    report_invalid_filters(request, table_filter)
    table_page = TablePage(table_filter.apply(), request.GET, kept=table_filter.selections)
    queue = table_page.rows

    return render(
        request,
        INCOMING_TEMPLATE,
        {
            "queue": queue,
            "table_filter": table_filter,
            "table_page": table_page,
            "step_of": queue_step_of,
            # What the Izoh column's panel shows: every step of the DEC-016
            # chain already taken, which only the log kept. A request standing
            # at the Direktor carries the head's words with it, so whoever
            # decides next reads why it got this far.
            "decisions": decisions_for(queue),
        },
    )


@dataclass(frozen=True)
class ApprovalStep:
    """One of DEC-016's two approvals, read from the side of who took it.

    Tasdiqlangan Arizalar is one page for both: a Bo`lim Boshlig`i reads the
    requests they let through the first step, a Direktor the ones they let
    through the second. What differs is which column records the approval,
    which date is theirs, and - since the Direktor's is the chain's last -
    whether a Holati filter has anything to narrow.

    Attributes:
        approver_field: the column holding who took this step.
        role: what to call them on the page they read.
    """

    approver_field: str
    role: str
    period: DateColumn
    sorts: tuple
    filters: tuple


HEAD_APPROVAL = ApprovalStep(
    approver_field="tasdiqlagan_bolim_boshligi",
    role="Bo`lim Boshlig`i",
    period=APPROVED_PERIOD,
    sorts=APPROVED_SORTS,
    filters=APPROVED_FILTERS,
)
DIREKTOR_APPROVAL = ApprovalStep(
    approver_field="tasdiqlagan_direktor",
    role="Direktor",
    period=DIREKTOR_APPROVED_PERIOD,
    sorts=DIREKTOR_APPROVED_SORTS,
    filters=DIREKTOR_APPROVED_FILTERS,
)


def approval_step_of(user: AbstractBaseUser) -> ApprovalStep:
    """Which approval of the chain this reader takes."""
    if has_user_type(user, (DIREKTOR,)):
        return DIREKTOR_APPROVAL

    return HEAD_APPROVAL


def approved_by(user: AbstractBaseUser, step: ApprovalStep) -> QuerySet[PurchaseApplication]:
    """The purchase requests this person approved (REQ-ARIZA-016).

    Every one they let through, whatever became of it afterwards: a request
    the Direktor went on to refuse is still one its head approved, and a
    list that quietly dropped it would be a record of the outcome rather
    than of what they did.

    The date of their own step is annotated as tasdiqlagan_sana, so the
    table and the export read one name whichever step is being read.
    """
    return (
        PurchaseApplication.objects.filter(**{step.approver_field: user})
        .annotate(tasdiqlagan_sana=F(step.period.lookup))
        .select_related("department", "status", "created_by", "raised_application")
        .prefetch_related(purchase_lines())
    )


def approved_page(user: AbstractBaseUser, chosen_filters: Mapping[str, str]) -> dict[str, object]:
    """Everything Tasdiqlangan Arizalar renders."""
    step = approval_step_of(user)
    table_filter = TableFilter(
        step.filters,
        approved_by(user, step),
        chosen_filters,
        date_column=step.period,
        sort_choices=step.sorts,
    )
    table_page = TablePage(table_filter.apply(), chosen_filters, kept=table_filter.selections)
    applications = table_page.rows

    return {
        "applications": applications,
        "table_filter": table_filter,
        "table_page": table_page,
        "decisions": decisions_for(applications),
        "approver_role": step.role,
    }


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
    table_page = TablePage(table_filter.apply(), chosen_filters, kept=table_filter.selections)
    applications = table_page.rows

    return {
        "applications": applications,
        "table_filter": table_filter,
        "table_page": table_page,
        # What the Izoh column's panel shows: who accepted the application and
        # who refused one, which only the log kept.
        "decisions": decisions_for(applications),
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
    """The Qabul qilingan Arizalar table and the creation form (REQ-ARIZA-006).

    One page name, two pages. A Bo`lim Boshlig`i outside the purchasing
    department has nothing to accept and reads their own approvals here
    instead, under the name that describes them.
    """
    if sees_own_approvals(request.user):
        page_context = approved_page(request.user, request.GET)
        report_invalid_filters(request, page_context["table_filter"])

        return render(request, APPROVED_TEMPLATE, page_context)

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

    record_created(request.user, application)
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
    table_page = TablePage(table_filter.apply(), request.GET, kept=table_filter.selections)

    return render(
        request,
        ASSIGNED_TEMPLATE,
        {
            "applications": table_page.rows,
            "table_filter": table_filter,
            "table_page": table_page,
            "shows_the_holder": not own_work_only,
            # The two halves of the same rule: whoever hands the work out
            # reads the status, and whoever does it says what it is.
            "may_set_status": own_work_only,
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
    the people who handed it out are told inside the same transaction.
    """
    application = held_application(request, pk)

    try:
        with transaction.atomic():
            taken = application.accept_as_specialist(by=application.assigned_to)
            if taken:
                Notification.tell_of_specialist_acceptance(application)
    except ValueError:
        messages.error(
            request, f"{application.ariza_raqami} qabul qilinmadi: ariza tayinlanmagan."
        )
        return redirect("xarid:tayinlangan")

    if taken:
        record_edited(request.user, application)
        messages.success(request, f"{application.ariza_raqami} qabul qilindi.")
    else:
        messages.info(request, f"{application.ariza_raqami} allaqachon qabul qilingan.")

    return redirect("xarid:tayinlangan")


@require_POST
def set_application_status(request: HttpRequest, pk: int) -> HttpResponse:
    """Mark the state an assigned application is currently in (REQ-ARIZA-013).

    The holder's to say and nobody else's. Xarid bo`limi's head hands the
    work out and reads the column to see where it has got to; how far it has
    got is known to whoever is doing it, so the page shows them a badge and
    the specialist a drop-down. Asked here as well as in the template,
    because a control that is not drawn is not a control that cannot be
    posted to.
    """
    application = held_application(request, pk)

    if not acts_on_own_work_only(request.user):
        raise PermissionDenied(
            f"{request.user} does not do the work on {application.ariza_raqami}, "
            "so its status is not theirs to set."
        )

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
        record_edited(request.user, application)
        messages.success(request, f"{application.ariza_raqami} holati: {status.name}.")
    else:
        messages.info(request, f"{application.ariza_raqami} allaqachon shu holatda.")

    return redirect("xarid:tayinlangan")


def readable_application(request: HttpRequest, pk: int) -> Application:
    """The application whose documents this person may download (DEC-019).

    Asks the permission matrix about the page that currently shows it, so a
    document stops being reachable at the same moment the row stops being
    visible.

    Raises:
        PermissionDenied: when the caller may not open the page this
            application is on, or the application is at a stage no page shows.
        Http404: when there is no such application.
    """
    application = get_object_or_404(Application, pk=pk)

    page_name = page_showing_application(application, request.user)
    if page_name is None or not may_open(request.user, page_name):
        raise PermissionDenied(f"{request.user} may not see {application.ariza_raqami}.")

    return application


@login_required
def application_pdf(request: HttpRequest, pk: int) -> FileResponse:
    """Download one application's attachment as it was uploaded (DEC-019).

    Raises:
        Http404: when the application does not exist or has no attachment.
    """
    application = readable_application(request, pk)

    return attachment_response(application.pdf, attachment_name(application.ariza_raqami))


@login_required
def application_document(request: HttpRequest, pk: int) -> HttpResponse:
    """Download the application itself as a PDF, drawn from the record.

    The Ariza PDF column beside the Ilova PDF one: the attachment is what
    arrived with the request, and this is what the department knows, so a row
    is readable on paper even when nothing was ever attached to it.
    """
    application = readable_application(request, pk)

    return application_response(application)


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
        record_decision(request.user, application, approved=True)
        tell_sender_of_acceptance(application)
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
        record_decision(
            request.user,
            application,
            approved=False,
            comment=application.inkor_izohi,
        )
        tell_sender_of_refusal(application)
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
        record_edited(request.user, application)
        name = specialist.get_full_name() or specialist.username
        messages.success(request, f"{application.ariza_raqami} {name}ga tayinlandi.")
    else:
        messages.info(request, f"{application.ariza_raqami} allaqachon shu xodimga tayinlangan.")

    return redirect("xarid:qabul-arizalar")


# ---------------------------------------------------------------------------
# Contracts (sections 4.6, 4.8)
# ---------------------------------------------------------------------------


CONTRACT_DETAIL_TEMPLATE = "xarid/_shartnoma_tafsilot.html"

# Which contract page shows a contract at each stage. The Ko`rish dialog and
# the attachment behind it are readable exactly while the row is, which is
# the rule readable_application() follows for the other half of the workflow.
PAGE_SHOWING_CONTRACT_STAGE = {
    Contract.Stage.AGREED: "kelishinlingan",
    Contract.Stage.REJECTED: "kelishinlingan",
    Contract.Stage.SENT: "tuzilgan",
    Contract.Stage.SIGNED: "tuzilgan",
}


def readable_contract(request: HttpRequest, pk: int) -> Contract:
    """The contract this person may read the details of.

    Asked through the page that currently shows it rather than through a
    page permission named here: a contract moves between the two tables, and
    a check naming one of them would answer the wrong question the moment it
    moved.

    Raises:
        PermissionDenied: when the caller may not open the page this contract
            is on.
        Http404: when there is no such contract.
    """
    contract = get_object_or_404(
        Contract.all_objects.select_related(
            "application", "application__department", "supplier", "created_by"
        ).prefetch_related("items"),
        pk=pk,
    )

    # A deleted contract is on one page and one only, whatever stage it was
    # deleted at: O`chirilgan Shartnomalar draws Ko`rish beside Tiklash, so
    # an Admin can read a contract in full before putting it back.
    page_name = (
        "ochirilgan-shartnomalar"
        if contract.is_deleted
        else PAGE_SHOWING_CONTRACT_STAGE.get(contract.stage)
    )
    if page_name is None or not may_open(request.user, page_name):
        raise PermissionDenied(f"{request.user} may not see {contract.shartnoma_raqami}.")

    return contract


@login_required
def contract_detail(request: HttpRequest, pk: int) -> HttpResponse:
    """One contract's details, as the fragment the Ko`rish dialog shows.

    A fragment and not a page: the two contract tables fetch it when the
    button is pressed, so each page carries one dialog rather than one per
    row.
    """
    contract = readable_contract(request, pk)

    return render(
        request,
        CONTRACT_DETAIL_TEMPLATE,
        {"shartnoma": contract, "qatorlar": list(contract.items.all())},
    )


@login_required
def contract_pdf(request: HttpRequest, pk: int) -> FileResponse:
    """Download the contract's attachment as it was uploaded (DEC-019).

    Raises:
        Http404: when the contract has no attachment. Every contract entered
            since TASK-UZK-036A has one; the ones before it do not, and the
            dialog draws no button for those.
    """
    contract = readable_contract(request, pk)

    return attachment_response(contract.pdf, attachment_name(contract.shartnoma_raqami))


@login_required
def contract_document(request: HttpRequest, pk: int) -> HttpResponse:
    """Download the contract itself as a PDF, drawn from the record.

    The Shartnoma PDF beside the Shartnoma Ilova: the attachment is the
    document the department drew up, and this is what the application knows
    about it - the terms, the priced goods and the signature that settled it.

    Only once it is settled. A contract still waiting for a decision has no
    signature to print, and a sheet that looked like a contract while nobody
    had agreed to it is the one document this must never hand over. The
    control is drawn muted in that case, and this answers the same thing to
    anybody who asks for the URL anyway.

    Raises:
        Http404: when there is no such contract, or it has not been approved.
    """
    contract = readable_contract(request, pk)

    if not contract.is_signed:
        raise Http404(f"{contract.shartnoma_raqami} hali tasdiqlanmagan.")

    return contract_response(contract)


def agreed_contracts() -> QuerySet[Contract]:
    """The contracts on the Kelishinlingan page: agreed ones and rejected ones.

    A rejected contract belongs here because it is corrected and resent, and
    this is the page carrying its rejection comment as a column.
    """
    return (
        # EDITABLE_STAGES rather than the two values written out: the page
        # shows exactly the contracts whose status is still their specialist's
        # to change, and one name for that rule is what stops the page and the
        # model disagreeing about which those are.
        Contract.objects.filter(stage__in=Contract.EDITABLE_STAGES)
        .select_related(
            "application", "application__department", "supplier", "status", "created_by"
        )
        .prefetch_related(
            Prefetch("items", queryset=ContractItem.objects.all()),
            # The Holati column prints the last move under the current status,
            # and last_status_change reads this list - without it the page
            # would cost a query per contract.
            Prefetch(
                "status_changes",
                queryset=ContractStatusChange.objects.select_related(
                    "to_status", "from_status", "changed_by"
                ),
            ),
        )
    )


def contractable_applications(user: AbstractBaseUser) -> QuerySet[Application]:
    """The assigned applications this person may agree a contract against.

    A Katta Mutaxasis forms a contract on the basis of the application
    assigned to them (REQ-ROLE-007); everybody else sees all assigned ones.
    An application that already has a contract stays on the list: a second
    one against the same request is the department's business, not this
    function's.

    The suggestions and the POST are the same queryset, so a number this
    leaves out cannot be submitted either - the field matches what is typed
    against these rows and nothing else, which is what keeps a specialist
    from contracting against somebody else's work by typing its number.
    """
    applications = (
        Application.objects.filter(stage=Application.Stage.ASSIGNED)
        .select_related("department")
        .prefetch_related("items")
    )

    if acts_on_own_work_only(user):
        return applications.filter(assigned_to=user)

    return applications


class Suggestion(NamedTuple):
    """One row of a type-ahead list.

    Attributes:
        value: what typing is matched against, and what lands in the box.
        description: what the value is recognised by, shown beside it.
        detail: a fact the page needs about the chosen row and the reader
            does not, such as the INN a chosen firm fills in. Empty when
            there is none.
    """

    value: str
    description: str
    detail: str = ""


def application_suggestions(form: ContractForm) -> list[Suggestion]:
    """What the Ariza raqami box offers: each number, and what it is known by.

    Read off the form's own field rather than gathered separately, so the
    list somebody is shown and the list their typing is matched against
    cannot come apart.
    """
    field = form.fields["application"]

    return [
        Suggestion(application.ariza_raqami, field.describe(application))
        for application in field.queryset
    ]


def supplier_suggestions(form: ContractForm) -> list[Suggestion]:
    """What the Firma nomi box offers: each firm, with the INN it carries.

    The INN rides along as the detail rather than being fetched again when
    one is chosen (DEC-011): the page fills its read-only box from the row
    the reader picked, so the two can never be of different firms.
    """
    field = form.fields["supplier"]

    return [
        Suggestion(supplier.name, field.describe(supplier), supplier.inn)
        for supplier in field.queryset
    ]


class ContractNote(NamedTuple):
    """One thing written about a contract, whatever wrote it.

    Attributes:
        by: who wrote it. None only where a record somehow has no author.
        text: what they wrote.
        act: what the writing belongs to - entering the contract, deciding
            on it, or saying something about it. A comment without its act
            reads as an opinion rather than as a decision.
        badge: the class that act is drawn with.
        at: when, which is what the thread is ordered by.
    """

    by: AbstractBaseUser | None
    text: str
    act: str
    badge: str
    at: datetime


# What each kind of written text is called in the drawer, and how it looks.
NOTE_ENTERED = ("Kiritdi", "badge-soft")
NOTE_APPROVED = ("Tasdiqladi", "badge-approved")
NOTE_REJECTED = ("Inkor etdi", "badge-danger")
NOTE_COMMENT = ("Izoh", "badge-primary")


def contract_notes(contracts: Sequence[Contract]) -> dict[int, list[ContractNote]]:
    """Everything written about these contracts, oldest first, by contract id.

    Three sources in one thread: the note typed on the contract form, the
    reason each decision carried, and the comments people have added. They
    are one list because a reader wants the contract's story in order, not
    three lists to interleave by eye.

    Two queries for the whole page whatever the number of rows, which is
    what decisions_for() exists for and what the comments are fetched in
    one go for.
    """
    contracts = list(contracts)
    if not contracts:
        return {}

    decisions = decisions_for(contracts)
    threads: dict[int, list[ContractNote]] = {}

    for contract in contracts:
        notes = []
        if contract.izoh:
            notes.append(
                ContractNote(
                    contract.created_by,
                    contract.izoh,
                    *NOTE_ENTERED,
                    contract.yaratilingan_sana,
                )
            )
        for decision in decisions.get(contract.pk, []):
            act = NOTE_APPROVED if decision.approved else NOTE_REJECTED
            notes.append(
                ContractNote(decision.by, decision.comment, *act, decision.at)
            )
        threads[contract.pk] = notes

    written = ContractComment.objects.filter(
        contract_id__in=threads
    ).select_related("author")
    for comment in written:
        threads[comment.contract_id].append(
            ContractNote(
                comment.author, comment.matn, *NOTE_COMMENT, comment.created_at
            )
        )

    for notes in threads.values():
        notes.sort(key=lambda note: note.at)

    return threads


def opened_thread(chosen_filters: Mapping[str, str] | None) -> int | None:
    """The contract whose comment drawer should already be open, or None.

    Posting a comment reloads the page, and a reader put back at the top of
    a table they were reading a thread in has lost their place. The comment
    action redirects with the contract in the query string, and this reads
    it back.
    """
    asked = (chosen_filters or {}).get("izoh")

    return int(asked) if asked and str(asked).isdigit() else None


def contract_page(
    user: AbstractBaseUser,
    chosen_filters: Mapping[str, str] | None = None,
    form: ContractForm | None = None,
    items: ContractItemFormSet | None = None,
    editing: Contract | None = None,
) -> dict[str, object]:
    """Everything the Kelishinlingan Shartnoma page renders.

    Args:
        user: who is looking, which decides what is theirs to act on.
        chosen_filters: the query string the table is narrowed by.
        form: a form to render in place of an empty one - a submission that
            came back with errors, or a contract opened for editing.
        items: its rows, likewise.
        editing: the contract that form belongs to, when it is an edit. It
            opens the same dialog Shartnoma Kiritish opens, pointed at the
            edit action: TASK-UZK-065 asks for one way of filling a contract
            in, not two that drift apart.
    """
    table_filter = TableFilter(
        CONTRACT_FILTERS,
        agreed_contracts(),
        chosen_filters,
        date_column=CONTRACT_PERIOD,
        sort_choices=CONTRACT_SORTS,
    )
    contract_form = (
        form if form is not None else ContractForm(applications=contractable_applications(user))
    )

    # A page of them, as a list: the page walks it twice - once for the table
    # and once for the drawers behind it - and the notes are read from it. A
    # drawer is built per row drawn, so paging the table pages them too.
    table_page = TablePage(table_filter.apply(), chosen_filters, kept=table_filter.selections)
    contracts = list(table_page.rows)

    return {
        "contracts": contracts,
        "table_filter": table_filter,
        "table_page": table_page,
        "shartnoma_statuslari": ShartnomaStatus.objects.active(),
        "is_own_contract": own_contract_test(user),
        "contract_notes": contract_notes(contracts),
        "opened_thread": opened_thread(chosen_filters),
        "form": contract_form,
        "ariza_suggestions": application_suggestions(contract_form),
        "firma_suggestions": supplier_suggestions(contract_form),
        "item_formset": (
            items
            if items is not None
            else ContractItemFormSet(queryset=ContractItem.objects.none())
        ),
        "open_form": form is not None,
        # What the dialog is for. The form partial reads it to decide the two
        # read-only boxes at the top, and the page to decide where the form
        # posts and what its buttons say.
        "shartnoma": editing,
        "suggested_units": SUGGESTED_UNITS,
    }


# The contract columns an edit may change. The attachment is not among
# them: it is only written when a new file was chosen, so that an empty box
# keeps the one on record rather than clearing it.
CONTRACT_EDITABLE_COLUMNS = (
    "application",
    "supplier",
    "shartnoma_turi",
    "status",
    "shartnoma_sanasi",
    "tolash_muddati",
    "muddat_talabi",
    "invoice_sanasi",
    "izoh",
)


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
    form = ContractForm(request.POST, request.FILES, applications=applications)
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
            pdf=form.cleaned_data["pdf"],
        )

    record_created(request.user, contract)
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
        .prefetch_related(
            purchase_lines(),
            # The status cell walks request -> department application ->
            # contract -> status, and the page has a test about costing the
            # same with five rows as with one.
            Prefetch(
                "raised_application__contracts",
                queryset=Contract.objects.select_related("status"),
            ),
        )
        .all()
    )


def visible_purchase_applications(
    user: AbstractBaseUser | None,
) -> QuerySet[PurchaseApplication]:
    """The purchase requests this person reads on Xarid Arizasi.

    Everybody reads the ones they raised and nobody else's: this is the page
    a request is raised on and followed from, and the approvers' other two
    pages carry the requests they decide and have decided. An Admin reads all
    of them, being the one account that maintains the rest.

    Applied to the query rather than to the template, so the rows somebody
    may not see are never fetched, exported or counted.
    """
    applications = purchase_applications()
    if reads_own_requests_only(user):
        return applications.filter(created_by=user)

    return applications


def approvals_for(user: AbstractBaseUser) -> QuerySet[PurchaseApplication]:
    """Every purchase request standing at this person's step of the chain.

    Three steps, one table (DEC-016). The requester's own Bo`lim Boshlig`i
    first, then any Direktor, and then the purchasing department, which takes
    an approved request up as the application it raised. Whoever is waited
    for sees what waits for them and nothing else.

    The third step is what Kelib Tushgan Arizalar used to list separately as
    arrived applications: the same records at the same moment of their life,
    read through the request they came from so that one table can carry the
    whole chain.

    Somebody at none of the steps - a requester, a Katta Mutaxasis - gets an
    empty queue rather than the whole of it.
    """
    queue = PurchaseApplication.objects.select_related(
        "department", "status", "created_by", "raised_application"
    ).prefetch_related(purchase_lines())

    steps: list[Q] = []

    if has_user_type(user, (BOLIM_BOSHLIGI,)):
        department = department_of(user)
        if department is not None:
            steps.append(
                Q(stage=PurchaseApplication.Stage.AWAITING_HEAD, department=department)
            )

    if has_user_type(user, (DIREKTOR,)):
        steps.append(Q(stage=PurchaseApplication.Stage.AWAITING_DIREKTOR))

    if works_arrived_applications(user):
        steps.append(
            Q(
                stage=PurchaseApplication.Stage.APPROVED,
                raised_application__stage=Application.Stage.INCOMING,
            )
        )

    if not steps:
        return queue.none()

    return queue.filter(reduce(operator.or_, steps))


def queue_step_of(application: PurchaseApplication) -> str:
    """Which of the chain's three steps this row is standing at.

    A word for the column rather than the stage's own label: the table is a
    list of things waiting for somebody, and what a reader needs is who.
    """
    if application.stage == PurchaseApplication.Stage.AWAITING_HEAD:
        return "Bo`lim boshlig`i"

    if application.stage == PurchaseApplication.Stage.AWAITING_DIREKTOR:
        return "Direktor"

    return "Xarid bo`limi"


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
        return redirect("xarid:kelib-arizalar")

    if approved:
        record_decision(request.user, application, approved=True)
        tell_requester_of_progress(application)
        tell_whoever_it_now_waits_for(application)

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

    return redirect("xarid:kelib-arizalar")


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

        return redirect("xarid:kelib-arizalar")

    if rejected:
        record_decision(
            request.user,
            application,
            approved=False,
            comment=application.inkor_izohi,
        )
        messages.success(request, f"{application.xarid_raqami} inkor etildi.")
    else:
        messages.info(request, f"{application.xarid_raqami} allaqachon inkor etilgan.")

    return redirect("xarid:kelib-arizalar")


def purchase_page(
    signed_in_department: Department | None = None,
    chosen_filters: Mapping[str, str] | None = None,
    form: PurchaseApplicationForm | None = None,
    items: PurchaseApplicationItemFormSet | None = None,
    viewer: AbstractBaseUser | None = None,
) -> dict[str, object]:
    """Everything the Xarid Arizasi page renders.

    The page a request is raised on and tracked from. Deciding one happens on
    Kelib Tushgan Arizalar instead: a request waiting for somebody belongs on
    the page they work, beside the applications that came through the same
    chain, rather than on the page it was typed into.

    Args:
        viewer: who is reading it, which decides which requests the table
            holds and whether the status cell may name the contract a state
            came from.
    """
    table_filter = TableFilter(
        PURCHASE_FILTERS,
        visible_purchase_applications(viewer),
        chosen_filters,
        date_column=PURCHASE_PERIOD,
        sort_choices=PURCHASE_SORTS,
    )
    table_page = TablePage(table_filter.apply(), chosen_filters, kept=table_filter.selections)
    applications = list(table_page.rows)
    return {
        "applications": applications,
        "table_filter": table_filter,
        "table_page": table_page,
        "signed_in_department": signed_in_department,
        # What the Izoh column's panel shows: every step of the DEC-016 chain
        # in the order it was taken, which only the log kept.
        "decisions": decisions_for(applications),
        # Whether this viewer may be told which contract a status came from.
        # DEC-015 gives Users this page and no contract page at all, so the
        # explanation must not hand them a fact from a page they cannot open -
        # the rule the attachment download already follows.
        "may_name_contract": contract_naming_test(viewer),
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
        chosen_filters=request.GET,
        viewer=request.user,
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
            purchase_page(
                department,
                form=form,
                items=items,
                viewer=request.user,
            ),
        )

    if not (form.is_valid() and items.is_valid()):
        messages.error(request, "Xarid arizasi yaratilmadi: formani tekshiring.")
        return render(
            request,
            PURCHASE_TEMPLATE,
            purchase_page(
                department,
                form=form,
                items=items,
                viewer=request.user,
            ),
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

    record_created(request.user, application)
    tell_whoever_it_now_waits_for(application)
    messages.success(request, f"{application.xarid_raqami} yaratildi.")

    return redirect("xarid:xarid-ariza")


def readable_purchase_application(request: HttpRequest, pk: int) -> PurchaseApplication:
    """The purchase application whose attachments this person may download.

    DEC-019's rule, applied to a record: somebody may open what a page of
    theirs would show them and nothing else, so the route answers 404 rather
    than handing over the file of a row no table of theirs ever held.

    A Users account: the requests it raised. A Bo`lim Boshlig`i: those, plus
    the ones standing at their step of DEC-016's chain and the ones they have
    already approved - the rows of Kelib Tushgan Arizalar and Tasdiqlangan
    Arizalar. Narrowing a head to their own would leave them deciding a
    request without being able to read what was attached to it.
    """
    applications = PurchaseApplication.objects.all()

    if has_user_type(request.user, (USERS,)):
        return get_object_or_404(applications.filter(created_by=request.user), pk=pk)

    if has_user_type(request.user, (BOLIM_BOSHLIGI,)):
        theirs = (
            Q(created_by=request.user)
            | Q(tasdiqlagan_bolim_boshligi=request.user)
            | Q(
                stage=PurchaseApplication.Stage.AWAITING_HEAD,
                department=department_of(request.user),
            )
        )
        return get_object_or_404(applications.filter(theirs), pk=pk)

    return get_object_or_404(applications, pk=pk)


def purchase_application_pdf(request: HttpRequest, pk: int) -> FileResponse:
    """Download one purchase application's PDF (DEC-019).

    The permission is on the route: a purchase application is on one page for
    its whole life.
    """
    application = readable_purchase_application(request, pk)

    return attachment_response(application.pdf, attachment_name(application.xarid_raqami))


def purchase_application_document(request: HttpRequest, pk: int) -> HttpResponse:
    """Download the request itself as a PDF, drawn from the record.

    The Ariza PDF column beside the Ilova PDF one: the attachment is what the
    requester uploaded, and this is what the system knows, so a row is
    readable on paper even when nothing was ever attached to it.
    """
    application = readable_purchase_application(request, pk)

    return purchase_application_response(application)


def purchase_application_original_pdf(request: HttpRequest, pk: int) -> FileResponse:
    """Download the attachment as it was uploaded, before any stamp.

    Raises:
        Http404: when there is no such application, or it has no original -
            every application that has not been approved, since until then
            pdf is the original.
    """
    application = readable_purchase_application(request, pk)

    return attachment_response(
        application.asl_pdf, attachment_name(application.xarid_raqami, "asl")
    )


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

QUEUE_EXPORT_COLUMNS = (
    ExportColumn("Ariza raqami", lambda ariza, line: ariza.xarid_raqami),
    ExportColumn("Ariza nomi", lambda ariza, line: ariza.shartnoma_nomi),
    ExportColumn("Bo'lim", lambda ariza, line: ariza.department.name),
    ExportColumn("Buyurtmachi", lambda ariza, line: display_name(ariza.created_by)),
    ExportColumn("Bosqich", lambda ariza, line: queue_step_of(ariza)),
    ExportColumn("Izoh", lambda ariza, line: ariza.izoh),
    ExportColumn("Yaratilgan", lambda ariza, line: local_date(ariza.yaratilingan_sana)),
)

APPROVED_EXPORT_COLUMNS = (
    ExportColumn("Ariza raqami", lambda ariza, line: ariza.xarid_raqami),
    ExportColumn("Ariza nomi", lambda ariza, line: ariza.shartnoma_nomi),
    ExportColumn("Buyurtmachi", lambda ariza, line: display_name(ariza.created_by)),
    ExportColumn("Holati", lambda ariza, line: ariza.get_stage_display()),
    ExportColumn("Izoh", lambda ariza, line: ariza.izoh),
    ExportColumn("Tasdiqlangan sana", lambda ariza, line: local_date(ariza.tasdiqlagan_sana)),
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

# What Tuzilgan adds to a contract download: the decision the page takes.
SIGNED_EXPORT_COLUMNS = (
    *CONTRACT_EXPORT_COLUMNS,
    ExportColumn(
        "Yuborilgan sana", lambda shartnoma, line: local_date(shartnoma.yuborilgan_sana)
    ),
    ExportColumn("Qaror", lambda shartnoma, line: shartnoma.get_stage_display()),
    # Empty rather than display_name(None), which answers "Foydalanuvchi":
    # a contract nobody has decided on has no decider to name.
    ExportColumn(
        "Kim tasdiqlagan",
        lambda shartnoma, line: display_name(shartnoma.tasdiqlagan)
        if shartnoma.tasdiqlagan
        else "",
    ),
    ExportColumn(
        "Tasdiqlangan sana", lambda shartnoma, line: local_date(shartnoma.tasdiqlangan_sana)
    ),
)

PURCHASE_EXPORT_COLUMNS = (
    ExportColumn("Ariza raqami", lambda ariza, line: ariza.xarid_raqami),
    ExportColumn("Shartnoma nomi", lambda ariza, line: ariza.shartnoma_nomi),
    ExportColumn("Bo'lim", lambda ariza, line: ariza.department.name),
    ExportColumn("Buyurtma nomi", lambda ariza, line: line.buyurtma_nomi),
    ExportColumn("Soni", lambda ariza, line: line.soni_display),
    ExportColumn("O'lchov", lambda ariza, line: line.olchov_birligi),
    # shown_status, not status: the page shows the contract's state once there
    # is one (TASK-UZK-033), and a download that held the raised-as status
    # instead would be a well-formed file that quietly disagreed with the
    # screen it came from.
    ExportColumn(
        "Holati",
        lambda ariza, line: ariza.shown_status.name if ariza.shown_status else "",
    ),
    ExportColumn(
        "Holat manbasi",
        lambda ariza, line: "Shartnoma" if ariza.status_follows_contract else "Ariza",
    ),
    ExportColumn("Mahsulot turi", lambda ariza, line: category_label(line)),
    ExportColumn("Izoh", lambda ariza, line: ariza.izoh),
    ExportColumn("Yaratilgan", lambda ariza, line: local_date(ariza.yaratilingan_sana)),
)


def incoming_export(request: HttpRequest, file_format: str) -> HttpResponse:
    """Download the Kelib tushgan table, filtered as the page is.

    The reader's own queue, not everybody's: a download must not hand over
    rows the table it came from would not show (DEC-019's rule, applied to a
    file rather than to an attachment).

    One row per request rather than per order line, because that is how this
    table renders - a row is something waiting for somebody, not a line item.
    """
    table_filter = TableFilter(
        INCOMING_FILTERS,
        approvals_for(request.user),
        request.GET,
        date_column=PURCHASE_PERIOD,
        sort_choices=PURCHASE_SORTS,
    )
    rows = [(application, None) for application in table_filter.apply()]
    export = TableExport("kelib-arizalar", QUEUE_EXPORT_COLUMNS, rows)
    return export_response(export, file_format)


def accepted_export(request: HttpRequest, file_format: str) -> HttpResponse:
    """Download the Qabul qilingan table, filtered as the page is.

    Whichever table that is: a head reading their own approvals downloads
    those, not the accepted applications they never see.
    """
    if sees_own_approvals(request.user):
        step = approval_step_of(request.user)
        own = TableFilter(
            step.filters,
            approved_by(request.user, step),
            request.GET,
            date_column=step.period,
            sort_choices=step.sorts,
        )
        rows = [(application, None) for application in own.apply()]

        return export_response(
            TableExport("tasdiqlangan-arizalar", APPROVED_EXPORT_COLUMNS, rows), file_format
        )

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


def signed_contracts_export(request: HttpRequest, file_format: str) -> HttpResponse:
    """Download the Tuzilgan table, filtered as the page is.

    The contract columns every contract download carries, and after them what
    this page is about: when it was sent, what was decided, and by whom.
    """
    table_filter = TableFilter(
        SIGNED_FILTERS,
        signed_contracts(),
        request.GET,
        date_column=SIGNED_PERIOD,
        sort_choices=SIGNED_SORTS,
    )
    export = TableExport(
        "tuzilgan", SIGNED_EXPORT_COLUMNS, lines_of(table_filter.apply())
    )
    return export_response(export, file_format)


def purchase_export(request: HttpRequest, file_format: str) -> HttpResponse:
    """Download the Xarid Arizasi table, filtered as the page is."""
    table_filter = TableFilter(
        PURCHASE_FILTERS,
        visible_purchase_applications(request.user),
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


def workload_filter(chosen: Mapping[str, str]) -> TableFilter:
    """The Xodimlar yuklamasi bar, built once for the page and its download.

    The bar offers the period and nothing else: there is one row per
    specialist already, so there is no column to narrow by. The page and the
    download build it here rather than each in their own place, so a file
    cannot come to hold something other than the screen.
    """
    return TableFilter((), assigned_work(), chosen, date_column=WORKLOAD_PERIOD)


def staff_workload_report(request: HttpRequest) -> HttpResponse:
    """Xodimlar yuklamasi: what each specialist is carrying (REQ-YUKLAMA-002)."""
    table_filter = workload_filter(request.GET)
    report_invalid_filters(request, table_filter)

    # The report whole, and a page of its rows: the totals row under the
    # table is the report's, not this page's, so it is the same figure
    # whichever page it is read on - as the exported file is.
    report = staff_workload(table_filter.period)
    table_page = TablePage(report.rows, request.GET, kept=table_filter.selections)

    return render(
        request,
        WORKLOAD_TEMPLATE,
        {"report": report, "table_filter": table_filter, "table_page": table_page},
    )


def staff_workload_export(request: HttpRequest, file_format: str) -> HttpResponse:
    """Download Xodimlar yuklamasi, narrowed as the page is (REQ-YUKLAMA-001)."""
    report = staff_workload(workload_filter(request.GET).period)
    export = report_export(
        report,
        "xodimlar-yuklamasi",
        "Xodim",
        "Xarid topshiriqlari",
        detail_label="Telefon",
    )
    return export_response(export, file_format)


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


def department_report_filter(chosen: Mapping[str, str]) -> TableFilter:
    """The Bo`limlar bar, built once for the page and its download.

    Its options come from the applications of departments the report has a
    row for, so it cannot offer a department that would empty the table: a
    deactivated department keeps its history but is not reported on.
    """
    return TableFilter(
        (BY_DEPARTMENT,),
        reported_applications(),
        chosen,
        date_column=DEPARTMENT_REPORT_PERIOD,
    )


def department_purchasing_report(request: HttpRequest) -> HttpResponse:
    """Korhona xaridi | Bo`limlar: what each department is buying."""
    table_filter = department_report_filter(request.GET)
    report_invalid_filters(request, table_filter)

    report = department_purchasing(table_filter.period, table_filter.fields[0].selected)
    table_page = TablePage(report.rows, request.GET, kept=table_filter.selections)

    return render(
        request,
        DEPARTMENTS_REPORT_TEMPLATE,
        {"report": report, "table_filter": table_filter, "table_page": table_page},
    )


def department_purchasing_export(request: HttpRequest, file_format: str) -> HttpResponse:
    """Download Bo`limlar xaridi, narrowed as the page is (REQ-XARID-001)."""
    table_filter = department_report_filter(request.GET)
    report = department_purchasing(table_filter.period, table_filter.fields[0].selected)
    export = report_export(report, "bolimlar", "Bo`lim Nomi", "Xarid topshiriqlari")
    return export_response(export, file_format)


# ---------------------------------------------------------------------------
# Korhona xaridi | Mahsulotlar
# ---------------------------------------------------------------------------
PRODUCTS_TEMPLATE = "xarid/pages/mahsulotlar.html"

PRODUCTS_EXPORT_COLUMNS = (
    ExportColumn("Ariza raqami", lambda ariza, line: ariza.ariza_raqami),
    ExportColumn("Bo'lim", lambda ariza, line: ariza.department.name),
    *ORDER_LINE_EXPORT_COLUMNS,
    ExportColumn("Izoh", lambda ariza, line: ariza.izoh),
    ExportColumn("Qabul qilingan sana", lambda ariza, line: local_date(ariza.qabul_qilingan_sana)),
    ExportColumn("Holati", lambda ariza, line: ariza.current_status_label),
)


def product_lines() -> QuerySet[ApplicationItem]:
    """Every ordered product line, newest application first (REQ-XARID-003).

    One row per line rather than per application: this report is read to find
    a product, not to work through a queue. Lines of a rejected application
    are included - it was still asked for, and its row says so in the status
    column - though DEC-019 keeps its attachment unreachable.
    """
    return (
        ApplicationItem.objects.select_related(
            "application",
            "application__department",
            "mahsulot_turi",
        )
        .prefetch_related("application__contracts__status")
        .order_by("-application__kelib_tushgan_sana", "-application_id", "id")
    )


def products_filter(chosen: Mapping[str, str]) -> TableFilter:
    """The Mahsulotlar bar, built once for the page and its download."""
    return TableFilter(
        PRODUCTS_FILTERS,
        product_lines(),
        chosen,
        date_column=PRODUCTS_PERIOD,
    )


def products_list(request: HttpRequest) -> HttpResponse:
    """Korhona xaridi | Mahsulotlar: every ordered line and where it stands."""
    table_filter = products_filter(request.GET)
    report_invalid_filters(request, table_filter)

    table_page = TablePage(table_filter.apply(), request.GET, kept=table_filter.selections)

    return render(
        request,
        PRODUCTS_TEMPLATE,
        {
            "lines": table_page.rows,
            "table_filter": table_filter,
            "table_page": table_page,
            # The row asks before drawing a link, so it never offers one that
            # would answer 403.
            "pdf_is_reachable": pdf_is_reachable,
        },
    )


def products_export(request: HttpRequest, file_format: str) -> HttpResponse:
    """Download the Mahsulotlar table, narrowed as the page is."""
    lines = products_filter(request.GET).apply()
    export = TableExport(
        "mahsulotlar",
        PRODUCTS_EXPORT_COLUMNS,
        [(line.application, line) for line in lines],
    )
    return export_response(export, file_format)


def pdf_is_reachable(application: Application) -> bool:
    """Whether this application's PDF can still be downloaded (DEC-019).

    An attachment follows the record: it is reachable while some page shows
    the application, and a rejected one is on no page. The row renders a link
    only when there is something behind it, rather than one that answers 403.
    """
    return bool(application.pdf) and application.stage in PAGE_SHOWING_STAGE

# ---------------------------------------------------------------------------
# Korhona xaridi | Mahsulot Turi
# ---------------------------------------------------------------------------
CATEGORY_REPORT_TEMPLATE = "xarid/pages/mahsulot-tur.html"

# The type report counts an application from the day it arrived, the same
# date the departments report uses, so the two agree over one period.
# The path from a product type to the date its application arrived. Unlike the
# other two reports, this bar's rows are the subject itself rather than the
# applications being counted, so the column carries the whole path: that way
# the bar can narrow its own rows as every other bar in the application can,
# instead of holding a period it would raise on.
CATEGORY_REPORT_PERIOD = DateColumn(
    "Kelib tushgan sana", "application_items__application__kelib_tushgan_sana"
)

# The type drop-down reads the types that are actually on an order line, and
# posts back the parameter the Mahsulotlar page filters by - the same one the
# Ko`rish link carries.
BY_ITEM_CATEGORY = FilterColumn(
    "mahsulot",
    "Mahsulot turi",
    "pk",
    ("name",),
)


def category_report_filter(chosen: Mapping[str, str]) -> TableFilter:
    """The Mahsulot Turi bar, built once for the page and its download."""
    return TableFilter(
        (BY_ITEM_CATEGORY,),
        MahsulotTuri.objects.active(),
        chosen,
        date_column=CATEGORY_REPORT_PERIOD,
    )


def category_purchasing_report(request: HttpRequest) -> HttpResponse:
    """Korhona xaridi | Mahsulot Turi: what is bought of each product type."""
    table_filter = category_report_filter(request.GET)
    report_invalid_filters(request, table_filter)

    report = category_purchasing(table_filter.period, table_filter.fields[0].selected)
    table_page = TablePage(report.rows, request.GET, kept=table_filter.selections)

    return render(
        request,
        CATEGORY_REPORT_TEMPLATE,
        {"report": report, "table_filter": table_filter, "table_page": table_page},
    )


def category_purchasing_export(request: HttpRequest, file_format: str) -> HttpResponse:
    """Download the Mahsulot Turi table, narrowed as the page is."""
    table_filter = category_report_filter(request.GET)
    report = category_purchasing(table_filter.period, table_filter.fields[0].selected)
    export = report_export(
        report,
        "mahsulot-tur",
        "Mahsulot Turi",
        "Xarid topshiriqlari",
        detail_label="Kodi",
    )
    return export_response(export, file_format)


def chosen_status(requested: str | None) -> ShartnomaStatus | None:
    """The status a request asked for, or None when it asked for nothing usable.

    Anything that is not a plain number is treated as no choice rather than
    handed to the ORM, which raises on it: the drop-down always posts a real
    id, so a value that is not one came from a hand-made request, and this
    page answers every other refusal with a message. set_status has the
    message for choosing nothing.
    """
    if not requested or not requested.isdigit():
        return None

    return ShartnomaStatus.objects.filter(pk=requested).first()


@require_POST
def contract_set_status(request: HttpRequest, pk: int) -> HttpResponse:
    """Move one contract to a status (REQ-SHTSTATUS-001).

    Every refusal answers with a message rather than a 404. The case that
    actually happens is a race - somebody sending the contract while this
    page was open - and a person told their change was not saved needs to
    know why; a 404 does not say.

    A move that happened tells Xarid Bo`limi's Bo`lim Boshlig`i, from
    whichever of the two contract pages it was made on: the head handed the
    work out and a step forward is theirs to hear about. A press that moved
    nothing tells nobody.
    """
    contract = get_object_or_404(Contract, pk=pk)

    if not held_contract(request.user, contract):
        messages.error(
            request,
            f"{contract.shartnoma_raqami} holatini o`zgartirib bo`lmaydi: "
            "bu shartnoma sizning ishingizga tegishli emas.",
        )
        return back_to_contract_page(request)

    status = chosen_status(request.POST.get("holat"))
    try:
        moved = contract.set_status(status, by=request.user)
    except ValueError as refusal:
        messages.error(request, str(refusal))
        return back_to_contract_page(request)

    if moved:
        record_edited(request.user, contract)
        tell_head_of_status_change(contract, by=request.user)
        messages.success(
            request,
            f"{contract.shartnoma_raqami} holati o`zgartirildi: {status.name}.",
        )
    else:
        messages.info(
            request,
            f"{contract.shartnoma_raqami} allaqachon {status.name} holatida.",
        )

    return back_to_contract_page(request)


def save_status_before_sending(
    request: HttpRequest, contract: Contract
) -> bool:
    """Apply the status the send form carried, and say whether to carry on.

    The Kelishinlingan page has no Saqlash of its own since this task: the
    drop-down sits in its own column and rides along with Yuborish, so one
    click saves the status and sends. Sending is the step that cannot be
    taken back - the contract leaves the page - so a status that will not
    save stops the send rather than being sent with the wrong one.

    A form that carried no status at all is not a refusal. A contract with no
    status yet offers a blank first option, and choosing nothing there means
    "send it as it is", not "clear the status".

    Returns:
        True when the send should go ahead. False when the status was refused
        and a message saying so has been added.
    """
    requested = request.POST.get("holat")
    if not requested:
        return True

    try:
        contract.set_status(chosen_status(requested), by=request.user)
    except ValueError as refusal:
        messages.error(request, f"{refusal} Shartnoma yuborilmadi.")
        return False

    return True


def contract_to_act_on(request: HttpRequest, pk: int) -> Contract | None:
    """The contract this row action is about, or None with the reason said.

    One check for Tahrirlash and O`chirish: both are the row's to perform,
    both refuse a contract that has gone for approval, and both answer with
    a message rather than a 403 - the caller had the page, and what stops
    them is which contract they picked.

    Returns:
        The contract, or None when a message has been added saying why not.
    """
    # all_objects, so that a row somebody deleted while this page was open
    # is answered with the sentence saying so rather than with a 404 - the
    # page cannot show what became of it, and a 404 does not say.
    contract = get_object_or_404(Contract.all_objects, pk=pk)

    if contract.is_deleted:
        messages.info(
            request,
            f"{contract.shartnoma_raqami} allaqachon o`chirilgan. Admin uni "
            "O`chirilgan Shartnomalar sahifasidan tiklashi mumkin.",
        )
        return None

    if not held_contract(request.user, contract):
        messages.error(
            request,
            f"{contract.shartnoma_raqami} sizning ishingizga tegishli emas.",
        )
        return None

    if not contract.is_editable:
        messages.error(
            request,
            f"{contract.shartnoma_raqami} allaqachon tasdiqlashga yuborilgan, "
            "o`zgartirib bo`lmaydi.",
        )
        return None

    return contract


def contract_edit(request: HttpRequest, pk: int) -> HttpResponse:
    """The Shartnoma Kiritish dialog again, filled in, for one contract.

    The same dialog on the same page, pointed at the edit action, which is
    how the page already comes back when a new contract fails validation.
    One way of filling a contract in rather than two, and the row adder, the
    calculator and the type-ahead boxes all bind at load over a page that
    was loaded - which a form fetched into a dialog afterwards would not be.
    """
    contract = contract_to_act_on(request, pk)
    if contract is None:
        return redirect("xarid:kelishinlingan")

    applications = contractable_applications(request.user)
    rows = ContractItem.objects.filter(contract=contract)

    if request.method != "POST":
        return render(
            request,
            AGREED_CONTRACTS_TEMPLATE,
            contract_page(
                request.user,
                form=ContractEditForm(instance=contract, applications=applications),
                items=ContractItemEditFormSet(queryset=rows),
                editing=contract,
            ),
        )

    form = ContractEditForm(
        request.POST, request.FILES, instance=contract, applications=applications
    )
    items = ContractItemEditFormSet(request.POST, queryset=rows)

    if not (form.is_valid() and items.is_valid()):
        messages.error(request, "Shartnoma saqlanmadi: formani tekshiring.")
        return render(
            request,
            AGREED_CONTRACTS_TEMPLATE,
            contract_page(request.user, form=form, items=items, editing=contract),
        )

    terms = {
        column: form.cleaned_data[column]
        for column in CONTRACT_EDITABLE_COLUMNS
    }
    # An empty box keeps the file on record: the edit form does not demand a
    # PDF, and "no new file" must not mean "remove the one there".
    if form.cleaned_data["pdf"]:
        terms["pdf"] = form.cleaned_data["pdf"]

    try:
        contract.update_terms(
            items=filled_in_rows(items, CONTRACT_LINE_FIELDS), **terms
        )
    except ValueError as refusal:
        messages.error(request, str(refusal))
        return render(
            request,
            AGREED_CONTRACTS_TEMPLATE,
            contract_page(request.user, form=form, items=items, editing=contract),
        )

    record_edited(request.user, contract)
    messages.success(
        request,
        f"{contract.shartnoma_raqami} saqlandi. "
        f"Shartnoma qiymati: {contract.qiymati_display} UZS.",
    )

    return redirect("xarid:kelishinlingan")


@require_POST
def contract_comment(request: HttpRequest, pk: int) -> HttpResponse:
    """Add one comment to a contract's thread (TASK-UZK-066).

    Anybody who may open the page may write on any contract it shows.
    Commenting is not acting on the contract - Tahrirlash, Yuborish and
    O`chirish still ask whose it is - and a thread only its holder may
    write to is a thread a head cannot ask a question in.
    """
    contract = get_object_or_404(Contract, pk=pk)

    written = (request.POST.get("matn") or "").strip()
    if not written:
        messages.error(request, "Izoh yozilmadi: matn bo`sh.")
        return back_to_thread(contract)

    comment = ContractComment.objects.create(
        contract=contract, author=request.user, matn=written
    )
    tell_thread_of_comment(contract, comment)
    messages.success(request, f"{contract.shartnoma_raqami} uchun izoh qo`shildi.")

    return back_to_thread(contract)


def back_to_thread(contract: Contract) -> HttpResponse:
    """Back to the table, with this contract's drawer open where it was."""
    return redirect(f"{reverse('xarid:kelishinlingan')}?izoh={contract.pk}")


@require_POST
def contract_delete(request: HttpRequest, pk: int) -> HttpResponse:
    """Take one contract off the page, keeping the row (TASK-UZK-064).

    Deleting is reversible and says so: the message names the page an Admin
    puts it back from, because a row vanishing with no way back is the thing
    people are afraid of when they do not press the button.
    """
    contract = contract_to_act_on(request, pk)
    if contract is None:
        return redirect("xarid:kelishinlingan")

    try:
        deleted = contract.soft_delete(by=request.user)
    except ValueError as refusal:
        messages.error(request, str(refusal))
        return redirect("xarid:kelishinlingan")

    if deleted:
        # After, not before. record_deleted() says to call it first, while
        # the record can still say what it was - that is for a deletion that
        # destroys the row, and this one keeps it. Calling it first would
        # log a deletion that the line above can still refuse.
        record_deleted(request.user, contract)
        messages.success(
            request,
            f"{contract.shartnoma_raqami} o`chirildi va O`chirilgan "
            "Shartnomalar sahifasiga o`tdi.",
        )
    else:
        messages.info(request, f"{contract.shartnoma_raqami} allaqachon o`chirilgan.")

    return redirect("xarid:kelishinlingan")


DELETED_CONTRACTS_TEMPLATE = "xarid/pages/ochirilgan-shartnomalar.html"


def deleted_contracts() -> QuerySet[Contract]:
    """The contracts that were deleted, newest deletion first.

    all_objects, because the ordinary manager is the one that hides them.
    """
    return (
        Contract.all_objects.filter(deleted_at__isnull=False)
        .select_related(
            "application",
            "application__department",
            "supplier",
            "status",
            "created_by",
            "deleted_by",
        )
        .prefetch_related("items")
        .order_by("-deleted_at", "-id")
    )


def deleted_contracts_list(request: HttpRequest) -> HttpResponse:
    """O`chirilgan Shartnomalar: what was deleted, and the way back."""
    table_page = TablePage(deleted_contracts(), request.GET)

    return render(
        request,
        DELETED_CONTRACTS_TEMPLATE,
        {"contracts": list(table_page.rows), "table_page": table_page},
    )


@require_POST
def contract_restore(request: HttpRequest, pk: int) -> HttpResponse:
    """Put a deleted contract back where it was (TASK-UZK-064)."""
    contract = get_object_or_404(Contract.all_objects, pk=pk)

    if contract.restore(by=request.user):
        record_edited(request.user, contract)
        messages.success(
            request,
            f"{contract.shartnoma_raqami} tiklandi va Kelishinlingan "
            "sahifasiga qaytdi.",
        )
    else:
        messages.info(request, f"{contract.shartnoma_raqami} o`chirilmagan edi.")

    return redirect("xarid:ochirilgan-shartnomalar")


@require_POST
def contract_send_for_approval(request: HttpRequest, pk: int) -> HttpResponse:
    """Save the chosen status and send one contract on (REQ-SHARTNOMA-005).

    The message names where the contract went, not only that it went. Sending
    takes it off this page, and a row disappearing with no explanation is how
    somebody concludes they deleted something.

    A send that happened tells Xarid Bo`limi's Bo`lim Boshlig`i and Menejer
    that the contract now waits for them, after the transition reported
    success - so a refused send tells nobody.
    """
    contract = get_object_or_404(Contract, pk=pk)

    if not held_contract(request.user, contract):
        messages.error(
            request,
            f"{contract.shartnoma_raqami} yuborilmadi: bu shartnoma sizning "
            "ishingizga tegishli emas.",
        )
        return redirect("xarid:kelishinlingan")

    if not save_status_before_sending(request, contract):
        return redirect("xarid:kelishinlingan")

    try:
        sent = contract.send_for_approval(by=request.user)
    except ValueError as refusal:
        messages.error(request, str(refusal))
        return redirect("xarid:kelishinlingan")

    if sent:
        record_edited(request.user, contract)
        tell_of_contract_sent(contract, by=request.user)
        messages.success(
            request,
            f"{contract.shartnoma_raqami} tasdiqlashga yuborildi va "
            "Tuzilgan Shartnomalar sahifasiga o`tdi.",
        )
    else:
        messages.info(
            request,
            f"{contract.shartnoma_raqami} allaqachon tasdiqlashga yuborilgan.",
        )

    return redirect("xarid:kelishinlingan")


# ---------------------------------------------------------------------------
# Tuzilgan Shartnomalar: the department head decides
# ---------------------------------------------------------------------------
SIGNED_CONTRACTS_TEMPLATE = "xarid/pages/tuzilgan.html"

# The stages this page shows: waiting for a decision, and decided. A rejected
# contract is not here - it went back to its specialist, which is what a
# rejection means (REQ-SHARTNOMA-004).
DECIDED_STAGES = (Contract.Stage.SENT, Contract.Stage.SIGNED)


def back_to_contract_page(request: HttpRequest) -> HttpResponse:
    """Return to whichever contract page the action was used from.

    The status control is on two pages since this task, so a redirect to a
    named one would move somebody off the page they were working on.
    """
    referer = request.META.get("HTTP_REFERER") or ""
    if reverse("xarid:tuzilgan") in referer:
        return redirect("xarid:tuzilgan")

    return redirect("xarid:kelishinlingan")


def signed_contracts() -> QuerySet[Contract]:
    """The contracts the department head has to decide on, or has decided."""
    return (
        Contract.objects.filter(stage__in=DECIDED_STAGES)
        .select_related(
            "application", "application__department", "supplier", "status", "created_by"
        )
        .prefetch_related(
            Prefetch("items", queryset=ContractItem.objects.all()),
            Prefetch(
                "status_changes",
                queryset=ContractStatusChange.objects.select_related(
                    "to_status", "from_status", "changed_by"
                ),
            ),
        )
        .order_by(F("yuborilgan_sana").desc(nulls_last=True), "-id")
    )


def signed_contracts_list(request: HttpRequest) -> HttpResponse:
    """Tuzilgan Shartnomalar (REQ-SHARTNOMA-001, REQ-SHARTNOMA-002)."""
    table_filter = TableFilter(
        SIGNED_FILTERS,
        signed_contracts(),
        request.GET,
        date_column=SIGNED_PERIOD,
        sort_choices=SIGNED_SORTS,
    )
    report_invalid_filters(request, table_filter)
    table_page = TablePage(table_filter.apply(), request.GET, kept=table_filter.selections)

    return render(
        request,
        SIGNED_CONTRACTS_TEMPLATE,
        {
            "contracts": table_page.rows,
            "table_filter": table_filter,
            "table_page": table_page,
            "may_decide": decides_on_contracts(request.user),
            # The status control asks the same question here as on
            # Kelishinlingan: a specialist may open this page, and offering
            # them a control for somebody else's contract only produces a
            # refusal they could have been spared.
            "is_own_contract": own_contract_test(request.user),
            # And one more question, which Kelishinlingan does not ask: a
            # Katta Mutaxasis reads this page rather than working it
            # (TASK-UZK-068).
            "may_move_status": moves_status_on_tuzilgan(request.user),
            "shartnoma_statuslari": ShartnomaStatus.objects.active(),
        },
    )


@require_POST
def contract_accept(request: HttpRequest, pk: int) -> HttpResponse:
    """Approve one contract (REQ-SHARTNOMA-002)."""
    contract = get_object_or_404(Contract, pk=pk)

    if not decides_on_contracts(request.user):
        raise PermissionDenied(
            f"{request.user} may not decide on {contract.shartnoma_raqami}."
        )

    try:
        approved = contract.accept(by=request.user)
    except ValueError as refusal:
        messages.error(request, str(refusal))
        return redirect("xarid:tuzilgan")

    if approved:
        record_decision(request.user, contract, approved=True)
        tell_holders_of_decision(
            contract, by=request.user, kind=Notification.Kind.CONTRACT_APPROVED
        )
        messages.success(request, f"{contract.shartnoma_raqami} qabul qilindi.")
    else:
        messages.info(request, f"{contract.shartnoma_raqami} allaqachon qabul qilingan.")

    return redirect("xarid:tuzilgan")


@require_POST
def contract_reject(request: HttpRequest, pk: int) -> HttpResponse:
    """Send one contract back to its specialist (REQ-SHARTNOMA-004)."""
    contract = get_object_or_404(Contract, pk=pk)

    if not decides_on_contracts(request.user):
        raise PermissionDenied(
            f"{request.user} may not decide on {contract.shartnoma_raqami}."
        )

    try:
        rejected = contract.reject(by=request.user, comment=request.POST.get("izoh", ""))
    except ValueError as refusal:
        messages.error(request, str(refusal))
        return redirect("xarid:tuzilgan")

    if rejected:
        record_decision(
            request.user,
            contract,
            approved=False,
            comment=contract.inkor_izohi,
        )
        tell_holders_of_decision(
            contract,
            by=request.user,
            kind=Notification.Kind.CONTRACT_RETURNED,
            comment=contract.inkor_izohi,
        )
        messages.success(
            request,
            f"{contract.shartnoma_raqami} inkor qilindi va mutaxassisga qaytarildi.",
        )
    else:
        messages.info(request, f"{contract.shartnoma_raqami} allaqachon hal qilingan.")

    return redirect("xarid:tuzilgan")


@require_POST
def contract_undo_approval(request: HttpRequest, pk: int) -> HttpResponse:
    """Take back an approval, leaving the contract awaiting one (TASK-UZK-067).

    The approval is undone, not the contract: it stays on Tuzilgan and can
    be decided again. Whoever may decide may undo - the one who approved it
    is often not the one at the desk when the mistake is noticed, and a
    button only its presser can use is one that cannot fix anything.

    The holders are told, because they were told it was approved and a
    correction nobody hears is how somebody goes on believing the first
    thing they were told.
    """
    contract = get_object_or_404(Contract, pk=pk)

    if not decides_on_contracts(request.user):
        raise PermissionDenied(
            f"{request.user} may not decide on {contract.shartnoma_raqami}."
        )

    if contract.undo_approval(by=request.user):
        record_edited(request.user, contract)
        tell_holders_of_decision(
            contract,
            by=request.user,
            kind=Notification.Kind.CONTRACT_APPROVAL_UNDONE,
        )
        messages.success(
            request,
            f"{contract.shartnoma_raqami} tasdig`i bekor qilindi, shartnoma "
            "yana qarorni kutmoqda.",
        )
    else:
        messages.info(request, f"{contract.shartnoma_raqami} tasdiqlanmagan edi.")

    return redirect("xarid:tuzilgan")


def contract_naming_test(user: AbstractBaseUser) -> Callable[[Contract | None], bool]:
    """A test of whether this person may be told a given contract's number.

    Asked once per page rather than per row: may_open reads the person's user
    type, which is a query.

    Args:
        user: the person reading the page.

    Returns:
        A predicate over one contract, false for no contract at all.
    """
    openable = {
        page_name
        for page_name in set(PAGE_SHOWING_CONTRACT.values())
        if may_open(user, page_name)
    }

    return lambda contract: contract is not None and contract.page_showing in openable
