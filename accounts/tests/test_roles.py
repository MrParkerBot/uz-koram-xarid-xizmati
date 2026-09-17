"""Tests for the role model and role assignment of TASK-UZK-010.

The question these answer is not "can a role be stored" but "who is denied".
An unassigned account, an account whose type was retired, and an anonymous
visitor must all resolve to no role, because every page check from
TASK-UZK-012 onward asks this code and trusts the answer.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.template.loader import render_to_string
from django.test import TestCase
from django.utils.crypto import get_random_string

from accounts.models import UserProfile, UserType
from accounts.roles import (
    ADMIN,
    DEPARTMENT_USER_TYPES,
    MENEJER,
    assign_user_type,
    has_user_type,
    profile_of,
    user_type_name_of,
    user_type_of,
)


def make_user(username: str):
    """An account with no type, which is how every account starts."""
    return get_user_model().objects.create_user(
        username=username, password=get_random_string(24)
    )


class DepartmentUserTypeTests(TestCase):
    """DEC-013 fixes six types, and the migration has to create them."""

    def test_every_type_the_decision_names_exists(self) -> None:
        for name in DEPARTMENT_USER_TYPES:
            with self.subTest(user_type=name):
                self.assertTrue(UserType.objects.filter(name=name).exists())

    def test_the_names_in_the_code_match_the_rows_in_the_database(self) -> None:
        # The constants and the seeded rows are written in two places, so a
        # rename in one without the other would silently deny everybody.
        seeded = set(UserType.objects.values_list("name", flat=True))

        self.assertEqual(set(DEPARTMENT_USER_TYPES), seeded)

    def test_there_are_exactly_six(self) -> None:
        self.assertEqual(UserType.objects.count(), 6)

    def test_a_type_cannot_be_created_twice(self) -> None:
        with self.assertRaises(IntegrityError), transaction.atomic():
            UserType.objects.create(name=ADMIN)


class UnassignedUserTests(TestCase):
    """Nobody is waved through for want of a role."""

    def test_an_account_with_no_profile_has_no_type(self) -> None:
        user = make_user("no.profile")

        self.assertIsNone(user_type_of(user))

    def test_an_account_with_a_profile_but_no_type_has_no_type(self) -> None:
        user = make_user("empty.profile")
        UserProfile.objects.create(user=user)

        self.assertIsNone(user_type_of(user))

    def test_an_anonymous_visitor_has_no_type(self) -> None:
        self.assertIsNone(user_type_of(AnonymousUser()))

    def test_none_has_no_type(self) -> None:
        self.assertIsNone(user_type_of(None))

    def test_an_unassigned_user_is_refused_by_every_role_check(self) -> None:
        user = make_user("unassigned")

        self.assertFalse(has_user_type(user, DEPARTMENT_USER_TYPES))

    def test_an_anonymous_visitor_is_refused_by_every_role_check(self) -> None:
        self.assertFalse(has_user_type(AnonymousUser(), DEPARTMENT_USER_TYPES))


class AssignmentTests(TestCase):
    """Assigning, reassigning and removing a type."""

    def setUp(self) -> None:
        self.user = make_user("assignable")
        self.admin_type = UserType.objects.get(name=ADMIN)
        self.manager_type = UserType.objects.get(name=MENEJER)

    def test_assigning_a_type_makes_it_readable(self) -> None:
        assign_user_type(self.user, self.admin_type)

        self.assertEqual(user_type_of(self.user), self.admin_type)

    def test_assignment_creates_the_profile_when_there_is_none(self) -> None:
        # createsuperuser knows nothing about profiles, so the first account
        # in any installation arrives without one.
        self.assertFalse(UserProfile.objects.filter(user=self.user).exists())

        assign_user_type(self.user, self.admin_type)

        self.assertTrue(UserProfile.objects.filter(user=self.user).exists())

    def test_reassigning_replaces_the_previous_type(self) -> None:
        assign_user_type(self.user, self.admin_type)

        assign_user_type(self.user, self.manager_type)

        self.assertEqual(user_type_of(self.user), self.manager_type)
        self.assertEqual(UserProfile.objects.filter(user=self.user).count(), 1)

    def test_a_type_can_be_taken_away(self) -> None:
        assign_user_type(self.user, self.admin_type)

        assign_user_type(self.user, None)

        self.assertIsNone(user_type_of(self.user))

    def test_changing_a_type_changes_the_answer_immediately(self) -> None:
        # Read from the database on every call rather than cached anywhere, so
        # a change takes effect on the user's next request rather than at
        # their next sign-in.
        assign_user_type(self.user, self.manager_type)
        self.assertFalse(has_user_type(self.user, [ADMIN]))

        assign_user_type(self.user, self.admin_type)

        self.assertTrue(has_user_type(self.user, [ADMIN]))

    def test_profile_of_is_safe_to_call_twice(self) -> None:
        first = profile_of(self.user)
        second = profile_of(self.user)

        self.assertEqual(first.pk, second.pk)


class RetiredUserTypeTests(TestCase):
    """A type removed from the lists must not keep granting access."""

    def setUp(self) -> None:
        self.user = make_user("retired.type")
        self.user_type = UserType.objects.get(name=MENEJER)
        assign_user_type(self.user, self.user_type)

    def test_a_deactivated_type_grants_nothing(self) -> None:
        # DEC-009: deleting is deactivating, so that records referring to the
        # row still resolve. Access is not one of those references.
        self.user_type.is_active = False
        self.user_type.save(update_fields=["is_active"])

        self.assertIsNone(user_type_of(self.user))
        self.assertFalse(has_user_type(self.user, [MENEJER]))

    def test_the_assignment_survives_deactivation(self) -> None:
        self.user_type.is_active = False
        self.user_type.save(update_fields=["is_active"])

        profile = UserProfile.objects.get(user=self.user)

        self.assertEqual(profile.user_type, self.user_type)

    def test_an_active_type_still_appears_in_the_lists(self) -> None:
        self.user_type.is_active = False
        self.user_type.save(update_fields=["is_active"])

        active_names = set(UserType.objects.active().values_list("name", flat=True))

        self.assertNotIn(MENEJER, active_names)
        self.assertIn(ADMIN, active_names)

    def test_a_type_in_use_cannot_be_deleted_outright(self) -> None:
        # on_delete=PROTECT: soft delete is the route, and losing the history
        # of who held which role is not something a stray delete should do.
        with self.assertRaises(ProtectedError):
            self.user_type.delete()


class DisplayTests(TestCase):
    """What the page shows for a user's role."""

    def test_the_type_name_is_shown_for_an_assigned_user(self) -> None:
        user = make_user("displayed")
        assign_user_type(user, UserType.objects.get(name=ADMIN))

        self.assertEqual(user_type_name_of(user), ADMIN)

    def test_an_unassigned_user_shows_nothing(self) -> None:
        self.assertEqual(user_type_name_of(make_user("blank")), "")

    def test_an_anonymous_visitor_shows_nothing(self) -> None:
        self.assertEqual(user_type_name_of(AnonymousUser()), "")

    def test_the_header_shows_the_signed_in_users_type(self) -> None:
        user = make_user("header.user")
        assign_user_type(user, UserType.objects.get(name=MENEJER))
        self.client.force_login(user)

        response = self.client.get("/")

        self.assertContains(response, MENEJER)

    def test_the_header_falls_back_to_the_username_without_a_type(self) -> None:
        # Rendered directly rather than fetched: since TASK-UZK-012 a user with
        # no type may open no page, so the only way to see what the header
        # shows them is to render the shell.
        user = make_user("fallback.user")

        shell = render_to_string("base.html", {"user": user})

        self.assertIn("fallback.user", shell)


class BareStringGuardTests(TestCase):
    """has_user_type takes a collection of names, and says so loudly.

    A bare string is iterable, so passing one used to compare a type name
    against its own letters and answer False for everybody - silently, which
    is the worst way for a permission question to be wrong. TASK-UZK-028 hit
    exactly that and its tests caught it; this keeps the trap closed.
    """

    def test_a_bare_string_is_refused(self) -> None:
        user = make_user("bare.string")
        assign_user_type(user, UserType.objects.get(name=ADMIN))

        with self.assertRaises(TypeError):
            has_user_type(user, ADMIN)

    def test_a_collection_of_one_still_works(self) -> None:
        user = make_user("collection.of.one")
        assign_user_type(user, UserType.objects.get(name=ADMIN))

        self.assertTrue(has_user_type(user, (ADMIN,)))
