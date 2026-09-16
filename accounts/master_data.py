"""The shape every master data page in the specification shares.

Sections 3.2 and 3.5 to 3.8 describe the same page eight times over: a table
with a counter and row actions, a small form beside it, Save adding a record
and Cancel discarding it, Edit opening the form filled in, and Delete removing
the record after a confirmation.

DEC-009 defines what Delete means for all of them - the record is deactivated,
leaves the list and every drop-down, and stays resolvable for the applications
and contracts that already reference it - and DEC-023 defines Category Number
where a page has one.

This module holds the parts that do not differ, so the eight pages differ only
where the specification says they do. TASK-UZK-014 is the first of them.

TASK-UZK-016 is the third, which is where the four views each page repeats -
list, create, update, delete - moved here as MasterDataPage. The two pages
written before it keep their own copies: they are merged and reviewed, and
rewriting them with no behaviour change belongs in a diff a reviewer can read
as a refactor rather than inside a feature.
"""

from __future__ import annotations

from collections.abc import Callable

from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

# DEC-023: a six-digit integer. Written as a range rather than a string
# pattern because the field is a number, and 000123 is not six digits of a
# number however it is typed.
SMALLEST_CATEGORY_NUMBER = 100_000
LARGEST_CATEGORY_NUMBER = 999_999

CATEGORY_NUMBER_VALIDATORS = (
    MinValueValidator(SMALLEST_CATEGORY_NUMBER),
    MaxValueValidator(LARGEST_CATEGORY_NUMBER),
)


def category_number_field(label: str = "Category Number") -> forms.IntegerField:
    """The optional six-digit Category Number a master data form may carry."""
    return forms.IntegerField(
        label=label,
        required=False,
        validators=list(CATEGORY_NUMBER_VALIDATORS),
        help_text="6 xonali son (masalan 100123).",
    )



def required_category_number_field(
    label: str = "Category Raqami",
) -> forms.IntegerField:
    """The Category Number a master data form insists on.

    The Mahsulot Turlari form marks it required and calls it a code, and
    TASK-UZK-046 reports purchases by category - a category with no number
    would have nothing to report under. The six-digit rule is the same rule,
    taken from the same validators, so the required and optional forms of the
    field cannot drift apart.
    """
    return forms.IntegerField(
        label=label,
        required=True,
        validators=list(CATEGORY_NUMBER_VALIDATORS),
        help_text="6 xonali kod (masalan 100042).",
    )

# The badge colours the supplied pages offer, mapped to the classes the
# vendored style.css already defines. Stored as the page's own word rather than
# the CSS class, so a restyle does not rewrite the data.
#
# Shared here rather than owned by UserType because Ariza Status needs the same
# palette. The order is the order the choices were first migrated in; changing
# it would make Django ask for a migration that changes nothing.
BADGE_COLOURS: dict[str, str] = {
    "orange": "badge-primary",
    "blue": "badge-info",
    "green": "badge-approved",
    "yellow": "badge-trial",
    "gray": "badge-soft",
}

DEFAULT_BADGE_COLOUR = "orange"


def badge_colour_field(label: str = "Badge Rangi") -> models.CharField:
    """The badge colour column a master data table carries."""
    return models.CharField(
        label,
        max_length=16,
        choices=[(colour, colour) for colour in BADGE_COLOURS],
        default=DEFAULT_BADGE_COLOUR,
    )


def badge_class_for(colour: str) -> str:
    """The CSS class a page puts on a badge of this colour.

    An unrecognised colour falls back to the neutral badge rather than
    rendering an empty class attribute, so a row that somehow holds a retired
    colour still looks like a badge.
    """
    return BADGE_COLOURS.get(colour, "badge-soft")


# A status list has an order the work moves through, and it is neither
# alphabetical nor reliably the creation timestamp: rows seeded in one loop can
# share a timestamp to the microsecond, and the tie-break then decides. So the
# order is a number the row carries.
#
# Steps of ten, so a status can later be dropped between two without renumbering
# the table.
POSITION_STEP = 10

