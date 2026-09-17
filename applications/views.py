"""The application and contract pages of sections 4.1, 4.2, 4.6 and 4.9.

Lists with row actions and no form, which is why they do not use
MasterDataPage: that abstraction is a table beside a form, and these are
tables beside nothing.

The same record on two pages, told apart by its stage: Kelib tushgan shows
what has arrived and not been decided, Qabul qilingan shows what was accepted
and is waiting to be given to somebody.

Accept and Reject are the two decisions section 4.1 describes, and both are
wired (TASK-UZK-023, TASK-UZK-024). The filter bar the supplied page carries
is left inert; TASK-UZK-041 builds filtering for every table at once.
"""

from __future__ import annotations

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import F, Prefetch, QuerySet
from django.http import FileResponse, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.contract_editing import may_edit_contracts
from accounts.models import UserProfile
from accounts.permissions import may_open
from accounts.roles import (
    ADMIN,
    KATTA_MUTAXASIS,
    assignable_specialists,
    department_of,
    has_user_type,
)
from applications.attachments import attachment_response
from applications.forms import (
    SUGGESTED_UNITS,
    ApplicationForm,
    ApplicationItemFormSet,
    ContractForm,
    ContractItemFormSet,
    PurchaseApplicationForm,
    PurchaseApplicationItemFormSet,
)
from applications.models import (
    Application,
    ApplicationItem,
    Contract,
    ContractItem,
    ContractStatusChange,
    PurchaseApplication,
    PurchaseApplicationItem,
)
from applications.notifications import notify_admins_of_acceptance
from reference.models import ArizaStatus, ShartnomaStatus

# The four columns one order line is made of, named once so the creation
# view and the line model cannot drift apart.
ORDER_LINE_FIELDS = (
    "mahsulot_turi",
    "buyurtma_nomi",
    "buyurtma_soni",
    "olchov_birligi",
)

# A contract's row of goods. It shares three columns with an order line
# and has no category: REQ-SHARTNOMA-006 asks a supplier's price for a
# part number, not which of the department's categories it falls in.
CONTRACT_LINE_FIELDS = (
    "buyurtma_nomi",
    "part_number",
    "buyurtma_soni",
    "olchov_birligi",
    "narxi",
)

INCOMING_TEMPLATE = "pages/kelib-arizalar.html"
ACCEPTED_TEMPLATE = "pages/qabul-arizalar.html"
ASSIGNED_TEMPLATE = "pages/tayinlangan.html"
PURCHASE_TEMPLATE = "pages/xarid-ariza.html"
AGREED_CONTRACTS_TEMPLATE = "pages/kelishinlingan.html"
CREATED_CONTRACTS_TEMPLATE = "pages/tuzilgan.html"

# Which page shows an application at each stage. The attachment follows the
# record rather than the route: a PDF is downloadable by whoever may open the
# page the application is currently on, not by whoever may open the page it
# happened to be on when the link was written.
#
# DEC-015 is why that distinction has teeth. Direktor may open Kelib tushgan
# and may not open Qabul qilingan, so a download guarded by the incoming page
# alone would stay open to them after the application had left it. The stages
# TASK-UZK-023 to TASK-UZK-028 add belong here as they arrive.
PAGE_SHOWING_STAGE: dict[str, str] = {
    Application.Stage.INCOMING: "kelib-arizalar",
    Application.Stage.ACCEPTED: "qabul-arizalar",
    # Tayinlangan, and deliberately not qabul-arizalar although an assigned
    # application is still listed there. DEC-015 gives Katta Mutaxasis the
    # Tayinlangan page and not the Qabul qilingan one, so pointing an
    # assigned application at the accepted page would hand a specialist work
    # whose attachment they cannot open. Nobody loses by this: every type
    # that may open qabul-arizalar may open tayinlangan too.
    Application.Stage.ASSIGNED: "tayinlangan",
    # A rejected application is off the workflow, and TASK-UZK-024 left it
    # there: nothing in the specification lists rejected applications, so
    # there is no page to answer for one and its attachment stops being
    # reachable the moment it is rejected. Deliberate, and tested, so that
    # whichever task adds a rejected list has to decide this rather than
    # inherit it.
}


def application_lines() -> Prefetch:
    """The order lines of an application, with the category each names.

    Both lists render one row per line, so both fetch the lines the same way:
    one query for every application's lines and one join for their categories,
    rather than two queries per row.
    """
    return Prefetch(
        "items",
        queryset=ApplicationItem.objects.select_related("mahsulot_turi"),
    )


def incoming_applications() -> QuerySet[Application]:
    """The applications still waiting to be accepted or rejected.

    Filtered on the stage code rather than on an Ariza Status name, because
    DEC-017 lets an administrator rename or delete any status row and this
    list would then quietly empty.
    """
    return (
        Application.objects.filter(stage=Application.Stage.INCOMING)
        .select_related("department")
        .prefetch_related(application_lines())
    )


def accepted_applications() -> QuerySet[Application]:
    """The applications on the Qabul qilingan page: accepted, and assigned.

    Assigned ones stay rather than leaving, because REQ-ARIZA-007 puts
    re-assignment on this row: the specialist's name replaces the chooser and
    a Qayta tayinlash control replaces the Tayinlash button. A list that
    dropped an application the moment it was given out would take the
    re-assignment control with it.

    Ordered by when they were accepted, newest first, rather than by when they
    arrived: this page is worked through in the order decisions were taken,
    and an application that sat in the incoming list for a week is new here on
    the day it is accepted.

    An accepted row with no acceptance date should not exist - accept() is the
    only thing that writes this stage and it always stamps the date - but the
    ordering says what happens to one anyway, because the alternative is a
    silent answer that differs by database. nulls_last puts it at the bottom
    rather than above every application that has a real date, which is where
    SQLite would otherwise sort it, and the arrival date is the fallback the
    #29 review pointed out this function claimed and did not have.
    """
    return (
        Application.objects.filter(
            stage__in=(Application.Stage.ACCEPTED, Application.Stage.ASSIGNED)
        )
        # accepted_by is deliberately not selected: nothing on this page
        # renders the acceptor, so joining auth_user would fetch a password
        # hash per row for a column that does not exist. assigned_to is
        # selected because the row does render that name, which is the
        # difference between the two.
        .select_related("department", "assigned_to")
        .prefetch_related(application_lines())
        .order_by(
            F("qabul_qilingan_sana").desc(nulls_last=True),
            "-kelib_tushgan_sana",
            "-id",
        )
    )


