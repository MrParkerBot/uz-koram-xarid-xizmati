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

from urllib.parse import urlparse

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import AbstractBaseUser, AnonymousUser
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import Resolver404, resolve

from xarid.models import (
    ADMIN,
    BOLIM_BOSHLIGI,
    DIREKTOR,
    KATTA_MUTAXASIS,
    MENEJER,
    USERS,
    UserProfile,
    department_of,
    has_user_type,
    profile_of,
    purchasing_department,
    user_type_of,
)
from xarid.navigation import navigation_page_names

# Section 11's list for "Bo`lim Boshligi - Menejer" (REQ-RUHSAT-002).
_SECTION_11_DEPARTMENT_HEAD = frozenset(
    {"kelib-arizalar", "qabul-arizalar", "tayinlangan", "kelishinlingan", "xarid-ariza"}
)

# What is left of that list for a Bo`lim Boshlig`i outside the purchasing
# department. The rest of section 11's pages are the purchasing department's
# own work - accepting what arrives, handing it out, agreeing contracts - and
# a head elsewhere only raises requests, approves their department's, and
# reads back what they approved.
_OUTSIDE_THE_PURCHASING_DEPARTMENT = frozenset(
    {"kelib-arizalar", "qabul-arizalar", "xarid-ariza"}
)

# Section 11's list for Katta Mutaxasis (REQ-RUHSAT-003).
_SECTION_11_SENIOR_SPECIALIST = frozenset({"tayinlangan", "kelishinlingan", "xarid-ariza"})

# Top suppliers is not in DEC-015: the supplied sidebar had no such page and
# the matrix was written from it. It is granted to the types that may open the
# dashboard, because REQ-DASH-005 makes it the page the dashboard's own Top
# suppliers panel links to - the same figures, with room for all of them.
#
# Xarid Bo`limi's own head holds the dashboard, so they hold this too. A head
# outside the purchasing department holds neither, although they read the
# three Korhona xaridi reports: those say what the enterprise buys, and this
# says who it buys from and for how much, which DEC-015 only ever showed to
# the types holding the dashboard. It is the boundary most worth confirming.

# The three "Korhona xaridi" reports, which DEC-015 names as a group.
_ENTERPRISE_PURCHASE_REPORTS = frozenset({"bolimlar", "mahsulot-tur", "mahsulotlar"})

# Pages that are the purchasing department's own, whoever is asking: holding
# the type is not enough, the account has to be in that department.
#
# Firmalar is the list of who the company buys from. Its head, its Menejer and
# its Katta Mutaxasis are the people who deal with those firms and who know
# when a new one is needed, and waiting on an administrator to add one blocks
# the contract that needed it. A Menejer of some other department has no
# business editing it - which is a question about the department rather than
# about the type, so it is asked here rather than in the matrix.
_PURCHASING_DEPARTMENT_PAGES = frozenset({"firmalar"})

PAGES_BY_USER_TYPE: dict[str, frozenset[str]] = {
    BOLIM_BOSHLIGI: _SECTION_11_DEPARTMENT_HEAD
    | _ENTERPRISE_PURCHASE_REPORTS
    # These three reach Xarid Bo`limi's own head and no other, because
    # _OUTSIDE_THE_PURCHASING_DEPARTMENT does not hold them.
    #
    # Tuzilgan Shartnomalar: the contracts on it are the ones their
    # department agreed, and a head elsewhere has no business reading what
    # the company has committed to. Reading, not deciding -
    # decides_on_contracts() still answers Admin alone (DEC-013), so the page
    # renders for them without its controls.
    #
    # Asosiy Panel, and Top suppliers with it: the note above grants the
    # ranking to the types that may open the dashboard, because REQ-DASH-005
    # makes it the page the dashboard's own Top suppliers panel links to.
    # Granting one without the other would put a link on their dashboard
    # that answers 403, which is the thing navigation_groups() exists to
    # avoid.
    #
    # Mahsulot Turlari: the categories every application and every report is
    # written in terms of. They are the purchasing department's own
    # vocabulary - its head is who knows a new category is needed and what it
    # should be called - and waiting on an administrator to add one blocks the
    # request that needed it. A head elsewhere does not hold it: they raise
    # requests in the categories that exist.
    | {"xodimlar-yuklamasi", "tuzilgan", "dashboard", "top-suppliers", "mahsulot-turlari"}
    | _PURCHASING_DEPARTMENT_PAGES,
    KATTA_MUTAXASIS: _SECTION_11_SENIOR_SPECIALIST | {"tuzilgan"} | _PURCHASING_DEPARTMENT_PAGES,
    MENEJER: frozenset(
        {
            "dashboard",
            "top-suppliers",
            "kelib-arizalar",
            "qabul-arizalar",
            "tayinlangan",
            "kelishinlingan",
            "tuzilgan",
            "xarid-ariza",
            "logs",
        }
    )
    | _PURCHASING_DEPARTMENT_PAGES,
    DIREKTOR: frozenset(
        {
            "dashboard",
            "top-suppliers",
            "kelib-arizalar",
            # Read as Tasdiqlangan Arizalar: the second step of DEC-016's
            # chain is the Direktor's, so the requests they let through are
            # read back on the page that names them, as a head reads theirs.
            "qabul-arizalar",
            "tuzilgan",
            "xarid-ariza",
            "logs",
        }
    ),
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
        "shartnoma-turi",
        "bolim-royhati",
        "integration",
        # What O`chirish takes off Kelishinlingan, and where Tiklash puts it
        # back from (TASK-UZK-064). Admin alone: undoing somebody else's
        # deletion is an administrator's job, and the page is a list of
        # things the department has decided it does not have.
        "ochirilgan-shartnomalar",
    }
)