# What an unplaced row carries. Zero rather than null so the column can be
# ordered on without a null-handling rule in every query.
UNPLACED = 0


def position_field(label: str = "Tartib") -> models.PositiveIntegerField:
    """Where a row sits in an ordered master data list."""
    return models.PositiveIntegerField(
        label,
        default=UNPLACED,
        blank=True,
        help_text=(
            "Ro'yhatdagi va hisobot ustunlaridagi tartib. "
            "Bo'sh qoldirilsa, oxiriga qo'shiladi."
        ),
    )


def position_form_field(label: str = "Tartib") -> forms.IntegerField:
    """The optional position a master data form may offer.

    Optional because an administrator adding a status almost always wants it
    at the end, and making them work out which number that is would be a
    question with one sensible answer.
    """
    return forms.IntegerField(
        label=label,
        required=False,
        min_value=1,
        help_text="Ro'yhatdagi tartib. Bo'sh qoldirilsa, oxiriga qo'shiladi.",
    )


def next_position(model: type[models.Model]) -> int:
    """The position that puts a new row at the end of this table."""
    last = model.objects.aggregate(models.Max("position"))["position__max"]
    return (last or UNPLACED) + POSITION_STEP


def deactivate(record) -> None:
    """Delete a master data record the way DEC-009 defines deletion.

    The row stays, so an application or contract that already refers to it
    still resolves; it simply stops appearing in lists and drop-downs.
    """
    record.is_active = False
    record.save(update_fields=["is_active"])


class MasterDataForm(forms.ModelForm):
    """The validation every master data form shares.

    Two records must not share a name, and refusing a clash has to say which
    of the two things happened: the name is in use, or the name belongs to a
    record somebody deleted and therefore cannot see. Django's own message
    says neither, and says it in English.

    A second master data page made this shared; TASK-UZK-014 wrote it first.
    """

    NAME_ALREADY_USED = "Bu nom allaqachon mavjud."
    NAME_HELD_BY_DELETED_RECORD = (
        "Bu nom o'chirilgan yozuvga tegishli. Boshqa nom kiriting."
    )

    def clean_position(self) -> int:
        """Blank means the end of the list.

        Only called on a form that declares a position field; the master data
        pages whose rows have no inherent order do not.
        """
        return self.cleaned_data.get("position") or UNPLACED

    def refuse_a_clash(
        self,
        value,
        *,
        lookup: str,
        already_used: str,
        held_by_deleted_record: str,
    ):
        """Return value, or raise saying which kind of clash it hit.

        Django refuses a duplicate on its own, but with one message for two
        situations that need different answers from the person reading it.
        DEC-009 keeps a deleted row in the table, so a value can be taken by a
        record that is nowhere on the page - and being told it already exists,
        while looking at a list that does not contain it, is the one case
        worth spelling out.

        Args:
            value: the submitted value, returned unchanged when it is free.
            lookup: the queryset lookup that finds a clash, such as
                name__iexact or category_number.
            already_used: what to say when the clash is with a visible row.
            held_by_deleted_record: what to say when it is with a deleted one.

        Raises:
            forms.ValidationError: when the value is taken, either way.
        """
        taken = self._meta.model.objects.filter(**{lookup: value})
        if self.instance.pk is not None:
            taken = taken.exclude(pk=self.instance.pk)

        clash = taken.first()
        if clash is None:
            return value

        if clash.is_active:
            raise forms.ValidationError(already_used)

        raise forms.ValidationError(held_by_deleted_record)

    def clean_name(self) -> str:
        """Refuse a name already taken, case-insensitively."""
        return self.refuse_a_clash(
            self.cleaned_data["name"],
            lookup="name__iexact",
            already_used=self.NAME_ALREADY_USED,
            held_by_deleted_record=self.NAME_HELD_BY_DELETED_RECORD,
        )


