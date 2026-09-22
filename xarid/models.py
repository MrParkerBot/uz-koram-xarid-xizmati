"""The purchasing department's records.

Three families live here:

- facts about people: UserType (a role, which DEC-013 makes master data),
  UserProfile and UserSpecialty;
- the lists work is described with: ArizaStatus, ShartnomaStatus,
  MahsulotTuri, ShartnomaTuri, Department and Supplier - all master data with
  the DEC-009 soft delete;
- the work itself: Application and its order lines, Contract and its priced
  rows, PurchaseApplication with DEC-016's approval chain, and the Notification
  a transition leaves behind.

A record with a life cycle carries a *stage* - a code the workflow branches on
- beside a *status* row a person reads and an administrator may rename or
delete (DEC-017, DEC-010). Every list filters on the stage; where the workflow
needs a particular status row it finds it by the code the seeded rows carry.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractBaseUser, AnonymousUser
from django.core.validators import (
    MaxValueValidator,
    MinValueValidator,
    RegexValidator,
)
from django.db import models, transaction
from django.db.models import QuerySet
from django.utils import timezone

from xarid.attachments import application_pdf_field, attachment_storage, contract_pdf_field

# ---------------------------------------------------------------------------
# Roles (DEC-013). The spellings are the department's own and are what the
# seeded rows are called.
# ---------------------------------------------------------------------------

ADMIN = "Admin"
BOLIM_BOSHLIGI = "Bo`lim Boshlig`i"
MENEJER = "Menejer"
KATTA_MUTAXASIS = "Katta Mutaxasis"
DIREKTOR = "Direktor"
USERS = "Users"

DEPARTMENT_USER_TYPES: tuple[str, ...] = (
    ADMIN,
    BOLIM_BOSHLIGI,
    MENEJER,
    KATTA_MUTAXASIS,
    DIREKTOR,
    USERS,
)

# ---------------------------------------------------------------------------
# Master data building blocks (DEC-009 soft delete, DEC-023 Category Number).
# ---------------------------------------------------------------------------

MASTER_DATA_NAME_LENGTH = 128

# DEC-023: a six-digit integer, written as a range because the field is a
# number and 000123 is not six digits of a number however it is typed.
SMALLEST_CATEGORY_NUMBER = 100_000
LARGEST_CATEGORY_NUMBER = 999_999

CATEGORY_NUMBER_VALIDATORS = (
    MinValueValidator(SMALLEST_CATEGORY_NUMBER),
    MaxValueValidator(LARGEST_CATEGORY_NUMBER),
)

# The badge colours the supplied pages offer, mapped to the classes the
# vendored style.css defines. Stored as the page's own word so a restyle does
# not rewrite the data. The order is the order first migrated in.
BADGE_COLOURS: dict[str, str] = {
    "orange": "badge-primary",
    "blue": "badge-info",
    "green": "badge-approved",
    "yellow": "badge-trial",
    "gray": "badge-soft",
}

DEFAULT_BADGE_COLOUR = "orange"

# A status list has an order the work moves through. Steps of ten, so a status
# can later be dropped between two without renumbering the table. Zero means
# unplaced.
POSITION_STEP = 10
UNPLACED = 0

# The supplied contract form caps Firma INN at nine characters and leaves it
# optional: a foreign supplier's tax identifier is not an Uzbek INN.
INN_LENGTH = 9
INN_FORMAT = RegexValidator(
    rf"^\d{{{INN_LENGTH}}}$",
    message=f"INN {INN_LENGTH} ta raqamdan iborat bo`lishi kerak.",
)


def badge_colour_field(label: str = "Badge Rangi") -> models.CharField:
    """The badge colour column a master data table carries."""
    return models.CharField(
        label,
        max_length=16,
        choices=[(colour, colour) for colour in BADGE_COLOURS],
        default=DEFAULT_BADGE_COLOUR,
    )


def badge_class_for(colour: str) -> str:
    """The CSS class for a badge of this colour, neutral when unrecognised."""
    return BADGE_COLOURS.get(colour, "badge-soft")


def position_field(label: str = "Tartib") -> models.PositiveIntegerField:
    """Where a row sits in an ordered master data list."""
    return models.PositiveIntegerField(
        label,
        default=UNPLACED,
        blank=True,
        help_text=(
            "Ro'yhatdagi va hisobot ustunlaridagi tartib. Bo'sh qoldirilsa, oxiriga qo'shiladi."
        ),
    )


def next_position(model: type[models.Model]) -> int:
    """The position that puts a new row at the end of this table."""
    last = model.objects.aggregate(models.Max("position"))["position__max"]
    return (last or UNPLACED) + POSITION_STEP


def next_category_number(model: type[models.Model]) -> int:
    """The six-digit number a new category takes when nobody typed one.

    One past the highest in the table, counting deleted rows: DEC-009 keeps a
    deleted category's row, it keeps its number with it, and the number is
    unique across the table rather than across the visible part of it.

    Once the highest is 999999 the count cannot go on, so the lowest number
    nobody holds is taken instead - the gaps left by categories numbered by
    hand. A table holding all nine hundred thousand of them is refused rather
    than given a seventh digit, which is not a Category Raqami (DEC-023).
    """
    highest = model.objects.aggregate(models.Max("category_number"))["category_number__max"]
    nominee = max(SMALLEST_CATEGORY_NUMBER, (highest or 0) + 1)
    if nominee <= LARGEST_CATEGORY_NUMBER:
        return nominee

    taken = set(model.objects.values_list("category_number", flat=True))
    for candidate in range(SMALLEST_CATEGORY_NUMBER, LARGEST_CATEGORY_NUMBER + 1):
        if candidate not in taken:
            return candidate

    raise ValueError("Category raqamlari tugadi: barcha olti xonali raqamlar band.")


def deactivate(record: MasterDataRecord) -> None:
    """Delete a master data record the way DEC-009 defines deletion.

    The row stays, so an application or contract that already refers to it
    still resolves; it simply stops appearing in lists and drop-downs.
    """
    record.is_active = False
    record.save(update_fields=["is_active"])


class MasterDataQuerySet(models.QuerySet):
    """Queries every master data table answers."""

    def active(self) -> MasterDataQuerySet:
        """The rows that still appear in lists and drop-downs."""
        return self.filter(is_active=True)


class MasterDataRecord(models.Model):
    """What every master data table has in common.

    A subclass must declare `name`, which is what the record prints as. The
    optional Category Number follows DEC-023; MahsulotTuri overrides it as
    required and unique.
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


class OrderedStatus(MasterDataRecord):
    """A status row with a badge colour and a place in a progression."""

    badge_colour = badge_colour_field()
    position = position_field()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs) -> None:
        """Place a new row at the end of the list when it was not placed."""
        if self.position == UNPLACED:
            self.position = next_position(type(self))
        super().save(*args, **kwargs)

    @property
    def badge_class(self) -> str:
        """The CSS class the page puts on this status's badge."""
        return badge_class_for(self.badge_colour)


# ---------------------------------------------------------------------------
# People
# ---------------------------------------------------------------------------


