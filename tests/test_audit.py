"""Tests for the section 10 log (TASK-UZK-052, REQ-LOG-001, DEC-029).

Every write the application makes through its own pages leaves one entry
naming who did it. An approval does not add a row: REQ-LOG-001's columns put
the creation and its approval on one, so the approval completes the entry the
creation left.
"""

from __future__ import annotations

from django.test import TestCase

from tests.support import (
    PASSWORD,
    SignedInAdminTestCase,
    a_category,
    a_contract,
    a_department,
    a_pdf,
    a_supplier,
    an_application,
    an_assigned_application,
    formset_management,
    make_user,
    page,
)
from xarid.audit import APPROVED, REFUSED, record_created, record_decision, record_deleted
from xarid.models import (
    ADMIN,
    BOLIM_BOSHLIGI,
    DIREKTOR,
    KATTA_MUTAXASIS,
    MENEJER,
    USERS,
    AuditEntry,
    Contract,
    PurchaseApplication,
    Supplier,
    UserSpecialty,
    UserType,
)


class WritingEntriesTests(TestCase):
    """What the module writes, given a record and a person."""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.department = a_department("Texnik bo`lim")
        cls.actor = make_user("audit.actor", user_type=ADMIN, department=cls.department)

    def test_a_creation_names_the_actor_their_department_and_the_record(self) -> None:
        supplier = a_supplier()

        entry = record_created(self.actor, supplier)

        self.assertEqual(entry.actor, self.actor)
        self.assertEqual(entry.actor_department, self.department)
        self.assertEqual(entry.form_name, "Firma")
        self.assertEqual(entry.record_label, supplier.name)
        self.assertEqual(entry.action, AuditEntry.Action.CREATED)
        self.assertIsNotNone(entry.created_at)

    def test_an_actor_with_no_department_still_writes_an_entry(self) -> None:
        """A department is a column, not a condition."""
        nomad = make_user("audit.nomad", user_type=ADMIN)

        entry = record_created(nomad, a_supplier())

        self.assertIsNone(entry.actor_department)

    def test_an_entry_outlives_the_record_it_describes(self) -> None:
        supplier = a_supplier(name="Doomed LLC", inn="923456789")
        entry = record_deleted(self.actor, supplier)

        Supplier.objects.filter(pk=supplier.pk).delete()
        entry.refresh_from_db()

        self.assertEqual(entry.record_label, "Doomed LLC")
        self.assertEqual(entry.action, AuditEntry.Action.DELETED)

    def test_a_decision_completes_the_creation_rather_than_adding_a_row(self) -> None:
        supplier = a_supplier()
        created = record_created(self.actor, supplier)
        approver = make_user("audit.approver", user_type=DIREKTOR, department=self.department)

        decided = record_decision(approver, supplier, approved=True, comment="Yaxshi")

        self.assertEqual(decided.pk, created.pk)
        self.assertEqual(AuditEntry.objects.count(), 1)
        self.assertEqual(decided.approver, approver)
        self.assertEqual(decided.approver_department, self.department)
        self.assertEqual(decided.approval_comment, "Yaxshi")
        self.assertEqual(decided.approval_outcome, APPROVED)
        self.assertTrue(decided.was_decided)

    def test_a_refusal_carries_its_comment_and_says_it_refused(self) -> None:
        supplier = a_supplier()
        record_created(self.actor, supplier)

        decided = record_decision(self.actor, supplier, approved=False, comment="Narx noto'g'ri")

        self.assertEqual(decided.approval_outcome, REFUSED)
        self.assertEqual(decided.approval_comment, "Narx noto'g'ri")

    def test_a_decision_on_a_record_with_no_entry_gets_one_of_its_own(self) -> None:
        """A record made before this log existed can still be approved."""
        supplier = a_supplier()

        decided = record_decision(self.actor, supplier, approved=True)

        self.assertEqual(AuditEntry.objects.count(), 1)
        self.assertEqual(decided.action, AuditEntry.Action.EDITED)
        self.assertTrue(decided.was_decided)


