"""Tests for the records: master data, roles, numbering and the workflows."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.contrib.auth.models import AnonymousUser
from django.db import IntegrityError, transaction
from django.test import TestCase
from pypdf import PdfReader

from tests.support import (
    ADMIN,
    TemporaryAttachmentsMixin,
    a_category,
    a_department,
    a_purchase_application,
    a_supplier,
    an_accepted_application,
    an_application,
    an_assigned_application,
    make_user,
)
from xarid.forms import DepartmentForm
from xarid.models import (
    BOLIM_BOSHLIGI,
    DEPARTMENT_USER_TYPES,
    DIREKTOR,
    KATTA_MUTAXASIS,
    MENEJER,
    POSITION_STEP,
    Application,
    ApplicationItem,
    ArizaStatus,
    Contract,
    ContractItem,
    MahsulotTuri,
    Notification,
    PurchaseApplication,
    ShartnomaStatus,
    ShartnomaTuri,
    UserSpecialty,
    UserType,
    assignable_specialists,
    badge_class_for,
    deactivate,
    department_of,
    has_user_type,
    money_display,
    next_number,
    purchasing_department,
    user_type_of,
)
from xarid.permissions import (
    contract_editor,
    grant_contract_editing,
    may_edit_contracts,
    revoke_contract_editing,
)


class SeededMasterDataTests(TestCase):
    """The migration seeds what the application cannot start without."""

    def test_the_six_department_user_types_exist_as_system_roles(self) -> None:
        for name in DEPARTMENT_USER_TYPES:
            with self.subTest(user_type=name):
                self.assertTrue(UserType.objects.get(name=name).is_system_role)

    def test_the_seeded_application_statuses_carry_codes_in_workflow_order(self) -> None:
        self.assertEqual(
            list(ArizaStatus.objects.values_list("code", "position")),
            [("new", 10), ("accepted", 20), ("assigned", 30), ("cancelled", 40)],
        )

    def test_the_contract_statuses_and_types_are_seeded(self) -> None:
        """The five states DEC-010 names, and nothing the workflow finds by code."""
        self.assertEqual(
            list(ShartnomaStatus.objects.values_list("name", flat=True)),
            [
                "Boshlang`ich xolatda",
                "Birjaga qo`yilgan",
                "Shartnoma tuzilgan",
                "Yetkazib berilgan",
                "Bekor qilingan",
            ],
        )
        self.assertEqual(
            list(ShartnomaTuri.objects.values_list("name", flat=True)),
            ["Import", "Mahalliy (Local)"],
        )


class MasterDataTests(TestCase):
    """The DEC-009 soft delete, ordering and badge colours."""

    def test_deactivating_hides_a_record_but_keeps_the_row(self) -> None:
        specialty = UserSpecialty.objects.create(name="Metallurg")

        deactivate(specialty)

        self.assertFalse(UserSpecialty.objects.active().filter(pk=specialty.pk).exists())
        self.assertTrue(UserSpecialty.objects.filter(pk=specialty.pk).exists())

    def test_a_new_status_is_placed_at_the_end_when_unplaced(self) -> None:
        status = ArizaStatus.objects.create(name="Kutilmoqda")

        self.assertEqual(status.position, 4 * POSITION_STEP + POSITION_STEP)
        self.assertEqual(list(ArizaStatus.objects.all())[-1], status)

    def test_a_status_with_a_position_keeps_it(self) -> None:
        status = ShartnomaStatus.objects.create(name="Tekshiruvda", position=15)

        self.assertEqual(status.position, 15)

    def test_with_code_finds_only_an_active_row(self) -> None:
        accepted = ArizaStatus.with_code(ArizaStatus.Code.ACCEPTED)
        self.assertEqual(accepted.name, "Qabul qilingan")

        deactivate(accepted)

        self.assertIsNone(ArizaStatus.with_code(ArizaStatus.Code.ACCEPTED))

    def test_badge_class_falls_back_to_the_neutral_badge(self) -> None:
        self.assertEqual(badge_class_for("green"), "badge-approved")
        self.assertEqual(badge_class_for("magenta"), "badge-soft")

    def test_a_category_prints_as_its_number_and_name(self) -> None:
        self.assertEqual(str(a_category()), "100042 - Metallurgiya")

    def test_two_suppliers_may_have_no_inn_but_not_the_same_one(self) -> None:
        a_supplier("Alpha", inn="")
        a_supplier("Beta", inn="")
        a_supplier("Gamma", inn="111111111")

        with self.assertRaises(IntegrityError), transaction.atomic():
            a_supplier("Delta", inn="111111111")

    def test_a_category_number_must_be_unique(self) -> None:
        a_category(100042, "Metallurgiya")

        with self.assertRaises(IntegrityError), transaction.atomic():
            MahsulotTuri.objects.create(category_number=100042, name="Boshqa")


class PurchasingDepartmentTests(TestCase):
    """Which Bo`lim works the arrived applications, and the one-at-a-time rule."""

    def test_none_is_marked_until_somebody_marks_one(self) -> None:
        a_department("Ishlab chiqarish")

        self.assertIsNone(purchasing_department())

    def test_the_marked_one_is_the_one_that_comes_back(self) -> None:
        a_department("Ishlab chiqarish")
        purchasing = a_department("Xarid bo`limi")
        purchasing.is_purchasing = True
        purchasing.save(update_fields=["is_purchasing"])

        self.assertEqual(purchasing_department(), purchasing)

    def test_a_retired_department_stops_being_the_purchasing_one(self) -> None:
        """DEC-009 keeps the row for what points at it, not to keep using it."""
        purchasing = a_department("Xarid bo`limi")
        purchasing.is_purchasing = True
        purchasing.is_active = False
        purchasing.save(update_fields=["is_purchasing", "is_active"])

        self.assertIsNone(purchasing_department())

    def test_two_purchasing_departments_are_refused(self) -> None:
        first = a_department("Xarid bo`limi")
        first.is_purchasing = True
        first.save(update_fields=["is_purchasing"])
        second = a_department("Ikkinchi xarid")

        second.is_purchasing = True
        with self.assertRaises(IntegrityError), transaction.atomic():
            second.save(update_fields=["is_purchasing"])

    def test_the_form_refuses_a_second_one_by_name_instead_of_by_crashing(self) -> None:
        held_by = a_department("Xarid bo`limi")
        held_by.is_purchasing = True
        held_by.save(update_fields=["is_purchasing"])

        form = DepartmentForm({"name": "Ikkinchi xarid", "is_purchasing": True})

        self.assertFalse(form.is_valid())
        self.assertIn(held_by.name, form.errors["is_purchasing"][0])

    def test_the_form_lets_the_one_that_holds_it_keep_it(self) -> None:
        """Editing the purchasing department must not trip over its own mark."""
        purchasing = a_department("Xarid bo`limi")
        purchasing.is_purchasing = True
        purchasing.save(update_fields=["is_purchasing"])

        form = DepartmentForm(
            {"name": purchasing.name, "is_purchasing": True}, instance=purchasing
        )

        self.assertTrue(form.is_valid(), form.errors)


