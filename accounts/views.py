"""The Users page: the table, the create and edit form, and deletion."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.forms import UserAdministrationForm

USERS_TEMPLATE = "pages/users.html"


def listed_users() -> QuerySet:
    """The users the page shows, newest last.

    Deactivated accounts are absent: DEC-009 makes deletion a deactivation, so
    a deleted user leaves the list while every record that refers to them still
    resolves. select_related reaches the profile in the same query, and the
    join is a left one - an account created before anybody assigned it a type
    has no profile row at all.
    """
    return (
        get_user_model()
        .objects.filter(is_active=True)
        .select_related("profile", "profile__user_type")
        .order_by("first_name", "last_name", "id")
    )


def render_users_page(
    request: HttpRequest,
    form: UserAdministrationForm,
    edited_user_id: int | None = None,
) -> HttpResponse:
    """Render the page with the given form, open for editing when asked."""
    return render(
        request,
        USERS_TEMPLATE,
        {
            "users": listed_users(),
            "form": form,
            "edited_user_id": edited_user_id,
            # The modal opens by itself when a submission failed or an edit was
            # requested, so the person is not sent back to a closed dialog to
            # find out what went wrong.
            "open_form": bool(form.errors) or edited_user_id is not None,
        },
    )


def user_list(request: HttpRequest) -> HttpResponse:
    """The Users page, optionally with one user open for editing."""
    edit_user_id = request.GET.get("edit")
    if edit_user_id:
        edited_user = get_object_or_404(
            get_user_model(), pk=edit_user_id, is_active=True
        )
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

    form.save()
    return redirect("users")


@require_POST
def user_update(request: HttpRequest, pk: int) -> HttpResponse:
    """Change a user's details, and their password when one was supplied."""
    edited_user = get_object_or_404(get_user_model(), pk=pk, is_active=True)

    form = UserAdministrationForm(request.POST, edited_user=edited_user)
    if not form.is_valid():
        return render_users_page(request, form, edited_user.pk)

    form.save()
    return redirect("users")


@require_POST
def user_delete(request: HttpRequest, pk: int) -> HttpResponseRedirect:
    """Delete a user the way DEC-009 defines deletion.

    The account is deactivated rather than removed: it leaves the list and can
    no longer sign in, while anything already referring to it still resolves.
    Deleting the row would take its applications and contracts with it.
    """
    deleted_user = get_object_or_404(get_user_model(), pk=pk, is_active=True)

    deleted_user.is_active = False
    deleted_user.save(update_fields=["is_active"])

    return redirect(reverse("users"))