def assigned_applications(specialist) -> QuerySet[Application]:
    """The applications one specialist has been given (REQ-ARIZA-007).

    What the Tayinlangan Arizalar page lists. That page is TASK-UZK-028 and
    is still the prototype, so this is written and tested here and rendered
    there - the assignment is not finished if nothing can read it back.

    Filtered on assigned_to rather than on the stage alone, because the stage
    says somebody has it and this asks who.
    """
    return (
        Application.objects.filter(
            stage=Application.Stage.ASSIGNED, assigned_to=specialist
        )
        # status is joined because the Holat column renders its name. The
        # #38 review found it fetched one query per row - the #29 finding in
        # the other direction, a column rendered with no join rather than a
        # join for a column nothing renders. assigned_to is still left out:
        # this page has no holder column, and the discipline is to join what
        # is rendered and nothing else.
        .select_related("department", "status")
        .prefetch_related(application_lines())
        .order_by(F("tayinlangan_sana").desc(nulls_last=True), "-id")
    )


def all_assigned_applications() -> QuerySet[Application]:
    """Every application somebody is working on, whoever that is.

    What the people who hand work out see on the Tayinlangan page. A
    specialist gets assigned_applications() instead, which is their own.

    assigned_to is joined because this list renders that name; the specialist
    view does not, which is why the two queries are not one with a flag.
    """
    return (
        Application.objects.filter(stage=Application.Stage.ASSIGNED)
        # status for the Holat column, assigned_to for the holder column.
        # Both are rendered on this page, and nothing else is joined.
        .select_related("department", "assigned_to", "status")
        .prefetch_related(application_lines())
        .order_by(F("tayinlangan_sana").desc(nulls_last=True), "-id")
    )


def incoming_list(request: HttpRequest) -> HttpResponse:
    """The table of applications that have arrived and not been decided."""
    return render(
        request,
        INCOMING_TEMPLATE,
        {"applications": incoming_applications()},
    )


def accepted_list(request: HttpRequest) -> HttpResponse:
    """The Qabul qilingan Arizalar table (REQ-ARIZA-006).

    Every column the specification names, including Qabul qilingan sana -
    which is the date acceptance happened, not the date the application
    arrived. The two are different and the page that confuses them is the one
    that makes the department head wonder why nothing was decided for a week.

    Tayinlangan xodim and the assignment controls are on every row and do
    nothing yet: TASK-UZK-027 wires them. Rendered visibly waiting rather than
    hidden, the way TASK-UZK-022 left the filter bar.

    The page also carries the TASK-UZK-026 creation form, empty. A bound one
    arrives here from application_create() when what somebody submitted did
    not validate, which is why the form is a parameter rather than something
    this function makes.
    """
    return render(request, ACCEPTED_TEMPLATE, accepted_page())


def accepted_page(
    form: ApplicationForm | None = None,
    items: ApplicationItemFormSet | None = None,
) -> dict[str, object]:
    """Everything the Qabul qilingan page renders.

    One function, so that a failed creation re-renders the same page the
    person was looking at rather than a stripped version of it. An unbound
    form is built when none is passed, which is the ordinary GET.

    Args:
        form: the bound application form to re-render with its errors.
        items: the bound order lines, likewise.
    """
    return {
        "applications": accepted_applications(),
        "form": form if form is not None else ApplicationForm(),
        "item_formset": (
            items
            if items is not None
            else ApplicationItemFormSet(queryset=ApplicationItem.objects.none())
        ),
        # The modal starts open only when there is something in it to correct,
        # so a refused submission comes back with what was typed still in it
        # rather than behind a closed modal.
        "open_form": form is not None,
        # The people an application may be given to (DEC-024). One query for
        # the page rather than one per row: the same list is rendered in
        # every unassigned row's chooser.
        "specialists": assignable_specialists(),
    }


def ordered_lines(items: ApplicationItemFormSet) -> list[dict[str, object]]:
    """The order lines somebody actually filled in, in the order they gave.

    A formset always carries at least one spare row - that is what the plus
    button clones - and a spare nobody typed into is not an order. Those come
    back with empty cleaned_data and are dropped here.

    Only the four order-line fields are taken. A model formset also puts a
    hidden id on every form, and passing that through to a new line would be
    handing the database a primary key from a form.
    """
    return [
        {field: line.cleaned_data[field] for field in ORDER_LINE_FIELDS}
        for line in items.forms
        if line.cleaned_data
    ]


@require_POST
def application_create(request: HttpRequest) -> HttpResponse:
    """Create an application and its order lines (REQ-ARIZA-008 to 011).

    POST only, and wrapped by the URL configuration in the qabul-arizalar
    permission, because that is the page offering the form.

    Everything is written inside one transaction, or nothing is. An
    application whose lines failed half way through is an order nobody can
    fill, and an application saved without the attachment REQ-ARIZA-009
    demands is one nobody can check - so the record, its lines and the file
    are one write.

    The application is created already accepted. The form is on the Qabul
    qilingan page and its button is Yaratish va Tayinlash: what it produces is
    something ready to be given to a specialist, not something waiting to be
    decided on a page it was never on. Recorded in the plan as the reading to
    challenge if it is wrong.

    Cancel is not a route. It closes the form in the browser, and because
    nothing is written until this view runs, there is nothing for it to undo.
    """
    form = ApplicationForm(request.POST, request.FILES)
    items = ApplicationItemFormSet(
        request.POST, queryset=ApplicationItem.objects.none()
    )

    if not (form.is_valid() and items.is_valid()):
        messages.error(request, "Ariza yaratilmadi: formani tekshiring.")
        return render(
            request,
            ACCEPTED_TEMPLATE,
            accepted_page(form=form, items=items),
        )

    with transaction.atomic():
        # The status is found by its code rather than its name, for the reason
        # accept() gives: DEC-017 lets an administrator rename these rows, and
        # a creation that fails because somebody renamed a status is a master
        # data page breaking the department's work.
        application = Application.raise_application(
            items=ordered_lines(items),
            department=form.cleaned_data["department"],
            buyurtmachi_ismi=form.cleaned_data["buyurtmachi_ismi"],
            izoh=form.cleaned_data["izoh"],
            pdf=form.cleaned_data["pdf"],
            stage=Application.Stage.ACCEPTED,
            qabul_qilingan_sana=timezone.now(),
            accepted_by=request.user,
            status=ArizaStatus.objects.filter(
                code=ArizaStatus.Code.ACCEPTED, is_active=True
            ).first(),
        )

    messages.success(request, f"{application.ariza_raqami} yaratildi.")

    return redirect("qabul-arizalar")


def assigned_list(request: HttpRequest) -> HttpResponse:
    """The Tayinlangan Arizalar page (REQ-ARIZA-012).

    Whose work it shows depends on who is looking, and that is the one
    decision this page makes. A Katta Mutaxasis sees the applications
    assigned to them and nobody else's - work somebody else was given is not
    theirs to see. Everybody else DEC-015 lets in here is a person who hands
    work out, and they see all of it, because where the work went is the
    question this page answers for them.

    The specialist's own list does not render the Tayinlangan xodim column: a
    column saying their own name on every row is a column that tells them
    nothing.

    Accept and Holat are on every row and do nothing yet - TASK-UZK-029 wires
    them. Rendered visibly waiting, the way TASK-UZK-022 left the filter bar.
    """
    own_work_only = acts_on_own_work_only(request.user)

    return render(
        request,
        ASSIGNED_TEMPLATE,
        {
            "applications": (
                assigned_applications(request.user)
                if own_work_only
                else all_assigned_applications()
            ),
            "shows_the_holder": not own_work_only,
            # DEC-017 lets an administrator retire a status. The drop-down
            # offers what is in use now; a row an application already holds
            # keeps rendering whether or not it is still offered.
            "statuses": ArizaStatus.objects.filter(is_active=True),
        },
    )


