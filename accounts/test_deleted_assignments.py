"""What the Users page does with an assignment whose row was deleted.

DEC-009 deletion keeps the row so that the records already pointing at it
still resolve. The Users page offered only the active rows, which quietly
broke that promise in the one case nobody looks at: a user whose department or
user type had been deleted lost it on the next save of any other field,
because the select carried no option for it and the field, being optional,
accepted the empty value the browser sent.

Nothing announced it. The administrator changed a phone number; the person
lost their department, or their user type and with it every page they could
open.

These are the tests for the case the review of TASK-UZK-020 found, written for
both fields because they are the same defect and the type is the worse half.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils.crypto import get_random_string

from accounts.models import UserProfile, UserType
from accounts.roles import ADMIN, assign_user_type
from reference.models import Department

DELETED_DEPARTMENT = "Eski bolim"
DELETED_USER_TYPE = "Tekshiruvchi"


def deactivate(record) -> None:
    """Delete a master data row the way DEC-009 defines deletion."""
    record.is_active = False
    record.save(update_fields=["is_active"])


class DeletedAssignmentTestCase(TestCase):
    """One member of the department, holding rows that are then deleted."""

    def setUp(self) -> None:
        self.client.force_login(self.make_user(ADMIN))

        self.department = Department.objects.create(name=DELETED_DEPARTMENT)
        self.user_type = UserType.objects.create(name=DELETED_USER_TYPE)

        self.member = get_user_model().objects.create_user(
            username="bobur.toshmatov",
            password=get_random_string(24),
            first_name="Bobur",
            last_name="Toshmatov",
        )
        self.profile = UserProfile.objects.create(
            user=self.member,
            user_type=self.user_type,
            department=self.department,
            phone_number="90 123 45 67",
        )

    def make_user(self, type_name: str = ADMIN):
        user = get_user_model().objects.create_user(
            username=f"user.{get_random_string(8).lower()}",
            password=get_random_string(24),
            first_name="Test",
            last_name=type_name,
        )
        assign_user_type(user, UserType.objects.get(name=type_name))
        return user

    def edit_the_surname(self, **overrides):
        """Save the member's form having changed nothing but the surname.

        The form posts every field, as a browser does. What matters is that
        the two drop-downs post whatever the page offered them - which, when
        the assigned row is missing from the select, is nothing at all.
        """
        fields = {
            "first_name": "Bobur",
            "last_name": "Bekov",
            "password": "",
            "phone_number": "90 123 45 67",
            "user_type": "",
            "department": "",
        }
        fields.update(overrides)
        return self.client.post(
            reverse("user-update", args=[self.member.pk]), fields
        )

    def form_for_the_member(self) -> str:
        return self.client.get(
            f"{reverse('users')}?edit={self.member.pk}"
        ).content.decode()

    def blank_form(self):
        """The form the page carries when nobody is being edited.

        Read from the response rather than the HTML, because a primary key
        rendered into an option value is not distinguishable from the same
        number in the other select.
        """
        return self.client.get(reverse("users")).context["form"]


class DeletedDepartmentTests(DeletedAssignmentTestCase):
    """A department that was deleted while somebody belonged to it."""

    def setUp(self) -> None:
        super().setUp()
        deactivate(self.department)

    def test_the_members_own_form_still_offers_it(self) -> None:
        # Otherwise the select cannot show what the row actually holds, and
        # an edit of any other field posts an empty department.
        page = self.form_for_the_member()

        self.assertIn(f'value="{self.department.pk}" selected', page)

    def test_editing_another_field_does_not_take_it_away(self) -> None:
        self.edit_the_surname(department=self.department.pk)
        self.profile.refresh_from_db()

        self.assertEqual(self.profile.department, self.department)

    def test_it_can_still_be_taken_away_deliberately(self) -> None:
        # Keeping a deleted assignment is not the same as being stuck with it.
        self.edit_the_surname(department="")
        self.profile.refresh_from_db()

        self.assertIsNone(self.profile.department)

    def test_nobody_else_is_offered_it(self) -> None:
        # It survives as an assignment; it is gone as a choice, which is the
        # whole of DEC-009.
        offered = self.blank_form().fields["department"].queryset

        self.assertNotIn(self.department, offered)


class DeletedUserTypeTests(DeletedAssignmentTestCase):
    """A user type that was deleted while somebody held it.

    The worse half: a type is what the permission matrix reads, so losing one
    silently is losing every page the person could open.
    """

    def setUp(self) -> None:
        super().setUp()
        deactivate(self.user_type)

    def test_the_members_own_form_still_offers_it(self) -> None:
        page = self.form_for_the_member()

        self.assertIn(f'value="{self.user_type.pk}" selected', page)

    def test_editing_another_field_does_not_take_it_away(self) -> None:
        self.edit_the_surname(user_type=self.user_type.pk)
        self.profile.refresh_from_db()

        self.assertEqual(self.profile.user_type, self.user_type)

    def test_it_can_still_be_taken_away_deliberately(self) -> None:
        self.edit_the_surname(user_type="")
        self.profile.refresh_from_db()

        self.assertIsNone(self.profile.user_type)

    def test_nobody_else_is_offered_it(self) -> None:
        offered = self.blank_form().fields["user_type"].queryset

        self.assertNotIn(self.user_type, offered)
