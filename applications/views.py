"""The Kelib tushgan Arizalar page (section 4.1).

A list with row actions and no form, which is why it does not use
MasterDataPage: that abstraction is a table beside a form, and this is a table
beside nothing.

Accept and Reject are rendered as the specification describes them and are
wired by TASK-UZK-023 and TASK-UZK-024. The filter bar the supplied page
carries is left inert; TASK-UZK-041 builds filtering for every table at once.
"""

from __future__ import annotations

from django.http import FileResponse, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render

from applications.attachments import attachment_response
from applications.models import Application

INCOMING_TEMPLATE = "pages/kelib-arizalar.html"


def incoming_applications() -> list[Application]:
    """The applications still waiting to be accepted or rejected.

    Filtered on the stage code rather than on an Ariza Status name, because
    DEC-017 lets an administrator rename or delete any status row and this
    list would then quietly empty.
    """
    return (
        Application.objects.filter(stage=Application.Stage.INCOMING)
        .select_related("department", "mahsulot_turi")
    )


def incoming_list(request: HttpRequest) -> HttpResponse:
    """The table of applications that have arrived and not been decided."""
    return render(
        request,
        INCOMING_TEMPLATE,
        {"applications": incoming_applications()},
    )


def application_pdf(request: HttpRequest, pk: int) -> FileResponse:
    """Download one application's PDF.

    Wrapped in the same permission as the page that offers it, so an
    attachment is reachable by exactly the people who may see the row it
    belongs to (DEC-019). The file itself lives outside anything published,
    so this view is the only way to it.
    """
    application = get_object_or_404(Application, pk=pk)

    return attachment_response(
        application.pdf, f"{application.ariza_raqami}.pdf"
    )
