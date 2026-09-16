"""The lists the department's work is described with.

Sections 3.5 to 3.8 of the specification give four tables their own master data
page - Ariza Status, Shartnoma Status, Mahsulot Turlari and Shartnoma turi -
and DEC-011 and DEC-018 add suppliers and departments to the same family. None
of them is a fact about a person, which is what accounts holds, so they live
here instead.

What they have in common - the DEC-009 soft delete, the DEC-023 Category
Number, the badge palette and the refusal of a duplicate name - stays in
accounts/master_data.py, where the first two master data pages put it.
TASK-UZK-016 is the first table in this application.
"""

from __future__ import annotations

from django.core.validators import RegexValidator
from django.db import models

from accounts.master_data import (
    UNPLACED,
    badge_class_for,
    badge_colour_field,
    next_position,
    position_field,
)
from accounts.models import MASTER_DATA_NAME_LENGTH, MasterDataRecord


class ArizaStatus(MasterDataRecord):
    """A state an application can be in (section 3.5).

    DEC-017 makes these editable master data rather than a fixed list: the
    four the migration seeds are examples the department is expected to
    extend, not names the code may rely on. Deleting one deactivates it
    (DEC-009), so an application already sitting in that status still
    resolves while the status leaves the page and every drop-down.
    """

    name = models.CharField(
        "Status Nomi", max_length=MASTER_DATA_NAME_LENGTH, unique=True
    )
    badge_colour = badge_colour_field()
    position = position_field()
    class Meta:
        # By position, not by name. A status list describes a progression, and
        # sorting alphabetically puts "Bekor qilingan" first and the starting
        # state third. DEC-010 has the workload and purchasing reports
        # generate one column per active status, so this is the order those
        # columns come out in too. Name is the tie-break so that two rows left
        # at the same position still sort predictably.
        ordering = ("position", "name")
        verbose_name = "Ariza Status"
        verbose_name_plural = "Ariza Statuslari"

    def save(self, *args, **kwargs) -> None:
        """Place a new row at the end of the list when it was not placed.

        An administrator who does not care where the status goes leaves the
        field blank and gets the end, which is almost always what a new status
        is. One who does care types a number and gets that.
        """
        if self.position == UNPLACED:
            self.position = next_position(type(self))
        super().save(*args, **kwargs)

    @property
    def badge_class(self) -> str:
        """The CSS class the page puts on this status's badge."""
        return badge_class_for(self.badge_colour)


class ShartnomaStatus(MasterDataRecord):
    """A state a contract can be in (section 3.5).

    DEC-010 settles the conflict between section 3.5, which makes these
    editable master data, and sections 4.3 to 4.6, which print five fixed
    counter columns: the five are seeded as examples and the reports generate
    one column per active status instead. So nothing may treat this table as
    having five rows, and TASK-UZK-044 and TASK-UZK-045 read objects.active()
    rather than a constant.

    Identical in shape to ArizaStatus. Two tables that happen to agree are not
    yet a base class; TASK-UZK-019 adds the third and is where that is worth
    deciding.
    """

    name = models.CharField(
        "Status Nomi", max_length=MASTER_DATA_NAME_LENGTH, unique=True
    )
    badge_colour = badge_colour_field()
    position = position_field()
    class Meta:
        # By position, not by name. A status list describes a progression, and
        # sorting alphabetically puts "Bekor qilingan" first and the starting
        # state third. DEC-010 has the workload and purchasing reports
        # generate one column per active status, so this is the order those
        # columns come out in too. Name is the tie-break so that two rows left
        # at the same position still sort predictably.
        ordering = ("position", "name")
        verbose_name = "Shartnoma Status"
        verbose_name_plural = "Shartnoma Statuslari"

    def save(self, *args, **kwargs) -> None:
        """Place a new row at the end of the list when it was not placed.

        An administrator who does not care where the status goes leaves the
        field blank and gets the end, which is almost always what a new status
        is. One who does care types a number and gets that.
        """
        if self.position == UNPLACED:
            self.position = next_position(type(self))
        super().save(*args, **kwargs)

    @property
    def badge_class(self) -> str:
        """The CSS class the page puts on this status's badge."""
        return badge_class_for(self.badge_colour)


class MahsulotTuri(MasterDataRecord):
    """A product category (section 3.6).

    The first master data table in this application that is not shaped like
    the two status tables. It has a description they do not, and neither the
    badge colour nor the ordering position they do: the supplied page shows
    neither, and a list of categories has no progression to order by.

    Its category number is required and unique, which is stricter than the
    specification states outright. It follows from the supplied form, which
    marks the field required and calls it a code, and from TASK-UZK-046, which
    reports purchases by category - two categories sharing a number would be
    merged in that report, and one with no number would be missing from it.

    The table ships empty. DEC-017 and DEC-010 name starting values for the
    two status tables; nothing names any here, and the six in the prototype
    are an illustration rather than a customer taxonomy.
    """

    category_number = models.PositiveIntegerField(
        "Category Raqami",
        unique=True,
        help_text=(
            "Six digits, and the code the department knows the category "
            "by (DEC-023)."
        ),
    )
    name = models.CharField(
        "Category Nomi", max_length=MASTER_DATA_NAME_LENGTH, unique=True
    )
    description = models.TextField("Tavsif", blank=True)

    class Meta:
        # By the code, not the name. It is what the department identifies a
        # category by and what the supplied table sorts on.
        ordering = ("category_number",)
        verbose_name = "Mahsulot Turi"
        verbose_name_plural = "Mahsulot Turlari"

    def __str__(self) -> str:
        return f"{self.category_number} - {self.name}"