class MasterDataLoggingTests(SignedInAdminTestCase):
    """The eight master data pages, which share one write path."""

    def test_adding_a_record_is_logged_once(self) -> None:
        self.client.post(page("user-specialty-create"), {"name": "Muhandis"})

        entry = AuditEntry.objects.get()
        self.assertEqual(entry.actor, self.admin)
        self.assertEqual(entry.action, AuditEntry.Action.CREATED)
        self.assertEqual(entry.record_label, "Muhandis")

    def test_editing_a_record_is_logged_as_an_edit(self) -> None:
        specialty = UserSpecialty.objects.create(name="Muhandis")

        self.client.post(page("user-specialty-update", specialty.pk), {"name": "Bosh muhandis"})

        entry = AuditEntry.objects.get()
        self.assertEqual(entry.action, AuditEntry.Action.EDITED)
        self.assertEqual(entry.record_label, "Bosh muhandis")

    def test_deleting_a_record_is_logged_with_the_label_it_had(self) -> None:
        specialty = UserSpecialty.objects.create(name="Muhandis")

        self.client.post(page("user-specialty-delete", specialty.pk))

        entry = AuditEntry.objects.get()
        self.assertEqual(entry.action, AuditEntry.Action.DELETED)
        self.assertEqual(entry.record_label, "Muhandis")

    def test_a_refused_form_writes_nothing(self) -> None:
        self.client.post(page("user-specialty-create"), {"name": ""})

        self.assertFalse(AuditEntry.objects.exists())

    def test_a_refused_rename_of_a_system_role_writes_nothing(self) -> None:
        admin_type = self.admin.profile.user_type

        self.client.post(page("user-types-update", admin_type.pk), {"name": "Boshqa"})

        self.assertFalse(AuditEntry.objects.exists())


class ApplicationLoggingTests(TestCase):
    """Accepting and refusing an application."""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.department = a_department()
        cls.manager = make_user("log.manager", user_type=MENEJER, department=cls.department)

    def setUp(self) -> None:
        super().setUp()
        self.client.force_login(self.manager)

    def test_accepting_is_logged_against_the_application(self) -> None:
        application = an_application(department=self.department)

        self.client.post(page("ariza-qabul", application.pk))

        entry = AuditEntry.objects.get()
        self.assertEqual(entry.approver, self.manager)
        self.assertEqual(entry.approval_outcome, APPROVED)
        self.assertEqual(entry.record_label, str(application))

    def test_accepting_twice_is_logged_once(self) -> None:
        application = an_application(department=self.department)

        self.client.post(page("ariza-qabul", application.pk))
        self.client.post(page("ariza-qabul", application.pk))

        self.assertEqual(AuditEntry.objects.count(), 1)

    def test_refusing_carries_the_reason_into_the_log(self) -> None:
        application = an_application(department=self.department)

        self.client.post(page("ariza-inkor", application.pk), {"inkor_izohi": "Narx noto'g'ri"})

        entry = AuditEntry.objects.get()
        self.assertEqual(entry.approval_outcome, REFUSED)
        self.assertEqual(entry.approval_comment, "Narx noto'g'ri")

    def test_a_refusal_with_no_reason_is_not_logged(self) -> None:
        """The transition refuses it, so nothing happened to log."""
        application = an_application(department=self.department)

        self.client.post(page("ariza-inkor", application.pk), {"inkor_izohi": "   "})

        self.assertFalse(AuditEntry.objects.exists())