class UserType(MasterDataRecord):
    """A role, as the specification's User Types page defines one.

    The six DEC-013 fixes are marked as system roles: permissions.py decides
    what each may open by name, so they cannot be renamed or deleted from the
    User Types page. Their badge colour and Category Number stay editable.
    """

    name = models.CharField("User Type", max_length=MASTER_DATA_NAME_LENGTH, unique=True)
    badge_colour = badge_colour_field()
    is_system_role = models.BooleanField(
        default=False,
        help_text=(
            "One of the six DEC-013 fixes. The permission matrix names it, so "
            "it cannot be renamed or deleted from the User Types page."
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


class UserSpecialty(MasterDataRecord):
    """A specialty a member of the department holds (section 3.2)."""

    name = models.CharField("Specialty Nomi", max_length=MASTER_DATA_NAME_LENGTH, unique=True)

    class Meta:
        ordering = ("name",)
        verbose_name = "User Specialty"
        verbose_name_plural = "User Specialties"


class Department(MasterDataRecord):
    """A Bo`lim - a department of the enterprise (DEC-018).

    The specification gives departments no page but groups by them and fills
    one in from the signed-in user, neither of which works on free text. They
    are Admin-maintained master data.
    """

    name = models.CharField("Bo`lim Nomi", max_length=MASTER_DATA_NAME_LENGTH, unique=True)
    is_purchasing = models.BooleanField(
        "Xarid bo`limi",
        default=False,
        help_text=(
            "The department that works the approved requests: its Bo`lim "
            "Boshlig`i and Menejer are who Kelib Tushgan Arizalar is for. "
            "One department at a time, set here rather than matched on a "
            "name that anybody may rename."
        ),
    )

    class Meta:
        ordering = ("name",)
        verbose_name = "Bo`lim"
        verbose_name_plural = "Bo`limlar"
        constraints = (
            models.UniqueConstraint(
                fields=["is_purchasing"],
                condition=models.Q(is_purchasing=True),
                name="only_one_purchasing_department",
                violation_error_message="Xarid bo`limi bitta bo`lishi kerak.",
            ),
        )


def purchasing_department_workers() -> list[AbstractBaseUser]:
    """The people an approved request is handed to: Xarid Bo`limi's own.

    Its Bo`lim Boshlig`i and its Menejer, the two who work Kelib Tushgan
    Arizalar. Empty while no department is marked as the purchasing one,
    because then there is nobody it could mean.
    """
    purchasing = purchasing_department()
    if purchasing is None:
        return []

    return [
        *users_of_type(BOLIM_BOSHLIGI, department=purchasing),
        *users_of_type(MENEJER, department=purchasing),
    ]


def purchasing_department_head() -> list[AbstractBaseUser]:
    """Xarid Bo`limi's Bo`lim Boshlig`i, on their own.

    Narrower than purchasing_department_workers() on purpose: a status
    moving is the head's business, and the Menejer hears about a contract
    when it is sent rather than every time it advances a step. Empty while
    no department is marked as the purchasing one, because then there is
    nobody it could mean.
    """
    purchasing = purchasing_department()
    if purchasing is None:
        return []

    return list(users_of_type(BOLIM_BOSHLIGI, department=purchasing))


def purchasing_department() -> Department | None:
    """The department that works arrived applications, or None while none is set.

    None is an ordinary state, not a fault: nothing declares one until an
    administrator ticks the box, and every page that asks has to keep working
    until they do.
    """
    return Department.objects.filter(is_purchasing=True, is_active=True).first()


class UserProfile(models.Model):
    """The department's own facts about an account.

    The type is held on a profile rather than on the account, so Django's
    default User model stays in place.
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
        Department,
        on_delete=models.PROTECT,
        related_name="users",
        null=True,
        blank=True,
        help_text=(
            "DEC-018: the Xarid Arizasi form fills the department in from "
            "whoever is signed in. Nullable so accounts created before "
            "departments existed still save."
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

    class Meta:
        verbose_name = "User Profile"
        verbose_name_plural = "User Profiles"

    def __str__(self) -> str:
        return f"{self.user.get_username()} ({self.user_type or 'no user type'})"


def user_type_of(user: AbstractBaseUser | AnonymousUser | None) -> UserType | None:
    """The active type assigned to this user, or None when they have none.

    None is a real answer rather than an error: an account can exist before
    anybody decides what it is for, and an anonymous visitor has no type at
    all. Every caller has to handle it - a user with no type is denied, never
    waved through. Read from the database on every call, so changing
    somebody's type takes effect on their next request.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return None

    profile = UserProfile.objects.filter(user=user).select_related("user_type").first()
    if profile is None:
        return None

    user_type = profile.user_type
    if user_type is None or not user_type.is_active:
        return None

    return user_type


def user_type_name_of(user: AbstractBaseUser | AnonymousUser | None) -> str:
    """The user's type as a display string, empty when they have none."""
    user_type = user_type_of(user)
    return user_type.name if user_type is not None else ""


def has_user_type(
    user: AbstractBaseUser | AnonymousUser | None,
    permitted_type_names: Iterable[str],
) -> bool:
    """Whether this user's type is one of the ones named.

    Raises:
        TypeError: when a bare string is passed instead of a collection, since
            a string is iterable and would quietly answer False for everybody.
    """
    if isinstance(permitted_type_names, str):
        raise TypeError("permitted_type_names is a collection of names, not one name.")

    user_type = user_type_of(user)
    if user_type is None:
        return False

    return user_type.name in set(permitted_type_names)


def users_of_type(type_name: str, department: Department | None = None) -> QuerySet:
    """The accounts a step may be waiting for: this type, optionally this department.

    The same two conditions has_user_type() and department_of() answer one
    person with, asked of everybody instead: an inactive type is no type, and
    a retired department is no department.

    Deactivated accounts are left out. The permission checks never ask -
    somebody who cannot sign in cannot reach a button either - but a list of
    who is awaited must not name somebody who will never come.
    """
    users = get_user_model().objects.filter(
        is_active=True,
        profile__user_type__name=type_name,
        profile__user_type__is_active=True,
    )
    if department is not None:
        users = users.filter(
            profile__department=department, profile__department__is_active=True
        )

    return users.order_by("first_name", "last_name", "username")


def profile_of(user: AbstractBaseUser) -> UserProfile:
    """This user's profile, created on first use.

    Accounts made with createsuperuser know nothing about profiles and still
    need one the moment somebody assigns them a type.
    """
    profile, _ = UserProfile.objects.get_or_create(user=user)
    return profile


def assign_user_type(user: AbstractBaseUser, user_type: UserType | None) -> UserProfile:
    """Give this user a type, or take theirs away when passed None."""
    profile = profile_of(user)
    profile.user_type = user_type
    profile.save(update_fields=["user_type"])
    return profile


def department_of(
    user: AbstractBaseUser | AnonymousUser | None,
) -> Department | None:
    """The active department this user belongs to, or None.

    None for an anonymous visitor, for somebody never given a department, and
    for somebody whose department has since been deleted (DEC-009 keeps the
    row for the records that point at it, not to keep offering it).
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return None

    profile = UserProfile.objects.filter(user=user).select_related("department").first()
    if profile is None:
        return None

    department = profile.department
    if department is None or not department.is_active:
        return None

    return department


def assignable_specialists() -> QuerySet:
    """The active Katta Mutaxasis accounts an application may be given to.

    Katta Mutaxasis and nobody else (DEC-024): a manager who can pick anybody
    can pick somebody with no Tayinlangan page to see the work on.

    Xarid Bo`limi's own, and not every Katta Mutaxasis in the enterprise.
    Accepting an arrived application and handing it out is the purchasing
    department's work, so its head hands it to their own people; a specialist
    in the department that asked for the purchase is not who does it.

    Every active Katta Mutaxasis while no purchasing department is named,
    which is an ordinary state rather than a fault - the page has to keep
    working until an administrator ticks the box.

    The answer is the drop-down on Qabul Qilingan Arizalar and the rule
    assign() checks, which are the same question asked twice: a name that is
    not offered must not be assignable by a request that names it anyway.
    """
    return users_of_type(KATTA_MUTAXASIS, department=purchasing_department())


# ---------------------------------------------------------------------------
# The lists the work is described with
# ---------------------------------------------------------------------------


class ArizaStatus(OrderedStatus):
    """A state an application can be in (section 3.5).

    Editable master data (DEC-017). The seeded rows carry a machine-readable
    code the workflow finds them by; a row an administrator adds has none and
    is never chosen automatically. A renamed row keeps its code.
    """

    class Code(models.TextChoices):
        """The rows the application itself relies on."""

        NEW = "new", "Yangi"
        ACCEPTED = "accepted", "Qabul qilingan"
        ASSIGNED = "assigned", "Tayinlangan"
        CANCELLED = "cancelled", "Bekor qilingan"

    name = models.CharField("Status Nomi", max_length=MASTER_DATA_NAME_LENGTH, unique=True)
    code = models.CharField(
        max_length=16,
        choices=Code.choices,
        blank=True,
        help_text=(
            "How the workflow finds this row. Set on the seeded statuses and "
            "empty on any an administrator adds."
        ),
    )

    class Meta:
        ordering = ("position", "name")
        constraints = [
            models.UniqueConstraint(
                fields=["code"],
                condition=~models.Q(code=""),
                name="unique_ariza_status_code",
            )
        ]
        verbose_name = "Ariza Status"
        verbose_name_plural = "Ariza Statuslari"

    @classmethod
    def with_code(cls, code: str) -> ArizaStatus | None:
        """The active row carrying this code, or None when it was deleted.

        None rather than an error: a master data page must not be able to stop
        the workflow, so an application is still accepted with no status.
        """
        return cls.objects.filter(code=code, is_active=True).first()


class ShartnomaStatus(OrderedStatus):
    """A state a contract can be in (section 3.5).

    The seeded rows are examples (DEC-010); reports generate one column per
    active status rather than assuming them.

    It carries no code column, deliberately and unlike ArizaStatus: DEC-010
    makes these rows an administrator invents, renames and retires, so no
    code here may name one.
    """

    name = models.CharField("Status Nomi", max_length=MASTER_DATA_NAME_LENGTH, unique=True)
    is_completed = models.BooleanField(
        "Tugallangan holat",
        default=False,
        help_text=(
            "A contract in this status is finished, and the dashboard counts "
            "it as completed. The statuses are editable (DEC-010), so which "
            "one means completed is marked here rather than named in the "
            "code. Only one status may hold the marker."
        ),
    )

    is_signed = models.BooleanField(
        "Tuzilgan holat",
        default=False,
        help_text=(
            "A contract in this status has been signed, and the dashboard "
            "counts it under Tuzilgan Shartnomalar. Marked here rather than "
            "named in the code, for the same reason the completed marker is "
            "(DEC-010). Only one status may hold the marker."
        ),
    )

    class Meta:
        ordering = ("position", "name")
        verbose_name = "Shartnoma Status"
        verbose_name_plural = "Shartnoma Statuslari"

    def save(self, *args, **kwargs) -> None:
        """Save, keeping each marker on at most one status.

        Marking this row takes that marker off whichever row held it, so each
        dashboard figure always has one definition however the page is used.
        The two markers are independent: a department whose workflow ends at
        signature may put both on the same row.
        """
        super().save(*args, **kwargs)
        for marker in ("is_completed", "is_signed"):
            if getattr(self, marker):
                type(self).objects.exclude(pk=self.pk).filter(**{marker: True}).update(
                    **{marker: False}
                )

    @classmethod
    def completed_status(cls) -> ShartnomaStatus | None:
        """The status marked as the completed state, or None when none is.

        None rather than an error: master data may be edited into a state
        where nothing is marked, and the dashboard then reports no completed
        contracts instead of failing to render.

        A deleted status still answers. Deleting deactivates (DEC-009), and a
        contract that reached the finished state stayed finished when the row
        naming that state left the lists; dropping it from the count would
        make the dashboard fall the moment somebody tidied the status list.
        The marker is what is being read here, not the list of statuses still
        on offer, which is why this does not use active() the way
        status_columns() does.
        """
        return cls.objects.filter(is_completed=True).first()

    @classmethod
    def signed_status(cls) -> ShartnomaStatus | None:
        """The status marked as the signed state, or None when none is.

        Answers on the same terms as completed_status(): None rather than an
        error when nothing is marked, and a deactivated row still answers,
        because a contract that was signed stayed signed when the row naming
        that state left the lists.
        """
        return cls.objects.filter(is_signed=True).first()


class MahsulotTuri(MasterDataRecord):
    """A product category (section 3.6).

    Its category number is unique, because the supplied form calls it a code
    and reports by category would merge two categories sharing one. It is not
    typed in unless somebody wants a particular number: left blank, the next
    one is taken, as a status left unplaced goes to the end of its list.
    """

    category_number = models.PositiveIntegerField(
        "Category Raqami",
        unique=True,
        blank=True,
        help_text=(
            "Olti xonali kod, bo'lim kategoriyani shu raqam bilan taniydi. "
            "Bo'sh qoldirilsa, keyingi raqam avtomatik beriladi."
        ),
    )
    name = models.CharField("Category Nomi", max_length=MASTER_DATA_NAME_LENGTH, unique=True)
    description = models.TextField("Tavsif", blank=True)

    class Meta:
        ordering = ("category_number",)
        verbose_name = "Mahsulot Turi"
        verbose_name_plural = "Mahsulot Turlari"

    def save(self, *args, **kwargs) -> None:
        """Number a new category when it was not numbered.

        In the model rather than in the form, so that a category created from
        the admin, from a shell or by a later page is numbered the same way as
        one created from the Mahsulot Turlari page.
        """
        if self.category_number is None:
            self.category_number = next_category_number(type(self))
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.category_number} - {self.name}"


class ShartnomaTuri(MasterDataRecord):
    """A kind of contract (section 3.7). Import and Local are seeded (DEC-023)."""

    name = models.CharField("Shartnoma Turi", max_length=MASTER_DATA_NAME_LENGTH, unique=True)

    class Meta:
        ordering = ("name",)
        verbose_name = "Shartnoma Turi"
        verbose_name_plural = "Shartnoma Turlari"


class Supplier(MasterDataRecord):
    """A Firma - a supplier the department buys from (DEC-011).

    Master data rather than a name typed into every contract, so the dashboard
    can count suppliers. Daraja is free text until the customer defines it
    (DEC-025).
    """

    name = models.CharField("Firma Nomi", max_length=MASTER_DATA_NAME_LENGTH, unique=True)
    inn = models.CharField(
        "Firma INN raqami",
        max_length=INN_LENGTH,
        blank=True,
        validators=[INN_FORMAT],
        help_text="Nine digits. Optional: a foreign supplier has no Uzbek INN.",
    )
    daraja = models.CharField("Daraja", max_length=32, blank=True)

    class Meta:
        ordering = ("name",)
        verbose_name = "Firma"
        verbose_name_plural = "Firmalar"
        constraints = [
            # Unique among the suppliers that have one, so several firms may
            # have no INN while no two share one.
            models.UniqueConstraint(
                fields=["inn"],
                condition=~models.Q(inn=""),
                name="unique_supplier_inn_when_given",
            )
        ]


# ---------------------------------------------------------------------------
# Numbering (DEC-022): PREFIX-YYYY-NNNNN, resetting each year.
# ---------------------------------------------------------------------------

ARIZA_NUMBER_PREFIX = "ARZ"
CONTRACT_NUMBER_PREFIX = "SHT"
XARID_NUMBER_PREFIX = "XA"
NUMBER_DIGITS = 5


def next_number(
    prefix: str, model: type[models.Model], field: str, today: date | None = None
) -> str:
    """The next number in one year's sequence.

    The highest number is found by sorting as text, which is correct because
    the sequence is zero-padded to a fixed width; the unique column turns a
    collision into an error rather than a duplicate. Call it inside the same
    transaction as the save.

    Args:
        prefix: the letters in front of the year, such as ARZ or XA.
        model: the model holding the sequence.
        field: the name of its number column.
        today: the date the year is taken from; today when omitted.
    """
    year = (today or date.today()).year
    start = f"{prefix}-{year}-"

    highest = (
        model.objects.filter(**{f"{field}__startswith": start})
        .order_by(f"-{field}")
        .values_list(field, flat=True)
        .first()
    )
    used = int(highest.removeprefix(start)) if highest else 0

    return f"{start}{used + 1:0{NUMBER_DIGITS}d}"


def next_ariza_raqami(today: date | None = None) -> str:
    """The next department application number for this year."""
    return next_number(ARIZA_NUMBER_PREFIX, Application, "ariza_raqami", today)


def next_shartnoma_raqami(today: date | None = None) -> str:
    """The next contract number for this year."""
    return next_number(CONTRACT_NUMBER_PREFIX, Contract, "shartnoma_raqami", today)


def next_xarid_raqami(today: date | None = None) -> str:
    """The next purchase application number for this year."""
    return next_number(XARID_NUMBER_PREFIX, PurchaseApplication, "xarid_raqami", today)


# ---------------------------------------------------------------------------
# Money and quantities
# ---------------------------------------------------------------------------

# The smallest order anybody can place: one thousandth, the finest the
# quantity column stores. Zero is refused too.
SMALLEST_QUANTITY = Decimal("0.001")

# One tiyin, the finest a money column stores (DEC-026).
SMALLEST_PRICE = Decimal("0.01")

# What every money amount is rounded to before it is stored or added up.
SOUM = Decimal("0.01")


def money_display(amount: Decimal) -> str:
    """An amount of soums grouped the Uzbek way: 125 000 000,00.

    Django renders 125000000.00 under LANGUAGE_CODE uz as "125000000,00",
    which reads as billions to most readers. The group separator is a
    non-breaking space so a browser cannot wrap an amount across two lines.
    """
    whole, _, fraction = f"{amount:.2f}".partition(".")

    return f"{int(whole):,}".replace(",", " ") + f",{fraction}"


# ---------------------------------------------------------------------------
# The application (section 4.1) and what it orders
# ---------------------------------------------------------------------------


class Application(models.Model):
    """One purchase application, as section 4.1 describes it.

    Its stage is a code the workflow branches on; its status is an ArizaStatus
    row a person reads. Every transition is a conditional write inside a
    transaction, so two simultaneous callers cannot both be told they did it.
    """

    class Stage(models.TextChoices):
        """Where an application has got to, in terms the code may rely on."""

        INCOMING = "incoming", "Kelib tushgan"
        ACCEPTED = "accepted", "Qabul qilingan"
        ASSIGNED = "assigned", "Tayinlangan"
        REJECTED = "rejected", "Inkor etilgan"

    ariza_raqami = models.CharField("Ariza raqami", max_length=32, unique=True)
    department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name="applications",
        verbose_name="Bo`lim nomi",
    )
    buyurtmachi_ismi = models.CharField(
        "Buyurtmachi ismi",
        max_length=255,
        blank=True,
        help_text="Who asked for this, as typed on the form (REQ-ARIZA-008).",
    )
    izoh = models.TextField("Izoh", blank=True)
    pdf = application_pdf_field()
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="submitted_applications",
        null=True,
        blank=True,
        verbose_name="Yuboruvchi",
        help_text="The requester whose purchase application raised this one.",
    )
    status = models.ForeignKey(
        ArizaStatus,
        on_delete=models.PROTECT,
        related_name="applications",
        null=True,
        blank=True,
        verbose_name="Status",
        help_text=(
            "The Ariza Status the work is in, which Tayinlangan Arizalar "
            "shows and its holder moves along. Nullable because DEC-017 lets "
            "an administrator delete every status, and a master data page "
            "must not stop the workflow."
        ),
    )
    kelib_tushgan_sana = models.DateTimeField("Kelib tushgan sana", auto_now_add=True)
    qabul_qilingan_sana = models.DateTimeField("Qabul qilingan sana", null=True, blank=True)
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="accepted_applications",
        null=True,
        blank=True,
        verbose_name="Qabul qilgan",
    )
    inkor_izohi = models.TextField(
        "Inkor izohi",
        blank=True,
        help_text="Why it was rejected; compulsory at the moment of rejection.",
    )
    inkor_qilingan_sana = models.DateTimeField("Inkor qilingan sana", null=True, blank=True)
    rejected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="rejected_applications",
        null=True,
        blank=True,
        verbose_name="Inkor qilgan",
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="assigned_applications",
        null=True,
        blank=True,
        verbose_name="Tayinlangan xodim",
        help_text="The Katta Mutaxasis this application is for (REQ-ARIZA-007).",
    )
    xodim_qabul_qilgan_sana = models.DateTimeField(
        "Xodim qabul qilgan sana",
        null=True,
        blank=True,
        help_text=(
            "When the assigned specialist took the work (REQ-ARIZA-013). "
            "Cleared when the application moves to somebody else."
        ),
    )
    tayinlangan_sana = models.DateTimeField(
        "Tayinlangan sana",
        null=True,
        blank=True,
        help_text="When the current assignment was made.",
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="applications_assigned_by_me",
        null=True,
        blank=True,
        verbose_name="Tayinlagan",
    )
    stage = models.CharField(max_length=16, choices=Stage.choices, default=Stage.INCOMING)

    class Meta:
        # Newest first: the department head works through what has just
        # arrived, not through what has been sitting there longest.
        ordering = ("-kelib_tushgan_sana", "-id")
        verbose_name = "Ariza"
        verbose_name_plural = "Arizalar"

    def __str__(self) -> str:
        return self.ariza_raqami

    @property
    def current_status_label(self) -> str:
        """Where this application has got to, as a report prints it.

        The contract's status when a contract has been raised, because that is
        the further along of the two, and the application's own stage
        otherwise. A display helper: it reads state, it does not decide it,
        and it is deliberately not the "application status follows the
        contract" behaviour of TASK-UZK-037 and 033 - which is absent from
        this codebase, so the statuses past Tayinlangan are unreachable until
        that work lands. The report shows what is there rather than what the
        specification's flow promises.
        """
        # contracts.all() rather than a fresh order_by: Contract.Meta already
        # orders newest first, and a queryset built here would ignore the
        # prefetch a list page sets up and go to the database once per row.
        contracts = list(self.contracts.all())
        latest = contracts[0] if contracts else None
        if latest is not None and latest.status is not None:
            return latest.status.name
        return self.get_stage_display()

    @property
    def is_incoming(self) -> bool:
        """Whether this application is still waiting to be decided."""
        return self.stage == self.Stage.INCOMING

    @property
    def is_assigned(self) -> bool:
        """Whether somebody is currently working on this application."""
        return self.stage == self.Stage.ASSIGNED

    @property
    def is_taken(self) -> bool:
        """Whether the holder has accepted this application."""
        return self.xodim_qabul_qilgan_sana is not None

    @transaction.atomic
    def accept(self, by: AbstractBaseUser) -> bool:
        """Accept this application, once.

        Moves it to the ACCEPTED stage, stamps the date and the decider, and
        attaches the accepted status when that row still exists.

        Returns:
            True when this call accepted it, False when somebody else already
            had - the second click of a double click is not an error.

        Raises:
            ValueError: when the application is not incoming, such as one
                already rejected.
        """
        self.refresh_from_db()

        if self.stage == self.Stage.ACCEPTED:
            return False

        if not self.is_incoming:
            raise ValueError(
                f"{self.ariza_raqami} is {self.stage}, not incoming, so it cannot be accepted."
            )

        decided_at = timezone.now()
        status = ArizaStatus.with_code(ArizaStatus.Code.ACCEPTED)

        # The condition is part of the write: the database compares the stage
        # while it holds the row, so the loser of a race cannot overwrite the
        # winner's date and acceptor.
        accepted = (
            type(self)
            .objects.filter(pk=self.pk, stage=self.Stage.INCOMING)
            .update(
                stage=self.Stage.ACCEPTED,
                qabul_qilingan_sana=decided_at,
                accepted_by=by,
                status=status,
            )
        )

        if not accepted:
            self.refresh_from_db()
            return False

        self.stage = self.Stage.ACCEPTED
        self.qabul_qilingan_sana = decided_at
        self.accepted_by = by
        self.status = status

        return True

    @transaction.atomic
    def reject(self, by: AbstractBaseUser, comment: str) -> bool:
        """Reject this application, once, with a reason (REQ-ARIZA-005).

        Returns:
            True when this call rejected it, False when it was already
            rejected.

        Raises:
            ValueError: when the comment is empty or only whitespace, or when
                the application is not incoming. Both leave the record as it
                was.
        """
        reason = (comment or "").strip()
        if not reason:
            raise ValueError(f"{self.ariza_raqami} cannot be rejected without a comment.")

        self.refresh_from_db()

        if self.stage == self.Stage.REJECTED:
            return False

        if not self.is_incoming:
            raise ValueError(
                f"{self.ariza_raqami} is {self.stage}, not incoming, so it cannot be rejected."
            )

        decided_at = timezone.now()
        status = ArizaStatus.with_code(ArizaStatus.Code.CANCELLED)

        rejected = (
            type(self)
            .objects.filter(pk=self.pk, stage=self.Stage.INCOMING)
            .update(
                stage=self.Stage.REJECTED,
                inkor_izohi=reason,
                inkor_qilingan_sana=decided_at,
                rejected_by=by,
                status=status,
            )
        )

        if not rejected:
            self.refresh_from_db()
            return False

        self.stage = self.Stage.REJECTED
        self.inkor_izohi = reason
        self.inkor_qilingan_sana = decided_at
        self.rejected_by = by
        self.status = status

        return True

    @transaction.atomic
    def assign(self, by: AbstractBaseUser, specialist: AbstractBaseUser | None) -> bool:
        """Give this application to a specialist, or to a different one.

        DEC-024 lets Admin re-assign at any time, including after the
        specialist accepted, so the same method does both. The previous
        holder's acceptance is cleared: the new holder has not taken anything.

        Returns:
            True when this call moved it, False when it was already with that
            specialist.

        Raises:
            ValueError: when the specialist is not an assignable Katta
                Mutaxasis, or the application is neither accepted nor assigned.
        """
        if specialist is None or not assignable_specialists().filter(pk=specialist.pk).exists():
            raise ValueError(
                f"{specialist} is not a Katta Mutaxasis, so "
                f"{self.ariza_raqami} cannot be assigned to them."
            )

        self.refresh_from_db()

        if self.assigned_to_id == specialist.pk:
            return False

        assignable = (self.Stage.ACCEPTED, self.Stage.ASSIGNED)
        if self.stage not in assignable:
            raise ValueError(f"{self.ariza_raqami} is {self.stage}, so it cannot be assigned.")

        decided_at = timezone.now()
        # Handing the work out is the first thing Tayinlangan Arizalar has to
        # report, so the status starts there rather than at whatever the row
        # carried on the page before. A re-assignment starts it again: the new
        # holder has not taken it, and their column should not say they have.
        status = ArizaStatus.with_code(ArizaStatus.Code.ASSIGNED)

        assigned = (
            type(self)
            .objects.filter(pk=self.pk, stage__in=assignable, assigned_to=self.assigned_to)
            .update(
                stage=self.Stage.ASSIGNED,
                assigned_to=specialist,
                assigned_by=by,
                tayinlangan_sana=decided_at,
                xodim_qabul_qilgan_sana=None,
                status=status,
            )
        )

        if not assigned:
            self.refresh_from_db()
            return False

        self.stage = self.Stage.ASSIGNED
        self.assigned_to = specialist
        self.assigned_by = by
        self.tayinlangan_sana = decided_at
        self.xodim_qabul_qilgan_sana = None
        self.status = status

        return True

    @transaction.atomic
    def accept_as_specialist(self, by: AbstractBaseUser | None) -> bool:
        """Record that the holder took this application (REQ-ARIZA-013).

        The stage does not move: assign() has to keep working afterwards.

        Returns:
            True when this call recorded it, False when it was already
            recorded.

        Raises:
            ValueError: when the application is not at the assigned stage, or
                is not assigned to this person.
        """
        self.refresh_from_db()

        if self.stage != self.Stage.ASSIGNED:
            raise ValueError(
                f"{self.ariza_raqami} is {self.stage}, not assigned, so "
                "there is nothing for a specialist to accept."
            )

        if by is None or self.assigned_to_id != getattr(by, "pk", None):
            raise ValueError(
                f"{self.ariza_raqami} is not assigned to {by}, so they cannot accept it."
            )

        if self.xodim_qabul_qilgan_sana is not None:
            return False

        accepted_at = timezone.now()
        # The second thing the page reports, and the last one the workflow
        # sets by itself: from here the holder moves the row along the Ariza
        # Statuses as the work actually reaches them.
        status = ArizaStatus.with_code(ArizaStatus.Code.ACCEPTED)

        taken = (
            type(self)
            .objects.filter(
                pk=self.pk,
                stage=self.Stage.ASSIGNED,
                assigned_to=by,
                xodim_qabul_qilgan_sana__isnull=True,
            )
            .update(xodim_qabul_qilgan_sana=accepted_at, status=status)
        )

        if not taken:
            self.refresh_from_db()
            return False

        self.xodim_qabul_qilgan_sana = accepted_at
        self.status = status

        return True

    @transaction.atomic
    def set_status(self, status: ArizaStatus | None) -> bool:
        """Mark the state this assigned application is currently in.

        Returns:
            True when this call changed it, False when it was already that
            status.

        Raises:
            ValueError: when status is None or inactive, or when this
                application is not one somebody is working on.
        """
        if status is None:
            raise ValueError(f"{self.ariza_raqami} needs a status to be set to.")

        if not status.is_active:
            raise ValueError(
                f"{status.name} is not in use, so {self.ariza_raqami} cannot be moved to it."
            )

        self.refresh_from_db()

        if self.stage != self.Stage.ASSIGNED:
            raise ValueError(
                f"{self.ariza_raqami} is {self.stage}, not assigned, so "
                "there is no work in progress to report a status for."
            )

        if self.status_id == status.pk:
            return False

        type(self).objects.filter(pk=self.pk).update(status=status)
        self.status = status

        return True

    @classmethod
    @transaction.atomic
    def raise_application(cls, items: Sequence[Mapping[str, object]], **fields) -> Application:
        """Create an application and its order lines in one transaction.

        The only way an application should be created, so that nothing ends up
        without a number.

        Args:
            items: one mapping of ApplicationItem fields per order line, in
                the order they should be read.
            **fields: the application's own columns.

        Raises:
            ValueError: when items is empty (REQ-ARIZA-010).
        """
        if not items:
            raise ValueError("An application needs at least one order line (REQ-ARIZA-010).")

        application = cls.objects.create(ariza_raqami=next_ariza_raqami(), **fields)
        ApplicationItem.objects.bulk_create(
            [ApplicationItem(application=application, **line) for line in items]
        )

        return application


