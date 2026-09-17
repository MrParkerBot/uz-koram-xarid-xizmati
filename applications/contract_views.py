"""The Kelishinlingan Shartnoma page of section 4.6.

The contracts the department has agreed, and the form REQ-SHARTNOMA-006
enters one with. A contract is formed on the basis of an application somebody
is already working on, which is what contractable_applications() narrows the
chooser to.
"""

from __future__ import annotations

from django.contrib import messages
from django.db import transaction
from django.db.models import Prefetch, QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from applications.forms import (
    SUGGESTED_UNITS,
    ContractForm,
    ContractItemFormSet,
)
from applications.models import Application, Contract, ContractItem
from applications.queries import acts_on_own_work_only

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


AGREED_CONTRACTS_TEMPLATE = "pages/kelishinlingan.html"


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
        .prefetch_related(contract_lines())
    )


def contract_lines() -> Prefetch:
    """The goods rows of a contract, in the order they were entered."""
    return Prefetch("items", queryset=ContractItem.objects.all())


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
    form = ContractForm(request.POST, applications=applications)
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
        )

    messages.success(
        request,
        f"{contract.shartnoma_raqami} yaratildi. "
        f"Shartnoma qiymati: {contract.qiymati_display} UZS.",
    )

    return redirect("kelishinlingan")
