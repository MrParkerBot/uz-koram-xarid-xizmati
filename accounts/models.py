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


class MasterDataQuerySet(models.QuerySet):
    """Queries every master data table answers.

    Shared because DEC-009 gives them all the same deletion rule: a deleted
    row is deactivated, leaves the lists and stays resolvable.
    """

    def active(self) -> MasterDataQuerySet:
        """The types that still appear in lists and drop-downs.

        A deleted type is marked inactive rather than removed (DEC-009), so
        that a user who was assigned it still resolves.
        """
        return self.filter(is_active=True)


class UserType(models.Model):
    """A role, as the specification's User Types page defines one."""

    name = models.CharField("User Type", max_length=64, unique=True)
    category_number = models.PositiveIntegerField(
        "Category Number", null=True, blank=True
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = MasterDataQuerySet.as_manager()

    class Meta:
        ordering = ("name",)
        verbose_name = "User Type"
        verbose_name_plural = "User Types"

    def __str__(self) -> str:
        return self.name


class UserProfile(models.Model):
    """The department's own facts about an account.

    Today that is the user's type. TASK-UZK-013 adds the contract-edit
    permission and TASK-UZK-014 the specialty, both of which belong to the
    person rather than to the login.
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


class UserSpecialty(models.Model):
    """A specialty a member of the department holds (section 3.2).

    Master data, like UserType: a row an administrator maintains rather than a
    constant. Deleting one deactivates it (DEC-009), so that a person or an
    application already referring to it still resolves while the specialty
    leaves the lists and drop-downs.
    """

    name = models.CharField("Specialty Nomi", max_length=128, unique=True)
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
        verbose_name = "User Specialty"
        verbose_name_plural = "User Specialties"

    def __str__(self) -> str:
        return self.name