class OrderLine(models.Model):
    """One line of what somebody ordered: what, how much, in what unit.

    Abstract and shared by the three line tables. The quantity floor is
    repeated as a named constraint on each concrete table.
    """

    buyurtma_nomi = models.CharField("Buyurtma nomi", max_length=255)
    buyurtma_soni = models.DecimalField(
        "Buyurtma soni",
        max_digits=12,
        decimal_places=3,
        validators=[MinValueValidator(SMALLEST_QUANTITY)],
    )
    olchov_birligi = models.CharField(
        "O`lchov birligi",
        max_length=16,
        help_text="ta, kg, m and so on. Free text (REQ-ARIZA-003).",
    )

    class Meta:
        abstract = True

    @property
    def soni_display(self) -> Decimal:
        """The quantity without the trailing zeros the column stores.

        Under LANGUAGE_CODE uz the decimal separator is a comma, so 2.500 would
        print as "2,500" and read as two and a half thousand.
        """
        quantity = self.buyurtma_soni.normalize()
        if quantity.as_tuple().exponent > 0:
            return quantity.quantize(Decimal(1))

        return quantity


class ApplicationItem(OrderLine):
    """One line of what an application orders (REQ-ARIZA-010)."""

    application = models.ForeignKey(
        Application,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="Ariza",
    )
    mahsulot_turi = models.ForeignKey(
        MahsulotTuri,
        on_delete=models.PROTECT,
        related_name="application_items",
        verbose_name="Mahsulot Turi",
    )

    class Meta:
        ordering = ("id",)
        verbose_name = "Ariza qatori"
        verbose_name_plural = "Ariza qatorlari"
        constraints = (
            models.CheckConstraint(
                condition=models.Q(buyurtma_soni__gte=SMALLEST_QUANTITY),
                name="order_line_quantity_is_positive",
                violation_error_message="Buyurtma soni noldan katta bo`lishi kerak.",
            ),
        )

    def __str__(self) -> str:
        return f"{self.buyurtma_nomi} - {self.soni_display} {self.olchov_birligi}"


