"""Who may edit an entered contract.

The specification's Users page carries an "Edit Permission" switch, and
CONFLICT-001 - section 3.3 says the permission is open by default while
section 3.4 says only one person may hold it - was settled by DEC-021: an
exclusive lock, off by default. At most one user holds it, granting it to
somebody takes it from whoever had it, and nobody holds it until Admin grants
it.

The exclusivity is enforced here rather than by a database constraint. A
unique index cannot express "at most one row is true" portably, and expressing
it by hand would leave the rule in two places.
"""

from __future__ import annotations

from django.contrib.auth.models import AbstractBaseUser
from django.db import transaction

from accounts.models import UserProfile
from accounts.roles import profile_of


def contract_editor() -> UserProfile | None:
    """The one user who may edit contracts, or None while nobody may.

    None is the state every installation starts in (DEC-021), not an error.
    """
    return (
        UserProfile.objects.select_related("user")
        .filter(may_edit_contracts=True, user__is_active=True)
        .first()
    )


def may_edit_contracts(user: AbstractBaseUser | None) -> bool:
    """Whether this user currently holds the contract-edit permission."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False

    return UserProfile.objects.filter(
        user=user, may_edit_contracts=True
    ).exists()


@transaction.atomic
def grant_contract_editing(user: AbstractBaseUser) -> UserProfile:
    """Give this user the permission, taking it from whoever held it.

    One statement clears every holder rather than only the one we believe in,
    so that a database that somehow holds two - restored from a backup, edited
    by hand - is corrected rather than left with the rule quietly broken.
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
