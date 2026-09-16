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

from django.db import models

from accounts.master_data import (
    UNPLACED,
    badge_class_for,
    badge_colour_field,
    next_position,
    position_field,
)
from accounts.models import MasterDataQuerySet


class ArizaStatus(models.Model):
    """A state an application can be in (section 3.5).

    DEC-017 makes these editable master data rather than a fixed list: the
    four the migration seeds are examples the department is expected to
    extend, not names the code may rely on. Deleting one deactivates it
    (DEC-009), so an application already sitting in that status still
    resolves while the status leaves the page and every drop-down.
    """

    name = models.CharField("Status Nomi", max_length=64, unique=True)
    badge_colour = badge_colour_field()
    category_number = models.PositiveIntegerField(
        "Category Number",
        null=True,
        blank=True,
        help_text="Six digits when present (DEC-023).",
    )
    position = position_field()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = MasterDataQuerySet.as_manager()

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

    def __str__(self) -> str:
        return self.name

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


class ShartnomaStatus(models.Model):
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

    name = models.CharField("Status Nomi", max_length=64, unique=True)
    badge_colour = badge_colour_field()
    category_number = models.PositiveIntegerField(
        "Category Number",
        null=True,
        blank=True,
        help_text="Six digits when present (DEC-023).",
    )
    position = position_field()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = MasterDataQuerySet.as_manager()

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

    def __str__(self) -> str:
        return self.name

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
