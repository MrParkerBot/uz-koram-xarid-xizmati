"""Tests for the pages: what they show and what their actions do."""

from __future__ import annotations

from datetime import date

from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.urls import reverse
from django.utils.crypto import get_random_string

from tests.support import (
    PASSWORD,
    SignedInAdminTestCase,
    a_category,
    a_department,
    a_pdf,
    a_purchase_application,
    a_supplier,
    an_accepted_application,
    an_application,
    an_assigned_application,
    formset_management,
    make_user,
    page,
)
from xarid.models import (
    ADMIN,
    BOLIM_BOSHLIGI,
    DIREKTOR,
    KATTA_MUTAXASIS,
    MENEJER,
    USERS,
    Application,
    ArizaStatus,
    Contract,
    Department,
    MahsulotTuri,
    Notification,
    PurchaseApplication,
    ShartnomaStatus,
    ShartnomaTuri,
    Supplier,
    UserProfile,
    UserSpecialty,
    UserType,
)
from xarid.permissions import contract_editor
from xarid.views import PROTOTYPE_PAGE_TEMPLATES

# One row per master data page: page name, model, the context list's marker in
# the page and the fields a valid Save posts.
MASTER_DATA_PAGES = (
    ("user-specialty", UserSpecialty, {"name": "Metallurg"}),
    ("user-types", UserType, {"name": "Buxgalter", "badge_colour": "blue"}),
    ("ariza-status", ArizaStatus, {"name": "Kutilmoqda", "badge_colour": "yellow"}),
    ("shartnoma-status", ShartnomaStatus, {"name": "Tekshiruvda", "badge_colour": "blue"}),
    ("mahsulot-turlari", MahsulotTuri, {"category_number": "100042", "name": "Metallurgiya"}),
    ("shartnoma-turi", ShartnomaTuri, {"name": "Framework"}),
    ("bolim-royhati", Department, {"name": "Logistika"}),
    ("firmalar", Supplier, {"name": "GazTrade", "inn": "987654321"}),
)