class PurchaseApplicationLoggingTests(TestCase):
    """The DEC-016 approval chain, where a creation and its approval meet."""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.department = a_department()
        cls.requester = make_user("log.requester", user_type=USERS, department=cls.department)
        cls.head = make_user("log.head", user_type=BOLIM_BOSHLIGI, department=cls.department)

    def raise_one(self) -> PurchaseApplication:
        self.client.force_login(self.requester)
        self.client.post(
            page("xarid-ariza-yaratish"),
            {
                "shartnoma_nomi": "Kabel xaridi",
                "muddat_talabi": "",
                "izoh": "",
                **formset_management(1),
                "form-0-mahsulot_turi": a_category().pk,
                "form-0-buyurtma_nomi": "Kabel 4mm",
                "form-0-buyurtma_soni": "200",
                "form-0-olchov_birligi": "m",
                "pdf": a_pdf(),
            },
        )
        return PurchaseApplication.objects.get()

    def test_the_creation_and_its_approval_share_one_row(self) -> None:
        application = self.raise_one()
        self.assertEqual(AuditEntry.objects.count(), 1)

        self.client.force_login(self.head)
        self.client.post(page("xarid-ariza-tasdiqlash", application.pk))

        entry = AuditEntry.objects.get()
        self.assertEqual(entry.actor, self.requester)
        self.assertEqual(entry.action, AuditEntry.Action.CREATED)
        self.assertEqual(entry.approver, self.head)
        self.assertEqual(entry.approver_department, self.department)
        self.assertEqual(entry.approval_outcome, APPROVED)

    def test_a_refusal_fills_the_same_row_with_its_comment(self) -> None:
        application = self.raise_one()

        self.client.force_login(self.head)
        self.client.post(
            page("xarid-ariza-inkor", application.pk), {"inkor_izohi": "Byudjet yo'q"}
        )

        entry = AuditEntry.objects.get()
        self.assertEqual(entry.approval_outcome, REFUSED)
        self.assertEqual(entry.approval_comment, "Byudjet yo'q")

    def test_a_decision_by_somebody_not_asked_writes_nothing_new(self) -> None:
        application = self.raise_one()
        outsider = make_user(
            "log.outsider",
            user_type=BOLIM_BOSHLIGI,
            department=a_department("Boshqa bo`lim"),
        )

        self.client.force_login(outsider)
        self.client.post(page("xarid-ariza-tasdiqlash", application.pk))

        entry = AuditEntry.objects.get()
        self.assertIsNone(entry.approver)


class LogIsAppendOnlyTests(SignedInAdminTestCase):
    """DEC-029: entries are never edited or deleted through the application."""

    def test_the_admin_offers_no_way_to_add_change_or_delete_one(self) -> None:
        from django.contrib import admin as django_admin

        registered = django_admin.site._registry[AuditEntry]

        self.assertFalse(registered.has_add_permission(None))
        self.assertFalse(registered.has_change_permission(None))
        self.assertFalse(registered.has_delete_permission(None))

    def test_no_page_of_the_application_writes_to_the_log(self) -> None:
        """Nothing routes to it: the Logs page UZK-053 builds is read-only."""
        from xarid.urls import urlpatterns

        writing = [
            route.name
            for route in urlpatterns
            if route.name and ("log" in route.name and route.name != "logs")
        ]

        self.assertEqual(writing, [])


class ContractLoggingTests(TestCase):
    """The contract sites, where the approvals this table exists for happen."""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.department = a_department()
        cls.manager = make_user("c.log.manager", user_type=MENEJER, department=cls.department)
        cls.specialist = make_user(
            "c.log.specialist", user_type=KATTA_MUTAXASIS, department=cls.department
        )
        # DEC-013 makes Admin the Xarid bo`lim boshlig`i, who is the one
        # REQ-SHARTNOMA-002 gives the contract decision to.
        cls.decider = make_user("c.log.decider", user_type=ADMIN, department=cls.department)

    def a_held_contract(self) -> Contract:
        application = an_assigned_application(
            self.manager, self.specialist, department=self.department
        )
        return a_contract(application, self.specialist)

    def test_sending_a_contract_for_approval_is_logged_as_an_edit(self) -> None:
        contract = self.a_held_contract()
        self.client.force_login(self.specialist)

        self.client.post(page("kelishinlingan-yuborish", contract.pk))

        entry = AuditEntry.objects.get()
        self.assertEqual(entry.action, AuditEntry.Action.EDITED)
        self.assertEqual(entry.actor, self.specialist)
        self.assertEqual(entry.record_label, str(contract))

    def test_sending_twice_is_logged_once(self) -> None:
        contract = self.a_held_contract()
        self.client.force_login(self.specialist)

        self.client.post(page("kelishinlingan-yuborish", contract.pk))
        self.client.post(page("kelishinlingan-yuborish", contract.pk))

        self.assertEqual(AuditEntry.objects.count(), 1)

    def test_approving_a_contract_records_the_approver(self) -> None:
        contract = self.a_held_contract()
        self.client.force_login(self.specialist)
        self.client.post(page("kelishinlingan-yuborish", contract.pk))
        self.client.force_login(self.decider)

        self.client.post(page("tuzilgan-tasdiqlash", contract.pk))

        decided = AuditEntry.objects.filter(approved_at__isnull=False).get()
        self.assertEqual(decided.approver, self.decider)
        self.assertEqual(decided.approver_department, self.department)
        self.assertEqual(decided.approval_outcome, APPROVED)

    def test_refusing_a_contract_carries_its_comment(self) -> None:
        contract = self.a_held_contract()
        self.client.force_login(self.specialist)
        self.client.post(page("kelishinlingan-yuborish", contract.pk))
        self.client.force_login(self.decider)

        self.client.post(page("tuzilgan-inkor", contract.pk), {"izoh": "Narx yuqori"})

        decided = AuditEntry.objects.filter(approved_at__isnull=False).get()
        self.assertEqual(decided.approval_outcome, REFUSED)
        self.assertEqual(decided.approval_comment, "Narx yuqori")

    def test_a_refusal_with_no_comment_is_not_logged(self) -> None:
        contract = self.a_held_contract()
        self.client.force_login(self.specialist)
        self.client.post(page("kelishinlingan-yuborish", contract.pk))
        AuditEntry.objects.all().delete()
        self.client.force_login(self.decider)

        self.client.post(page("tuzilgan-inkor", contract.pk), {"izoh": "  "})

        self.assertFalse(AuditEntry.objects.exists())