def acts_on_own_work_only(user) -> bool:
    """Whether this person may only touch the applications they hold.

    A Katta Mutaxasis may. Everybody else DEC-015 lets onto the Tayinlangan
    page hands work out and may touch all of it. One function, so that what
    the page shows and what the page may do cannot drift apart - which they
    would the first time one of them was changed and the other was not.
    """
    return has_user_type(user, (KATTA_MUTAXASIS,))


def held_application(request: HttpRequest, pk: int) -> Application:
    """The application this request may act on, or a refusal.

    Raises:
        PermissionDenied: when a specialist reaches for work that is not
            theirs. They may open the page, so this is about the row rather
            than about the page, which is why it is not the URL wrapper
            answering.
        Http404: when there is no such application.
    """
    application = get_object_or_404(Application, pk=pk)

    if (
        acts_on_own_work_only(request.user)
        and application.assigned_to_id != request.user.pk
    ):
        raise PermissionDenied(
            f"{request.user} does not hold {application.ariza_raqami}."
        )

    return application


@require_POST
def accept_assigned_application(request: HttpRequest, pk: int) -> HttpResponse:
    """The holder takes the work assigned to them (REQ-ARIZA-013).

    POST only, under the permission of the page offering the button. The
    acceptance is recorded against the holder rather than against whoever
    pressed it: a manager accepting on a specialist's behalf records that the
    specialist took it, because that is what the record is for.

    Accepting tells Admin, which is the second half of REQ-ARIZA-013. The
    notification is produced inside the same transaction as the acceptance,
    so there is never an acceptance nobody was told about, nor a notification
    about an acceptance that did not happen.
    """
    application = held_application(request, pk)

    try:
        with transaction.atomic():
            taken = application.accept_as_specialist(
                by=application.assigned_to
            )
            if taken:
                notify_admins_of_acceptance(application)
    except ValueError:
        messages.error(
            request,
            f"{application.ariza_raqami} qabul qilinmadi: ariza tayinlanmagan.",
        )
        return redirect("tayinlangan")

    if taken:
        messages.success(
            request, f"{application.ariza_raqami} qabul qilindi."
        )
    else:
        messages.info(
            request, f"{application.ariza_raqami} allaqachon qabul qilingan."
        )

    return redirect("tayinlangan")


@require_POST
def set_application_status(request: HttpRequest, pk: int) -> HttpResponse:
    """Mark the state an application is currently in (REQ-ARIZA-013).

    The status is looked up among the active rows only, so a retired one
    cannot be chosen by a request that did not come from the drop-down. A
    choice that is not a number is nobody's status rather than a crash - the
    #35 review found that shape on the assignment route.
    """
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
        # Two refusals, and being told the wrong one sends whoever
        # investigates somewhere unrelated - the point the #28 review made
        # about rejection.
        if application.stage != Application.Stage.ASSIGNED:
            messages.error(
                request,
                f"{application.ariza_raqami} holati o`zgartirilmadi: ariza "
                "tayinlanmagan.",
            )
        else:
            messages.error(
                request,
                f"{application.ariza_raqami} holati o`zgartirilmadi: holat "
                "tanlanishi shart.",
            )

        return redirect("tayinlangan")

    if changed:
        messages.success(
            request,
            f"{application.ariza_raqami} holati: {status.name}.",
        )
    else:
        messages.info(
            request,
            f"{application.ariza_raqami} allaqachon shu holatda.",
        )

    return redirect("tayinlangan")


def application_pdf(request: HttpRequest, pk: int) -> FileResponse:
    """Download one application's PDF (DEC-019).

    The file lives outside anything published and has no URL of its own, so
    this view is the only way to it. It asks the permission matrix about the
    page that currently shows the application, so the attachment stops being
    reachable at the same moment the row stops being visible.

    Raises:
        PermissionDenied: when the caller may not open the page this
            application is on, or the application is at a stage no page shows.
        Http404: when the application does not exist or has no attachment.
    """
    application = get_object_or_404(Application, pk=pk)

    page_name = PAGE_SHOWING_STAGE.get(application.stage)
    if page_name is None or not may_open(request.user, page_name):
        raise PermissionDenied(
            f"{request.user} may not see {application.ariza_raqami}."
        )

    return attachment_response(
        application.pdf, f"{application.ariza_raqami}.pdf"
    )


@require_POST
def accept_application(request: HttpRequest, pk: int) -> HttpResponse:
    """Accept one incoming application (REQ-ARIZA-004).

    POST only, and wrapped by the URL configuration in the permission of the
    page that offers the button, so an application cannot be accepted by
    somebody who may not see it.

    The second click of a double click is not an error: the record says it was
    already accepted and the page says so too, rather than accepting it twice
    or showing a crash.

    Nor is a page that went stale. Somebody who opens the list, goes to lunch
    and comes back to click Qabul on an application a colleague rejected in
    the meantime had the permission they needed - what changed is the
    application. They are told that and sent back to a list that now shows the
    truth, rather than shown a Forbidden page that sends whoever investigates
    to the permission matrix for something that has nothing to do with it.
    """
    application = get_object_or_404(Application, pk=pk)

    try:
        accepted = application.accept(by=request.user)
    except ValueError:
        messages.error(
            request,
            f"{application.ariza_raqami} qabul qilinmadi: ariza allaqachon "
            "hal qilingan.",
        )
        return redirect("kelib-arizalar")

    if accepted:
        messages.success(
            request, f"{application.ariza_raqami} qabul qilindi."
        )
    else:
        messages.info(
            request, f"{application.ariza_raqami} allaqachon qabul qilingan."
        )

    return redirect("kelib-arizalar")


@require_POST
def reject_application(request: HttpRequest, pk: int) -> HttpResponse:
    """Reject one incoming application, with a reason (REQ-ARIZA-005).

    The comment is what the sender is told, so a rejection without one is
    refused rather than recorded empty - and refused here as well as in the
    browser, because a required attribute is a convenience and not a rule.

    POST only, and wrapped by the URL configuration in the permission of the
    page that offers the button.
    """
    application = get_object_or_404(Application, pk=pk)

    try:
        rejected = application.reject(
            by=request.user, comment=request.POST.get("inkor_izohi", "")
        )
    except ValueError:
        if not application.is_incoming:
            # A decision was taken on this application by somebody else while
            # the page sat open. Reported the way accept_application reports
            # it, and for the reason the #26 review gave: the caller had the
            # permission they needed, and what changed is the application.
            messages.error(
                request,
                f"{application.ariza_raqami} inkor etilmadi: ariza "
                "allaqachon hal qilingan.",
            )
        else:
            messages.error(
                request,
                f"{application.ariza_raqami} inkor etilmadi: izoh "
                "kiritilishi shart.",
            )

        return redirect("kelib-arizalar")

    if rejected:
        messages.success(
            request, f"{application.ariza_raqami} inkor etildi."
        )
    else:
        messages.info(
            request, f"{application.ariza_raqami} allaqachon inkor etilgan."
        )

    return redirect("kelib-arizalar")


