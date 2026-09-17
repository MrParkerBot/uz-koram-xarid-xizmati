"""Reading and deciding on a user's role.

Every question about what somebody may do resolves through here, so that the
answer comes from the database on each request. DEC-013's six types are named
once, as the constants the rest of the application refers to; the rows
themselves are master data that TASK-UZK-015 lets an administrator maintain.
"""

from __future__ import annotations

from collections.abc import Iterable

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractBaseUser, AnonymousUser
from django.db.models import QuerySet

from accounts.models import UserProfile, UserType
from reference.models import Department

# DEC-013. The spellings are the department's own, and they are what the rows
# in the database are called - a rename in one place without the other would
# silently lock people out, which is why TASK-UZK-012's matrix tests assert
# every one of these resolves.
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


def user_type_of(user: AbstractBaseUser | AnonymousUser | None) -> UserType | None:
    """The type assigned to this user, or None when they have none.

    None is a real answer rather than an error: an account can exist before
    anybody decides what it is for, and an anonymous visitor has no type at
    all. Every caller has to handle it, which is the point - a user with no
    type is denied, never waved through.
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

    Read from the database on every call rather than cached on the session, so
    that changing somebody's type takes effect on their next request rather
    than at their next sign-in.
    """
    if isinstance(permitted_type_names, str):
        raise TypeError(
            "permitted_type_names is a collection of names, not one name. A "
            f"bare string is iterable, so {permitted_type_names!r} would be "
            "compared against its own letters and this would quietly answer "
            "False for everybody."
        )

    user_type = user_type_of(user)
    if user_type is None:
        return False

    return user_type.name in set(permitted_type_names)


def profile_of(user: AbstractBaseUser) -> UserProfile:
    """This user's profile, created on first use.

    Accounts made before the profile existed - and any made with
    createsuperuser, which knows nothing about it - still need one the moment
    somebody assigns them a type.
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
    """The department this user belongs to, or None when they have none.

    The same three answers user_type_of gives, reached the same way: the
    department, None for somebody who has not been given one, and None for an
    anonymous visitor - so a caller cannot forget to handle the last two. A
    department that was deleted answers None as well, because DEC-009 keeps
    the row for the records that already point at it, not to keep offering it.

    DEC-018 has the Xarid Arizasi form fill the department in from whoever is
    signed in, and TASK-UZK-030 asks here rather than reaching into the
    profile itself.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return None

    profile = (
        UserProfile.objects.filter(user=user).select_related("department").first()
    )
    if profile is None:
        return None

    department = profile.department
    if department is None or not department.is_active:
        return None

    return department


def assignable_specialists() -> QuerySet:
    """The users an application may be given to (DEC-024).

    Katta Mutaxasis and nobody else: the drop-down REQ-ARIZA-007 describes
    names specialists, and a manager who can pick anybody can pick somebody
    who has no Tayinlangan page to see the work on.

    Active accounts only, so a person who has left is not offered new work.
    An assignment already made is left alone when an account is deactivated -
    taking work off somebody's list without saying so hides it from everybody
    rather than from them.

    Ordered by name, because a drop-down of people is read rather than
    scanned.
    """
    return (
        get_user_model()
        .objects.filter(
            is_active=True, profile__user_type__name=KATTA_MUTAXASIS
        )
        .order_by("first_name", "last_name", "username")
    )
