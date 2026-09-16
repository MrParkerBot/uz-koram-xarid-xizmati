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

from accounts.master_data import badge_class_for, badge_colour_field

# One length for every master data name column. It was 64 on three tables
# and 128 on two, which was arbitrary rather than meaningful: nothing in
# the specification distinguishes them, so the next table had no basis for
# choosing. The wider of the two, because widening loses nothing.
MASTER_DATA_NAME_LENGTH = 128


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


class MasterDataRecord(models.Model):
    """What every master data table in the application has in common.

    Seven pages of the specification describe the same table seven times, and
    six of them are built. What they genuinely share is small: they can be
    deactivated rather than deleted (DEC-009), they know when they were
    created, they answer objects.active(), and they print as their name.

    Deliberately not here:

    - name, because each table labels it in its own words - "Status Nomi",
      "Specialty Nomi", "Category Nomi" - and a shared field with a generic
      label would be worse than a line per table. The length is standard
      across them, which is the part that was arbitrary.
    - badge_colour and position, which only the two status tables have. A
      status list has a progression and a colour; a list of specialties does
      not.

    category_number is here because DEC-023 gives it one meaning everywhere it
    appears, and optional is the common case. Mahsulot Turlari overrides it:
    there it is required and unique, because the supplied form calls it a code
    and TASK-UZK-046 reports by it.

    A subclass must declare name. __str__ reads it, which is the one thing
    this base assumes rather than provides.
    """

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
        abstract = True

    def __str__(self) -> str:
        return self.name


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