# ---------------------------------------------------------------------------
# The contract (section 4.6)
# ---------------------------------------------------------------------------


class LiveContractManager(models.Manager):
    """Contracts that have not been deleted, which is nearly always the ones meant.

    Deleting a contract is reversible (TASK-UZK-064): the row stays and is
    marked, so that O`chirilgan Shartnomalar can show it and Tiklash can put
    it back. That only works if everything else stops seeing it, and there
    are seven places outside this module that ask for contracts - the two
    pages, the exports, the dashboard's three figures. Filtering here rather
    than at each of them is the difference between a deleted contract
    disappearing and a deleted contract disappearing from most places.

    Contract.all_objects is the way to the deleted ones, named so that asking
    for them is a decision rather than a default.
    """

    def get_queryset(self) -> models.QuerySet:
        return super().get_queryset().filter(deleted_at__isnull=True)


class Contract(models.Model):
    """One contract agreed against an application, as section 4.6 describes.

    Its value is the total of its priced rows (REQ-SHARTNOMA-006) and is
    computed by raise_contract() rather than supplied.

    Deleting one is reversible and never loses the row (TASK-UZK-064): see
    LiveContractManager above, and soft_delete() below.
    """

    class Stage(models.TextChoices):
        """Where a contract has got to, in terms the code may rely on."""

        AGREED = "agreed", "Kelishinlingan"
        SENT = "sent", "Tasdiqlashga yuborilgan"
        SIGNED = "signed", "Tuzilgan"
        REJECTED = "rejected", "Inkor etilgan"

    shartnoma_raqami = models.CharField("Shartnoma raqami", max_length=32, unique=True)
    application = models.ForeignKey(
        Application,
        on_delete=models.PROTECT,
        related_name="contracts",
        verbose_name="Ariza",
    )
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.PROTECT,
        related_name="contracts",
        verbose_name="Firma nomi",
    )
    shartnoma_turi = models.ForeignKey(
        ShartnomaTuri,
        on_delete=models.PROTECT,
        related_name="contracts",
        null=True,
        blank=True,
        verbose_name="Shartnoma turi",
    )
    qiymati = models.DecimalField(
        "Shartnoma qiymati",
        max_digits=18,
        decimal_places=2,
        validators=[MinValueValidator(SMALLEST_PRICE)],
        help_text="In UZS (DEC-026); the total of the goods rows.",
    )
    status = models.ForeignKey(
        ShartnomaStatus,
        on_delete=models.PROTECT,
        related_name="contracts",
        null=True,
        blank=True,
        verbose_name="Holati",
    )
    stage = models.CharField(max_length=16, choices=Stage.choices, default=Stage.AGREED)
    inkor_izohi = models.TextField("Izoh (Inkor etilgan)", blank=True)
    yuborilgan_sana = models.DateTimeField(
        "Tasdiqlashga yuborilgan sana",
        null=True,
        blank=True,
        help_text=(
            "When this contract was last sent for approval. A resend "
            "overwrites it rather than keeping one row per attempt: DEC-024 "
            "makes a resend the same act again."
        ),
    )
    yuborgan = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="sent_contracts",
        null=True,
        blank=True,
        verbose_name="Kim yuborgan",
    )
    tasdiqlagan = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="approved_contracts",
        null=True,
        blank=True,
        verbose_name="Kim tasdiqlagan",
    )
    tasdiqlangan_sana = models.DateTimeField("Tasdiqlangan sana", null=True, blank=True)
    inkor_qilgan = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="rejected_contracts",
        null=True,
        blank=True,
        verbose_name="Kim inkor qilgan",
    )
    inkor_sanasi = models.DateTimeField("Inkor qilingan sana", null=True, blank=True)
    yuborishlar_soni = models.PositiveIntegerField(
        "Necha marta yuborilgan",
        default=0,
        help_text=(
            "How many times this contract has gone for approval. The two "
            "columns above hold the last send and are overwritten by a "
            "resend, and the log TASK-UZK-052 builds cannot recover what was "
            "never recorded - a contract rejected and resent three times "
            "before that task ships would show one send and no sign of the "
            "other two. How many times it came back is the question the "
            "department will actually ask, and a count answers it without "
            "building that log early."
        ),
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="contracts",
        verbose_name="Kim shartnoma qilgan",
    )
    shartnoma_sanasi = models.DateField(
        "Shartnoma sanasi",
        null=True,
        blank=True,
        help_text="The date on the contract itself.",
    )
    tolash_muddati = models.DateField("To`lash muddati", null=True, blank=True)
    invoice_sanasi = models.DateField(
        "Invoice sanasi",
        null=True,
        blank=True,
        help_text=(
            "The date on the supplier's invoice. Added by DEC-025 so that the "
            "Invoice stage of the dashboard's processing time has a source; "
            "the document names the stage but models no invoice anywhere."
        ),
    )
    muddat_talabi = models.DateField("Muddat talabi", null=True, blank=True)
    izoh = models.TextField("Izoh", blank=True)
    pdf = contract_pdf_field()
    yaratilingan_sana = models.DateTimeField("Yaratilingan sana", auto_now_add=True)
    deleted_at = models.DateTimeField(
        "O`chirilgan sana",
        null=True,
        blank=True,
        help_text=(
            "When this contract was deleted. Null for a contract in use. "
            "Deleting never removes the row (TASK-UZK-064): an Admin restores "
            "it from O`chirilgan Shartnomalar, and a contract number that was "
            "issued is not issued twice."
        ),
    )
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="deleted_contracts",
        null=True,
        blank=True,
        verbose_name="Kim o`chirgan",
    )

    # all_objects first, so it is the base manager: reverse relations and
    # refresh_from_db() go through that one, and a base manager that hides
    # rows makes a deleted contract unreadable even to the page whose job is
    # to show it. objects is the default for everything that queries.
    all_objects = models.Manager()
    objects = LiveContractManager()

    class Meta:
        ordering = ("-yaratilingan_sana", "-id")
        verbose_name = "Shartnoma"
        verbose_name_plural = "Shartnomalar"
        base_manager_name = "all_objects"
        default_manager_name = "objects"

    def __str__(self) -> str:
        return f"{self.shartnoma_raqami} - {self.supplier.name}"

    # The stages in which a contract's terms may still be changed. A contract
    # awaiting somebody's approval, or already approved, having its rows or
    # its price rewritten is not something the specification describes.
    EDITABLE_STAGES = (Stage.AGREED, Stage.REJECTED)

    # The stages in which its progress may still be reported, which is a
    # different question and was the same one until TASK-UZK-039.
    #
    # REQ-ROLE-008 has the specialist keep changing a contract's status for
    # the life of the agreement, and DEC-010 seeds Yetkazib berilgan - a
    # contract is delivered after it is signed, not before. Sharing
    # EDITABLE_STAGES would mean approving a contract froze its status
    # forever, so that seeded status could never be reached and DEC-028's
    # "continues through its status chain" would be impossible.
    #
    # SENT is the stage that refuses: a contract awaiting a decision must not
    # change underneath the person making it.
    MOVABLE_STAGES = (Stage.AGREED, Stage.REJECTED, Stage.SIGNED)

    @property
    def is_rejected(self) -> bool:
        """Whether this contract was refused."""
        return self.stage == self.Stage.REJECTED

    @property
    def is_editable(self) -> bool:
        """Whether this contract's terms may still be changed."""
        return self.stage in self.EDITABLE_STAGES

    @property
    def status_may_move(self) -> bool:
        """Whether this contract's progress may still be reported.

        Not the same question as is_editable, although it was until
        TASK-UZK-039: a signed contract's terms are settled and its progress
        is not.
        """
        return self.stage in self.MOVABLE_STAGES

    @property
    def awaits_approval(self) -> bool:
        """Whether the department head still has to decide on this."""
        return self.stage == self.Stage.SENT

    @property
    def is_signed(self) -> bool:
        """Whether the department head approved this contract."""
        return self.stage == self.Stage.SIGNED

    @property
    def page_showing(self) -> str | None:
        """The page this contract is currently on, or None while it is on none.

        One place answers it, because two things ask: whoever wants to link to
        a contract, and whoever has to decide whether somebody may be told it
        exists at all.
        """
        return PAGE_SHOWING_CONTRACT.get(self.stage)

    @property
    def is_sent(self) -> bool:
        """Whether this contract is with the department head."""
        return self.stage == self.Stage.SENT

    @property
    def send_label(self) -> str:
        """What the send control reads (DEC-024).

        Re-Send after a rejection, Yuborish before one. Decided on the record
        rather than in the template, because it is a rule from a decision
        rather than a choice of words - and because the page is not the only
        thing that will ever ask.
        """
        return "Re-Send" if self.is_rejected else "Yuborish"

    @transaction.atomic
    def send_for_approval(self, by: AbstractBaseUser) -> bool:
        """Submit this contract to the department head (REQ-SHARTNOMA-005).

        The move out of the specialist's hands, which also takes the contract
        off the Kelishinlingan page: that page is the contracts still theirs
        to work on. A contract at the agreed stage has not been anywhere; a
        rejected one is coming back for a second time, which DEC-024
        describes and which is the same act rather than a different one.

        The rejection comment is not cleared. REQ-SHARTNOMA-004 gives it a
        column, the approver about to look at this contract again is the
        person most helped by seeing why it came back, and DEC-024 says
        nothing either way - so the comment stays and the stage is what says
        the contract has moved on.

        Args:
            by: the person sending it, recorded against the send.

        Returns:
            True when this call sent it, False when somebody else sent it
            between the read and the write.

        Raises:
            ValueError: when the contract is not one its specialist still
                holds. Which of the two that is - already awaiting approval,
                or already approved - is in the message, because being told
                the wrong one sends whoever reads it looking for a queue the
                contract left days ago.
        """
        self.refresh_from_db()

        if self.is_sent:
            raise ValueError(
                f"{self.shartnoma_raqami} allaqachon tasdiqlashga yuborilgan."
            )

        if not self.is_editable:
            raise ValueError(
                f"{self.shartnoma_raqami} allaqachon tasdiqlangan, yuborib "
                "bo`lmaydi."
            )

        sent_at = timezone.now()

        # Conditional on the stage, for the reason set_status() gives one
        # field along: two clicks landing together should send one contract
        # once, and count one send.
        moved = (
            type(self)
            .objects.filter(pk=self.pk, stage__in=self.EDITABLE_STAGES)
            .update(
                stage=self.Stage.SENT,
                yuborilgan_sana=sent_at,
                yuborgan=by,
                yuborishlar_soni=models.F("yuborishlar_soni") + 1,
            )
        )
        if not moved:
            self.refresh_from_db()
            return False

        self.stage = self.Stage.SENT
        self.yuborilgan_sana = sent_at
        self.yuborgan = by
        self.yuborishlar_soni += 1

        return True

    @transaction.atomic
    def accept(self, by: AbstractBaseUser) -> bool:
        """Approve this contract (REQ-SHARTNOMA-002).

        The department head's half of the send. REQ-SHARTNOMA-002 says an
        accepted contract is sent to the next department, and DEC-028 says
        there is no such department: nothing is built for it, the contract
        continues through the status chain TASK-UZK-037 gave it, and the gap
        stays visible rather than being filled with an invented integration.

        The status is not moved here either. DEC-028 has the contract continue
        through its chain, and TASK-UZK-037 made that chain something a person
        chooses rather than a consequence of somebody else's decision.

        Args:
            by: the person approving it, recorded as the decider.

        Returns:
            True when this call approved it, False when it was already
            approved - the second click of a double click.

        Raises:
            ValueError: when the contract is not awaiting approval. One still
                with its specialist has not been offered to anybody, and a
                rejected one has been decided already.
        """
        self.refresh_from_db()

        if self.is_signed:
            return False

        if not self.awaits_approval:
            raise ValueError(
                f"{self.shartnoma_raqami} tasdiqlashda turgani yo`q, "
                "tasdiqlab bo`lmaydi."
            )

        decided_at = timezone.now()
        decided = (
            type(self)
            .objects.filter(pk=self.pk, stage=self.Stage.SENT)
            .update(
                stage=self.Stage.SIGNED,
                tasdiqlagan=by,
                tasdiqlangan_sana=decided_at,
            )
        )
        if not decided:
            self.refresh_from_db()
            return False

        self.stage = self.Stage.SIGNED
        self.tasdiqlagan = by
        self.tasdiqlangan_sana = decided_at

        return True

    @transaction.atomic
    def reject(self, by: AbstractBaseUser, comment: str) -> bool:
        """Send this contract back to its specialist (REQ-SHARTNOMA-004).

        Where a rejection lands is the half worth stating: "returned back" is
        not a stage of its own. It is the contract sitting on the
        Kelishinlingan page again, with its comment in the column
        REQ-SHARTNOMA-004 gives it and the Re-Send control DEC-024 names -
        which is where its specialist left it.

        The comment is the point of a rejection rather than a decoration on
        it, so an empty or whitespace one is refused here and not only on the
        page: a page is one way in. Application.reject holds the same rule one
        section earlier for the same reason.

        Args:
            by: the person rejecting it, recorded as the decider.
            comment: why it came back. Required.

        Returns:
            True when this call rejected it, False when somebody decided it
            first.

        Raises:
            ValueError: when the comment is empty, or when the contract is not
                awaiting approval.
        """
        reason = (comment or "").strip()
        if not reason:
            raise ValueError(f"{self.shartnoma_raqami} inkor qilinmadi: izoh majburiy.")

        self.refresh_from_db()

        if not self.awaits_approval:
            raise ValueError(
                f"{self.shartnoma_raqami} tasdiqlashda turgani yo`q, "
                "inkor qilib bo`lmaydi."
            )

        decided_at = timezone.now()
        decided = (
            type(self)
            .objects.filter(pk=self.pk, stage=self.Stage.SENT)
            .update(
                stage=self.Stage.REJECTED,
                inkor_izohi=reason,
                inkor_qilgan=by,
                inkor_sanasi=decided_at,
            )
        )
        if not decided:
            self.refresh_from_db()
            return False

        self.stage = self.Stage.REJECTED
        self.inkor_izohi = reason
        self.inkor_qilgan = by
        self.inkor_sanasi = decided_at

        return True

    @property
    def last_status_change(self) -> ContractStatusChange | None:
        """The most recent move, or None while there has been none.

        Reads the whole list rather than slicing it, so a page that
        prefetched status_changes pays nothing here. A queryset sliced in a
        property is a query per row, which is what the review of the products
        page found and what the query-count test on this page guards.
        """
        changes = list(self.status_changes.all())

        return changes[0] if changes else None

    @transaction.atomic
    def set_status(self, status: ShartnomaStatus | None, by: AbstractBaseUser) -> bool:
        """Move this contract to a status (REQ-SHTSTATUS-001, REQ-ROLE-008).

        What "permitted" means here is narrower than the requirement sounds,
        and the narrowness is the point. DEC-010 makes the statuses rows an
        administrator invents and extends, and ShartnomaStatus carries no code
        column - deliberately, unlike ArizaStatus - so no code here can name a
        particular status, let alone draw a graph between two of them. A
        transition table over names would be a table the Shartnoma Status page
        could invalidate, which is the thing DEC-010 exists to prevent.

        So what is enforced is what the data can say: the status has to be one
        that is in use, the contract has to be one its specialist is still
        working on, and moving to the status it already has is not a move. The
        order the department works to is not in the specification and is not
        invented here.

        Every move writes a ContractStatusChange in this transaction, so a
        contract cannot arrive at a status with no record of how it got there.

        Args:
            status: the ShartnomaStatus to move to. Must be in use.
            by: the person making the move, recorded against it.

        Returns:
            True when this call moved it. False when it was already there, and
            False when somebody else moved it first - both are the same thing
            to the caller: this click changed nothing.

        Raises:
            ValueError: when status is None, when it is not in use, or when
                the contract has left the stages its specialist works in.
                Choosing nothing is not a way of clearing a status, a retired
                row is one an administrator has taken out of use, and a
                contract awaiting approval is not one to move.
        """
        if status is None:
            raise ValueError(f"{self.shartnoma_raqami} uchun holat tanlanmadi.")

        if not status.is_active:
            raise ValueError(
                f"{status.name} ishlatilmayapti, shuning uchun "
                f"{self.shartnoma_raqami} unga o`tkazilmaydi."
            )

        self.refresh_from_db()

        if not self.status_may_move:
            raise ValueError(
                f"{self.shartnoma_raqami} holatini o`zgartirib bo`lmaydi: "
                "shartnoma tasdiqlashda turibdi."
            )

        if self.status_id == status.pk:
            return False

        was = self.status_id

        # Conditional on the status it is moving from, so two clicks landing
        # together produce one move and one history row rather than two of
        # each - the guard accept_as_specialist() carries, on a table whose
        # whole purpose is to answer when a contract passed a status. The
        # check above is the cheap answer for an ordinary second click; this
        # is the one that holds when both arrive at once.
        moved = (
            type(self)
            .objects.filter(pk=self.pk, status_id=was, stage__in=self.MOVABLE_STAGES)
            .update(status=status)
        )
        if not moved:
            self.refresh_from_db()
            return False

        ContractStatusChange.objects.create(
            contract=self,
            from_status_id=was,
            to_status=status,
            changed_by=by,
        )
        self.status = status

        return True

    @transaction.atomic
    def update_terms(self, items: Sequence[Mapping[str, object]], **fields) -> None:
        """Rewrite this contract's terms and the goods it covers (TASK-UZK-064).

        The rows are replaced rather than matched up one by one: what comes
        back from the form is the contract's goods as they now stand, and a
        row somebody removed is a row that is not in it. The value is
        recomputed from what is left, never taken from a caller - the same
        rule raise_contract() enforces, for the same reason.

        Args:
            items: one mapping of ContractItem fields per row of goods, as
                the contract should now read.
            **fields: the contract's own columns to change. A column left
                out keeps what it has, which is how an edit that attaches no
                new PDF keeps the one on file.

        Raises:
            ValueError: when items is empty, when qiymati is passed, or when
                the contract has left the stages its terms may change in.
        """
        if "qiymati" in fields:
            raise ValueError(
                "A contract value is the sum of its rows (REQ-SHARTNOMA-006), "
                "not a field a caller sets."
            )

        if not items:
            raise ValueError("A contract needs at least one row of goods (REQ-SHARTNOMA-007).")

        if not self.is_editable:
            raise ValueError(
                f"{self.shartnoma_raqami} tahrirlanmadi: shartnoma allaqachon "
                "tasdiqlashga yuborilgan."
            )

        lines = [ContractItem(contract=self, **line) for line in items]

        self.items.all().delete()
        ContractItem.objects.bulk_create(lines)

        for column, value in fields.items():
            setattr(self, column, value)
        self.qiymati = contract_value_of(lines)

        self.save(update_fields=[*fields, "qiymati"])

    @transaction.atomic
    def undo_approval(self, by: AbstractBaseUser) -> bool:
        """Take an approval back, leaving the contract awaiting one again.

        Bekor Qilish beside the Tasdiqlangan badge (TASK-UZK-067). The
        approval is undone, not the contract: it stays on Tuzilgan, at the
        stage it was at before somebody decided, and can be approved or
        rejected again. Who approved it and when are cleared, because they
        describe a decision that no longer stands.

        The send is untouched - yuborilgan_sana, yuborgan and the count of
        sends are the specialist's act, not the approver's, and a contract
        that had been sent once has still been sent once.

        Args:
            by: the person taking it back. Not recorded on the contract; the
                audit log is where the act is kept.

        Returns:
            True when this call undid it, False when the contract was not
            approved - a second click, or two arriving together.
        """
        self.refresh_from_db()

        if not self.is_signed:
            return False

        # Conditional on the stage, for the reason set_status() gives: two
        # clicks landing together undo one approval.
        undone = (
            type(self)
            .objects.filter(pk=self.pk, stage=self.Stage.SIGNED)
            .update(stage=self.Stage.SENT, tasdiqlagan=None, tasdiqlangan_sana=None)
        )
        if not undone:
            self.refresh_from_db()
            return False

        self.stage = self.Stage.SENT
        self.tasdiqlagan = None
        self.tasdiqlangan_sana = None

        return True

    @property
    def is_deleted(self) -> bool:
        """Whether this contract has been deleted."""
        return self.deleted_at is not None

    def holders(self) -> list[AbstractBaseUser]:
        """The people whose contract this is, for anything that must tell them.

        The other side of own_contract_test(), which asks of one person
        whether a contract is theirs; this asks of one contract who those
        people are, and the two agree on purpose. A Katta Mutaxasis holds
        the contract their application was assigned to them; a Menejer or a
        Bo`lim Boshlig`i holds the one they entered. Both at once is
        ordinary - usually they are two different people, sometimes one.

        Returns:
            The holders, without repeats and without the empty places an
            unassigned application leaves.
        """
        by_id = {
            person.pk: person
            for person in (self.application.assigned_to, self.created_by)
            if person is not None
        }

        return list(by_id.values())

    @transaction.atomic
    def soft_delete(self, by: AbstractBaseUser) -> bool:
        """Take this contract off the working pages, keeping the row.

        Only while it is still its specialist's: a contract awaiting a
        decision, or one already approved, is not theirs to withdraw, and
        deleting what somebody else is deciding on is how a decision is made
        about a thing that is no longer there.

        Args:
            by: the person deleting it, recorded against the deletion.

        Returns:
            True when this call deleted it, False when it was already gone -
            a second click, or two arriving together.

        Raises:
            ValueError: when the contract has left the stages its specialist
                works in.
        """
        self.refresh_from_db()

        if self.is_deleted:
            return False

        if not self.is_editable:
            raise ValueError(
                f"{self.shartnoma_raqami} o`chirilmadi: shartnoma allaqachon "
                "tasdiqlashga yuborilgan."
            )

        deleted_at = timezone.now()
        # Conditional on the row still being undeleted, for the reason
        # set_status() gives: two clicks landing together delete once.
        gone = (
            type(self)
            .all_objects.filter(
                pk=self.pk, deleted_at__isnull=True, stage__in=self.EDITABLE_STAGES
            )
            .update(deleted_at=deleted_at, deleted_by=by)
        )
        if not gone:
            self.refresh_from_db()
            return False

        self.deleted_at = deleted_at
        self.deleted_by = by

        return True

    @transaction.atomic
    def restore(self, by: AbstractBaseUser) -> bool:
        """Put a deleted contract back on the page it came from.

        The stage it was deleted at is the stage it returns to: deleting does
        not move a contract along, so restoring does not either.

        Args:
            by: the person restoring it. Not recorded on the contract - the
                two columns say who deleted it, and they are cleared - the
                audit log is where the restore is kept.

        Returns:
            True when this call restored it, False when it was not deleted.
        """
        self.refresh_from_db()

        if not self.is_deleted:
            return False

        back = (
            type(self)
            .all_objects.filter(pk=self.pk, deleted_at__isnull=False)
            .update(deleted_at=None, deleted_by=None)
        )
        if not back:
            self.refresh_from_db()
            return False

        self.deleted_at = None
        self.deleted_by = None

        return True

    @property
    def qiymati_display(self) -> str:
        """The contract value, grouped so a person can read it."""
        return money_display(self.qiymati)

    @property
    def buyurtma_xulosasi(self) -> str:
        """The Buyurtma line of the Ko`rish dialog: one row, and how many more.

        A contract of one row reads as that row's name. A contract of several
        names the first and counts the rest, because the dialog lists them all
        underneath and a card repeating the table is a card nobody reads.

        Reads items.all() so a prefetched list is not thrown away.
        """
        rows = list(self.items.all())
        if not rows:
            return "—"

        if len(rows) == 1:
            return rows[0].buyurtma_nomi

        return f"{rows[0].buyurtma_nomi} +{len(rows) - 1} ta"

    @classmethod
    @transaction.atomic
    def raise_contract(cls, items: Sequence[Mapping[str, object]], **fields) -> Contract:
        """Create a contract and its goods rows in one transaction.

        Args:
            items: one mapping of ContractItem fields per row of goods.
            **fields: the contract's own columns, without qiymati.

        Raises:
            ValueError: when items is empty, or when qiymati is passed - the
                value is the sum of the rows, not a field a caller sets.
        """
        if "qiymati" in fields:
            raise ValueError(
                "A contract value is the sum of its rows (REQ-SHARTNOMA-006), "
                "not a field a caller sets."
            )

        if not items:
            raise ValueError("A contract needs at least one row of goods (REQ-SHARTNOMA-007).")

        lines = [ContractItem(**line) for line in items]
        contract = cls.objects.create(
            shartnoma_raqami=next_shartnoma_raqami(),
            qiymati=contract_value_of(lines),
            **fields,
        )
        for line in lines:
            line.contract = contract
        ContractItem.objects.bulk_create(lines)

        return contract