class RoleTests(TestCase):
    """Reading a user's type and department."""

    def test_an_anonymous_visitor_and_an_untyped_account_have_no_type(self) -> None:
        untyped = make_user("untyped")

        self.assertIsNone(user_type_of(AnonymousUser()))
        self.assertIsNone(user_type_of(None))
        self.assertIsNone(user_type_of(untyped))

    def test_a_deactivated_type_counts_as_no_type(self) -> None:
        extra_type = UserType.objects.create(name="Vaqtinchalik")
        user = make_user("temp", user_type="Vaqtinchalik")
        self.assertEqual(user_type_of(user), extra_type)

        deactivate(extra_type)

        self.assertIsNone(user_type_of(user))
        self.assertFalse(has_user_type(user, ("Vaqtinchalik",)))

    def test_has_user_type_refuses_a_bare_string(self) -> None:
        user = make_user("admin", user_type=ADMIN)

        with self.assertRaises(TypeError):
            has_user_type(user, ADMIN)

    def test_department_of_answers_none_for_a_deleted_department(self) -> None:
        department = a_department()
        user = make_user("head", user_type=BOLIM_BOSHLIGI, department=department)
        self.assertEqual(department_of(user), department)

        deactivate(department)

        self.assertIsNone(department_of(user))
        self.assertIsNone(department_of(AnonymousUser()))

    def test_only_active_senior_specialists_are_assignable(self) -> None:
        specialist = make_user("spec", user_type=KATTA_MUTAXASIS)
        make_user("manager", user_type=MENEJER)
        former = make_user("former", user_type=KATTA_MUTAXASIS)
        former.is_active = False
        former.save()

        self.assertEqual(list(assignable_specialists()), [specialist])

    def test_only_xarid_bolimi_s_own_specialists_are_assignable(self) -> None:
        """The department that hands the work out hands it to its own people."""
        purchasing = a_department("Xarid bo`limi")
        purchasing.is_purchasing = True
        purchasing.save(update_fields=["is_purchasing"])
        ours = make_user("ours", user_type=KATTA_MUTAXASIS, department=purchasing)
        theirs = make_user(
            "theirs", user_type=KATTA_MUTAXASIS, department=a_department("IT bo`lim")
        )

        self.assertEqual(list(assignable_specialists()), [ours])
        self.assertNotIn(theirs, assignable_specialists())

    def test_a_specialist_elsewhere_cannot_be_assigned_by_naming_them(self) -> None:
        """The drop-down and the rule are the same question asked twice."""
        purchasing = a_department("Xarid bo`limi")
        purchasing.is_purchasing = True
        purchasing.save(update_fields=["is_purchasing"])
        head = make_user("assign.head", user_type=BOLIM_BOSHLIGI, department=purchasing)
        theirs = make_user(
            "assign.theirs", user_type=KATTA_MUTAXASIS, department=a_department("IT bo`lim")
        )
        application = an_accepted_application(head)

        with self.assertRaises(ValueError):
            application.assign(by=head, specialist=theirs)

    def test_everybody_is_assignable_while_no_purchasing_department_is_named(self) -> None:
        """An ordinary state: the page keeps working until the box is ticked."""
        anywhere = make_user(
            "anywhere", user_type=KATTA_MUTAXASIS, department=a_department("IT bo`lim")
        )

        self.assertEqual(list(assignable_specialists()), [anywhere])