class UserLoggingTests(SignedInAdminTestCase):
    """The Users page, whose records come from Django rather than from here."""

    def user_fields(self, **overrides) -> dict:
        fields = {
            "first_name": "Bobur",
            "last_name": "Toshmatov",
            "password": PASSWORD,
            "phone_number": "90 123 45 67",
            "user_type": UserType.objects.get(name=MENEJER).pk,
            "department": a_department().pk,
        }
        fields.update(overrides)
        return fields

    def test_adding_a_user_is_logged_under_a_name_the_log_chose(self) -> None:
        self.client.post(page("user-create"), self.user_fields())

        entry = AuditEntry.objects.get()
        self.assertEqual(entry.action, AuditEntry.Action.CREATED)
        self.assertEqual(entry.form_name, "Foydalanuvchi")

    def test_deleting_a_user_is_logged_before_they_are_deactivated(self) -> None:
        doomed = make_user("doomed.user", user_type=MENEJER)

        self.client.post(page("user-delete", doomed.pk))

        entry = AuditEntry.objects.get()
        self.assertEqual(entry.action, AuditEntry.Action.DELETED)
        self.assertEqual(entry.record_label, "doomed.user")

    def test_deleting_your_own_account_is_refused_and_not_logged(self) -> None:
        self.client.post(page("user-delete", self.admin.pk))

        self.assertFalse(AuditEntry.objects.exists())


class TwoApprovalsTests(TestCase):
    """DEC-016's chain: the head approves, then the director."""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.department = a_department()
        cls.requester = make_user("two.requester", user_type=USERS, department=cls.department)
        cls.head = make_user("two.head", user_type=BOLIM_BOSHLIGI, department=cls.department)
        cls.direktor = make_user("two.direktor", user_type=DIREKTOR)

    def test_the_second_approval_does_not_erase_the_first(self) -> None:
        """One approver per row, so two approvals need two rows."""
        self.client.force_login(self.requester)
        self.client.post(
            page("xarid-ariza-yaratish"),
            {
                "shartnoma_nomi": "Kabel xaridi",
                "muddat_talabi": "",
                "izoh": "",
                **formset_management(1),
                "form-0-mahsulot_turi": a_category().pk,
                "form-0-buyurtma_nomi": "Kabel 4mm",
                "form-0-buyurtma_soni": "200",
                "form-0-olchov_birligi": "m",
                "pdf": a_pdf(),
            },
        )
        application = PurchaseApplication.objects.get()

        self.client.force_login(self.head)
        self.client.post(page("xarid-ariza-tasdiqlash", application.pk))
        self.client.force_login(self.direktor)
        self.client.post(page("xarid-ariza-tasdiqlash", application.pk))

        approvers = [
            entry.approver
            for entry in AuditEntry.objects.filter(approved_at__isnull=False).order_by("id")
        ]
        self.assertEqual(approvers, [self.head, self.direktor])