def contract_value_of(lines: Iterable[ContractItem]) -> Decimal:
    """What everything on a contract comes to, rounded to the soum.

    Takes the lines rather than the contract, so the entry form can total
    rows nobody has saved yet.
    """
    return sum((line.umumiy_narx for line in lines), Decimal("0")).quantize(
        SOUM, rounding=ROUND_HALF_UP
    )


# Which page shows a contract at each stage. A contract with its specialist is
# on Kelishinlingan; once it is sent it is on Tuzilgan, decided or not. The map
# is what decides whether somebody may be told a contract's number, the way
# PAGE_SHOWING_STAGE decides whether they may download an application.
PAGE_SHOWING_CONTRACT: dict[str, str] = {
    Contract.Stage.AGREED: "kelishinlingan",
    Contract.Stage.REJECTED: "kelishinlingan",
    Contract.Stage.SENT: "tuzilgan",
    Contract.Stage.SIGNED: "tuzilgan",
}


class ContractStatusChange(models.Model):
    """One move of a contract from one status to another (REQ-ROLE-010).

    The first history table in the application. Everything else here keeps the
    current state and nothing else - an application's status is a column that
    gets overwritten - because DEC-024 puts the history in the section 10 log
    and TASK-UZK-052 builds that.

    This one is not waiting for it. The specialist keeps changing a contract's
    state, and "keeps changing" is a sequence: a contract sitting at Yetkazib
    berilgan with no record of when it passed Shartnoma tuzilgan cannot answer
    what the department is asking. When TASK-UZK-052 builds the general log,
    this is what it reads for contracts rather than something it replaces.
    """

    contract = models.ForeignKey(
        Contract,
        on_delete=models.CASCADE,
        related_name="status_changes",
        verbose_name="Shartnoma",
    )
    from_status = models.ForeignKey(
        ShartnomaStatus,
        on_delete=models.PROTECT,
        related_name="moves_away",
        null=True,
        blank=True,
        verbose_name="Oldingi holat",
        help_text=(
            "Null for the first move. Contract.status is nullable because "
            "DEC-010 lets an administrator retire every status, so a contract "
            "can be entered with none - and the move away from nothing is the "
            "one most worth recording, not the one to refuse."
        ),
    )
    to_status = models.ForeignKey(
        ShartnomaStatus,
        on_delete=models.PROTECT,
        related_name="moves_here",
        verbose_name="Yangi holat",
    )
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="contract_status_changes",
        verbose_name="Kim o`zgartirgan",
    )
    changed_at = models.DateTimeField("O`zgartirilgan sana", auto_now_add=True)

    class Meta:
        # Newest first, so the first of status_changes is the last move -
        # which is what the page prints beneath the current status.
        ordering = ("-changed_at", "-id")
        verbose_name = "Shartnoma holati o`zgarishi"
        verbose_name_plural = "Shartnoma holati o`zgarishlari"

    def __str__(self) -> str:
        was = self.from_status.name if self.from_status_id else "-"

        return f"{self.contract.shartnoma_raqami}: {was} -> {self.to_status}"


