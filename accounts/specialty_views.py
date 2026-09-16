"""The User Specialty master data page (section 3.2)."""

from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.master_data import (
    MasterDataForm,
    category_number_field,
    deactivate,
)
from accounts.models import UserSpecialty

SPECIALTY_TEMPLATE = "pages/user-specialty.html"


class UserSpecialtyForm(MasterDataForm):
    """Capture one User Specialty.

    Category Number is not on the supplied page, and the specification does
    not give this table one. The field exists so an installation that wants it
    can show it without a migration, and DEC-023's six-digit rule applies the
    moment it is filled in.
    """

    category_number = category_number_field()

    class Meta:
        model = UserSpecialty
        fields = ("name", "category_number")


def render_specialty_page(
    request: HttpRequest,
    form: UserSpecialtyForm,
    edited_specialty_id: int | None = None,
) -> HttpResponse:
    """Render the page with the given form, filled in when editing."""
    return render(
        request,
        SPECIALTY_TEMPLATE,
        {
            "specialties": UserSpecialty.objects.active(),
            "form": form,
            "edited_specialty_id": edited_specialty_id,
        },
    )


def specialty_list(request: HttpRequest) -> HttpResponse:
    """The table, with one record open for editing when asked."""
    edit_id = request.GET.get("edit")
    if edit_id:
        edited = get_object_or_404(UserSpecialty, pk=edit_id, is_active=True)
        return render_specialty_page(
            request, UserSpecialtyForm(instance=edited), edited.pk
        )

    return render_specialty_page(request, UserSpecialtyForm())


@require_POST
def specialty_create(request: HttpRequest) -> HttpResponse:
    """Save adds the record to the list."""
    form = UserSpecialtyForm(request.POST)
    if not form.is_valid():
        return render_specialty_page(request, form)

    form.save()
    return redirect("user-specialty")


@require_POST
def specialty_update(request: HttpRequest, pk: int) -> HttpResponse:
    """Edit changes the record the form was opened on."""
    edited = get_object_or_404(UserSpecialty, pk=pk, is_active=True)

    form = UserSpecialtyForm(request.POST, instance=edited)
    if not form.is_valid():
        return render_specialty_page(request, form, edited.pk)

    form.save()
    return redirect("user-specialty")


@require_POST
def specialty_delete(request: HttpRequest, pk: int) -> HttpResponse:
    """Delete deactivates the record (DEC-009)."""
    deactivate(get_object_or_404(UserSpecialty, pk=pk, is_active=True))

    return redirect("user-specialty")
