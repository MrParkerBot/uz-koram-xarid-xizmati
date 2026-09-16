"""The User Types master data page (section 3.2).

A User Type is also a role: DEC-013 fixes six of them and
accounts/permissions.py decides what each may open by name. So this page has
one rule the User Specialty page does not - the six the department runs on
cannot be renamed or deleted here. Renaming one would detach it from every
permission written against it, and the user would simply lose access with
nothing anywhere saying why.

Everything else about them is editable, and an installation may add types of
its own freely.
"""

from __future__ import annotations

from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.master_data import MasterDataForm, category_number_field, deactivate
from accounts.models import UserType
from accounts.roles import DEPARTMENT_USER_TYPES

USER_TYPES_TEMPLATE = "pages/user-types.html"


def is_department_user_type(user_type: UserType) -> bool:
    """Whether this is one of the six roles DEC-013 fixes.

    Those six are named in accounts/permissions.py, so their names are part of
    the application rather than data an administrator maintains.
    """
    return user_type.name in DEPARTMENT_USER_TYPES


class UserTypeForm(MasterDataForm):
    """Capture one User Type.

    The name is read-only for the six DEC-013 fixes; the badge colour and the
    Category Number are not.
    """

    category_number = category_number_field()

    class Meta:
        model = UserType
        fields = ("name", "badge_colour", "category_number")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk is not None and is_department_user_type(self.instance):
            self.fields["name"].disabled = True

    @property
    def name_is_fixed(self) -> bool:
        """Whether the page should render the name as read-only."""
        return self.fields["name"].disabled


def render_user_types_page(
    request: HttpRequest,
    form: UserTypeForm,
    edited_type_id: int | None = None,
) -> HttpResponse:
    """Render the page with the given form, filled in when editing."""
    return render(
        request,
        USER_TYPES_TEMPLATE,
        {
            "user_types": UserType.objects.active(),
            "form": form,
            "edited_type_id": edited_type_id,
            "department_user_types": DEPARTMENT_USER_TYPES,
        },
    )


def user_type_list(request: HttpRequest) -> HttpResponse:
    """The table, with one type open for editing when asked."""
    edit_id = request.GET.get("edit")
    if edit_id:
        edited = get_object_or_404(UserType, pk=edit_id, is_active=True)
        return render_user_types_page(
            request, UserTypeForm(instance=edited), edited.pk
        )

    return render_user_types_page(request, UserTypeForm())


@require_POST
def user_type_create(request: HttpRequest) -> HttpResponse:
    """Save adds the type to the list."""
    form = UserTypeForm(request.POST)
    if not form.is_valid():
        return render_user_types_page(request, form)

    form.save()
    return redirect("user-types")


@require_POST
def user_type_update(request: HttpRequest, pk: int) -> HttpResponse:
    """Edit changes the type the form was opened on.

    A disabled field keeps its stored value whatever is posted, so a rename of
    one of the six arrives here and is ignored rather than refused - which is
    what a form built from the instance should do.
    """
    edited = get_object_or_404(UserType, pk=pk, is_active=True)

    form = UserTypeForm(request.POST, instance=edited)
    if not form.is_valid():
        return render_user_types_page(request, form, edited.pk)

    form.save()
    return redirect("user-types")


@require_POST
def user_type_delete(request: HttpRequest, pk: int) -> HttpResponse:
    """Delete deactivates the type, unless it is one the department runs on."""
    deleted = get_object_or_404(UserType, pk=pk, is_active=True)

    if is_department_user_type(deleted):
        # accounts/roles.py treats a deactivated type as no type at all, so
        # deleting Admin would take every administrator's access with it.
        raise PermissionDenied(
            f"{deleted.name} - tizim roli, o'chirib bo'lmaydi."
        )

    deactivate(deleted)
    return redirect("user-types")