def all_known_pages() -> frozenset[str]:
    """Every page name this matrix has an answer for."""
    granted = frozenset().union(*PAGES_BY_USER_TYPE.values())
    return granted | ADMIN_ONLY_PAGES


def permitted_pages(user: AbstractBaseUser | AnonymousUser | None) -> frozenset[str]:
    """Every page this user may open, worked out in one go.

    may_open() asks about one page and is what a view checks; this is the
    same rule asked once for a whole menu, so rendering the sidebar costs one
    look at who somebody is rather than one per link.

    Admin and superusers open everything. A user with no type, a user whose
    type was deactivated, and an anonymous visitor open nothing.
    """
    if getattr(user, "is_superuser", False):
        return all_known_pages()

    user_type = user_type_of(user)
    if user_type is None:
        return frozenset()

    if user_type.name == ADMIN:
        return all_known_pages()

    permitted = PAGES_BY_USER_TYPE.get(user_type.name, frozenset())

    if user_type.name == BOLIM_BOSHLIGI and not works_arrived_applications(user):
        return permitted & _OUTSIDE_THE_PURCHASING_DEPARTMENT

    if not belongs_to_the_purchasing_department(user):
        return permitted - _PURCHASING_DEPARTMENT_PAGES

    return permitted


def may_open(user: AbstractBaseUser | AnonymousUser | None, page_name: str) -> bool:
    """Whether this user may open this page."""
    return page_name in permitted_pages(user)


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