class ContractEditingTests(TestCase):
    """DEC-021: an exclusive lock that starts closed."""

    def test_nobody_holds_the_permission_at_first(self) -> None:
        self.assertIsNone(contract_editor())

    def test_granting_takes_the_permission_from_the_previous_holder(self) -> None:
        first = make_user("first")
        second = make_user("second")

        grant_contract_editing(first)
        grant_contract_editing(second)

        self.assertEqual(contract_editor().user, second)
        self.assertFalse(may_edit_contracts(first))
        self.assertTrue(may_edit_contracts(second))

    def test_revoking_leaves_nobody_holding_it(self) -> None:
        holder = make_user("holder")
        grant_contract_editing(holder)

        revoke_contract_editing(holder)

        self.assertIsNone(contract_editor())

    def test_a_deactivated_holder_is_not_reported(self) -> None:
        holder = make_user("holder")
        grant_contract_editing(holder)
        holder.is_active = False
        holder.save()

        self.assertIsNone(contract_editor())
        self.assertFalse(may_edit_contracts(holder))


class NumberingTests(TestCase):
    """DEC-022: PREFIX-YYYY-NNNNN, resetting each year."""

    def test_the_first_number_of_a_year_is_one(self) -> None:
        self.assertEqual(
            next_number("ARZ", Application, "ariza_raqami", date(2026, 3, 1)),
            "ARZ-2026-00001",
        )

    def test_applications_are_numbered_in_sequence(self) -> None:
        first = an_application()
        second = an_application()

        year = date.today().year
        self.assertEqual(first.ariza_raqami, f"ARZ-{year}-00001")
        self.assertEqual(second.ariza_raqami, f"ARZ-{year}-00002")

    def test_each_record_type_has_its_own_sequence(self) -> None:
        requester = make_user("requester")
        an_application()
        purchase = a_purchase_application(requester, a_department(), with_pdf=False)

        self.assertTrue(purchase.xarid_raqami.startswith("XA-"))
        self.assertTrue(purchase.xarid_raqami.endswith("-00001"))


class ApplicationCreationTests(TestCase):
    def test_an_application_needs_at_least_one_order_line(self) -> None:
        with self.assertRaises(ValueError):
            Application.raise_application(items=[], department=a_department())

    def test_the_database_refuses_an_order_for_nothing(self) -> None:
        with self.assertRaises(IntegrityError), transaction.atomic():
            Application.raise_application(
                items=[
                    {
                        "mahsulot_turi": a_category(),
                        "buyurtma_nomi": "Hech narsa",
                        "buyurtma_soni": "0",
                        "olchov_birligi": "ta",
                    }
                ],
                department=a_department(),
            )

    def test_the_quantity_is_shown_without_trailing_zeros(self) -> None:
        line = ApplicationItem(buyurtma_soni=Decimal("2.500"))
        self.assertEqual(str(line.soni_display), "2.5")

        line.buyurtma_soni = Decimal("500.000")
        self.assertEqual(str(line.soni_display), "500")