class MasterDataPageTests(SignedInAdminTestCase):
    """Every master data page is a table beside a form with the same behaviour."""

    def test_every_page_lists_its_active_records(self) -> None:
        for page_name, model, fields in MASTER_DATA_PAGES:
            with self.subTest(page=page_name):
                record = model.objects.create(**fields)
                hidden = model.objects.create(
                    **{
                        **fields,
                        "name": fields["name"] + " (o'chirilgan)",
                        **({"category_number": "100043"} if "category_number" in fields else {}),
                        **({"inn": "111111111"} if "inn" in fields else {}),
                    },
                    is_active=False,
                )

                response = self.client.get(page(page_name))

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, record.name)
                self.assertNotContains(response, hidden.name)

    def test_save_adds_a_record_and_returns_to_the_list(self) -> None:
        for page_name, model, fields in MASTER_DATA_PAGES:
            with self.subTest(page=page_name):
                response = self.client.post(page(f"{page_name}-create"), fields)

                self.assertRedirects(response, page(page_name))
                self.assertTrue(model.objects.active().filter(name=fields["name"]).exists())

    def test_a_duplicate_name_is_refused_with_the_page_still_showing_the_form(self) -> None:
        for page_name, model, fields in MASTER_DATA_PAGES:
            with self.subTest(page=page_name):
                model.objects.create(**fields)
                clashing = {**fields, "name": fields["name"].upper()}
                if "category_number" in fields:
                    clashing["category_number"] = "100099"
                if "inn" in fields:
                    clashing["inn"] = "222222222"

                response = self.client.post(page(f"{page_name}-create"), clashing)

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Bu nom allaqachon mavjud.")

    def test_a_name_held_by_a_deleted_record_says_so(self) -> None:
        UserSpecialty.objects.create(name="Metallurg", is_active=False)

        response = self.client.post(page("user-specialty-create"), {"name": "metallurg"})

        self.assertContains(response, "o&#x27;chirilgan yozuvga tegishli")

    def test_edit_opens_the_form_filled_in_and_update_changes_the_record(self) -> None:
        for page_name, model, fields in MASTER_DATA_PAGES:
            with self.subTest(page=page_name):
                record = model.objects.create(**fields)

                response = self.client.get(page(page_name), {"edit": record.pk})
                self.assertContains(response, f'value="{fields["name"]}"')
                self.assertContains(response, page(f"{page_name}-update", record.pk))

                renamed = {**fields, "name": fields["name"] + " 2"}
                response = self.client.post(page(f"{page_name}-update", record.pk), renamed)

                self.assertRedirects(response, page(page_name))
                record.refresh_from_db()
                self.assertEqual(record.name, fields["name"] + " 2")

    def test_delete_deactivates_after_the_page_asks(self) -> None:
        for page_name, model, fields in MASTER_DATA_PAGES:
            with self.subTest(page=page_name):
                record = model.objects.create(**fields)

                listed = self.client.get(page(page_name))
                self.assertContains(listed, f'data-confirm="{record.name} o&#39;chirilsinmi?"')

                response = self.client.post(page(f"{page_name}-delete", record.pk))

                self.assertRedirects(response, page(page_name))
                record.refresh_from_db()
                self.assertFalse(record.is_active)
                self.assertEqual(
                    self.client.get(page(page_name), {"edit": record.pk}).status_code, 404
                )

    def test_a_bad_edit_id_is_a_not_found(self) -> None:
        self.assertEqual(self.client.get(page("firmalar"), {"edit": "abc"}).status_code, 404)

    def test_actions_are_post_only(self) -> None:
        self.assertEqual(self.client.get(page("firmalar-create")).status_code, 405)
        self.assertEqual(self.client.get(page("firmalar-delete", 1)).status_code, 405)

    def test_a_category_number_must_be_six_digits_and_unique(self) -> None:
        response = self.client.post(
            page("mahsulot-turlari-create"), {"category_number": "42", "name": "Qisqa"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(MahsulotTuri.objects.exists())

        a_category(100042, "Metallurgiya")
        response = self.client.post(
            page("mahsulot-turlari-create"), {"category_number": "100042", "name": "Boshqa"}
        )
        self.assertContains(response, "Bu raqam allaqachon mavjud.")

    def test_a_supplier_inn_must_be_nine_digits_and_unique(self) -> None:
        response = self.client.post(page("firmalar-create"), {"name": "Alpha", "inn": "12"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Supplier.objects.exists())

        a_supplier("Beta", inn="123456789")
        response = self.client.post(page("firmalar-create"), {"name": "Gamma", "inn": "123456789"})
        self.assertContains(response, "Bu INN allaqachon ro`yhatda bor.")

    def test_a_system_role_cannot_be_renamed_or_deleted(self) -> None:
        admin_type = UserType.objects.get(name=ADMIN)

        renamed = self.client.post(
            page("user-types-update", admin_type.pk), {"name": "Boss", "badge_colour": "blue"}
        )
        deleted = self.client.post(page("user-types-delete", admin_type.pk))

        self.assertEqual(renamed.status_code, 403)
        self.assertEqual(deleted.status_code, 403)
        admin_type.refresh_from_db()
        self.assertEqual(admin_type.name, ADMIN)
        self.assertTrue(admin_type.is_active)

    def test_a_system_role_keeps_its_name_but_changes_its_colour(self) -> None:
        admin_type = UserType.objects.get(name=ADMIN)

        response = self.client.post(
            page("user-types-update", admin_type.pk), {"name": ADMIN, "badge_colour": "green"}
        )

        self.assertRedirects(response, page("user-types"))
        admin_type.refresh_from_db()
        self.assertEqual(admin_type.badge_colour, "green")
        self.assertContains(self.client.get(page("user-types")), "badge-approved")


class UsersPageTests(SignedInAdminTestCase):
    """The Users page: creating, editing, deleting and the contract-edit lock."""

    def user_fields(self, **overrides) -> dict:
        fields = {
            "first_name": "Bobur",
            "last_name": "Toshmatov",
            "password": get_random_string(20),
            "phone_number": "90 123 45 67",
            "user_type": UserType.objects.get(name=MENEJER).pk,
            "department": a_department().pk,
        }
        fields.update(overrides)
        return fields

    def test_creating_derives_a_username_and_fills_the_profile(self) -> None:
        fields = self.user_fields()

        response = self.client.post(page("user-create"), fields)

        self.assertRedirects(response, page("users"))
        created = get_user_model().objects.get(username="bobur.toshmatov")
        self.assertTrue(created.check_password(fields["password"]))
        self.assertEqual(created.profile.user_type.name, MENEJER)
        self.assertEqual(created.profile.phone_number, "90 123 45 67")
        self.assertEqual(created.profile.department, a_department())

        listed = self.client.get(page("users"))
        self.assertContains(listed, "bobur.toshmatov")
        self.assertContains(listed, "+998 90 123 45 67")

    def test_a_second_person_with_the_same_name_gets_a_numbered_username(self) -> None:
        self.client.post(page("user-create"), self.user_fields())
        self.client.post(page("user-create"), self.user_fields())

        self.assertTrue(get_user_model().objects.filter(username="bobur.toshmatov2").exists())

    def test_creating_requires_a_password_and_a_well_formed_phone_number(self) -> None:
        no_password = self.client.post(page("user-create"), self.user_fields(password=""))
        bad_phone = self.client.post(
            page("user-create"), self.user_fields(phone_number="901234567")
        )

        self.assertContains(no_password, "Majburiy maydon")
        self.assertContains(bad_phone, "Format: 90 123 45 67")
        self.assertFalse(get_user_model().objects.filter(username="bobur.toshmatov").exists())

    def test_editing_with_an_empty_password_keeps_the_current_one(self) -> None:
        edited = make_user("bobur", first_name="Bobur", last_name="Toshmatov")

        response = self.client.post(
            page("user-update", edited.pk),
            self.user_fields(password="", phone_number="91 111 22 33"),
        )

        self.assertRedirects(response, page("users"))
        edited.refresh_from_db()
        self.assertTrue(edited.check_password(PASSWORD))
        self.assertEqual(edited.profile.phone_number, "91 111 22 33")

    def test_the_edit_form_opens_filled_in_without_the_password(self) -> None:
        edited = make_user("bobur", first_name="Bobur", last_name="Toshmatov")

        response = self.client.get(page("users"), {"edit": edited.pk})

        self.assertContains(response, 'value="Bobur"')
        self.assertContains(response, page("user-update", edited.pk))
        self.assertNotContains(response, PASSWORD)

    def test_deleting_deactivates_the_account(self) -> None:
        deleted = make_user("leaver", first_name="Sardor", last_name="Nazarov")

        response = self.client.post(page("user-delete", deleted.pk))

        self.assertRedirects(response, page("users"))
        deleted.refresh_from_db()
        self.assertFalse(deleted.is_active)
        self.assertNotContains(self.client.get(page("users")), "Sardor Nazarov")

    def test_an_administrator_cannot_delete_their_own_account(self) -> None:
        response = self.client.post(page("user-delete", self.admin.pk))

        self.assertEqual(response.status_code, 403)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_the_contract_editing_switch_grants_exclusively_and_revokes(self) -> None:
        first = make_user("first", first_name="Alisher", last_name="Karimov")
        second = make_user("second", first_name="Dilnoza", last_name="Yusupova")

        self.client.post(page("user-contract-editing", first.pk), {"may_edit_contracts": "on"})
        self.assertEqual(contract_editor().user, first)
        self.assertContains(
            self.client.get(page("users")), "Hozir: <strong>Alisher Karimov</strong>"
        )

        self.client.post(page("user-contract-editing", second.pk), {"may_edit_contracts": "on"})
        self.assertEqual(contract_editor().user, second)

        self.client.post(page("user-contract-editing", second.pk), {})
        self.assertIsNone(contract_editor())
        self.assertContains(self.client.get(page("users")), "Hozircha hech kimda yo'q.")


class IncomingApplicationsTests(SignedInAdminTestCase):
    """Kelib tushgan Arizalar and its two decisions."""

    def test_the_list_shows_incoming_applications_only(self) -> None:
        incoming = an_application()
        accepted = an_accepted_application(self.admin)

        response = self.client.get(page("kelib-arizalar"))

        self.assertContains(response, incoming.ariza_raqami)
        self.assertNotContains(response, accepted.ariza_raqami)
        self.assertContains(response, "Bolt M12x50")
        self.assertContains(response, page("ariza-inkor", incoming.pk))

    def test_accepting_moves_the_application_and_says_so(self) -> None:
        application = an_application()

        response = self.client.post(page("ariza-qabul", application.pk), follow=True)

        self.assertContains(response, f"{application.ariza_raqami} qabul qilindi.")
        application.refresh_from_db()
        self.assertEqual(application.stage, Application.Stage.ACCEPTED)

    def test_a_stale_accept_is_told_rather_than_forbidden(self) -> None:
        application = an_application()
        application.reject(by=self.admin, comment="Narx")

        response = self.client.post(page("ariza-qabul", application.pk), follow=True)

        self.assertContains(response, "allaqachon hal qilingan")

    def test_rejecting_needs_a_comment(self) -> None:
        application = an_application()

        without = self.client.post(
            page("ariza-inkor", application.pk), {"inkor_izohi": " "}, follow=True
        )
        self.assertContains(without, "izoh kiritilishi shart")
        application.refresh_from_db()
        self.assertTrue(application.is_incoming)

        with_comment = self.client.post(
            page("ariza-inkor", application.pk), {"inkor_izohi": "Narx noto'g'ri"}, follow=True
        )
        self.assertContains(with_comment, f"{application.ariza_raqami} inkor etildi.")
        application.refresh_from_db()
        self.assertEqual(application.inkor_izohi, "Narx noto'g'ri")


class AcceptedApplicationsTests(SignedInAdminTestCase):
    """Qabul qilingan Arizalar: the list, the creation form and assignment."""

    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        cls.specialist = make_user(
            "spec", user_type=KATTA_MUTAXASIS, first_name="Dilnoza", last_name="Yusupova"
        )

    def creation_fields(self, **overrides) -> dict:
        fields = {
            "department": a_department().pk,
            "buyurtmachi_ismi": "Bobur Toshmatov",
            "izoh": "",
            **formset_management(1),
            "form-0-mahsulot_turi": a_category().pk,
            "form-0-buyurtma_nomi": "Bolt M12x50",
            "form-0-buyurtma_soni": "10",
            "form-0-olchov_birligi": "ta",
            "pdf": a_pdf(),
        }
        fields.update(overrides)
        return fields

    def test_the_list_shows_accepted_and_assigned_applications(self) -> None:
        accepted = an_accepted_application(self.admin)
        assigned = an_assigned_application(self.admin, self.specialist)
        incoming = an_application()

        response = self.client.get(page("qabul-arizalar"))

        self.assertContains(response, accepted.ariza_raqami)
        self.assertContains(response, assigned.ariza_raqami)
        self.assertNotContains(response, incoming.ariza_raqami)
        self.assertContains(response, "Dilnoza Yusupova")
        self.assertContains(response, "Qayta")

    def test_creating_an_application_makes_an_accepted_one_with_its_lines(self) -> None:
        response = self.client.post(page("ariza-yaratish"), self.creation_fields(), follow=True)

        created = Application.objects.get()
        self.assertContains(response, f"{created.ariza_raqami} yaratildi.")
        self.assertEqual(created.stage, Application.Stage.ACCEPTED)
        self.assertEqual(created.accepted_by, self.admin)
        self.assertEqual(created.status.code, ArizaStatus.Code.ACCEPTED)
        self.assertEqual(created.items.get().buyurtma_nomi, "Bolt M12x50")
        self.assertTrue(created.pdf)

    def test_creating_without_an_attachment_brings_the_form_back_open(self) -> None:
        fields = self.creation_fields()
        del fields["pdf"]

        response = self.client.post(page("ariza-yaratish"), fields)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "PDF ilova yuklanishi shart")
        self.assertContains(response, 'id="create-modal" class="modal-overlay"')
        self.assertFalse(Application.objects.exists())

    def test_a_file_that_is_not_a_pdf_is_refused(self) -> None:
        fields = self.creation_fields(pdf=a_pdf(name="ariza.txt"))

        response = self.client.post(page("ariza-yaratish"), fields)

        self.assertContains(response, "Faqat PDF fayl yuklanadi.")

    def test_assigning_and_re_assigning_from_the_page(self) -> None:
        application = an_accepted_application(self.admin)

        response = self.client.post(
            page("ariza-tayinlash", application.pk), {"xodim": self.specialist.pk}, follow=True
        )
        self.assertContains(response, "Dilnoza Yusupovaga tayinlandi")
        application.refresh_from_db()
        self.assertEqual(application.assigned_to, self.specialist)

        other = make_user(
            "spec2", user_type=KATTA_MUTAXASIS, first_name="Sardor", last_name="Nazarov"
        )
        response = self.client.post(
            page("ariza-tayinlash", application.pk), {"xodim": other.pk}, follow=True
        )
        self.assertContains(response, "Sardor Nazarovga tayinlandi")

    def test_assigning_nobody_or_a_non_specialist_is_refused(self) -> None:
        application = an_accepted_application(self.admin)

        nobody = self.client.post(
            page("ariza-tayinlash", application.pk), {"xodim": "abc"}, follow=True
        )
        manager = make_user("manager", user_type=MENEJER)
        not_a_specialist = self.client.post(
            page("ariza-tayinlash", application.pk), {"xodim": manager.pk}, follow=True
        )

        for response in (nobody, not_a_specialist):
            self.assertContains(response, "Katta Mutaxasis tanlanishi shart")
        application.refresh_from_db()
        self.assertIsNone(application.assigned_to)


class AssignedApplicationsTests(SignedInAdminTestCase):
    """Tayinlangan Arizalar: whose work is shown, taking it and reporting on it."""

    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        cls.specialist = make_user(
            "spec", user_type=KATTA_MUTAXASIS, first_name="Dilnoza", last_name="Yusupova"
        )
        cls.other_specialist = make_user(
            "spec2", user_type=KATTA_MUTAXASIS, first_name="Sardor", last_name="Nazarov"
        )

    def test_a_manager_sees_everybody_s_work_with_the_holder_column(self) -> None:
        mine = an_assigned_application(self.admin, self.specialist)
        theirs = an_assigned_application(self.admin, self.other_specialist)

        response = self.client.get(page("tayinlangan"))

        self.assertContains(response, mine.ariza_raqami)
        self.assertContains(response, theirs.ariza_raqami)
        self.assertContains(response, "<th>Tayinlangan xodim</th>")

    def test_a_specialist_sees_only_their_own_work(self) -> None:
        mine = an_assigned_application(self.admin, self.specialist)
        theirs = an_assigned_application(self.admin, self.other_specialist)
        self.client.force_login(self.specialist)

        response = self.client.get(page("tayinlangan"))

        self.assertContains(response, mine.ariza_raqami)
        self.assertNotContains(response, theirs.ariza_raqami)
        self.assertNotContains(response, "<th>Tayinlangan xodim</th>")

    def test_taking_the_work_tells_the_administrators(self) -> None:
        application = an_assigned_application(self.admin, self.specialist)
        self.client.force_login(self.specialist)

        response = self.client.post(page("tayinlangan-qabul", application.pk), follow=True)

        self.assertContains(response, f"{application.ariza_raqami} qabul qilindi.")
        self.assertContains(response, "Qabul qilingan</span>")
        self.assertEqual(Notification.objects.filter(recipient=self.admin).count(), 1)

        again = self.client.post(page("tayinlangan-qabul", application.pk), follow=True)
        self.assertContains(again, "allaqachon qabul qilingan")

    def test_a_manager_may_take_the_work_on_the_holder_s_behalf(self) -> None:
        application = an_assigned_application(self.admin, self.specialist)

        self.client.post(page("tayinlangan-qabul", application.pk))

        application.refresh_from_db()
        self.assertTrue(application.is_taken)

    def test_the_status_is_changed_from_the_row(self) -> None:
        application = an_assigned_application(self.admin, self.specialist)
        status = ArizaStatus.with_code(ArizaStatus.Code.ASSIGNED)

        response = self.client.post(
            page("tayinlangan-holat", application.pk), {"status": status.pk}, follow=True
        )
        self.assertContains(response, f"holati: {status.name}.")

        nothing = self.client.post(
            page("tayinlangan-holat", application.pk), {"status": ""}, follow=True
        )
        self.assertContains(nothing, "holat tanlanishi shart")


class ContractsTests(SignedInAdminTestCase):
    """Kelishinlingan Shartnoma and the entry form."""

    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        cls.specialist = make_user("spec", user_type=KATTA_MUTAXASIS)
        cls.application = an_assigned_application(cls.admin, cls.specialist)
        cls.supplier = a_supplier()

    def contract_fields(self, **overrides) -> dict:
        fields = {
            "application": self.application.pk,
            "supplier": self.supplier.pk,
            "shartnoma_turi": ShartnomaTuri.objects.get(name="Import").pk,
            "status": ShartnomaStatus.objects.first().pk,
            "shartnoma_sanasi": date.today().isoformat(),
            "tolash_muddati": "",
            "muddat_talabi": "",
            "izoh": "",
            **formset_management(2),
            "form-0-buyurtma_nomi": "Bolt",
            "form-0-part_number": "PN-1",
            "form-0-buyurtma_soni": "500",
            "form-0-olchov_birligi": "ta",
            "form-0-narxi": "85000",
            "form-1-buyurtma_nomi": "Gayka",
            "form-1-part_number": "",
            "form-1-buyurtma_soni": "500",
            "form-1-olchov_birligi": "ta",
            "form-1-narxi": "1000.50",
        }
        fields.update(overrides)
        return fields

    def test_entering_a_contract_totals_its_rows(self) -> None:
        response = self.client.post(
            page("shartnoma-yaratish"), self.contract_fields(), follow=True
        )

        contract = Contract.objects.get()
        self.assertEqual(str(contract.qiymati), "43000250.00")
        self.assertContains(response, f"{contract.shartnoma_raqami} yaratildi.")
        self.assertContains(response, "43 000 250,00")
        self.assertContains(response, "PN-1")
        self.assertEqual(contract.created_by, self.admin)

    def test_the_list_shows_agreed_and_rejected_contracts(self) -> None:
        self.client.post(page("shartnoma-yaratish"), self.contract_fields())
        rejected = Contract.objects.get()
        rejected.stage = Contract.Stage.REJECTED
        rejected.inkor_izohi = "Narx qayta ko'rilsin"
        rejected.save()

        response = self.client.get(page("kelishinlingan"))

        self.assertContains(response, rejected.shartnoma_raqami)
        self.assertContains(response, "Narx qayta ko&#39;rilsin")

    def test_a_contract_needs_a_supplier_a_date_and_at_least_one_row(self) -> None:
        response = self.client.post(
            page("shartnoma-yaratish"),
            self.contract_fields(supplier="", shartnoma_sanasi="", **formset_management(0)),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Shartnoma yaratilmadi")
        self.assertFalse(Contract.objects.exists())

    def test_a_specialist_may_only_contract_against_their_own_application(self) -> None:
        other = make_user("spec2", user_type=KATTA_MUTAXASIS)
        theirs = an_assigned_application(self.admin, other)
        self.client.force_login(self.specialist)

        response = self.client.post(
            page("shartnoma-yaratish"), self.contract_fields(application=theirs.pk)
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Contract.objects.exists())
        listed = self.client.get(page("kelishinlingan"))
        self.assertContains(listed, self.application.ariza_raqami)
        self.assertNotContains(listed, theirs.ariza_raqami)

    def test_the_supplier_drop_down_carries_the_inn(self) -> None:
        response = self.client.get(page("kelishinlingan"))

        self.assertContains(response, 'data-inn="123456789"')


class PurchaseApplicationsTests(SignedInAdminTestCase):
    """Xarid Arizasi: raising a request, the approval queue and the downloads."""

    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        cls.department = a_department("Texnik bo`lim")
        cls.other_department = a_department("Moliya bo`limi")
        cls.requester = make_user("requester", user_type=USERS, department=cls.department)
        cls.head = make_user("head", user_type=BOLIM_BOSHLIGI, department=cls.department)
        cls.other_head = make_user(
            "other.head", user_type=BOLIM_BOSHLIGI, department=cls.other_department
        )
        cls.direktor = make_user("direktor", user_type=DIREKTOR)

    def request_fields(self, **overrides) -> dict:
        fields = {
            "shartnoma_nomi": "Kabel xaridi",
            "muddat_talabi": "",
            "izoh": "",
            **formset_management(1),
            "form-0-mahsulot_turi": a_category().pk,
            "form-0-buyurtma_nomi": "Kabel 4mm",
            "form-0-buyurtma_soni": "200",
            "form-0-olchov_birligi": "m",
            "pdf": a_pdf(),
        }
        fields.update(overrides)
        return fields

    def test_a_requester_raises_a_request_against_their_own_department(self) -> None:
        self.client.force_login(self.requester)

        response = self.client.post(
            page("xarid-ariza-yaratish"), self.request_fields(), follow=True
        )

        request = PurchaseApplication.objects.get()
        self.assertContains(response, f"{request.xarid_raqami} yaratildi.")
        self.assertEqual(request.department, self.department)
        self.assertEqual(request.created_by, self.requester)
        self.assertEqual(request.stage, PurchaseApplication.Stage.AWAITING_HEAD)
        self.assertEqual(request.status.code, ArizaStatus.Code.NEW)

    def test_a_requester_without_a_department_is_told_what_is_missing(self) -> None:
        stray = make_user("stray", user_type=USERS)
        self.client.force_login(stray)

        response = self.client.post(page("xarid-ariza-yaratish"), self.request_fields())

        self.assertContains(response, "bo`lim biriktirilmagan")
        self.assertFalse(PurchaseApplication.objects.exists())

    def test_the_queue_shows_each_approver_only_what_waits_for_them(self) -> None:
        request = a_purchase_application(self.requester, self.department)
        queue_marker = "Tasdiqlashni kutayotgan arizalar"

        self.client.force_login(self.head)
        self.assertContains(self.client.get(page("xarid-ariza")), queue_marker)
        self.client.force_login(self.other_head)
        self.assertNotContains(self.client.get(page("xarid-ariza")), queue_marker)
        self.client.force_login(self.direktor)
        self.assertNotContains(self.client.get(page("xarid-ariza")), queue_marker)

        request.approve(by=self.head)
        self.assertContains(self.client.get(page("xarid-ariza")), queue_marker)
        self.client.force_login(self.requester)
        self.assertNotContains(self.client.get(page("xarid-ariza")), queue_marker)

    def test_the_chain_from_the_page_raises_the_department_application(self) -> None:
        request = a_purchase_application(self.requester, self.department)

        self.client.force_login(self.head)
        response = self.client.post(page("xarid-ariza-tasdiqlash", request.pk), follow=True)
        self.assertContains(response, "direktorga yuborildi")

        self.client.force_login(self.direktor)
        response = self.client.post(page("xarid-ariza-tasdiqlash", request.pk), follow=True)
        request.refresh_from_db()
        self.assertContains(response, f"{request.raised_application.ariza_raqami} yaratildi")
        self.assertEqual(request.stage, PurchaseApplication.Stage.APPROVED)
        self.client.force_login(self.admin)
        self.assertContains(
            self.client.get(page("kelib-arizalar")), request.raised_application.ariza_raqami
        )

    def test_a_late_approval_is_told_rather_than_forbidden(self) -> None:
        request = a_purchase_application(self.requester, self.department)
        request.approve(by=self.head)
        self.client.force_login(self.head)

        response = self.client.post(page("xarid-ariza-tasdiqlash", request.pk), follow=True)

        self.assertContains(response, "allaqachon hal qilingan")

    def test_refusing_needs_a_comment_and_tells_the_requester(self) -> None:
        request = a_purchase_application(self.requester, self.department)
        self.client.force_login(self.head)

        without = self.client.post(
            page("xarid-ariza-inkor", request.pk), {"inkor_izohi": ""}, follow=True
        )
        self.assertContains(without, "izoh kiritilishi shart")

        with_comment = self.client.post(
            page("xarid-ariza-inkor", request.pk), {"inkor_izohi": "Byudjet yo'q"}, follow=True
        )
        self.assertContains(with_comment, f"{request.xarid_raqami} inkor etildi.")
        self.assertEqual(Notification.objects.filter(recipient=self.requester).count(), 1)

    def test_the_pdf_and_the_original_download(self) -> None:
        request = a_purchase_application(self.requester, self.department)

        stamped = self.client.get(page("xarid-ariza-pdf", request.pk))
        self.assertEqual(stamped.status_code, 200)
        self.assertIn(f'filename="{request.xarid_raqami}.pdf"', stamped["Content-Disposition"])
        self.assertEqual(self.client.get(page("xarid-ariza-asl-pdf", request.pk)).status_code, 404)

        request.approve(by=self.head)
        request.approve(by=self.direktor)

        original = self.client.get(page("xarid-ariza-asl-pdf", request.pk))
        self.assertEqual(original.status_code, 200)
        self.assertIn("-asl.pdf", original["Content-Disposition"])

    def test_a_request_without_an_attachment_has_nothing_to_download(self) -> None:
        request = a_purchase_application(self.requester, self.department, with_pdf=False)

        self.assertEqual(self.client.get(page("xarid-ariza-pdf", request.pk)).status_code, 404)


class PrototypePageTests(SignedInAdminTestCase):
    """The pages that are still the supplied prototype render with their scripts."""

    def test_every_prototype_page_renders(self) -> None:
        for page_name in PROTOTYPE_PAGE_TEMPLATES:
            with self.subTest(page=page_name):
                response = self.client.get(page(page_name))

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "xarid/js/main.js")

    def test_every_page_script_a_template_asks_for_exists(self) -> None:
        for script in (
            "dashboard",
            "tuzilgan",
            "mahsulot-tur",
            "integration",
            "logs",
        ):
            with self.subTest(script=script):
                self.assertIsNotNone(finders.find(f"xarid/js/pages/{script}.js"))

    def test_the_dashboard_answers_at_the_site_root(self) -> None:
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Asosiy Panel")
        self.assertContains(response, reverse("xarid:kelib-arizalar"))


class LandingPageTests(SignedInAdminTestCase):
    """Signing in lands on the first page the user's type may open."""

    def test_an_admin_lands_on_the_dashboard(self) -> None:
        self.assertRedirects(self.client.get(page("landing")), page("dashboard"))

    def test_a_requester_lands_on_the_purchase_page(self) -> None:
        self.client.force_login(make_user("requester", user_type=USERS))

        self.assertRedirects(self.client.get(page("landing")), page("xarid-ariza"))

    def test_an_account_with_no_type_is_refused(self) -> None:
        self.client.force_login(make_user("untyped"))

        self.assertEqual(self.client.get(page("landing")).status_code, 403)

    def test_a_superuser_without_a_type_lands_on_the_dashboard(self) -> None:
        self.client.force_login(make_user("root", is_staff=True, is_superuser=True))

        self.assertRedirects(self.client.get(page("landing")), page("dashboard"))
        self.assertFalse(UserProfile.objects.filter(user__username="root").exists())
