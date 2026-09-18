"""Who may open which page, and who may edit contracts.

The page matrix is DEC-015, which supersedes section 11 of the specification.
Where DEC-015 says a role "additionally" has a page, the addition is read
against what section 11 gave that same role - recorded as an assumption, since
DEC-013 splits "Bo`lim Boshligi - Menejer" into two roles that section 11 wrote
as one.

Admin opens everything, and so does a Django superuser: createsuperuser knows
nothing about User Types, and an account that can administer everything through
/admin/ should not be locked out of the pages it administers.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import AbstractBaseUser, AnonymousUser
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpRequest, HttpResponse

from xarid.models import (
    ADMIN,
    BOLIM_BOSHLIGI,
    DIREKTOR,
    KATTA_MUTAXASIS,
    MENEJER,
    USERS,
    UserProfile,
    has_user_type,
    profile_of,
    user_type_of,
)
from xarid.navigation import navigation_page_names

# Section 11's list for "Bo`lim Boshligi - Menejer" (REQ-RUHSAT-002).
_SECTION_11_DEPARTMENT_HEAD = frozenset(
    {"kelib-arizalar", "qabul-arizalar", "tayinlangan", "kelishinlingan", "xarid-ariza"}
)

# Section 11's list for Katta Mutaxasis (REQ-RUHSAT-003).
_SECTION_11_SENIOR_SPECIALIST = frozenset({"tayinlangan", "kelishinlingan", "xarid-ariza"})

# The three "Korhona xaridi" reports, which DEC-015 names as a group.
_ENTERPRISE_PURCHASE_REPORTS = frozenset({"bolimlar", "mahsulot-tur", "mahsulotlar"})

PAGES_BY_USER_TYPE: dict[str, frozenset[str]] = {
    BOLIM_BOSHLIGI: _SECTION_11_DEPARTMENT_HEAD
    | _ENTERPRISE_PURCHASE_REPORTS
    | {"xodimlar-yuklamasi"},
    KATTA_MUTAXASIS: _SECTION_11_SENIOR_SPECIALIST | {"tuzilgan"},
    MENEJER: frozenset(
        {
            "dashboard",
            "kelib-arizalar",
            "qabul-arizalar",
            "tayinlangan",
            "kelishinlingan",
            "tuzilgan",
            "xarid-ariza",
            "logs",
        }
    ),
    DIREKTOR: frozenset({"dashboard", "kelib-arizalar", "tuzilgan", "xarid-ariza", "logs"}),
    USERS: frozenset({"xarid-ariza"}),
}

# Pages nobody but Admin may open, listed so a test can tell "deliberately
# Admin-only" from "forgotten".
ADMIN_ONLY_PAGES = frozenset(
    {
        "user-specialty",
        "user-types",
        "users",
        "ariza-status",
        "shartnoma-status",
        "mahsulot-turlari",
        "shartnoma-turi",
        "bolim-royhati",
        "firmalar",
        "integration",
    }
)


def all_known_pages() -> frozenset[str]:
    """Every page name this matrix has an answer for."""
    granted = frozenset().union(*PAGES_BY_USER_TYPE.values())
    return granted | ADMIN_ONLY_PAGES


def may_open(user: AbstractBaseUser | AnonymousUser | None, page_name: str) -> bool:
    """Whether this user may open this page.

    Admin and superusers open everything. A user with no type, a user whose
    type was deactivated, and an anonymous visitor open nothing.
    """
    if getattr(user, "is_superuser", False):
        return True

    user_type = user_type_of(user)
    if user_type is None:
        return False

    if user_type.name == ADMIN:
        return True

    return page_name in PAGES_BY_USER_TYPE.get(user_type.name, frozenset())


def require_page_permission(page_name: str) -> Callable:
    """Close a view to anonymous visitors and to types DEC-015 does not permit.

    An anonymous visitor is redirected to the login page by Django's own
    login_required. A signed-in visitor of the wrong type gets 403 rather than
    a redirect: sending them to the login page would suggest signing in again
    would help.
    """

    def decorate(view: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
        @wraps(view)
        def permitted_view(request: HttpRequest, *args, **kwargs) -> HttpResponse:
            if not may_open(request.user, page_name):
                raise PermissionDenied(f"{request.user} may not open {page_name}.")
            return view(request, *args, **kwargs)

        return login_required(permitted_view)

    return decorate


def first_page_for(user: AbstractBaseUser | AnonymousUser | None) -> str | None:
    """The page name to send this user to when they have not asked for one.

    The sidebar's own order, so that somebody lands on the first thing they
    would have clicked. None when they may open nothing at all.
    """
    for page_name in navigation_page_names():
        if may_open(user, page_name):
            return page_name

    return None


def acts_on_own_work_only(user: AbstractBaseUser | AnonymousUser | None) -> bool:
    """Whether this person may only touch the applications they hold.

    A Katta Mutaxasis may. Everybody else DEC-015 lets onto the Tayinlangan
    page hands work out and may touch all of it.
    """
    return has_user_type(user, (KATTA_MUTAXASIS,))


def contract_mover(user) -> Callable[[object], bool]:
    """A test of whether this person may move a contract, asked once.

    acts_on_own_work_only reads the person's user type, which is a query. A
    page of contracts asking it per row pays that per row, so the page asks
    here once and then only compares ids - the same defect the review of the
    products page found in a property.

    Args:
        user: the person asking.

    Returns:
        A predicate over one contract.
    """
    if not acts_on_own_work_only(user):
        return lambda contract: True

    holder = getattr(user, "pk", None)

    return lambda contract: contract.application.assigned_to_id == holder


def held_contract(user, contract) -> bool:
    """Whether this person may move this contract's status.

    Four user types may open the Kelishinlingan page, so page permission is
    not the whole answer: without a row-level rule a specialist could move a
    contract raised for somebody else's work, while the application half of
    the workflow refuses exactly that.

    Asked through the application's assignment rather than through who
    created the contract: DEC-024 lets an Admin re-assign at any time, and the
    contract goes with the work. Everybody the matrix lets onto the page who
    is not restricted to their own work may move any of them.

    Args:
        user: the person asking.
        contract: the contract they want to move.

    Returns:
        Whether the move is theirs to make.
    """
    return contract_mover(user)(contract)


# ---------------------------------------------------------------------------
# Contract editing: an exclusive lock that starts closed (DEC-021).
# ---------------------------------------------------------------------------


def contract_editor() -> UserProfile | None:
    """The one active user who may edit contracts, or None while nobody may."""
    return (
        UserProfile.objects.select_related("user")
        .filter(may_edit_contracts=True, user__is_active=True)
        .first()
    )


def may_edit_contracts(user: AbstractBaseUser | AnonymousUser | None) -> bool:
    """Whether this active user currently holds the contract-edit permission."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False

    return UserProfile.objects.filter(
        user=user, may_edit_contracts=True, user__is_active=True
    ).exists()


@transaction.atomic
def grant_contract_editing(user: AbstractBaseUser) -> UserProfile:
    """Give this user the permission, taking it from whoever held it.

    One statement clears every holder rather than only the one we believe in,
    so a database that somehow holds two is corrected.
    """
    UserProfile.objects.filter(may_edit_contracts=True).exclude(user=user).update(
        may_edit_contracts=False
    )

    profile = profile_of(user)
    profile.may_edit_contracts = True
    profile.save(update_fields=["may_edit_contracts"])
    return profile


def revoke_contract_editing(user: AbstractBaseUser) -> UserProfile:
    """Take the permission away, leaving nobody holding it."""
    profile = profile_of(user)
    profile.may_edit_contracts = False
    profile.save(update_fields=["may_edit_contracts"])
    return profile