def chosen_specialist(chosen: str | None):
    """The specialist a submitted choice names, or None when it names none.

    The lookup is by primary key, and a primary key lookup coerces what it is
    given: handing it a value that is not a number raises out of the ORM and
    the request answers 500. The #35 review found that, and the fix is here
    rather than at the call site because "what did they choose" is one
    question with one answer - somebody, or nobody.

    Anything that is not a number is nobody. So is a number naming an account
    that is not a Katta Mutaxasis, or one that has left: the chooser only
    ever offers specialists, so a request naming anybody else did not come
    from it.

    Args:
        chosen: the raw form value, which may be absent, empty or nonsense.

    Returns:
        The user, or None.
    """
    if not chosen or not chosen.isdigit():
        return None

    return assignable_specialists().filter(pk=int(chosen)).first()


@require_POST
def assign_application(request: HttpRequest, pk: int) -> HttpResponse:
    """Give one accepted application to a specialist (REQ-ARIZA-007).

    POST only, and wrapped by the URL configuration in the permission of the
    page offering the control, so an application cannot be given out by
    somebody who may not see it.

    The same route does assignment and re-assignment. DEC-024 makes them the
    same act - Admin may move an application at any time, including after the
    specialist accepted it - and a separate route would only be the same code
    with a different name on it.

    A page that went stale is reported the way accept_application reports one:
    the caller had the permission they needed, and what changed is the
    application.
    """
    application = get_object_or_404(Application, pk=pk)
    specialist = chosen_specialist(request.POST.get("xodim"))

    try:
        assigned = application.assign(by=request.user, specialist=specialist)
    except ValueError:
        if specialist is None:
            # Either nothing was chosen, or what was chosen is not somebody
            # this application may be given to. The two are one message: the
            # chooser only ever offers specialists, so a request naming
            # anybody else did not come from it.
            messages.error(
                request,
                f"{application.ariza_raqami} tayinlanmadi: Katta Mutaxasis "
                "tanlanishi shart.",
            )
        else:
            messages.error(
                request,
                f"{application.ariza_raqami} tayinlanmadi: ariza qabul "
                "qilinmagan.",
            )

        return redirect("qabul-arizalar")

    if assigned:
        name = specialist.get_full_name() or specialist.username
        messages.success(
            request, f"{application.ariza_raqami} {name}ga tayinlandi."
        )
    else:
        messages.info(
            request,
            f"{application.ariza_raqami} allaqachon shu xodimga tayinlangan.",
        )

    return redirect("qabul-arizalar")


def agreed_contracts() -> QuerySet[Contract]:
    """The contracts on the Kelishinlingan Shartnoma page (REQ-SHARTNOMA-004).

    Agreed contracts and rejected ones. A rejected contract belongs here
    because DEC-024 says it is corrected and resent - it needs somewhere a
    person can see it and act on it, and this is the page carrying its
    rejection comment as a column. The #48 review found the query filtering to
    the agreed stage alone, which made REQ-SHARTNOMA-004's Izoh column
    permanently empty and left TASK-UZK-038's Re-Send control no row to live
    on.

    Filtered on the stage code rather than on a ShartnomaStatus name, for the
    reason every list here gives: DEC-010 makes the statuses examples the
    department extends, so a list reading one quietly empties the day
    somebody retires it.

    Everything the row renders is joined and nothing else. The application and
    its department for the first two columns, the supplier for Firma nomi, the
    status for Holati, and the person who made it for Kim shartnoma qilgan.

    Buyurtma nomi comes from the contract's own goods rows since
    TASK-UZK-035. It borrowed the application's lines while a contract had
    none, and that stopped being right the moment Shartnoma qiymati became
    the total of the contract's rows: a row listing what the department
    asked for beside a value covering what the supplier agreed to would
    read as one statement and be two.
    """
    return (
        Contract.objects.filter(
            stage__in=(Contract.Stage.AGREED, Contract.Stage.REJECTED)
        )
        .select_related(
            "application",
            "application__department",
            "supplier",
            "status",
            "created_by",
        )
        .prefetch_related(contract_lines(), contract_status_history())
    )


def contract_lines() -> Prefetch:
    """The goods rows of a contract, in the order they were entered."""
    return Prefetch("items", queryset=ContractItem.objects.all())


def contract_status_history() -> Prefetch:
    """Every move each listed contract has made, newest first.

    All of them rather than the last one, because a per-row slice is a query
    per row - the cost the review of #38 found on a list page. The page reads
    only the first through Contract.last_status_change, and a contract that
    has moved a dozen times is a dozen small rows in one query.
    """
    return Prefetch(
        "status_changes",
        queryset=ContractStatusChange.objects.select_related(
            "to_status", "changed_by"
        ),
    )


