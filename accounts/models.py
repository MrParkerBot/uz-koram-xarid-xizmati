"""Who a user is, in the purchasing department's own terms.

The specification calls a role a "User Type" and gives it a master data page of
its own (section 3.2), so it is a row rather than a constant. DEC-013 fixes the
six the department works with, superseding section 11's shorter list.

A user's type is held on a profile rather than on the account, because
django.contrib.auth.User already exists in this database and swapping the user
model after its migrations have run is not a change worth making for one
foreign key.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from accounts.master_data import (
    MasterDataQuerySet,
    MasterDataRecord,
    badge_class_for,
    badge_colour_field,
)

# Re-exported: the master data shape moved to accounts/master_data.py in
# TASK-UZK-020, and four merged modules import it from here. Moving a name
# is not a reason to make every caller chase it.
__all__ = [
    "MASTER_DATA_NAME_LENGTH",
    "MasterDataQuerySet",
    "MasterDataRecord",
    "UserProfile",
    "UserSpecialty",
    "UserType",
]

# One length for every master data name column. It was 64 on three tables
# and 128 on two, which was arbitrary rather than meaningful: nothing in
# the specification distinguishes them, so the next table had no basis for
# choosing. The wider of the two, because widening loses nothing.
MASTER_DATA_NAME_LENGTH = 128


class UserType(MasterDataRecord):
    """A role, as the specification's User Types page defines one."""

    name = models.CharField(
        "User Type", max_length=MASTER_DATA_NAME_LENGTH, unique=True
    )
    badge_colour = badge_colour_field()
    is_system_role = models.BooleanField(
        default=False,
        help_text=(
            "One of the six DEC-013 fixes. accounts/permissions.py decides "
            "what each may open by name, so a system role cannot be renamed "
            "or deleted from the User Types page."
        ),
    )

    class Meta:
        ordering = ("name",)
        verbose_name = "User Type"
        verbose_name_plural = "User Types"

    @property
    def badge_class(self) -> str:
        """The CSS class the page puts on this type's badge."""
        return badge_class_for(self.badge_colour)


class UserProfile(models.Model):
    """The department's own facts about an account.

    Today that is the user's type, their department and what they are
    permitted to edit - all facts about the person rather than the login.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    user_type = models.ForeignKey(
        UserType,
        on_delete=models.PROTECT,
        related_name="users",
        null=True,
        blank=True,
        help_text="A user with no type can open nothing that a role protects.",
    )
    department = models.ForeignKey(
        "reference.Department",
        on_delete=models.PROTECT,
        related_name="users",
        null=True,
        blank=True,
        help_text=(
            "DEC-018: every user belongs to a department, and the Xarid "
            "Arizasi form fills it in from whoever is signed in. Nullable so "
            "that the users who existed before departments did still save; "
            "whether the Users page should insist on one is a question for "
            "the customer."
        ),
    )
    phone_number = models.CharField(max_length=32, blank=True)
    may_edit_contracts = models.BooleanField(
        "Tahrirlash ruxsati",
        default=False,
        help_text=(
            "At most one user holds this at a time (DEC-021). Granting it to "
            "somebody takes it from whoever had it."
        ),
    )

    def __str__(self) -> str:
        return f"{self.user.get_username()} ({self.user_type or 'no user type'})"


class UserSpecialty(MasterDataRecord):
    """A specialty a member of the department holds (section 3.2).

    Master data, like UserType: a row an administrator maintains rather than a
    constant. Deleting one deactivates it (DEC-009), so that a person or an
    application already referring to it still resolves while the specialty
    leaves the lists and drop-downs.
    """

    name = models.CharField(
        "Specialty Nomi", max_length=MASTER_DATA_NAME_LENGTH, unique=True
    )

    class Meta:
        ordering = ("name",)
        verbose_name = "User Specialty"
        verbose_name_plural = "User Specialties"
