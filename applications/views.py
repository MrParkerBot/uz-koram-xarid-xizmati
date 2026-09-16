"""The Kelib tushgan Arizalar page (section 4.1).

A list with row actions and no form, which is why it does not use
MasterDataPage: that abstraction is a table beside a form, and this is a table
beside nothing.

Accept and Reject are rendered as the specification describes them and are
wired by TASK-UZK-023 and TASK-UZK-024. The filter bar the supplied page
carries is left inert; TASK-UZK-041 builds filtering for every table at once.
"""

from __future__ import annotations

from django.core.exceptions import PermissionDenied
from django.db.models import QuerySet
from django.http import FileResponse, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render

from accounts.permissions import may_open
from applications.attachments import attachment_response
from applications.models import Application

INCOMING_TEMPLATE = "pages/kelib-arizalar.html"

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
    # A rejected application is off the workflow. Nothing lists it yet, so
    # nobody may fetch its attachment; TASK-UZK-024 decides where it shows.
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


def incoming_list(request: HttpRequest) -> HttpResponse:
    """The table of applications that have arrived and not been decided."""
    return render(
        request,
        INCOMING_TEMPLATE,
        {"applications": incoming_applications()},
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
