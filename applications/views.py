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
from django.db.models import QuerySet
from django.http import FileResponse, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.permissions import may_open
from applications.attachments import attachment_response
from applications.models import Application

INCOMING_TEMPLATE = "pages/kelib-arizalar.html"
ACCEPTED_TEMPLATE = "pages/qabul-arizalar.html"

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
    # A rejected application is off the workflow, and TASK-UZK-024 left it
    # there: nothing in the specification lists rejected applications, so
    # there is no page to answer for one and its attachment stops being
    # reachable the moment it is rejected. Deliberate, and tested, so that
    # whichever task adds a rejected list has to decide this rather than
    # inherit it.
}


def incoming_applications() -> QuerySet[Application]:
    """The applications still waiting to be accepted or rejected.

    Filtered on the stage code rather than on an Ariza Status name, because
    DEC-017 lets an administrator rename or delete any status row and this
    list would then quietly empty.
    """
    return Application.objects.filter(
        stage=Application.Stage.INCOMING
    ).select_related("department", "mahsulot_turi")


def accepted_applications() -> QuerySet[Application]:
    """The applications that were accepted and are waiting to be given out.

    Ordered by when they were accepted, newest first, rather than by when they
    arrived: this page is worked through in the order decisions were taken,
    and an application that sat in the incoming list for a week is new here on
    the day it is accepted. Falls back to the model ordering for anything
    whose date is somehow missing, which nothing should produce.
    """
    return (
        Application.objects.filter(stage=Application.Stage.ACCEPTED)
        .select_related("department", "mahsulot_turi", "accepted_by")
        .order_by("-qabul_qilingan_sana", "-id")
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
    """
    return render(
        request,
        ACCEPTED_TEMPLATE,
        {"applications": accepted_applications()},
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
