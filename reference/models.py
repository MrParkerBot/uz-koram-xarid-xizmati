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

from accounts.master_data import badge_class_for, badge_colour_field
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
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = MasterDataQuerySet.as_manager()

    class Meta:
        ordering = ("name",)
        verbose_name = "Ariza Status"
        verbose_name_plural = "Ariza Statuslari"

    def __str__(self) -> str:
        return self.name

    @property
    def badge_class(self) -> str:
        """The CSS class the page puts on this status's badge."""
        return badge_class_for(self.badge_colour)
