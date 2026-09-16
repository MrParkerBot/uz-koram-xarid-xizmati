"""The two application lists of sections 4.1 and 4.2.

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

from accounts.permissions import may_open
from accounts.roles import KATTA_MUTAXASIS, assignable_specialists, has_user_type
from applications.attachments import attachment_response
from applications.forms import ApplicationForm, ApplicationItemFormSet
from applications.models import Application, ApplicationItem
from reference.models import ArizaStatus

# The four columns one order line is made of, named once so the creation
# view and the line model cannot drift apart.
ORDER_LINE_FIELDS = (
    "mahsulot_turi",
    "buyurtma_nomi",
    "buyurtma_soni",
    "olchov_birligi",
)

INCOMING_TEMPLATE = "pages/kelib-arizalar.html"
ACCEPTED_TEMPLATE = "pages/qabul-arizalar.html"
ASSIGNED_TEMPLATE = "pages/tayinlangan.html"

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
        .select_related("department")
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
        .select_related("department", "assigned_to")
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
    own_work_only = has_user_type(request.user, (KATTA_MUTAXASIS,))

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
        },
    )


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
