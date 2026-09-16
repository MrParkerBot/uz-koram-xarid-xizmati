"""Tests for accepting an incoming application (TASK-UZK-023).

Two things carry the weight here.

The first is that the accepted status is found by its code and not by its name.
DEC-017 lets an administrator rename any status row, so a lookup by name is one
that stops working the day somebody exercises the page they were given. There
is a test that renames the status first and then accepts.

The second is that a master data page must not be able to stop the workflow.
DEC-017 also lets an administrator delete every status. An application is still
accepted when there is none left - with no status rather than with a refusal.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils.crypto import get_random_string

from accounts.models import UserType
from accounts.roles import ADMIN, MENEJER, USERS, assign_user_type
from applications.models import Application
from reference.models import ArizaStatus, Department, MahsulotTuri


def make_user(type_name: str = ADMIN):
    user = get_user_model().objects.create_user(
        username=f"user.{get_random_string(8).lower()}",
        password=get_random_string(24),
        first_name="Test",
        last_name=type_name,
    )
    assign_user_type(user, UserType.objects.get(name=type_name))
    return user


class AcceptanceTestCase(TestCase):
    """One incoming application and somebody who may decide it."""

    def setUp(self) -> None:
        self.decider = make_user(ADMIN)
        self.client.force_login(self.decider)
        self.application = Application.raise_application(
            department=Department.objects.create(name="Texnik bolim"),
            mahsulot_turi=MahsulotTuri.objects.create(
                category_number=100042, name="Metallurgiya"
            ),
            buyurtma_nomi="Bolt M12",
            buyurtma_soni=500,
            olchov_birligi="ta",
        )
        self.url = reverse("ariza-qabul", args=[self.application.pk])

    def accept(self):
        return self.client.post(self.url)

    def reload(self) -> Application:
        self.application.refresh_from_db()
        return self.application


class SeededCodeTests(TestCase):
    """The migration gives the seeded statuses their codes, and only those."""

    def test_the_seeded_statuses_carry_codes(self) -> None:
        coded = dict(
            ArizaStatus.objects.exclude(code="").values_list("code", "name")
        )

        self.assertEqual(
            coded,
            {
                "new": "Yangi",
                "accepted": "Qabul qilingan",
                "assigned": "Tayinlangan",
                "cancelled": "Bekor qilingan",
            },
        )

    def test_a_status_an_administrator_adds_has_no_code(self) -> None:
        # The code means "the application itself relies on this row", and
        # only the application can say that.
        added = ArizaStatus.objects.create(name="Ko`rib chiqilmoqda")

        self.assertEqual(added.code, "")

    def test_two_statuses_cannot_claim_the_same_code(self) -> None:
        from django.db import IntegrityError

        with self.assertRaises(IntegrityError):
            ArizaStatus.objects.create(
                name="Boshqa qabul", code=ArizaStatus.Code.ACCEPTED
            )

    def test_several_statuses_may_have_no_code(self) -> None:
        ArizaStatus.objects.create(name="Birinchi")
        ArizaStatus.objects.create(name="Ikkinchi")

        self.assertEqual(ArizaStatus.objects.filter(code="").count(), 2)


class TransitionTests(AcceptanceTestCase):
    """Accepting moves the application on and records what happened."""

    def test_accepting_moves_it_to_the_accepted_stage(self) -> None:
        self.accept()

        self.assertEqual(self.reload().stage, Application.Stage.ACCEPTED)

    def test_an_accepted_application_leaves_the_incoming_list(self) -> None:
        self.accept()

        page = self.client.get(reverse("kelib-arizalar")).content.decode()

        self.assertNotIn(self.application.ariza_raqami, page)

    def test_accepting_stamps_the_date(self) -> None:
        # TASK-UZK-025 shows this as the Qabul qilingan sana column.
        self.accept()

        self.assertIsNotNone(self.reload().qabul_qilingan_sana)

    def test_accepting_records_who_decided(self) -> None:
        self.accept()

        self.assertEqual(self.reload().accepted_by, self.decider)

    def test_accepting_redirects_back_to_the_page(self) -> None:
        self.assertRedirects(self.accept(), reverse("kelib-arizalar"))


class StatusTests(AcceptanceTestCase):
    """The status is found by code, and its absence does not block anything."""

    def test_accepting_attaches_the_accepted_status(self) -> None:
        self.accept()

        self.assertEqual(
            self.reload().status.code, ArizaStatus.Code.ACCEPTED
        )

    def test_the_status_is_found_after_it_has_been_renamed(self) -> None:
        # The whole reason the code exists. DEC-017 invites an administrator
        # to rename these rows, and this lookup must not notice.
        accepted = ArizaStatus.objects.get(code=ArizaStatus.Code.ACCEPTED)
        accepted.name = "Bo`lim qabul qildi"
        accepted.save(update_fields=["name"])

        self.accept()

        self.assertEqual(self.reload().status, accepted)

    def test_a_deleted_status_is_not_chosen(self) -> None:
        ArizaStatus.objects.filter(code=ArizaStatus.Code.ACCEPTED).update(
            is_active=False
        )

        self.accept()

        self.assertIsNone(self.reload().status)

    def test_the_application_is_still_accepted_with_no_status_at_all(self):
        # A master data page must not be able to stop the workflow. DEC-017
        # lets an administrator delete every status; acceptance still works.
        ArizaStatus.objects.update(is_active=False)

        self.accept()

        self.assertEqual(self.reload().stage, Application.Stage.ACCEPTED)
        self.assertIsNone(self.reload().status)

    def test_a_status_an_administrator_added_is_never_chosen(self) -> None:
        ArizaStatus.objects.create(name="Qabul qilindi (yangi)")

        self.accept()

        self.assertEqual(
            self.reload().status.code, ArizaStatus.Code.ACCEPTED
        )


class AcceptingTwiceTests(AcceptanceTestCase):
    """The second click of a double click is not an error."""

    def test_accepting_twice_does_not_produce_two_accepted_applications(self):
        self.accept()
        self.accept()

        self.assertEqual(
            Application.objects.filter(
                stage=Application.Stage.ACCEPTED
            ).count(),
            1,
        )

    def test_the_second_accept_leaves_the_first_decision_alone(self) -> None:
        self.accept()
        first = self.reload()
        decided_at, decided_by = first.qabul_qilingan_sana, first.accepted_by

        self.client.force_login(make_user(MENEJER))
        self.accept()

        self.assertEqual(self.reload().qabul_qilingan_sana, decided_at)
        self.assertEqual(self.reload().accepted_by, decided_by)

    def test_the_second_accept_is_not_an_error(self) -> None:
        self.accept()

        self.assertRedirects(self.accept(), reverse("kelib-arizalar"))

    def test_accept_returns_whether_it_did_anything(self) -> None:
        self.assertTrue(self.application.accept(by=self.decider))
        self.assertFalse(self.application.accept(by=self.decider))

    def test_accepting_a_rejected_application_is_refused(self) -> None:
        # Not a double click: a request for something that should not happen.
        self.application.stage = Application.Stage.REJECTED
        self.application.save(update_fields=["stage"])

        with self.assertRaises(ValueError):
            self.application.accept(by=self.decider)


class AccessTests(AcceptanceTestCase):
    """The action answers to the page that offers it."""

    def test_the_route_refuses_a_get(self) -> None:
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 405)
        self.assertEqual(self.reload().stage, Application.Stage.INCOMING)

    def test_somebody_who_may_not_open_the_page_may_not_accept(self) -> None:
        self.client.force_login(make_user(USERS))

        response = self.accept()

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.reload().stage, Application.Stage.INCOMING)

    def test_an_anonymous_visitor_is_redirected(self) -> None:
        self.client.logout()

        self.assertEqual(self.accept().status_code, 302)
        self.assertEqual(self.reload().stage, Application.Stage.INCOMING)

    def test_the_page_asks_before_accepting(self) -> None:
        page = self.client.get(reverse("kelib-arizalar")).content.decode()

        self.assertIn("data-confirm=", page)