class ShartnomaTuri(MasterDataRecord):
    """A kind of contract (section 3.7).

    The plainest master data table in the application: a name and nothing
    else, which is all the supplied page shows.

    DEC-023 settles CONFLICT-004 here. Section 3.7 makes contract type a
    maintainable list while the section 4.8 contract form fixes it to Import
    and Local; the decision is for section 3.7, with those two seeded as a
    starting point. So nothing may treat the pair as exhaustive - TASK-UZK-034
    and TASK-UZK-035 read this table.
    """

    name = models.CharField(
        "Shartnoma Turi", max_length=MASTER_DATA_NAME_LENGTH, unique=True
    )

    class Meta:
        ordering = ("name",)
        verbose_name = "Shartnoma Turi"
        verbose_name_plural = "Shartnoma Turlari"


class Department(MasterDataRecord):
    """A Bo`lim - a department of the enterprise (DEC-018).

    The specification never gives departments a page, but it groups by them in
    section 4.4 and auto-fills one from the signed-in user in section 4.9,
    neither of which works on text typed into each application. DEC-018 makes
    them Admin-maintained master data, which means they need somewhere to be
    maintained; TASK-UZK-020 adds the plainest page in the application for it.

    Whether this list is the purchasing department's own sub-units or every
    department that can raise a purchase application is not stated. Section
    4.9 filling it in from the signed-in user points at the second, and it is
    recorded as a question rather than answered here.
    """

    name = models.CharField(
        "Bo`lim Nomi", max_length=MASTER_DATA_NAME_LENGTH, unique=True
    )

    class Meta:
        ordering = ("name",)
        verbose_name = "Bo`lim"
        verbose_name_plural = "Bo`limlar"


# The supplied contract form caps Firma INN at nine characters and shows
# 123456789 as the placeholder, so nine digits is the customer's own
# expectation rather than this task's invention. It also leaves the field
# optional, which matters: DEC-023 seeds an Import contract type, so foreign
# suppliers are expected, and a foreign firm's tax identifier is not an Uzbek
# INN. Following the form means such a firm is entered without one.
INN_LENGTH = 9

INN_FORMAT = RegexValidator(
    rf"^\d{{{INN_LENGTH}}}$",
    message=f"INN {INN_LENGTH} ta raqamdan iborat bo`lishi kerak.",
)


class Supplier(MasterDataRecord):
    """A Firma - a supplier the department buys from (DEC-011).

    The specification gives suppliers no page, but the dashboard counts them
    and ranks the top ones, and the contract form types the firm's name into
    every contract. Two contracts naming the same firm are then two unrelated
    strings, and a count over strings is not a count of suppliers. DEC-011
    makes them master data selected on the contract form; TASK-UZK-021 adds
    the page to maintain them, following the precedent TASK-UZK-020 set.

    Daraja is free text. DEC-025 adds the field because the dashboard filters
    by it, and defines neither its values nor who assigns them. A scale
    invented here would be an invented scale, so TASK-UZK-048 will filter on
    whatever the department actually enters.
    """

    name = models.CharField(
        "Firma Nomi", max_length=MASTER_DATA_NAME_LENGTH, unique=True
    )
    inn = models.CharField(
        "Firma INN raqami",
        max_length=INN_LENGTH,
        blank=True,
        validators=[INN_FORMAT],
        help_text=(
            "Nine digits, as the supplied contract form asks for. Optional: a "
            "foreign supplier has no Uzbek INN."
        ),
    )
    daraja = models.CharField(
        "Daraja",
        max_length=32,
        blank=True,
        help_text=(
            "DEC-025 adds this because the dashboard filters by it, and does "
            "not say what values it takes. Free text until the customer says."
        ),
    )

    class Meta:
        ordering = ("name",)
        verbose_name = "Firma"
        verbose_name_plural = "Firmalar"
        constraints = [
            # Unique among the suppliers that have one, so several firms may
            # have no INN while no two share one. Without it the dashboard
            # count and the top-supplier ranking would double-count a firm
            # entered twice, which is what DEC-011 exists to prevent.
            models.UniqueConstraint(
                fields=["inn"],
                condition=~models.Q(inn=""),
                name="unique_supplier_inn_when_given",
            )
        ]
