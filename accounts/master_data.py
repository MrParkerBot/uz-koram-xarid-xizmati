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
"""

from __future__ import annotations

from django import forms
from django.core.validators import MaxValueValidator, MinValueValidator

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


def deactivate(record) -> None:
    """Delete a master data record the way DEC-009 defines deletion.

    The row stays, so an application or contract that already refers to it
    still resolves; it simply stops appearing in lists and drop-downs.
    """
    record.is_active = False
    record.save(update_fields=["is_active"])