class ContractItem(OrderLine):
    """One priced row of goods a contract covers (REQ-SHARTNOMA-006)."""

    contract = models.ForeignKey(
        Contract,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="Shartnoma",
    )
    part_number = models.CharField(
        "Part Number",
        max_length=64,
        blank=True,
        help_text="The supplier's own code for this item. Optional.",
    )
    narxi = models.DecimalField(
        "Narxi",
        max_digits=18,
        decimal_places=2,
        validators=[MinValueValidator(SMALLEST_PRICE)],
        help_text="The price of one, in UZS (DEC-026).",
    )

    class Meta:
        ordering = ("id",)
        verbose_name = "Shartnoma qatori"
        verbose_name_plural = "Shartnoma qatorlari"
        constraints = (
            models.CheckConstraint(
                condition=models.Q(buyurtma_soni__gte=SMALLEST_QUANTITY),
                name="contract_line_quantity_is_positive",
                violation_error_message="Miqdori noldan katta bo`lishi kerak.",
            ),
            models.CheckConstraint(
                condition=models.Q(narxi__gte=SMALLEST_PRICE),
                name="contract_line_price_is_positive",
                violation_error_message="Narxi noldan katta bo`lishi kerak.",
            ),
        )

    def __str__(self) -> str:
        return f"{self.buyurtma_nomi} - {self.umumiy_narx_display}"

    @property
    def umumiy_narx(self) -> Decimal:
        """Umumiy Narx: the price of one times how many, rounded to the soum."""
        return (self.narxi * self.buyurtma_soni).quantize(SOUM, rounding=ROUND_HALF_UP)

    @property
    def umumiy_narx_display(self) -> str:
        """The line total, grouped the way the contract value is."""
        return money_display(self.umumiy_narx)

    @property
    def narxi_display(self) -> str:
        """The unit price, grouped the way the line total is."""
        return money_display(self.narxi)


class ContractComment(models.Model):
    """One thing somebody wrote about a contract (TASK-UZK-066).

    The Izoh drawer shows three kinds of written text together: the note
    entered on the contract form, the reasons decisions carried, and these.
    Only these are written for their own sake - the other two are the
    by-product of an act - which is why only these are a table.

    Kept for the life of the contract and never edited: the drawer is read
    as a record of what was said and when, and a record somebody can go back
    and change is not one. Deleting the contract leaves them; restoring it
    brings them back with it.
    """

    contract = models.ForeignKey(
        Contract,
        on_delete=models.CASCADE,
        related_name="comments",
        verbose_name="Shartnoma",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="contract_comments",
        verbose_name="Kim yozgan",
    )
    matn = models.TextField("Izoh")
    created_at = models.DateTimeField("Yozilgan sana", auto_now_add=True)

    class Meta:
        # Oldest first: a thread is read downwards.
        ordering = ("created_at", "id")
        verbose_name = "Shartnoma izohi"
        verbose_name_plural = "Shartnoma izohlari"

    def __str__(self) -> str:
        return f"{self.contract.shartnoma_raqami}: {self.matn[:40]}"


# ---------------------------------------------------------------------------
# The purchase application (section 4.9) and DEC-016's approval chain
# ---------------------------------------------------------------------------


