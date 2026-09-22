"""A purchase request shows the state of its contract (TASK-UZK-033).

There is no mapping between an ArizaStatus and a ShartnomaStatus and none is
invented here: DEC-010 makes the two tables independent and extensible, so the
contract's status is shown as it is and the row says where it came from.

The state is derived, never copied: the request's own status column still
records what it was raised as, and these tests assert that it is untouched
after the contract moves.
"""

from __future__ import annotations

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from tests.support import (
    SignedInAdminTestCase,
    a_contract,
    a_department,
    a_purchase_application,
    make_user,
    page,
)
from xarid.models import (
    ADMIN,
    BOLIM_BOSHLIGI,
    DIREKTOR,
    KATTA_MUTAXASIS,
    USERS,
    Contract,
    PurchaseApplication,
    ShartnomaStatus,
)


class ShownStatusTests(TestCase):
    """What the request shows, and what it keeps."""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.texnik = a_department("Texnik bo`lim")
        cls.head = make_user(
            "shown.head", user_type=BOLIM_BOSHLIGI, department=cls.texnik
        )
        cls.admin = make_user("shown.admin", user_type=ADMIN)
        cls.direktor = make_user("shown.direktor", user_type=DIREKTOR)
        cls.specialist = make_user("shown.specialist", user_type=KATTA_MUTAXASIS)
        cls.requester = make_user("shown.requester", user_type=USERS, department=cls.texnik)
        cls.first, cls.second = tuple(ShartnomaStatus.objects.active())[:2]

    def a_request(self) -> PurchaseApplication:
        return a_purchase_application(self.requester, self.texnik, with_pdf=False)

    def an_approved_request(self) -> PurchaseApplication:
        request = self.a_request()
        request.approve(by=self.head)
        request.refresh_from_db()
        request.approve(by=self.direktor)
        request.refresh_from_db()
        return request

    def contracted(self, status) -> PurchaseApplication:
        request = self.an_approved_request()
        application = request.raised_application
        # The raised application arrives as any other does: accepted, then
        # assigned, before a contract can be formed against it.
        application.accept(by=self.admin)
        application.refresh_from_db()
        application.assign(by=self.admin, specialist=self.specialist)
        a_contract(application, self.specialist, status=status)
        return PurchaseApplication.objects.get(pk=request.pk)

    def test_a_request_with_no_contract_shows_its_own_status(self) -> None:
        request = self.a_request()

        self.assertEqual(request.shown_status, request.status)
        self.assertFalse(request.status_follows_contract)
        self.assertIsNone(request.contract)

    def test_an_approved_request_with_no_contract_yet_shows_its_own(self) -> None:
        """A missing hop is an ordinary state, not a fault."""
        request = self.an_approved_request()

        self.assertEqual(request.shown_status, request.status)
        self.assertFalse(request.status_follows_contract)

    def test_a_request_with_a_contract_shows_the_contract_status(self) -> None:
        request = self.contracted(self.first)

        self.assertEqual(request.shown_status, self.first)
        self.assertTrue(request.status_follows_contract)

    def test_a_contract_with_no_status_leaves_the_request_showing_its_own(self) -> None:
        request = self.contracted(None)

        self.assertEqual(request.shown_status, request.status)
        self.assertFalse(request.status_follows_contract)

    def test_the_newest_contract_decides(self) -> None:
        request = self.contracted(self.first)
        a_contract(request.raised_application, self.specialist, status=self.second)

        request = PurchaseApplication.objects.get(pk=request.pk)

        self.assertEqual(request.shown_status, self.second)

    def test_the_state_follows_the_contract_as_it_moves(self) -> None:
        request = self.contracted(self.first)
        contract = request.contract

        contract.set_status(self.second, by=self.specialist)

        self.assertEqual(
            PurchaseApplication.objects.get(pk=request.pk).shown_status, self.second
        )

    def test_nothing_is_copied_into_the_request(self) -> None:
        """The column still records what the request was raised as."""
        request = self.contracted(self.first)
        raised_as = PurchaseApplication.objects.get(pk=request.pk).status

        request.contract.set_status(self.second, by=self.specialist)

        self.assertEqual(PurchaseApplication.objects.get(pk=request.pk).status, raised_as)