class ApplicationDecisionTests(TestCase):
    """Accepting and rejecting an incoming application (REQ-ARIZA-004, 005)."""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.manager = make_user("manager", user_type=MENEJER)

    def test_accepting_stamps_the_date_the_decider_and_the_status(self) -> None:
        application = an_application()

        self.assertTrue(application.accept(by=self.manager))

        application.refresh_from_db()
        self.assertEqual(application.stage, Application.Stage.ACCEPTED)
        self.assertEqual(application.accepted_by, self.manager)
        self.assertIsNotNone(application.qabul_qilingan_sana)
        self.assertEqual(application.status.code, ArizaStatus.Code.ACCEPTED)

    def test_accepting_twice_is_not_an_error_and_keeps_the_first_decision(self) -> None:
        application = an_application()
        application.accept(by=self.manager)
        first_decision = application.qabul_qilingan_sana

        second = make_user("second", user_type=MENEJER)
        self.assertFalse(application.accept(by=second))

        application.refresh_from_db()
        self.assertEqual(application.accepted_by, self.manager)
        self.assertEqual(application.qabul_qilingan_sana, first_decision)

    def test_an_application_is_still_accepted_when_the_status_row_is_gone(self) -> None:
        deactivate(ArizaStatus.with_code(ArizaStatus.Code.ACCEPTED))
        application = an_application()

        self.assertTrue(application.accept(by=self.manager))
        self.assertIsNone(application.status)

    def test_a_rejected_application_cannot_be_accepted(self) -> None:
        application = an_application()
        application.reject(by=self.manager, comment="Narx noto'g'ri")

        with self.assertRaises(ValueError):
            application.accept(by=self.manager)

    def test_rejecting_requires_a_comment(self) -> None:
        application = an_application()

        with self.assertRaises(ValueError):
            application.reject(by=self.manager, comment="   ")

        application.refresh_from_db()
        self.assertTrue(application.is_incoming)

    def test_rejecting_records_the_reason_and_the_cancelled_status(self) -> None:
        application = an_application()

        self.assertTrue(application.reject(by=self.manager, comment="  Narx noto'g'ri  "))

        application.refresh_from_db()
        self.assertEqual(application.stage, Application.Stage.REJECTED)
        self.assertEqual(application.inkor_izohi, "Narx noto'g'ri")
        self.assertEqual(application.rejected_by, self.manager)
        self.assertEqual(application.status.code, ArizaStatus.Code.CANCELLED)
        self.assertFalse(application.reject(by=self.manager, comment="Yana"))