def page_or_landing(page_name: str) -> Callable:
    """Close a view that is also a way in, sending a refusal somewhere useful.

    require_page_permission() answers 403, which is the right answer for a
    page somebody asked for by name: they had to type the URL or follow a link
    the sidebar never drew for them.

    The site root is not that. It is where a browser goes when it is given the
    host and nothing else, and where a bookmark of "the application" points,
    so somebody arrives there without having chosen it. Three of the six types
    may not open the dashboard that answers there (DEC-015), and answering
    them 403 for visiting the application is a refusal of the address rather
    than of anything they did. They are sent to their own first page instead.
    """

    def decorate(view: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
        @wraps(view)
        def permitted_view(request: HttpRequest, *args, **kwargs) -> HttpResponse:
            if may_open(request.user, page_name):
                return view(request, *args, **kwargs)

            return redirect("xarid:landing")

        return login_required(permitted_view)

    return decorate


def page_behind(url: str) -> str | None:
    """The page name a URL belongs to, or None when it is not one of them.

    Used to ask whether somewhere a person is about to be sent is somewhere
    they may go. A URL that is not a page in the matrix - their own
    notifications, an attachment, an action - answers None, which means "this
    is not a question the matrix answers" rather than "refuse it".
    """
    try:
        match = resolve(urlparse(url).path)
    except (Resolver404, ValueError):
        return None

    return match.url_name if match.url_name in all_known_pages() else None


def may_be_sent_to(user: AbstractBaseUser | AnonymousUser | None, url: str) -> bool:
    """Whether landing on this URL would work for this user, rather than 403.

    What ?next= is checked against after a sign-in: the login page carries
    wherever the visitor was turned away from, and that may be a page their
    account may not open - one person signing out and another signing in on
    the same browser is the ordinary way it happens.
    """
    page_name = page_behind(url)

    return page_name is None or may_open(user, page_name)


def first_page_for(user: AbstractBaseUser | AnonymousUser | None) -> str | None:
    """The page name to send this user to when they have not asked for one.

    The sidebar's own order, so that somebody lands on the first thing they
    would have clicked. None when they may open nothing at all.
    """
    permitted = permitted_pages(user)
    for page_name in navigation_page_names():
        if page_name in permitted:
            return page_name

    return None


def acts_on_own_work_only(user: AbstractBaseUser | AnonymousUser | None) -> bool:
    """Whether this person may only touch the applications they hold.

    A Katta Mutaxasis may. Everybody else DEC-015 lets onto the Tayinlangan
    page hands work out and may touch all of it.
    """
    return has_user_type(user, (KATTA_MUTAXASIS,))


def reads_own_requests_only(user: AbstractBaseUser | AnonymousUser | None) -> bool:
    """Whether Xarid Arizasi shows this person only the requests they raised.

    Everybody but an Admin, whatever their type. The page is where a request
    is raised and followed, so what it holds is the reader's own; the requests
    an approver has to read in order to decide them are on Kelib Tushgan
    Arizalar, and the ones they decided are on Tasdiqlangan Arizalar, each
    under the heading that says what the list is. An Admin keeps every row,
    because maintaining the system means being able to see what is in it.

    Asked the way permitted_pages() asks it, so that "Admin" means the same
    thing in both places: the user type, or a superuser standing in for one.
    An account whose type is unrecognised or deactivated falls to its own
    requests rather than to all of them, which is the safe direction to fall.

    This governs the table, not the attachments: a head still opens the PDF
    of a request standing at their step, because deciding it blind is not
    deciding it. readable_purchase_application() carries that rule.
    """
    if getattr(user, "is_superuser", False):
        return False

    return not has_user_type(user, (ADMIN,))


def belongs_to_the_purchasing_department(user: AbstractBaseUser | AnonymousUser | None) -> bool:
    """Whether this account is in Xarid Bo`limi, for the pages that are its own.

    Falls closed while no department is marked as the purchasing one, unlike
    works_arrived_applications() which falls open. The two answer different
    questions: that one keeps a queue working until an administrator ticks the
    box, and a queue opening to everybody who may see it costs a muddle. This
    one decides who may edit the list of firms the company buys from, and
    until the department is named nobody has been put in it - so the page
    stays where it was, with Admin.

    Admin is in every department for this purpose, as everywhere else.
    """
    if has_user_type(user, (ADMIN,)):
        return True

    purchasing = purchasing_department()

    return purchasing is not None and department_of(user) == purchasing


def works_arrived_applications(user: AbstractBaseUser | AnonymousUser | None) -> bool:
    """Whether this person works the applications that have arrived.

    Kelib Tushgan Arizalar belongs to the purchasing department: its Bo`lim
    Boshlig`i and its Menejer are who an approved request is handed to, and a
    head of some other department opens the page for their own approval queue
    rather than to accept somebody else's work.

    Admin and Direktor keep the whole queue: one maintains the system and the
    other sits above every department in DEC-016's chain.

    While no department is marked as the purchasing one, everybody DEC-015
    lets onto the page keeps what they had. The mark is a switch an
    administrator has to throw, and a queue that emptied itself the moment
    this shipped would be a fault, not a policy.
    """
    if has_user_type(user, (ADMIN, DIREKTOR)):
        return True

    purchasing = purchasing_department()
    if purchasing is None:
        return True

    if has_user_type(user, (BOLIM_BOSHLIGI, MENEJER)):
        return department_of(user) == purchasing

    return False


def sees_own_approvals(user: AbstractBaseUser | AnonymousUser | None) -> bool:
    """Whether Qabul Qilingan Arizalar is this person's own approvals instead.

    A Bo`lim Boshlig`i outside the purchasing department never accepts an
    application: accepting is what the purchasing department does with what
    arrives. What that head has on the page is the other half of the same
    word - the purchase requests they themselves approved on their way
    through DEC-016's chain - so the page and its sidebar entry say
    Tasdiqlangan rather than Qabul Qilingan.

    A Direktor reads it the same way, for the same reason: the chain's second
    approval is theirs, and a request they let through leaves their queue and
    is read back here. Accepting what arrived stays the purchasing
    department's, and a Direktor was never given that page.

    Otherwise the mirror of works_arrived_applications(): a head who does
    work the arrived queue keeps the page exactly as it was.
    """
    if has_user_type(user, (DIREKTOR,)):
        return True

    return has_user_type(user, (BOLIM_BOSHLIGI,)) and not works_arrived_applications(user)


def decides_on_contracts(user) -> bool:
    """Whether this person is one of those who approve a contract.

    Admin, and Xarid Bo`limi's own Bo`lim Boshlig`i and Menejer
    (TASK-UZK-067). REQ-SHARTNOMA-002 gives the decision to the department
    head, and DEC-013 read that as Admin because "Admin is the Xarid bo`lim
    boshlig`i"; where the department is actually staffed, the head and the
    manager hold accounts of their own two types, and the decision is
    theirs. Admin keeps it as well - a contract nobody left in the office
    can decide is a contract that stops.

    Its own, not any: a Bo`lim Boshlig`i of another department cannot open
    the page at all, and a Menejer elsewhere has no business approving what
    this department has committed to.

    Four user types may open the Tuzilgan page and not all of them decide,
    so the route asks this as well as the template.

    Args:
        user: the person asking.

    Returns:
        Whether the decision is theirs to make.
    """
    if has_user_type(user, (ADMIN,)):
        return True

    if not has_user_type(user, (BOLIM_BOSHLIGI, MENEJER)):
        return False

    # Not works_arrived_applications(), which falls open while no purchasing
    # department is named so that its queue keeps working until an
    # administrator ticks the box. This one falls closed: the queue opening
    # to everybody who may see it costs a muddle, and the approval opening
    # to everybody who may see it commits the company. Until the department
    # is named, the decision stays where DEC-013 left it.
    purchasing = purchasing_department()

    return purchasing is not None and department_of(user) == purchasing


def moves_status_on_tuzilgan(user: AbstractBaseUser | AnonymousUser | None) -> bool:
    """Whether this person may still move a status from Tuzilgan Shartnomalar.

    Everybody the matrix lets onto the page except a Katta Mutaxasis
    (TASK-UZK-068). A contract on this page has left their hands: it is
    waiting on a decision or has had one, and the drop-down there let them
    keep changing something they no longer hold. Kelishinlingan is where
    they report progress, and what is on Tuzilgan is theirs to read.

    The route behind the control is shared with Kelishinlingan and still
    answers held_contract(), so this narrows what is drawn rather than what
    is permitted; signed_contract_status_may_move() is where the two meet.
    """
    return not has_user_type(user, (KATTA_MUTAXASIS,))


def own_contract_test(user) -> Callable[[object], bool]:
    """A test of whether a contract is this person's to act on, asked once.

    Three answers, because "own" means a different thing to each type:

    A Katta Mutaxasis holds the work, so a contract is theirs when the
    application behind it was assigned to them (REQ-ROLE-007).

    A Menejer and a Bo`lim Boshlig`i hold no assignment - they hand work out
    rather than take it - so what is theirs is what they entered themselves
    (TASK-UZK-064). Everything else on Kelishinlingan they read: the
    specialist working a contract is the one who changes it, and a contract
    being edited or withdrawn by somebody who is not working it is the thing
    that rule exists to prevent.

    An Admin holds everything, which is what maintaining the system means.

    The type is read once here rather than per row: it is a query, and a page
    of contracts asking it per row pays that per row - the same defect the
    review of the products page found in a property.

    Args:
        user: the person asking.

    Returns:
        A predicate over one contract.
    """
    asking = getattr(user, "pk", None)

    if acts_on_own_work_only(user):
        return lambda contract: contract.application.assigned_to_id == asking

    if has_user_type(user, (MENEJER, BOLIM_BOSHLIGI)):
        return lambda contract: contract.created_by_id == asking

    return lambda contract: True


def held_contract(user, contract) -> bool:
    """Whether this contract is this person's to change, send or withdraw.

    Four user types may open the Kelishinlingan page, so page permission is
    not the whole answer: without a row-level rule a specialist could move a
    contract raised for somebody else's work, while the application half of
    the workflow refuses exactly that.

    One question behind every control in the row - the status drop-down,
    Saqlash, Tahrirlash, Yuborish and O`chirish - so that what a person can
    press and what the route will accept cannot drift apart. What counts as
    theirs is own_contract_test's to say.

    Args:
        user: the person asking.
        contract: the contract they want to act on.

    Returns:
        Whether it is theirs to act on.
    """
    return own_contract_test(user)(contract)


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