class PurchaseApplication(models.Model):
    """What a requester asks the purchasing department for (section 4.9).

    The other way in. The requester's own Bo`lim Boshlig`i approves first,
    then Direktor, and only then does the department's own Application appear
    on Kelib tushgan Arizalar. The department is filled from the requester's
    account (DEC-018), never typed.
    """

    class Stage(models.TextChoices):
        """Where in the approval chain this request has got to."""

        AWAITING_HEAD = "awaiting_head", "Bo`lim boshlig`i tasdig`ini kutmoqda"
        AWAITING_DIREKTOR = "awaiting_direktor", "Direktor tasdig`ini kutmoqda"
        APPROVED = "approved", "Tasdiqlangan"
        REJECTED = "rejected", "Inkor etilgan"

    xarid_raqami = models.CharField("Ariza raqami", max_length=32, unique=True)
    shartnoma_nomi = models.CharField(
        "Shartnoma nomi",
        max_length=255,
        help_text="What the purchase is for (REQ-ARIZA-015).",
    )
    department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name="purchase_applications",
        verbose_name="Bo`lim nomi",
        help_text="Filled from the requester's own account (DEC-018).",
    )
    muddat_talabi = models.DateField("Muddat talabi", null=True, blank=True)
    izoh = models.TextField("Izoh", blank=True)
    pdf = application_pdf_field()
    asl_pdf = models.FileField(
        "Asl ilova (PDF)",
        upload_to="arizalar/%Y/%m",
        storage=attachment_storage,
        blank=True,
        help_text=(
            "The attachment exactly as it was uploaded. Blank until an "
            "approval stamps pdf; from then on it names the original file."
        ),
    )
    status = models.ForeignKey(
        ArizaStatus,
        on_delete=models.PROTECT,
        related_name="purchase_applications",
        null=True,
        blank=True,
        verbose_name="Xozirgi holati",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="purchase_applications",
        verbose_name="Yaratgan",
    )
    yaratilingan_sana = models.DateTimeField("Yaratilingan sana", auto_now_add=True)
    stage = models.CharField(max_length=24, choices=Stage.choices, default=Stage.AWAITING_HEAD)
    tasdiqlagan_bolim_boshligi = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="purchase_applications_approved_as_head",
        null=True,
        blank=True,
        verbose_name="Tasdiqlagan bo`lim boshlig`i",
    )
    bolim_boshligi_sanasi = models.DateTimeField(
        "Bo`lim boshlig`i tasdiqlagan sana", null=True, blank=True
    )
    tasdiqlagan_direktor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="purchase_applications_approved_as_direktor",
        null=True,
        blank=True,
        verbose_name="Tasdiqlagan direktor",
    )
    direktor_sanasi = models.DateTimeField("Direktor tasdiqlagan sana", null=True, blank=True)
    inkor_izohi = models.TextField(
        "Inkor izohi",
        blank=True,
        help_text="Why it was refused; compulsory at the moment of refusal.",
    )
    inkor_qilgan = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="purchase_applications_rejected",
        null=True,
        blank=True,
        verbose_name="Inkor qilgan",
    )
    inkor_sanasi = models.DateTimeField("Inkor qilingan sana", null=True, blank=True)
    raised_application = models.OneToOneField(
        Application,
        on_delete=models.PROTECT,
        related_name="raised_from",
        null=True,
        blank=True,
        verbose_name="Yaratilgan ariza",
        help_text="The department's own application this became on approval.",
    )

    class Meta:
        ordering = ("-yaratilingan_sana", "-id")
        verbose_name = "Xarid arizasi"
        verbose_name_plural = "Xarid arizalari"

    def __str__(self) -> str:
        return f"{self.xarid_raqami} - {self.shartnoma_nomi}"

    @property
    def contract(self) -> Contract | None:
        """The contract formed from this request, or None while there is none.

        Three hops, any of which can be missing, and each missing hop is an
        ordinary state rather than a fault: a request that has not been
        approved has raised no department application, and one that has may
        have no contract against it yet.

        The newest when there is more than one. Nothing forbids a second
        contract against the same application, so the ordering Contract
        already declares is what decides - read as a list rather than a slice,
        so a page that prefetched the contracts pays nothing here.
        """
        if self.raised_application_id is None:
            return None

        contracts = list(self.raised_application.contracts.all())

        return contracts[0] if contracts else None

    @property
    def status_follows_contract(self) -> bool:
        """Whether what this request shows comes from its contract.

        The page asks so that it can say so. A status that silently changed
        from one table's word to another table's word would leave a requester
        with no way to tell why - and DEC-010 makes the two tables
        independent, so the words need not even look related.
        """
        contract = self.contract

        return contract is not None and contract.status_id is not None

    @property
    def shown_status(self) -> OrderedStatus | None:
        """The state this request is currently in (REQ-ARIZA-017).

        Section 4.9 has the current status change according to the contract's
        state, and the mapping is worth reading slowly: DEC-010 answered
        UNKNOWN-005 without defining any correspondence between an ArizaStatus
        and a ShartnomaStatus. An administrator extends the two tables
        independently, so a translation table written here would be invented
        in the code and invalidated by the next row somebody adds on either
        page. The contract's status is therefore shown as it is, and that is
        the whole mapping.

        Derived rather than copied. A column kept in step by a hook is out of
        step the first time something writes around the hook - and this record
        needs no column, because the contract knows its status and the request
        knows its contract. status is left exactly as it was, so the record
        still knows what it was raised as.

        Not the same as Application.current_status_label, which TASK-UZK-047
        added one model along: that answers a printed label for a report row,
        and this answers the status row itself, so a page can render its
        badge and its colour. Two questions that look alike and are not.
        """
        contract = self.contract
        if contract is not None and contract.status_id is not None:
            return contract.status

        return self.status

    @property
    def awaits_approval(self) -> bool:
        """Whether somebody still has to decide about this request."""
        return self.stage in (self.Stage.AWAITING_HEAD, self.Stage.AWAITING_DIREKTOR)

    def awaits(self, user: AbstractBaseUser | AnonymousUser | None) -> bool:
        """Whether this request is waiting for this particular person.

        The requester's *own* Bo`lim Boshlig`i first, then any Direktor: a
        department head approving another department's spending is what the
        chain exists to prevent.
        """
        if self.stage == self.Stage.AWAITING_HEAD:
            return (
                has_user_type(user, (BOLIM_BOSHLIGI,)) and department_of(user) == self.department
            )

        if self.stage == self.Stage.AWAITING_DIREKTOR:
            return has_user_type(user, (DIREKTOR,))

        return False

    def approval_chain(self) -> list[tuple[str, list[AbstractBaseUser]]]:
        """DEC-016's two steps and who may take each one, in order.

        The mirror of awaits(): that answers whether one person may decide
        this, and this answers who all of those people are at every step, so
        a document can name who is still to sign before any of them has.

        The requester's *own* department head first, then any Direktor - the
        same two conditions awaits() applies, asked the other way round. Each
        step is named by the user type that takes it.
        """
        return [
            (BOLIM_BOSHLIGI, list(users_of_type(BOLIM_BOSHLIGI, department=self.department))),
            (DIREKTOR, list(users_of_type(DIREKTOR))),
        ]

    def moved_past(self, user: AbstractBaseUser | AnonymousUser | None) -> bool:
        """Whether this request has gone beyond the step this person decides.

        A department head reaching for one already sent to Direktor is simply
        late; a Direktor reaching for one still waiting for the head is out of
        order, which is not the same thing.
        """
        decided = (self.Stage.APPROVED, self.Stage.REJECTED)

        if has_user_type(user, (BOLIM_BOSHLIGI,)) and department_of(user) == self.department:
            return self.stage != self.Stage.AWAITING_HEAD

        if has_user_type(user, (DIREKTOR,)):
            return self.stage in decided

        return False

    @transaction.atomic
    def approve(self, by: AbstractBaseUser) -> bool:
        """Take this request one step along DEC-016's chain.

        The department head's approval moves it to Direktor; Direktor's
        approval stamps the document and creates the department's own
        application, both records written together or neither.

        Returns:
            True when this call moved it, False when somebody else already had.

        Raises:
            ValueError: when this request is not waiting for this person.
        """
        self.refresh_from_db()

        if not self.awaits(by):
            raise ValueError(f"{self.xarid_raqami} is not waiting for {by} to approve it.")

        decided_at = timezone.now()
        was = self.stage

        if was == self.Stage.AWAITING_HEAD:
            moved = (
                type(self)
                .objects.filter(pk=self.pk, stage=was)
                .update(
                    stage=self.Stage.AWAITING_DIREKTOR,
                    tasdiqlagan_bolim_boshligi=by,
                    bolim_boshligi_sanasi=decided_at,
                )
            )
            if not moved:
                self.refresh_from_db()
                return False

            self.stage = self.Stage.AWAITING_DIREKTOR
            self.tasdiqlagan_bolim_boshligi = by
            self.bolim_boshligi_sanasi = decided_at

            return True

        # Stamped before the department's application is created, so what
        # that record shares is the approved document; and before the stage
        # is written, so a stamping failure never leaves an approved request
        # with an unstamped document.
        self.stamp_approval(by, decided_at)

        raised = self.raise_department_application()
        moved = (
            type(self)
            .objects.filter(pk=self.pk, stage=was)
            .update(
                stage=self.Stage.APPROVED,
                tasdiqlagan_direktor=by,
                direktor_sanasi=decided_at,
                raised_application=raised,
            )
        )
        if not moved:
            raised.delete()
            self.refresh_from_db()
            return False

        self.stage = self.Stage.APPROVED
        self.tasdiqlagan_direktor = by
        self.direktor_sanasi = decided_at
        self.raised_application = raised

        return True

    def stamp_approval(self, by: AbstractBaseUser, approved_at) -> bool:
        """Put the approval onto the document as a QR code (REQ-ARIZA-019).

        The original is kept in asl_pdf the first time this runs, pointing at
        the same stored file rather than copying its bytes.

        Returns:
            True when a stamp was applied, False when there was nothing to
            stamp - an application with no attachment is not refused over it.
        """
        from xarid.attachments import approval_payload, stamp_with_qr

        if not self.pdf:
            return False

        payload = approval_payload(self.xarid_raqami, by, approved_at)
        stamped = stamp_with_qr(self.pdf, payload, f"{self.xarid_raqami}-tasdiqlangan.pdf")

        if not self.asl_pdf:
            self.asl_pdf.name = self.pdf.name

        self.pdf.save(stamped.name, stamped, save=False)
        type(self).objects.filter(pk=self.pk).update(pdf=self.pdf.name, asl_pdf=self.asl_pdf.name)

        return True

    def raise_department_application(self) -> Application:
        """Turn this request into the department's own incoming application.

        The attachment is shared rather than copied: both records name the
        same stored file, so the race path in approve() can delete the
        application it just created without taking a file with it.
        """
        return Application.raise_application(
            items=[
                {
                    "mahsulot_turi": line.mahsulot_turi,
                    "buyurtma_nomi": line.buyurtma_nomi,
                    "buyurtma_soni": line.buyurtma_soni,
                    "olchov_birligi": line.olchov_birligi,
                }
                for line in self.items.all()
            ],
            department=self.department,
            buyurtmachi_ismi=(self.created_by.get_full_name() or self.created_by.username),
            izoh=self.izoh,
            pdf=self.pdf,
            sender=self.created_by,
        )

    @transaction.atomic
    def reject(self, by: AbstractBaseUser, comment: str) -> bool:
        """Refuse this request, with a reason, and notify the requester.

        Returns:
            True when this call refused it, False when it was already refused.

        Raises:
            ValueError: when the comment is empty or only whitespace, or when
                this request is not waiting for this person.
        """
        reason = (comment or "").strip()
        if not reason:
            raise ValueError(f"{self.xarid_raqami} cannot be refused without a comment.")

        self.refresh_from_db()

        if self.stage == self.Stage.REJECTED:
            return False

        if not self.awaits(by):
            raise ValueError(f"{self.xarid_raqami} is not waiting for {by} to decide it.")

        decided_at = timezone.now()
        refused = (
            type(self)
            .objects.filter(pk=self.pk, stage=self.stage)
            .update(
                stage=self.Stage.REJECTED,
                inkor_izohi=reason,
                inkor_qilgan=by,
                inkor_sanasi=decided_at,
                status=ArizaStatus.with_code(ArizaStatus.Code.CANCELLED),
            )
        )

        if not refused:
            self.refresh_from_db()
            return False

        self.refresh_from_db()
        Notification.tell_requester_of_rejection(self)

        return True

    @classmethod
    @transaction.atomic
    def raise_purchase_application(
        cls, items: Sequence[Mapping[str, object]], **fields
    ) -> PurchaseApplication:
        """Create a purchase application and its order lines in one write.

        Args:
            items: one mapping of PurchaseApplicationItem fields per line.
            **fields: the application's own columns.

        Raises:
            ValueError: when items is empty (REQ-ARIZA-015).
        """
        if not items:
            raise ValueError(
                "A purchase application needs at least one order line (REQ-ARIZA-015)."
            )

        application = cls.objects.create(xarid_raqami=next_xarid_raqami(), **fields)
        PurchaseApplicationItem.objects.bulk_create(
            [PurchaseApplicationItem(application=application, **line) for line in items]
        )

        return application