class ApplicationAssignmentTests(TestCase):
    """Assigning, taking and reporting on an application (REQ-ARIZA-007, 013)."""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.manager = make_user("manager", user_type=MENEJER)
        cls.specialist = make_user("spec", user_type=KATTA_MUTAXASIS)
        cls.other_specialist = make_user("spec2", user_type=KATTA_MUTAXASIS)

    def test_only_a_senior_specialist_can_be_assigned(self) -> None:
        application = an_accepted_application(self.manager)

        with self.assertRaises(ValueError):
            application.assign(by=self.manager, specialist=self.manager)
        with self.assertRaises(ValueError):
            application.assign(by=self.manager, specialist=None)

    def test_an_incoming_application_cannot_be_assigned(self) -> None:
        application = an_application()

        with self.assertRaises(ValueError):
            application.assign(by=self.manager, specialist=self.specialist)

    def test_assigning_moves_the_application_and_records_who_did_it(self) -> None:
        application = an_accepted_application(self.manager)

        self.assertTrue(application.assign(by=self.manager, specialist=self.specialist))

        application.refresh_from_db()
        self.assertEqual(application.stage, Application.Stage.ASSIGNED)
        self.assertEqual(application.assigned_to, self.specialist)
        self.assertEqual(application.assigned_by, self.manager)
        self.assertIsNotNone(application.tayinlangan_sana)
        self.assertFalse(application.assign(by=self.manager, specialist=self.specialist))

    def test_the_holder_takes_the_work_once(self) -> None:
        application = an_assigned_application(self.manager, self.specialist)

        self.assertTrue(application.accept_as_specialist(by=self.specialist))
        self.assertFalse(application.accept_as_specialist(by=self.specialist))
        self.assertTrue(application.is_taken)

    def test_somebody_else_cannot_take_the_work(self) -> None:
        application = an_assigned_application(self.manager, self.specialist)

        with self.assertRaises(ValueError):
            application.accept_as_specialist(by=self.other_specialist)

    def test_re_assigning_clears_the_previous_acceptance(self) -> None:
        application = an_assigned_application(self.manager, self.specialist)
        application.accept_as_specialist(by=self.specialist)

        application.assign(by=self.manager, specialist=self.other_specialist)

        application.refresh_from_db()
        self.assertEqual(application.assigned_to, self.other_specialist)
        self.assertIsNone(application.xodim_qabul_qilgan_sana)

    def test_a_status_may_only_be_set_on_an_assigned_application(self) -> None:
        accepted = an_accepted_application(self.manager)
        status = ArizaStatus.with_code(ArizaStatus.Code.ASSIGNED)

        with self.assertRaises(ValueError):
            accepted.set_status(status)

        assigned = an_assigned_application(self.manager, self.specialist)
        # Assigning already put it at Tayinlangan, so moving it there again
        # would report no change; the holder's first move is the one after.
        onwards = ArizaStatus.with_code(ArizaStatus.Code.ACCEPTED)
        self.assertTrue(assigned.set_status(onwards))
        self.assertFalse(assigned.set_status(onwards))
        with self.assertRaises(ValueError):
            assigned.set_status(None)

    def test_a_retired_status_cannot_be_chosen(self) -> None:
        assigned = an_assigned_application(self.manager, self.specialist)
        retired = ArizaStatus.objects.create(name="Eski", is_active=False)

        with self.assertRaises(ValueError):
            assigned.set_status(retired)


class ContractTests(TestCase):
    """The contract's value is the total of its priced rows (REQ-SHARTNOMA-006)."""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.manager = make_user("manager", user_type=MENEJER)
        cls.specialist = make_user("spec", user_type=KATTA_MUTAXASIS)

    def rows(self) -> list[dict]:
        return [
            {
                "buyurtma_nomi": "Bolt",
                "part_number": "PN-1",
                "buyurtma_soni": Decimal("2.5"),
                "olchov_birligi": "kg",
                "narxi": Decimal("1000.10"),
            },
            {
                "buyurtma_nomi": "Gayka",
                "part_number": "",
                "buyurtma_soni": Decimal("3"),
                "olchov_birligi": "ta",
                "narxi": Decimal("0.33"),
            },
        ]

    def test_money_is_grouped_the_uzbek_way(self) -> None:
        self.assertEqual(money_display(Decimal("125000000")), "125 000 000,00")
        self.assertEqual(money_display(Decimal("7.5")), "7,50")

    def test_a_contract_totals_its_rows_to_the_soum(self) -> None:
        application = an_assigned_application(self.manager, self.specialist)

        contract = Contract.raise_contract(
            items=self.rows(),
            created_by=self.specialist,
            application=application,
            supplier=a_supplier(),
        )

        # 2.5 * 1000.10 = 2500.25 and 3 * 0.33 = 0.99
        self.assertEqual(contract.qiymati, Decimal("2501.24"))
        self.assertEqual(contract.items.count(), 2)
        self.assertTrue(contract.shartnoma_raqami.startswith("SHT-"))
        self.assertEqual(contract.qiymati_display, "2 501,24")

    def test_a_caller_may_not_supply_the_value_or_no_rows(self) -> None:
        application = an_assigned_application(self.manager, self.specialist)

        with self.assertRaises(ValueError):
            Contract.raise_contract(
                items=self.rows(),
                created_by=self.specialist,
                application=application,
                supplier=a_supplier(),
                qiymati=Decimal("1"),
            )
        with self.assertRaises(ValueError):
            Contract.raise_contract(
                items=[],
                created_by=self.specialist,
                application=application,
                supplier=a_supplier(),
            )

    def test_a_line_total_is_rounded_to_the_soum(self) -> None:
        line = ContractItem(buyurtma_soni=Decimal("1.005"), narxi=Decimal("1.01"))

        self.assertEqual(line.umumiy_narx, Decimal("1.02"))
        self.assertEqual(line.narxi_display, "1,01")


