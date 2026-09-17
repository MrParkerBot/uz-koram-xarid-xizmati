"""The Xarid Arizasi page of section 4.9.

What a requester asks the purchasing department for, the DEC-016 chain that
approves or refuses it, and the two downloads DEC-019 makes the only way to
an attachment.
"""

from __future__ import annotations

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Prefetch, QuerySet
from django.http import FileResponse, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.models import UserProfile
from accounts.roles import department_of, has_user_type
from applications.attachments import attachment_response
from applications.forms import (
    SUGGESTED_UNITS,
    PurchaseApplicationForm,
    PurchaseApplicationItemFormSet,
)
from applications.models import PurchaseApplication, PurchaseApplicationItem
from applications.queries import ordered_lines
from reference.models import ArizaStatus

PURCHASE_TEMPLATE = "pages/xarid-ariza.html"


def purchase_applications() -> QuerySet[PurchaseApplication]:
    """Every purchase application, newest first (REQ-ARIZA-014).

    Not filtered by requester. USERS is the only type with this page and
    nothing says a requester sees only their own; the department's own people
    open it to see what has been asked for, and a list that hid most of it
    would be answering a different question. Recorded as an unknown on the
    plan rather than settled here.
    """
    return (
        PurchaseApplication.objects.select_related("department", "status")
        .prefetch_related(purchase_lines())
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