class WhoIsToldWhichContractTests(SignedInAdminTestCase):
    """DEC-015 gives Users this page and no contract page at all."""

    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        cls.texnik = a_department("Texnik bo`lim")
        # Given a department because the Direktor raises a request of their
        # own below: Xarid Arizasi shows each reader only what they raised, so
        # a test about what the page tells a Direktor needs a row that is
        # theirs. A second Direktor takes the chain's own step, to keep
        # approving separate from raising.
        cls.direktor = make_user("told.direktor", user_type=DIREKTOR, department=cls.texnik)
        cls.approving_direktor = make_user("told.direktor2", user_type=DIREKTOR)
        cls.head = make_user(
            "told.head", user_type=BOLIM_BOSHLIGI, department=cls.texnik
        )
        cls.specialist = make_user("told.specialist", user_type=KATTA_MUTAXASIS)
        cls.requester = make_user("told.requester", user_type=USERS, department=cls.texnik)
        cls.status = ShartnomaStatus.objects.active().first()

    def a_contracted_request(self, raised_by=None) -> PurchaseApplication:
        request = a_purchase_application(
            raised_by or self.requester, self.texnik, with_pdf=False
        )
        request.approve(by=self.head)
        request.refresh_from_db()
        request.approve(by=self.approving_direktor)
        request.refresh_from_db()
        application = request.raised_application
        # The raised application arrives as any other does: accepted, then
        # assigned, before a contract can be formed against it.
        application.accept(by=self.admin)
        application.refresh_from_db()
        application.assign(by=self.admin, specialist=self.specialist)
        a_contract(application, self.specialist, status=self.status)
        return PurchaseApplication.objects.get(pk=request.pk)

    def test_the_page_shows_the_contract_status_and_says_so(self) -> None:
        self.a_contracted_request()

        response = self.client.get(page("xarid-ariza"))

        self.assertContains(response, self.status.name)
        self.assertContains(response, "Shartnoma holati")

    def test_a_requester_is_not_told_the_contract_number(self) -> None:
        request = self.a_contracted_request()
        self.client.force_login(self.requester)

        response = self.client.get(page("xarid-ariza"))

        self.assertContains(response, "Shartnoma holati")
        self.assertNotContains(response, request.contract.shartnoma_raqami)

    def test_somebody_who_may_open_the_contract_page_is_told_it(self) -> None:
        request = self.a_contracted_request()

        response = self.client.get(page("xarid-ariza"))

        self.assertContains(response, request.contract.shartnoma_raqami)

    def test_the_number_appears_for_direktor_once_the_contract_is_signed(self) -> None:
        """Direktor has Tuzilgan and not Kelishinlingan, so it depends on where it is."""
        request = self.a_contracted_request(raised_by=self.direktor)
        contract = request.contract
        self.client.force_login(self.direktor)

        before = self.client.get(page("xarid-ariza"))
        self.assertNotContains(before, contract.shartnoma_raqami)

        contract.send_for_approval(by=self.specialist)
        contract.refresh_from_db()
        contract.accept(by=self.admin)

        after = self.client.get(page("xarid-ariza"))
        self.assertContains(after, contract.shartnoma_raqami)

    def test_a_request_with_no_contract_says_nothing_about_one(self) -> None:
        a_purchase_application(self.requester, self.texnik, with_pdf=False)

        response = self.client.get(page("xarid-ariza"))

        self.assertNotContains(response, "Shartnoma holati")

    def test_the_page_costs_the_same_with_five_requests_as_with_one(self) -> None:
        self.a_contracted_request()
        with CaptureQueriesContext(connection) as one:
            self.client.get(page("xarid-ariza"))

        for _ in range(4):
            self.a_contracted_request()
        with CaptureQueriesContext(connection) as five:
            self.client.get(page("xarid-ariza"))

        self.assertEqual(len(five), len(one))


class ContractPageMapTests(TestCase):
    """One place answers where a contract currently is."""

    def test_each_stage_names_the_page_showing_it(self) -> None:
        cases = (
            (Contract.Stage.AGREED, "kelishinlingan"),
            (Contract.Stage.REJECTED, "kelishinlingan"),
            (Contract.Stage.SENT, "tuzilgan"),
            (Contract.Stage.SIGNED, "tuzilgan"),
        )
        for stage, expected in cases:
            with self.subTest(stage=stage):
                self.assertEqual(Contract(stage=stage).page_showing, expected)