class MasterDataPage:
    """The four views one master data page needs, built from what differs.

    A page of this kind is a table beside a form. Everything about how they
    behave is the same from page to page - Save adds a row and redirects, an
    invalid Save re-renders the page with the errors still on the form, Edit
    fills the form in from ?edit=, and Delete deactivates after a confirmation
    the template asks for. What differs is only the table, the form, the
    template and the name of the list the template reads.

    The views are built once, in the constructor, so the URL configuration
    refers to them as plain callables and the POST-only rule is attached where
    it cannot be forgotten.
    """

    def __init__(
        self,
        *,
        model: type[models.Model],
        form_class: type[MasterDataForm],
        template_name: str,
        url_name: str,
        context_object_name: str,
    ) -> None:
        """Describe one page.

        Args:
            model: the master data table this page maintains. It must carry
                is_active and answer objects.active(), which is what DEC-009
                deletion and every drop-down are built on.
            form_class: the form that captures one row.
            template_name: the template to render, which reads
                context_object_name and edited_record.
            url_name: the name of this page's own route, used for the
                redirect after a successful Save and Delete.
            context_object_name: what the template calls the list of rows.
        """
        self.model = model
        self.form_class = form_class
        self.template_name = template_name
        self.url_name = url_name
        self.context_object_name = context_object_name

        self.list_records: Callable[..., HttpResponse] = self._list_records
        self.create_record: Callable[..., HttpResponse] = require_POST(
            self._create_record
        )
        self.update_record: Callable[..., HttpResponse] = require_POST(
            self._update_record
        )
        self.delete_record: Callable[..., HttpResponse] = require_POST(
            self._delete_record
        )

    def _render_page(
        self,
        request: HttpRequest,
        form: MasterDataForm,
        edited_record: models.Model | None = None,
    ) -> HttpResponse:
        """Render the page with the given form, filled in when editing.

        edited_record is None when the form is a blank one for a new row, and
        the template decides from it whether Save posts to create or update.
        """
        return render(
            request,
            self.template_name,
            {
                self.context_object_name: self.model.objects.active(),
                "form": form,
                "edited_record": edited_record,
            },
        )

    def _active_record(self, pk: int | str) -> models.Model:
        """One row that has not been deleted, or a 404.

        A deleted row answers 404 rather than 403: it has left the page, and
        saying it exists but may not be touched would contradict that.

        pk arrives as an int from the URL converter on the edit and delete
        routes, and as the raw string from ?edit= on the list route - which is
        the one place it reaches the page without a converter having checked
        it. A pk that is not a number is a 404 here rather than the ValueError
        the query would otherwise raise, because ?edit=abc is a request for a
        record that does not exist, not a server fault.
        """
        try:
            return get_object_or_404(self.model, pk=pk, is_active=True)
        except (ValueError, ValidationError) as not_a_pk:
            raise Http404(
                f"{pk!r} is not the id of a {self.model._meta.verbose_name}."
            ) from not_a_pk

    def _list_records(self, request: HttpRequest) -> HttpResponse:
        """The table, with one row open for editing when asked."""
        edit_id = request.GET.get("edit")
        if edit_id:
            edited = self._active_record(edit_id)
            return self._render_page(request, self.form_class(instance=edited), edited)

        return self._render_page(request, self.form_class())

    def _create_record(self, request: HttpRequest) -> HttpResponse:
        """Save adds the row to the list."""
        form = self.form_class(request.POST)
        if not form.is_valid():
            return self._render_page(request, form)

        form.save()
        return redirect(self.url_name)

    def _update_record(self, request: HttpRequest, pk: int) -> HttpResponse:
        """Edit changes the row the form was opened on."""
        edited = self._active_record(pk)

        form = self.form_class(request.POST, instance=edited)
        if not form.is_valid():
            return self._render_page(request, form, edited)

        form.save()
        return redirect(self.url_name)

    def _delete_record(self, request: HttpRequest, pk: int) -> HttpResponse:
        """Delete deactivates the row (DEC-009)."""
        deactivate(self._active_record(pk))

        return redirect(self.url_name)