def contractable_applications(user) -> QuerySet[Application]:
    """The applications a contract may be agreed against (REQ-ROLE-007).

    Assigned ones, because a contract is formed on the basis of an application
    somebody is working on: one still sitting in Kelib tushgan has not been
    accepted by the department, and a rejected one is off the workflow
    entirely.

    Narrowed further for a Katta Mutaxasis, who forms a contract on the basis
    of the application assigned to them. acts_on_own_work_only() is the same
    question the Tayinlangan page asks about its rows, asked once so that what
    a specialist may act on there and what they may contract against here
    cannot drift apart.

    The department and the order lines are fetched because
    ApplicationChoiceField renders both in the drop-down label. The review of
    #52 found the join here already and nothing reading it, which is a query
    paying for a column nobody rendered.
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
    user,
    form: ContractForm | None = None,
    items: ContractItemFormSet | None = None,
    editing: Contract | None = None,
) -> dict[str, object]:
    """Everything the Kelishinlingan Shartnoma page renders.

    The user is passed in rather than the request, because the only thing this
    needs from a request is who is asking - and taking the whole request would
    invite the next reader to reach for something else on it.
    """
    return {
        "contracts": agreed_contracts(),
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
        "editing": editing,
        "statuses": ShartnomaStatus.objects.active(),
        # DEC-021's lock, so the page can render Tahrir disabled rather than
        # hidden. A control that is simply absent looks like a page that is
        # broken; one that says what is missing tells a specialist to ask
        # Admin.
        "may_edit": may_edit_contracts(user),
        "suggested_units": SUGGESTED_UNITS,
    }


def agreed_contracts_list(request: HttpRequest) -> HttpResponse:
    """The Kelishinlingan Shartnoma table and the form that adds to it.

    View and Send are on the page and do nothing yet - TASK-UZK-037 and
    TASK-UZK-038 build them. Rendered visibly waiting rather than hidden, the
    way every page here has left a control that belongs to a later task.
    """
    return render(
        request, AGREED_CONTRACTS_TEMPLATE, contract_page(request.user)
    )


@require_POST
def set_contract_status(request: HttpRequest, pk: int) -> HttpResponse:
    """Move a contract to a status (REQ-ROLE-008, REQ-SHTSTATUS-001).

    POST only, under the permission of the page carrying the control. The
    status is looked up among the active rows only, so a retired one cannot
    be chosen by a request that did not come from the drop-down, and a choice
    that is not a number is nobody's status rather than a crash - the shape
    the review of #35 established on the assignment route.

    Each refusal says which refusal it was. Being told the wrong one sends
    whoever investigates somewhere unrelated, which is the point the review of
    #28 made about rejection.

    Whose contract it is, is held_contract()'s question rather than this one's
    - the same separation the Tayinlangan page makes between the page and the
    row.

    Two pages carry this control since the review of #62 separated reporting a
    contract's progress from changing its terms: Kelishinlingan while it is
    still the specialist's, and Tuzilgan once it is signed. So the redirect
    reads the page the contract is on rather than naming one.
    """
    contract = held_contract(request, pk)
    chosen = request.POST.get("status")
    status = (
        ShartnomaStatus.objects.filter(pk=int(chosen), is_active=True).first()
        if chosen and chosen.isdigit()
        else None
    )

    back = contract.page_showing or "kelishinlingan"

    try:
        moved = contract.set_status(status, request.user)
    except ValueError:
        if not contract.status_may_move:
            messages.error(
                request,
                f"{contract.shartnoma_raqami} holati o`zgartirilmadi: "
                "shartnoma tasdiqlashga yuborilgan.",
            )
        else:
            messages.error(
                request,
                f"{contract.shartnoma_raqami} holati o`zgartirilmadi: "
                "holat tanlanishi shart.",
            )

        return redirect(back)

    if moved:
        messages.success(
            request,
            f"{contract.shartnoma_raqami} holati: {contract.status.name}.",
        )
    else:
        messages.info(
            request,
            f"{contract.shartnoma_raqami} allaqachon shu holatda.",
        )

    return redirect(back)


@require_POST
def send_contract_for_approval(
    request: HttpRequest, pk: int
) -> HttpResponse:
    """Send a contract to the department head (REQ-SHARTNOMA-005).

    POST only, under the permission of the page carrying the button, and
    through held_contract() so a specialist sends their own.

    The contract leaves this page when it is sent, because this page is the
    contracts still theirs to work on. That is abrupt if nobody says so, which
    is why the message names where it went rather than only that it went.

    That message names Tuzilgan Shartnomalar, and TASK-UZK-039 is what makes
    that page show a real contract - until it does, somebody following the
    sentence finds the prototype's three rows. Recorded rather than softened,
    because the sentence is true of the record and the page is the next task;
    a vaguer message would be wrong for longer.
    """
    contract = held_contract(request, pk)

    try:
        sent = contract.send_for_approval(request.user)
    except ValueError:
        # Two stages refuse a send and they are different facts. Telling
        # somebody an approved contract is "already sent for approval" sends
        # whoever they ask about it looking for an approval queue the contract
        # left days ago - the point the review of #28 made about rejection,
        # found here by the review of #60.
        messages.error(
            request,
            f"{contract.shartnoma_raqami} yuborilmadi: "
            + (
                "shartnoma allaqachon tasdiqlashga yuborilgan."
                if contract.is_sent
                else "shartnoma allaqachon tasdiqlangan."
            ),
        )

        return redirect("kelishinlingan")

    if sent:
        messages.success(
            request,
            f"{contract.shartnoma_raqami} tasdiqlashga yuborildi va "
            "Tuzilgan Shartnomalar sahifasiga o`tdi.",
        )
    else:
        messages.info(
            request,
            f"{contract.shartnoma_raqami} allaqachon tasdiqlashga "
            "yuborilgan.",
        )

    return redirect("kelishinlingan")


def contract_pdf(request: HttpRequest, pk: int) -> FileResponse:
    """Download one contract's PDF (DEC-019).

    The file lives outside anything published and has no URL of its own, so
    this view is the only way to it. It asks the permission matrix about the
    page the contract is currently on, the way application_pdf() does and for
    the same reason: the attachment stops being reachable at the same moment
    the row stops being visible.

    Raises:
        PermissionDenied: when the caller may not open the page this contract
            is on, or the contract is at a stage no page shows.
        Http404: when the contract does not exist or has no attachment - which
            REQ-SHARTNOMA-003 says cannot happen, and a 404 is the honest
            answer if it somehow has.
    """
    contract = get_object_or_404(Contract, pk=pk)

    page_name = contract.page_showing
    if page_name is None or not may_open(request.user, page_name):
        raise PermissionDenied(
            f"{request.user} may not see {contract.shartnoma_raqami}."
        )

    return attachment_response(
        contract.pdf, f"{contract.shartnoma_raqami}.pdf"
    )


def held_contract(request: HttpRequest, pk: int) -> Contract:
    """The contract this request may act on, or a refusal.

    The row-level question the Tayinlangan page asks about an application,
    asked here about a contract. REQ-ROLE-008 has the specialist keep changing
    the state of the contracts they formed, and TASK-UZK-035 already narrowed
    which applications each of them may contract against - so without this the
    rule holds on the way in and disappears afterwards, which is what the
    review of #56 found.

    A contract is a specialist's when the application it fulfils is assigned
    to them, rather than when they created it: DEC-024 lets Admin re-assign an
    application at any time, and the contract goes with the work rather than
    staying with whoever first typed it.

    Raises:
        PermissionDenied: when a specialist reaches for a contract that is not
            theirs. They may open the page, so this is about the row rather
            than the page.
        Http404: when there is no such contract.
    """
    contract = get_object_or_404(
        Contract.objects.select_related("application"), pk=pk
    )

    if (
        acts_on_own_work_only(request.user)
        and contract.application.assigned_to_id != request.user.pk
    ):
        raise PermissionDenied(
            f"{request.user} does not hold {contract.shartnoma_raqami}."
        )

    return contract


def contract_has_moved_on(
    request: HttpRequest, contract: Contract
) -> HttpResponse | None:
    """The refusal a contract that has left this page earns, or None.

    One answer for every route guarding that rule, which the review of #56
    asked for: the edit form used to answer 404 while the status control
    answered with a message, and two answers for one rule is one too many.

    The message rather than the 404, because the case that actually happens is
    a race - somebody sent the contract for approval while this page was open -
    and a person who has just been told their change was not saved needs to
    know why, which a 404 does not say.
    """
    if contract.is_editable:
        return None

    messages.error(
        request,
        f"{contract.shartnoma_raqami} o`zgartirilmadi: shartnoma "
        "tasdiqlashga yuborilgan.",
    )

    return redirect("kelishinlingan")


def contract_edit(request: HttpRequest, pk: int) -> HttpResponse:
    """Open the entry form filled in (REQ-SHARTNOMA-005).

    The same form, the same modal and the same rows - which is what the
    document asks for, and is why this is a state of the Kelishinlingan page
    rather than a page of its own.

    REQ-SHARTNOMA-005 opens it "if the user has permission for this", and
    DEC-021 makes that an exclusive lock one person holds. TASK-UZK-040 put
    require_contract_editing on this route, beside the page permission:
    whether somebody may open Kelishinlingan and whether they are the one
    person who may edit a contract on it are different questions, and
    held_contract() below asks a third - whose contract this is.
    """
    contract = held_contract(request, pk)
    moved_on = contract_has_moved_on(request, contract)
    if moved_on is not None:
        return moved_on

    return render(
        request,
        AGREED_CONTRACTS_TEMPLATE,
        contract_page(
            request.user,
            form=ContractForm(
                instance=contract,
                applications=contractable_applications(request.user),
            ),
            items=ContractItemFormSet(queryset=contract.items.all()),
            editing=contract,
        ),
    )


@require_POST
def contract_update(request: HttpRequest, pk: int) -> HttpResponse:
    """Save an edited contract (REQ-SHARTNOMA-005, REQ-SHARTNOMA-003).

    The rows are replaced rather than merged, and the contract value is
    recomputed from whatever is left - both inside Contract.revise(), so that
    a contract's total cannot end up disagreeing with what is on it.

    The attachment is kept when nothing new is uploaded and replaced when
    something is. Neither is a branch here: the form field is required and
    Django hands back the stored file when the upload is empty, so an edit
    that would leave the contract without one is refused by the same rule
    that refuses an entry without one.
    """
    contract = held_contract(request, pk)
    moved_on = contract_has_moved_on(request, contract)
    if moved_on is not None:
        return moved_on

    form = ContractForm(
        request.POST,
        request.FILES,
        instance=contract,
        applications=contractable_applications(request.user),
    )
    items = ContractItemFormSet(request.POST, queryset=contract.items.all())

    if not (form.is_valid() and items.is_valid()):
        messages.error(request, "Shartnoma saqlanmadi: formani tekshiring.")
        return render(
            request,
            AGREED_CONTRACTS_TEMPLATE,
            contract_page(
                request.user, form=form, items=items, editing=contract
            ),
        )

    contract.revise(
        items=contract_rows(items),
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

    messages.success(
        request,
        f"{contract.shartnoma_raqami} saqlandi. "
        f"Shartnoma qiymati: {contract.qiymati_display} UZS.",
    )

    return redirect("kelishinlingan")


def contract_rows(items: ContractItemFormSet) -> list[dict[str, object]]:
    """The goods rows a valid entry form describes, in the order entered.

    The same shape ordered_lines() produces for an application: mappings
    rather than saved objects, because raise_contract() totals them before the
    contract they belong to exists.
    """
    return [
        {field: row.cleaned_data[field] for field in CONTRACT_LINE_FIELDS}
        for row in items.forms
        if row.cleaned_data
    ]


@require_POST
def contract_create(request: HttpRequest) -> HttpResponse:
    """Enter a contract and its goods rows (REQ-SHARTNOMA-006).

    POST only, under the permission of the page offering the form. Create
    stores the contract with every row in one transaction; Cancel is a button
    in the browser that closes the window, so there is nothing here for it to
    reach - which is REQ-SHARTNOMA-007's "no data is saved", enforced by there
    being no route rather than by a route that does nothing.

    Shartnoma qiymati is not read from the form even if one is posted.
    raise_contract() computes it from the rows, which is what makes the value
    the total of everything rather than a number somebody typed beside a
    different set of numbers.

    The columns are named one by one rather than gathered from the form. The
    review of #52 found a comprehension over Meta.fields here, which is
    correct until somebody declares a field on the form without listing it
    there - and TASK-UZK-036 is about to add the attachment REQ-SHARTNOMA-003
    says a contract must not be stored without.
    """
    applications = contractable_applications(request.user)
    form = ContractForm(
        request.POST, request.FILES, applications=applications
    )
    items = ContractItemFormSet(
        request.POST, queryset=ContractItem.objects.none()
    )

    if not (form.is_valid() and items.is_valid()):
        messages.error(request, "Shartnoma yaratilmadi: formani tekshiring.")
        return render(
            request,
            AGREED_CONTRACTS_TEMPLATE,
            contract_page(request.user, form=form, items=items),
        )

    with transaction.atomic():
        contract = Contract.raise_contract(
            items=contract_rows(items),
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

    messages.success(
        request,
        f"{contract.shartnoma_raqami} yaratildi. "
        f"Shartnoma qiymati: {contract.qiymati_display} UZS.",
    )

    return redirect("kelishinlingan")


def created_contracts() -> QuerySet[Contract]:
    """The contracts on the Tuzilgan Shartnomalar page (REQ-SHARTNOMA-001).

    The ones waiting for the department head, and the ones they have already
    approved. An approved contract stays rather than disappearing, because
    this is the only page on which anybody can see that it was approved - the
    prototype shows it the same way, with a badge instead of the two buttons.

    A rejected one is not here. It goes back to the specialist, which means
    back to the Kelishinlingan page, where REQ-SHARTNOMA-004 gives its comment
    a column and DEC-024 gives it a Re-Send control.

    Filtered on the stage code rather than on a ShartnomaStatus name, for the
    reason every list here gives: DEC-010 makes the statuses examples the
    department extends, so a list reading one quietly empties the day somebody
    retires it.
    """
    return (
        Contract.objects.filter(
            stage__in=(Contract.Stage.SENT, Contract.Stage.SIGNED)
        )
        .select_related(
            "application",
            "application__department",
            "supplier",
            "status",
            "created_by",
            "tasdiqlagan",
        )
        .prefetch_related(contract_lines(), contract_status_history())
    )


def may_decide_on_contracts(user) -> bool:
    """Whether this person is the department head REQ-SHARTNOMA-002 names.

    Four types may open this page and one of them decides. DEC-013 and the
    project context make Admin the Xarid bo`lim boshlig`i - the department
    head who receives contracts and approves them - so a page-level permission
    on its own would let a Menejer approve a contract that binds the company.

    The others are here to see what has been agreed, which is what
    REQ-SHARTNOMA-001 describes the page as.
    """
    return has_user_type(user, (ADMIN,))


def created_contracts_list(request: HttpRequest) -> HttpResponse:
    """The Tuzilgan Shartnomalar table (REQ-SHARTNOMA-001)."""
    return render(
        request,
        CREATED_CONTRACTS_TEMPLATE,
        {
            "contracts": created_contracts(),
            "may_decide": may_decide_on_contracts(request.user),
            "statuses": ShartnomaStatus.objects.active(),
        },
    )


def contract_awaiting_decision(request: HttpRequest, pk: int) -> Contract:
    """The contract this request may decide on, or a refusal.

    Raises:
        PermissionDenied: when the caller is not the department head. They may
            open the page, so this is about the action rather than the page -
            the same separation held_contract() makes about a row.
        Http404: when there is no such contract.
    """
    if not may_decide_on_contracts(request.user):
        raise PermissionDenied(
            f"{request.user} is not the department head, so they may not "
            "decide on a contract."
        )

    return get_object_or_404(Contract, pk=pk)


@require_POST
def accept_contract(request: HttpRequest, pk: int) -> HttpResponse:
    """Approve a contract (REQ-SHARTNOMA-002).

    REQ-SHARTNOMA-002 says an accepted contract is sent to the next
    department. DEC-028 says there is no such department: nothing is built for
    it, and the contract continues through the status chain TASK-UZK-037 gave
    it. The gap stays visible rather than being filled with an integration to
    an unnamed destination.
    """
    contract = contract_awaiting_decision(request, pk)

    try:
        approved = contract.accept(request.user)
    except ValueError:
        messages.error(
            request,
            f"{contract.shartnoma_raqami} tasdiqlanmadi: shartnoma "
            "tasdiqlashga yuborilmagan.",
        )

        return redirect("tuzilgan")

    if approved:
        messages.success(
            request, f"{contract.shartnoma_raqami} tasdiqlandi."
        )
    else:
        messages.info(
            request, f"{contract.shartnoma_raqami} allaqachon tasdiqlangan."
        )

    return redirect("tuzilgan")


@require_POST
def reject_contract(request: HttpRequest, pk: int) -> HttpResponse:
    """Send a contract back to its specialist, with a reason.

    The comment is the point of the action, so the page asks for it in a
    window rather than refusing afterwards - the shape the Kelib tushgan and
    Xarid Arizasi rejections use. This refuses an empty one anyway, because a
    page is one way in.
    """
    contract = contract_awaiting_decision(request, pk)

    try:
        rejected = contract.reject(
            request.user, request.POST.get("inkor_izohi", "")
        )
    except ValueError:
        # Two refusals, and being told the wrong one sends whoever
        # investigates somewhere unrelated - the point the review of #28 made.
        if not contract.awaits_approval:
            messages.error(
                request,
                f"{contract.shartnoma_raqami} inkor etilmadi: shartnoma "
                "tasdiqlashga yuborilmagan.",
            )
        else:
            messages.error(
                request,
                f"{contract.shartnoma_raqami} inkor etilmadi: izoh "
                "kiritilishi shart.",
            )

        return redirect("tuzilgan")

    if rejected:
        messages.success(
            request,
            f"{contract.shartnoma_raqami} inkor etildi va mutaxassisga "
            "qaytarildi.",
        )
    else:
        messages.info(
            request, f"{contract.shartnoma_raqami} allaqachon inkor etilgan."
        )

    return redirect("tuzilgan")


def purchase_applications() -> QuerySet[PurchaseApplication]:
    """Every purchase application, newest first (REQ-ARIZA-014).

    Not filtered by requester. USERS is the only type with this page and
    nothing says a requester sees only their own; the department's own people
    open it to see what has been asked for, and a list that hid most of it
    would be answering a different question. Recorded as an unknown on the
    plan rather than settled here.
    """
    return (
        PurchaseApplication.objects.select_related(
            "department", "status", "raised_application"
        )
        .prefetch_related(
            purchase_lines(),
            # REQ-ARIZA-017: the status shown is the contract's when there is
            # one, so the walk to it is part of the page rather than a query
            # per row. Two hops, and missing either would cost one query per
            # request on a page that has a test about exactly that.
            Prefetch(
                "raised_application__contracts",
                queryset=Contract.objects.select_related("status"),
            ),
        )
        .all()
    )


def purchase_lines() -> Prefetch:
    """The order lines of a purchase application, with their categories."""
    return Prefetch(
        "items",
        queryset=PurchaseApplicationItem.objects.select_related(
            "mahsulot_turi"
        ),
    )


def approvals_for(user) -> QuerySet[PurchaseApplication]:
    """The purchase requests waiting for this person to decide (DEC-016).

    A Bo`lim Boshlig`i sees the first step from their own department and
    nowhere else - own being the part that matters, because a department head
    approving another department's spending is what the chain exists to
    prevent. A Direktor sees the second step from anywhere. Everybody else
    sees none, including a requester looking at their own request.

    Built from the same rule PurchaseApplication.awaits() applies to one
    record, expressed as a filter rather than re-derived - so a change to who
    approves what cannot leave the queue and the action disagreeing.
    """
    from accounts.roles import BOLIM_BOSHLIGI, DIREKTOR, department_of

    waiting = PurchaseApplication.objects.select_related(
        "department", "status", "created_by"
    ).prefetch_related(purchase_lines())

    if has_user_type(user, (BOLIM_BOSHLIGI,)):
        department = department_of(user)
        if department is None:
            return waiting.none()

        return waiting.filter(
            stage=PurchaseApplication.Stage.AWAITING_HEAD,
            department=department,
        )

    if has_user_type(user, (DIREKTOR,)):
        return waiting.filter(
            stage=PurchaseApplication.Stage.AWAITING_DIREKTOR
        )

    return waiting.none()


def awaiting_approval(request: HttpRequest, pk: int) -> PurchaseApplication:
    """The request this person may decide, or a refusal.

    Two different refusals, and telling them apart is the point. Somebody who
    could never decide this request is denied. Somebody for whom it has simply
    moved on - a colleague got there first, or they double clicked - had the
    permission they needed, and what changed is the record. The #26 review
    settled that for accept_application, and the #44 review found this route
    answering Forbidden to both.

    Raises:
        PermissionDenied: when this person could not decide this request at
            any step - the wrong role, or another department's head.
        Http404: when there is no such request.
    """
    application = get_object_or_404(PurchaseApplication, pk=pk)

    if not (
        application.awaits(request.user) or application.moved_past(request.user)
    ):
        raise PermissionDenied(
            f"{application.xarid_raqami} is not {request.user} to decide."
        )

    # Either it is waiting for them, or it has moved while their page sat
    # open. The second is not a permission problem, so the view says what
    # happened and sends them back to a queue showing the truth.
    return application


@require_POST
def approve_purchase_application(
    request: HttpRequest, pk: int
) -> HttpResponse:
    """Take one request a step along the chain (REQ-ARIZA-016).

    POST only, under the permission of the page carrying the queue. Which
    step, and whether this person may take it, is the record's business
    rather than the view's.
    """
    application = awaiting_approval(request, pk)

    try:
        approved = application.approve(by=request.user)
    except ValueError:
        # Reachable only for a request that has moved on, because anybody who
        # could never decide it was refused above.
        messages.info(
            request,
            f"{application.xarid_raqami} allaqachon hal qilingan.",
        )
        return redirect("xarid-ariza")

    if approved and application.stage == PurchaseApplication.Stage.APPROVED:
        messages.success(
            request,
            f"{application.xarid_raqami} tasdiqlandi va "
            f"{application.raised_application.ariza_raqami} yaratildi.",
        )
    elif approved:
        messages.success(
            request,
            f"{application.xarid_raqami} tasdiqlandi va direktorga yuborildi.",
        )
    else:
        messages.info(
            request, f"{application.xarid_raqami} allaqachon tasdiqlangan."
        )

    return redirect("xarid-ariza")


@require_POST
def reject_purchase_application(
    request: HttpRequest, pk: int
) -> HttpResponse:
    """Refuse one request, with a reason (REQ-ARIZA-020)."""
    application = awaiting_approval(request, pk)

    try:
        rejected = application.reject(
            by=request.user, comment=request.POST.get("inkor_izohi", "")
        )
    except ValueError:
        if not application.awaits(request.user):
            # Either it has been decided, or it has moved to the next step
            # while this page sat open. Both are "not yours to decide now"
            # rather than "not yours ever".
            messages.info(
                request,
                f"{application.xarid_raqami} allaqachon hal qilingan.",
            )
        else:
            messages.error(
                request,
                f"{application.xarid_raqami} inkor etilmadi: izoh "
                "kiritilishi shart.",
            )

        return redirect("xarid-ariza")

    if rejected:
        messages.success(
            request, f"{application.xarid_raqami} inkor etildi."
        )
    else:
        messages.info(
            request, f"{application.xarid_raqami} allaqachon inkor etilgan."
        )

    return redirect("xarid-ariza")


def purchase_page(
    signed_in_department=None,
    approvals=None,
    form: PurchaseApplicationForm | None = None,
    items: PurchaseApplicationItemFormSet | None = None,
    user=None,
) -> dict[str, object]:
    """Everything the Xarid Arizasi page renders.

    The department is passed in rather than looked up here, because the view
    that writes has already asked - and asking twice is how the form comes to
    show one department while the record is written against another.
    """
    return {
        "applications": purchase_applications(),
        "signed_in_department": signed_in_department,
        "approvals": approvals,
        # Which contract pages this person may open. REQ-ARIZA-017 asks for
        # the status, and the row explains where the status came from - but
        # DEC-015 gives Users this page and no contract page at all, so the
        # explanation must not print a contract number to them. The status
        # itself is theirs to see; the contract's number is a fact from a page
        # they cannot open. Found by the review of #58.
        "visible_contract_pages": [
            page
            for page in ("kelishinlingan", "tuzilgan")
            if may_open(user, page)
        ],
        "form": form if form is not None else PurchaseApplicationForm(),
        "item_formset": (
            items
            if items is not None
            else PurchaseApplicationItemFormSet(
                queryset=PurchaseApplicationItem.objects.none()
            )
        ),
        "open_form": form is not None,
        "suggested_units": SUGGESTED_UNITS,
    }


def purchase_application_list(request: HttpRequest) -> HttpResponse:
    """The Xarid Arizasi table and the form that adds to it."""
    return render(
        request,
        PURCHASE_TEMPLATE,
        purchase_page(
            signed_in_department=department_of(request.user),
            approvals=approvals_for(request.user),
            user=request.user,
        ),
    )


def why_no_department(user) -> str:
    """Which of the two ways a requester can have no department to use.

    department_of() answers None for both - never assigned one, and assigned
    one an administrator has since retired - and the #42 review found the
    second being reported as the first. The remedies differ: somebody has to
    give them a department, or somebody has to bring the department back. A
    requester cannot do either, so the message is the whole of what they get
    and it has to name the right one.
    """
    profile = UserProfile.objects.filter(user=user).select_related(
        "department"
    ).first()
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

    POST only, under the permission of the page offering the form - which for
    a Users requester is the only page they have, so a refusal here is
    somebody who cannot do anything at all. Each one says what is wrong rather
    than only that something is.

    The department comes from the requester's own account (DEC-018) and is
    never read from the form. Somebody with no department is told to ask an
    administrator for one, because that is the actual remedy and they cannot
    apply it themselves.
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
                approvals_for(request.user),
                form=form,
                items=items,
                user=request.user,
            ),
        )

    if not (form.is_valid() and items.is_valid()):
        messages.error(
            request, "Xarid arizasi yaratilmadi: formani tekshiring."
        )
        return render(
            request,
            PURCHASE_TEMPLATE,
            purchase_page(
                department,
                approvals_for(request.user),
                form=form,
                items=items,
                user=request.user,
            ),
        )

    with transaction.atomic():
        application = PurchaseApplication.raise_purchase_application(
            items=ordered_lines(items),
            department=department,
            shartnoma_nomi=form.cleaned_data["shartnoma_nomi"],
            muddat_talabi=form.cleaned_data["muddat_talabi"],
            izoh=form.cleaned_data["izoh"],
            pdf=form.cleaned_data["pdf"],
            created_by=request.user,
            # Yangi, by its code rather than its name: DEC-017 lets an
            # administrator rename the row, and a request that could not be
            # raised because somebody renamed a status would be a master data
            # page breaking the department's work.
            status=ArizaStatus.objects.filter(
                code=ArizaStatus.Code.NEW, is_active=True
            ).first(),
        )

    messages.success(request, f"{application.xarid_raqami} yaratildi.")

    return redirect("xarid-ariza")


def purchase_application_pdf(request: HttpRequest, pk: int) -> FileResponse:
    """Download one purchase application's PDF (DEC-019).

    The permission is on the route rather than in here, which is the opposite
    of application_pdf() and deliberate: that one asks about the page showing
    the record's current stage, and a purchase application is on one page for
    its whole life. There is no PAGE_SHOWING_STAGE equivalent to consult, so
    require_page_permission('xarid-ariza') on the route is the whole rule.

    The #42 review found both a wrapper and an in-view check here. Two
    controls where one can never fail invites somebody to remove the one that
    matters.
    """
    application = get_object_or_404(PurchaseApplication, pk=pk)

    return attachment_response(
        application.pdf, f"{application.xarid_raqami}.pdf"
    )


def purchase_application_original_pdf(
    request: HttpRequest, pk: int
) -> FileResponse:
    """Download the attachment as it was uploaded, before any stamp.

    TASK-UZK-032 keeps the original when an approval rewrites the document,
    and the #46 review pointed out that nothing could produce it: DEC-019
    makes the download view the only way to a file, so a file with no view is
    a file nobody has. A stamped document is evidence, and evidence needs its
    original.

    Answers to the same permission as the stamped one, on the route. There is
    nothing more to decide here: anybody who may see the approved document may
    see what it was approved from.

    Raises:
        Http404: when there is no such application, or it has no original -
            which is every application that has not been approved, because
            until then pdf is the original.
    """
    application = get_object_or_404(PurchaseApplication, pk=pk)

    return attachment_response(
        application.asl_pdf, f"{application.xarid_raqami}-asl.pdf"
    )