class PurchaseApplicationTests(TemporaryAttachmentsMixin, TestCase):
    """DEC-016's approval chain, the QR stamp and the requester's notification."""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.department = a_department("Texnik bo`lim")
        cls.other_department = a_department("Moliya bo`limi")
        cls.requester = make_user(
            "requester",
            user_type="Users",
            department=cls.department,
            first_name="Bobur",
            last_name="Toshmatov",
        )
        cls.head = make_user("head", user_type=BOLIM_BOSHLIGI, department=cls.department)
        cls.other_head = make_user(
            "other.head", user_type=BOLIM_BOSHLIGI, department=cls.other_department
        )
        cls.direktor = make_user(
            "direktor", user_type=DIREKTOR, first_name="Dilnoza", last_name="Yusupova"
        )

    def test_a_new_request_waits_for_its_own_department_head(self) -> None:
        request = a_purchase_application(self.requester, self.department, with_pdf=False)

        self.assertEqual(request.stage, PurchaseApplication.Stage.AWAITING_HEAD)
        self.assertTrue(request.awaits(self.head))
        self.assertFalse(request.awaits(self.other_head))
        self.assertFalse(request.awaits(self.direktor))
        self.assertFalse(request.awaits(self.requester))

    def test_the_chain_names_the_people_each_step_may_be_taken_by(self) -> None:
        """approval_chain() is awaits() asked the other way round."""
        request = a_purchase_application(self.requester, self.department, with_pdf=False)

        chain = request.approval_chain()

        self.assertEqual([step for step, _ in chain], [BOLIM_BOSHLIGI, DIREKTOR])
        heads, direktors = (people for _, people in chain)
        self.assertEqual(heads, [self.head])
        self.assertEqual(direktors, [self.direktor])

    def test_the_chain_leaves_out_somebody_who_could_not_sign_in_to_sign(self) -> None:
        """A deactivated account is named by nothing that says who is awaited."""
        request = a_purchase_application(self.requester, self.department, with_pdf=False)
        self.head.is_active = False
        self.head.save(update_fields=["is_active"])

        heads = request.approval_chain()[0][1]

        self.assertEqual(heads, [])

    def test_the_chain_leaves_out_somebody_whose_type_was_retired(self) -> None:
        """An inactive type is no type, the rule user_type_of() already applies."""
        request = a_purchase_application(self.requester, self.department, with_pdf=False)
        retired = UserType.objects.get(name=DIREKTOR)
        retired.is_active = False
        retired.save(update_fields=["is_active"])

        direktors = request.approval_chain()[1][1]

        self.assertEqual(direktors, [])
        self.assertFalse(request.awaits(self.direktor))

    def test_the_head_approves_first_and_only_one_step(self) -> None:
        request = a_purchase_application(self.requester, self.department, with_pdf=False)

        with self.assertRaises(ValueError):
            request.approve(by=self.direktor)

        self.assertTrue(request.approve(by=self.head))
        request.refresh_from_db()
        self.assertEqual(request.stage, PurchaseApplication.Stage.AWAITING_DIREKTOR)
        self.assertEqual(request.tasdiqlagan_bolim_boshligi, self.head)
        self.assertTrue(request.awaits(self.direktor))
        self.assertTrue(request.moved_past(self.head))
        self.assertIsNone(request.raised_application)

    def test_the_direktor_raises_the_department_application_and_stamps_the_pdf(self) -> None:
        request = a_purchase_application(self.requester, self.department)
        original_bytes = request.pdf.read()
        request.pdf.close()
        request.approve(by=self.head)

        self.assertTrue(request.approve(by=self.direktor))

        request.refresh_from_db()
        self.assertEqual(request.stage, PurchaseApplication.Stage.APPROVED)
        raised = request.raised_application
        self.assertEqual(raised.stage, Application.Stage.INCOMING)
        self.assertEqual(raised.department, self.department)
        self.assertEqual(raised.sender, self.requester)
        self.assertEqual(raised.buyurtmachi_ismi, "Bobur Toshmatov")
        self.assertEqual(raised.items.count(), 1)
        self.assertEqual(raised.pdf.name, request.pdf.name)

        # The stamp rewrote the attachment and kept the original beside it.
        self.assertTrue(request.asl_pdf)
        self.assertNotEqual(request.asl_pdf.name, request.pdf.name)
        with request.asl_pdf.open("rb") as original:
            self.assertEqual(original.read(), original_bytes)
        with request.pdf.open("rb") as stamped:
            stamped_bytes = stamped.read()
        self.assertNotEqual(stamped_bytes, original_bytes)
        self.assertEqual(len(PdfReader(request.pdf.open("rb")).pages), 1)
        request.pdf.close()

    def test_an_approval_without_an_attachment_is_not_refused(self) -> None:
        request = a_purchase_application(self.requester, self.department, with_pdf=False)
        request.approve(by=self.head)

        self.assertTrue(request.approve(by=self.direktor))
        self.assertFalse(request.asl_pdf)
        self.assertIsNotNone(request.raised_application)

    def test_rejecting_requires_a_comment_and_tells_the_requester(self) -> None:
        request = a_purchase_application(self.requester, self.department, with_pdf=False)

        with self.assertRaises(ValueError):
            request.reject(by=self.head, comment="")
        with self.assertRaises(ValueError):
            request.reject(by=self.other_head, comment="Not mine")

        self.assertTrue(request.reject(by=self.head, comment="Byudjet yo'q"))
        request.refresh_from_db()
        self.assertEqual(request.stage, PurchaseApplication.Stage.REJECTED)
        self.assertEqual(request.status.code, ArizaStatus.Code.CANCELLED)
        notification = Notification.objects.get(purchase_application=request)
        self.assertEqual(notification.recipient, self.requester)
        self.assertEqual(notification.kind, Notification.Kind.PURCHASE_REJECTED)
        self.assertFalse(request.reject(by=self.head, comment="Yana"))


