"""Tests for the Edit Permission toggle of TASK-UZK-013.

DEC-021 settles CONFLICT-001 - section 3.3 says the permission is open by
default, section 3.4 says only one person may hold it - as an exclusive lock
that starts closed. The exclusivity is the whole point, so it is tested with
two users and with three, and from the page as well as from the code.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils.crypto import get_random_string

from accounts.contract_editing import (
    contract_editor,
    grant_contract_editing,
    may_edit_contracts,
    revoke_contract_editing,
)
from accounts.models import UserProfile, UserType
from accounts.roles import ADMIN, MENEJER, assign_user_type


def make_user(username: str, type_name: str = MENEJER):
    """An account of the given type, holding no permission."""
    user = get_user_model().objects.create_user(
        username=username, password=get_random_string(24), first_name="Test"
    )
    assign_user_type(user, UserType.objects.get(name=type_name))
    return user


class DefaultStateTests(TestCase):
    """DEC-021: nobody holds it until Admin grants it."""

    def test_a_new_user_does_not_hold_it(self) -> None:
        self.assertFalse(may_edit_contracts(make_user("fresh")))

    def test_nobody_holds_it_in_a_new_installation(self) -> None:
        make_user("one")
        make_user("two")

        self.assertIsNone(contract_editor())

    def test_an_anonymous_visitor_does_not_hold_it(self) -> None:
        self.assertFalse(may_edit_contracts(None))


class ExclusivityTests(TestCase):
    """At most one user, whatever route the grant takes."""

    def setUp(self) -> None:
        self.first = make_user("first.holder")
        self.second = make_user("second.holder")
        self.third = make_user("third.holder")

    def holders(self) -> set[str]:
        return set(
            UserProfile.objects.filter(may_edit_contracts=True).values_list(
                "user__username", flat=True
            )
        )

    def test_granting_to_a_second_user_takes_it_from_the_first(self) -> None:
        grant_contract_editing(self.first)

        grant_contract_editing(self.second)

        self.assertEqual(self.holders(), {"second.holder"})
        self.assertFalse(may_edit_contracts(self.first))
        self.assertTrue(may_edit_contracts(self.second))

    def test_a_third_grant_leaves_only_the_third(self) -> None:
        grant_contract_editing(self.first)
        grant_contract_editing(self.second)

        grant_contract_editing(self.third)

        self.assertEqual(self.holders(), {"third.holder"})

    def test_granting_twice_to_the_same_user_is_harmless(self) -> None:
        grant_contract_editing(self.first)

        grant_contract_editing(self.first)

        self.assertEqual(self.holders(), {"first.holder"})

    def test_revoking_leaves_nobody_holding_it(self) -> None:
        grant_contract_editing(self.first)

        revoke_contract_editing(self.first)

        self.assertEqual(self.holders(), set())
        self.assertIsNone(contract_editor())

    def test_a_database_holding_two_is_corrected_by_the_next_grant(self) -> None:
        # Not reachable through the page, but reachable through a restored
        # backup or a hand-edited row. The rule repairs itself rather than
        # leaving two holders because only the expected one was cleared.
        UserProfile.objects.filter(user__in=[self.first, self.second]).update(
            may_edit_contracts=True
        )

        grant_contract_editing(self.third)

        self.assertEqual(self.holders(), {"third.holder"})


class TogglePageTests(TestCase):
    """The switch on the Users page, which only Admin can reach."""

    def setUp(self) -> None:
        self.administrator = make_user("the.admin", ADMIN)
        self.first = make_user("first.holder")
        self.second = make_user("second.holder")
        self.client.force_login(self.administrator)

    def toggle(self, user, on: bool):
        payload = {"may_edit_contracts": "on"} if on else {}
        return self.client.post(
            reverse("user-contract-editing", args=[user.pk]), payload
        )

    def test_turning_it_on_grants_the_permission(self) -> None:
        self.toggle(self.first, on=True)

        self.assertTrue(may_edit_contracts(self.first))

    def test_turning_it_off_removes_the_permission(self) -> None:
        self.toggle(self.first, on=True)

        self.toggle(self.first, on=False)

        self.assertFalse(may_edit_contracts(self.first))

    def test_granting_it_to_a_second_user_removes_it_from_the_first(self) -> None:
        # The acceptance criterion, exercised through the page with two users.
        self.toggle(self.first, on=True)

        self.toggle(self.second, on=True)

        self.assertFalse(may_edit_contracts(self.first))
        self.assertTrue(may_edit_contracts(self.second))

    def test_the_page_says_who_holds_it(self) -> None:
        self.toggle(self.first, on=True)

        page = self.client.get(reverse("users")).content.decode()

        self.assertIn("first.holder", page)

    def test_the_page_says_when_nobody_holds_it(self) -> None:
        page = self.client.get(reverse("users")).content.decode()

        self.assertIn("Hozircha hech kimda yo'q", page)

    def test_the_switch_shows_the_stored_state(self) -> None:
        self.toggle(self.first, on=True)

        page = self.client.get(reverse("users")).content.decode()
        row = page.split(f'contract-editing-{self.first.pk}', 1)[1][:600]

        self.assertIn("checked", row)

    def test_the_toggle_needs_a_post(self) -> None:
        response = self.client.get(
            reverse("user-contract-editing", args=[self.first.pk])
        )

        self.assertEqual(response.status_code, 405)
        self.assertFalse(may_edit_contracts(self.first))

    def test_a_non_admin_cannot_grant_it(self) -> None:
        # The Users page is Admin-only under DEC-015, and so is this action:
        # otherwise a manager could grant themselves contract editing.
        self.client.force_login(self.first)

        response = self.toggle(self.first, on=True)

        self.assertEqual(response.status_code, 403)
        self.assertFalse(may_edit_contracts(self.first))

    def test_an_anonymous_visitor_cannot_grant_it(self) -> None:
        self.client.logout()

        response = self.toggle(self.first, on=True)

        self.assertEqual(response.status_code, 302)
        self.assertFalse(may_edit_contracts(self.first))


class DeletedHolderTests(TestCase):
    """A deactivated account must not keep the lock closed for everybody."""

    def test_a_deleted_holder_may_not_edit_contracts(self) -> None:
        # The two questions this module answers have to agree about the same
        # person: one saying "nobody is the editor" while the other says "yes,
        # they may" is how a deactivated account keeps its authority.
        holder = make_user("departed")
        grant_contract_editing(holder)

        holder.is_active = False
        holder.save(update_fields=["is_active"])

        self.assertFalse(may_edit_contracts(holder))

    def test_a_deleted_holder_is_not_reported_as_the_editor(self) -> None:
        # DEC-009 deletion is a deactivation, so the row survives with the
        # permission still set. Reporting them as the holder would leave the
        # page saying somebody who cannot sign in holds the only lock.
        holder = make_user("leaver")
        grant_contract_editing(holder)

        holder.is_active = False
        holder.save(update_fields=["is_active"])

        self.assertIsNone(contract_editor())