class PurchaseApplicationItem(OrderLine):
    """One line of what a purchase application asks for (REQ-ARIZA-015)."""

    application = models.ForeignKey(
        PurchaseApplication,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="Xarid arizasi",
    )
    mahsulot_turi = models.ForeignKey(
        MahsulotTuri,
        on_delete=models.PROTECT,
        related_name="purchase_application_items",
        verbose_name="Mahsulot Turi",
    )

    class Meta:
        ordering = ("id",)
        verbose_name = "Xarid arizasi qatori"
        verbose_name_plural = "Xarid arizasi qatorlari"
        constraints = (
            models.CheckConstraint(
                condition=models.Q(buyurtma_soni__gte=SMALLEST_QUANTITY),
                name="purchase_order_line_quantity_is_positive",
                violation_error_message="Buyurtma soni noldan katta bo`lishi kerak.",
            ),
        )

    def __str__(self) -> str:
        return f"{self.buyurtma_nomi} - {self.soni_display} {self.olchov_birligi}"


# ---------------------------------------------------------------------------
# Notifications: a record with a recipient, not a message with a transport
# ---------------------------------------------------------------------------


class Notification(models.Model):
    """Something one person should be told about one record.

    read_at stays null until the panel has actually shown it to them
    (TASK-UZK-054). Delivery is in-app and nothing else: a panel entry and an
    unread badge, no email and no SMS (DEC-012).
    """

    class Kind(models.TextChoices):
        """What happened. The wording belongs to whatever renders it."""

        SPECIALIST_ACCEPTED = "specialist_accepted", "Xodim arizani qabul qildi"
        PURCHASE_REJECTED = "purchase_rejected", "Xarid arizangiz inkor etildi"
        APPLICATION_ACCEPTED = "application_accepted", "Arizangiz qabul qilindi"
        APPLICATION_REJECTED = "application_rejected", "Arizangiz inkor etildi"
        # DEC-016's chain, told from both ends: the people a request has just
        # landed on, and the requester watching it move.
        PURCHASE_AWAITING_YOU = (
            "purchase_awaiting_you",
            "Yangi xarid arizasi tasdig`ingizni kutmoqda",
        )
        PURCHASE_ARRIVED = (
            "purchase_arrived",
            "Tasdiqlangan xarid arizasi xarid bo`limiga keldi",
        )
        PURCHASE_APPROVED_BY_HEAD = (
            "purchase_approved_by_head",
            "Xarid arizangiz bo`lim boshlig`i tomonidan tasdiqlandi",
        )
        PURCHASE_APPROVED = (
            "purchase_approved",
            "Xarid arizangiz tasdiqlandi",
        )
        # A contract leaving its specialist for the department head. Held
        # against the contract's own application, because a notification is
        # about an application or a purchase application and nothing else -
        # the contract's number and firma are in the izoh line.
        CONTRACT_SENT = (
            "contract_sent",
            "Shartnoma tasdiqlashga yuborildi",
        )
        # A contract advancing a step while its specialist still holds it.
        # Held against the application for the same reason CONTRACT_SENT is.
        CONTRACT_STATUS_CHANGED = (
            "contract_status_changed",
            "Shartnoma holati o`zgartirildi",
        )
        CONTRACT_COMMENTED = (
            "contract_commented",
            "Shartnoma bo`yicha yangi izoh",
        )
        # The decision, told to whoever the contract belongs to.
        CONTRACT_APPROVED = (
            "contract_approved",
            "Shartnomangiz tasdiqlandi",
        )
        CONTRACT_RETURNED = (
            "contract_returned",
            "Shartnomangiz inkor qilindi",
        )
        CONTRACT_APPROVAL_UNDONE = (
            "contract_approval_undone",
            "Shartnoma tasdig`i bekor qilindi",
        )

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
        verbose_name="Kimga",
    )
    application = models.ForeignKey(
        Application,
        on_delete=models.CASCADE,
        related_name="notifications",
        null=True,
        blank=True,
        verbose_name="Ariza",
    )
    purchase_application = models.ForeignKey(
        PurchaseApplication,
        on_delete=models.CASCADE,
        related_name="notifications",
        null=True,
        blank=True,
        verbose_name="Xarid arizasi",
    )
    kind = models.CharField(max_length=32, choices=Kind.choices)
    izoh = models.TextField(
        "Izoh",
        blank=True,
        help_text=(
            "The line of detail under the heading: the comment a decision "
            "carried, or what the notification is about. Kept here rather "
            "than read back from the record, so what somebody was told is "
            "what it said at the time."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at", "-id")
        verbose_name = "Bildirishnoma"
        verbose_name_plural = "Bildirishnomalar"
        constraints = (
            # A notification is about exactly one record.
            models.CheckConstraint(
                condition=(
                    models.Q(application__isnull=False, purchase_application__isnull=True)
                    | models.Q(application__isnull=True, purchase_application__isnull=False)
                ),
                name="notification_is_about_one_record",
                violation_error_message=(
                    "A notification is about an application or a purchase "
                    "application, not both and not neither."
                ),
            ),
        )

    def __str__(self) -> str:
        about = self.application or self.purchase_application

        return f"{self.get_kind_display()}: {about}"

    @classmethod
    def tell_of_specialist_acceptance(cls, application: Application) -> list[Notification]:
        """Tell the people whose work it was that a specialist took it up.

        Every active Admin, and Xarid Bo`limi's own Bo`lim Boshlig`i and
        Menejer - the two who handed the application out on Tayinlangan
        Arizalar, and so the two waiting to hear it was taken.

        Admin alone was the original rule, read from DEC-013's "Admin is the
        Xarid bo`lim boshlig`i". Where that head holds a Bo`lim Boshlig`i
        account rather than an Admin one, which is how the department is
        actually set up, it left the message with nobody to reach.

        Returns:
            The notifications produced; empty when there is nobody to tell,
            which is an ordinary state - no Admin, and no purchasing
            department named yet.
        """
        admins = get_user_model().objects.filter(is_active=True, profile__user_type__name=ADMIN)

        # By pk, so somebody who is both is told once.
        recipients = {
            person.pk: person for person in (*admins, *purchasing_department_workers())
        }

        return cls.objects.bulk_create(
            [
                cls(
                    recipient=person,
                    application=application,
                    kind=cls.Kind.SPECIALIST_ACCEPTED,
                )
                for person in recipients.values()
            ]
        )

    @classmethod
    def tell_requester_of_rejection(
        cls, purchase_application: PurchaseApplication
    ) -> Notification:
        """Tell a requester their purchase request was refused (REQ-ARIZA-020).

        The reason travels with it: a refusal a requester cannot read the
        reason for is a message telling them to go and ask.
        """
        return cls.objects.create(
            recipient=purchase_application.created_by,
            purchase_application=purchase_application,
            kind=cls.Kind.PURCHASE_REJECTED,
            izoh=purchase_application.inkor_izohi,
        )


# ---------------------------------------------------------------------------
# The log (section 10, REQ-LOG-001)
# ---------------------------------------------------------------------------


# How much of a record's label the log keeps. Long enough for every number,
# name and title the application produces; a label longer than this is cut
# rather than refused, because an audit entry is worth more than the tail of
# a name.
LABEL_LENGTH = 255


class AuditEntry(models.Model):
    """One thing the application did to one record, and who approved it.

    The nine columns REQ-LOG-001 names put a record's creation and its
    approval on one row - who, their department, what, when, which of
    created/edited/deleted, then the approver, their department, their
    comment and the approval time. So an approval is not a second entry: it
    completes the entry the creation left.

    The record is held as a name, a label and a plain integer rather than by
    foreign key, because an entry about a deletion has to outlive the record
    it describes. Deletion is deactivation here (DEC-009), so today the row
    survives anyway; the entry does not depend on that staying true.

    Entries are kept indefinitely and the application builds no way to edit
    or delete one (DEC-029). The only write after the fact is an approval
    filling in its half of a row.
    """

    class Action(models.TextChoices):
        """What was done, in the words section 10's column uses."""

        CREATED = "created", "Created"
        EDITED = "edited", "Edited"
        DELETED = "deleted", "Deleted"

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="audit_entries",
        verbose_name="Foydalanuvchi",
    )
    actor_department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name="audit_entries",
        null=True,
        blank=True,
        verbose_name="Foydalanuvchi bo`limi",
        help_text=(
            "The department the actor was in at the time. Recorded rather "
            "than read back from the account, so moving somebody between "
            "departments does not rewrite what the log says they did."
        ),
    )
    form_name = models.CharField(
        "Forma nomi",
        max_length=64,
        help_text="What kind of record it was, such as Firma or Shartnoma.",
    )
    record_label = models.CharField(
        "Yozuv",
        max_length=LABEL_LENGTH,
        help_text="What the record printed as when this happened.",
    )
    record_type = models.CharField(
        max_length=64,
        help_text=(
            "The model's label, such as xarid.supplier, for matching an "
            "approval to the creation it completes."
        ),
    )
    record_id = models.PositiveIntegerField(
        help_text=(
            "The record's primary key, as a number rather than a foreign "
            "key: an entry about a deleted record must outlive it."
        ),
    )
    action = models.CharField("Amal", max_length=16, choices=Action.choices)
    created_at = models.DateTimeField("Sana/Soat", auto_now_add=True)

    approver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="approved_audit_entries",
        null=True,
        blank=True,
        verbose_name="Tasdiqlovchi foydalanuvchi",
    )
    approver_department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name="approved_audit_entries",
        null=True,
        blank=True,
        verbose_name="Tasdiqlovchi bo`lim",
    )
    approval_comment = models.TextField("Tasdiq comment", blank=True)
    approved_at = models.DateTimeField("Tasdiq sanasi/vaqti", null=True, blank=True)
    approval_outcome = models.CharField(
        "Tasdiq natijasi",
        max_length=16,
        blank=True,
        help_text="Whether the decision approved the record or refused it.",
    )

    class Meta:
        ordering = ("-created_at", "-id")
        verbose_name = "Log yozuvi"
        verbose_name_plural = "Log yozuvlari"
        indexes = (models.Index(fields=["record_type", "record_id"]),)

    def __str__(self) -> str:
        return f"{self.get_action_display()}: {self.form_name} - {self.record_label}"

    @property
    def was_decided(self) -> bool:
        """Whether somebody has approved or refused this record."""
        return self.approved_at is not None