class NotificationTests(TestCase):
    def test_every_active_admin_is_told_of_a_specialist_acceptance(self) -> None:
        manager = make_user("manager", user_type=MENEJER)
        specialist = make_user("spec", user_type=KATTA_MUTAXASIS)
        first_admin = make_user("admin1", user_type=ADMIN)
        make_user("admin2", user_type=ADMIN)
        application = an_assigned_application(manager, specialist)

        produced = Notification.tell_of_specialist_acceptance(application)

        self.assertEqual(len(produced), 2)
        self.assertEqual(
            str(Notification.objects.filter(recipient=first_admin).get()),
            f"Xodim arizani qabul qildi: {application.ariza_raqami}",
        )

    def test_xarid_bolimi_is_told_of_a_specialist_acceptance_too(self) -> None:
        """The application was handed out on their page, so it is their news."""
        purchasing = a_department("Xarid bo`limi")
        purchasing.is_purchasing = True
        purchasing.save(update_fields=["is_purchasing"])
        head = make_user("xarid.head", user_type=BOLIM_BOSHLIGI, department=purchasing)
        manager = make_user("xarid.manager", user_type=MENEJER, department=purchasing)
        elsewhere = make_user("other.manager", user_type=MENEJER, department=a_department())
        specialist = make_user(
            "spec.two", user_type=KATTA_MUTAXASIS, department=purchasing
        )
        application = an_assigned_application(manager, specialist)

        Notification.tell_of_specialist_acceptance(application)

        told = set(
            Notification.objects.filter(
                kind=Notification.Kind.SPECIALIST_ACCEPTED
            ).values_list("recipient__username", flat=True)
        )
        self.assertEqual(told, {head.get_username(), manager.get_username()})
        self.assertNotIn(elsewhere.get_username(), told)

    def test_nobody_is_told_twice_of_one_acceptance(self) -> None:
        """An Admin who also works the purchasing department is one person."""
        purchasing = a_department("Xarid bo`limi")
        purchasing.is_purchasing = True
        purchasing.save(update_fields=["is_purchasing"])
        both = make_user("admin.head", user_type=ADMIN, department=purchasing)
        specialist = make_user(
            "spec.three", user_type=KATTA_MUTAXASIS, department=purchasing
        )
        application = an_assigned_application(both, specialist)

        produced = Notification.tell_of_specialist_acceptance(application)

        self.assertEqual([one.recipient for one in produced], [both])

    def test_a_notification_is_about_exactly_one_record(self) -> None:
        recipient = make_user("someone")

        with self.assertRaises(IntegrityError), transaction.atomic():
            Notification.objects.create(
                recipient=recipient, kind=Notification.Kind.SPECIALIST_ACCEPTED
            )
