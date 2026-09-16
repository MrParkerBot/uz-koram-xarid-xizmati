"""Which User Type may open which page.

The matrix is DEC-015, which supersedes section 11 of the specification -
section 11 lists only three roles, numbered 3 and 4 with no 1 and 2, and
assigns four pages to nobody at all.

Where DEC-015 says a role "additionally" has a page, the addition is read
against what section 11 gave that same role:

  Bo`lim Boshlig`i   section 11's "Bo`lim Boshligi - Menejer" list
                     + Xodimlar yuklamasi + the three Korhona xaridi reports
  Katta Mutaxasis    section 11's list + Tuzilgan Shartnomalar

That reading is recorded as an assumption rather than a certainty: DEC-013
splits "Bo`lim Boshligi - Menejer" into two roles that section 11 wrote as one,
so "additionally" has two possible baselines. The other reading would also give
Bo`lim Boshlig`i the Dashboard, Tuzilgan and Logs that DEC-015 grants Menejer.

Two pages DEC-015 names do not exist yet - "Xarid Arizasiga tasdiqlar"
(TASK-UZK-031) and "Top suppliers" (TASK-UZK-051). They are absent here rather
than guessed at; the task that builds each one adds its row, and a test fails
if any page is missing from this table.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps

from django.contrib.auth.models import AbstractBaseUser, AnonymousUser
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse

from accounts.roles import (
    ADMIN,
    BOLIM_BOSHLIGI,
    DIREKTOR,
    KATTA_MUTAXASIS,
    MENEJER,
    USERS,
    user_type_of,
)

# Section 11's list for "Bo`lim Boshligi - Menejer" (REQ-RUHSAT-002).
_SECTION_11_DEPARTMENT_HEAD = frozenset(
    {
        "kelib-arizalar",
        "qabul-arizalar",
        "tayinlangan",
        "kelishinlingan",
        "xarid-ariza",
    }
)

# Section 11's list for Katta Mutaxasis (REQ-RUHSAT-003).
_SECTION_11_SENIOR_SPECIALIST = frozenset(
    {"tayinlangan", "kelishinlingan", "xarid-ariza"}
)

# The three "Korhona xaridi" reports, which DEC-015 names as a group.
_ENTERPRISE_PURCHASE_REPORTS = frozenset(
    {"bolimlar", "mahsulot-tur", "mahsulotlar"}
)

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
    DIREKTOR: frozenset(
        {"dashboard", "kelib-arizalar", "tuzilgan", "xarid-ariza", "logs"}
    ),
    USERS: frozenset({"xarid-ariza"}),
}

# Pages nobody but Admin may open. Listed so that the test comparing this
# module against the URL configuration can tell "deliberately Admin-only" from
# "forgotten": the master data pages, the Users page and the 1C boundary.
ADMIN_ONLY_PAGES = frozenset(
    {
        "user-specialty",
        "user-types",
        "users",
        "ariza-status",
        "shartnoma-status",
        "mahsulot-turlari",
        "shartnoma-turi",
        # DEC-018. Not a page the specification describes; see
        # reference/department_views.py for why it exists.
        "bolim-royhati",
        # DEC-011, and invented for the same reason as bolim-royhati.
        "firmalar",
        "integration",
    }
)


def all_known_pages() -> frozenset[str]:
    """Every page this matrix has an answer for."""
    granted = frozenset().union(*PAGES_BY_USER_TYPE.values())
    return granted | ADMIN_ONLY_PAGES


def may_open(
    user: AbstractBaseUser | AnonymousUser | None, page_name: str
) -> bool:
    """Whether this user's type permits opening this page.

    Admin opens everything (DEC-015). A user with no type, a user whose type
    was deactivated, and an anonymous visitor open nothing: the answer is no
    rather than an error, so a caller cannot forget to handle it.
    """
    user_type = user_type_of(user)
    if user_type is None:
        return False

    if user_type.name == ADMIN:
        return True

    return page_name in PAGES_BY_USER_TYPE.get(user_type.name, frozenset())


def require_page_permission(page_name: str) -> Callable:
    """Wrap a view so that only the types DEC-015 permits reach it.

    Raises PermissionDenied rather than redirecting: the visitor is signed in
    and sending them to the login page would suggest signing in again would
    help.
    """

    def decorate(view: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
        @wraps(view)
        def permitted_view(request: HttpRequest, *args, **kwargs) -> HttpResponse:
            if not may_open(request.user, page_name):
                raise PermissionDenied(
                    f"{request.user} may not open {page_name}."
                )
            return view(request, *args, **kwargs)

        return permitted_view

    return decorate


def first_page_for(user: AbstractBaseUser | AnonymousUser | None) -> str | None:
    """The page to send this user to when they have not asked for one.

    The sidebar's own order, so that somebody lands on the first thing they
    would have clicked. None when they may open nothing at all - an account
    that exists but has been given no type.
    """
    from config.navigation import navigation_url_names

    for page_name in navigation_url_names():
        if may_open(user, page_name):
            return page_name

    return None
