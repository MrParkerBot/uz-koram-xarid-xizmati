"""Tests for the pages: what they show and what their actions do."""

from __future__ import annotations

from datetime import date, timedelta
from io import BytesIO

from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.utils.timezone import localtime
from openpyxl import load_workbook
from pypdf import PdfReader

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
    an_arrived_purchase_request,
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
    deactivate,
    profile_of,
)
from xarid.permissions import contract_editor
from xarid.views import PROTOTYPE_PAGE_TEMPLATES


def workbook_rows(response) -> list[list[object]]:
    """The rows of a downloaded workbook, header first."""
    sheet = load_workbook(BytesIO(response.content)).active
    return [list(row) for row in sheet.iter_rows(values_only=True)]


def pdf_text(response) -> str:
    """Everything a downloaded PDF has written on it, pages joined."""
    return " ".join(sheet.extract_text() for sheet in PdfReader(BytesIO(response.content)).pages)


def pdf_image_count(response) -> int:
    """How many images a downloaded PDF draws - its QR codes, here."""
    return sum(len(list(sheet.images)) for sheet in PdfReader(BytesIO(response.content)).pages)


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

    def test_a_category_left_unnumbered_is_given_the_next_number(self) -> None:
        """Bo`sh qoldirilsa, avtomatik: the page says so and the model does it."""
        a_category(100042, "Metallurgiya")

        response = self.client.post(
            page("mahsulot-turlari-create"), {"category_number": "", "name": "Kimyo"}
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(MahsulotTuri.objects.get(name="Kimyo").category_number, 100043)

    def test_the_first_category_of_an_empty_table_starts_the_range(self) -> None:
        self.client.post(page("mahsulot-turlari-create"), {"category_number": "", "name": "Metall"})

        self.assertEqual(MahsulotTuri.objects.get(name="Metall").category_number, 100000)

    def test_a_generated_number_skips_the_one_a_deleted_category_holds(self) -> None:
        """DEC-009 keeps the row, and the row keeps its number."""
        deleted = a_category(100500, "Eskirgan")
        deactivate(deleted)

        self.client.post(page("mahsulot-turlari-create"), {"category_number": "", "name": "Yangi"})

        self.assertEqual(MahsulotTuri.objects.get(name="Yangi").category_number, 100501)

    def test_editing_a_category_without_a_number_keeps_the_one_it_has(self) -> None:
        """Emptying the box leaves the code alone rather than renumbering it."""
        category = a_category(100042, "Metallurgiya")

        self.client.post(
            page("mahsulot-turlari-update", category.pk),
            {"category_number": "", "name": "Metallurgiya va qotishmalar"},
        )

        category.refresh_from_db()
        self.assertEqual(category.category_number, 100042)
        self.assertEqual(category.name, "Metallurgiya va qotishmalar")

    def test_a_number_that_was_typed_is_kept_as_typed(self) -> None:
        a_category(100042, "Metallurgiya")

        self.client.post(
            page("mahsulot-turlari-create"), {"category_number": "100777", "name": "Kimyo"}
        )

        self.assertEqual(MahsulotTuri.objects.get(name="Kimyo").category_number, 100777)

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
            "phone_number": "90-123-45-67",
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
        self.assertEqual(created.profile.phone_number, "90-123-45-67")
        self.assertEqual(created.profile.department, a_department())

        listed = self.client.get(page("users"))
        self.assertContains(listed, "bobur.toshmatov")
        self.assertContains(listed, "+998 90-123-45-67")

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
        self.assertContains(bad_phone, "Format: 90-123-45-67")
        self.assertFalse(get_user_model().objects.filter(username="bobur.toshmatov").exists())

    def test_editing_with_an_empty_password_keeps_the_current_one(self) -> None:
        edited = make_user("bobur", first_name="Bobur", last_name="Toshmatov")

        response = self.client.post(
            page("user-update", edited.pk),
            self.user_fields(password="", phone_number="91-111-22-33"),
        )

        self.assertRedirects(response, page("users"))
        edited.refresh_from_db()
        self.assertTrue(edited.check_password(PASSWORD))
        self.assertEqual(edited.profile.phone_number, "91-111-22-33")

    def test_the_edit_form_opens_filled_in_without_the_password(self) -> None:
        edited = make_user("bobur", first_name="Bobur", last_name="Toshmatov")

        response = self.client.get(page("users"), {"edit": edited.pk})

        self.assertContains(response, 'value="Bobur"')
        self.assertContains(response, page("user-update", edited.pk))
        self.assertNotContains(response, PASSWORD)

    def test_a_number_stored_before_the_mask_opens_and_lists_dashed(self) -> None:
        """An account saved as "90 123 45 67" must still edit and read alike."""
        edited = make_user("bobur", first_name="Bobur", last_name="Toshmatov")
        profile = profile_of(edited)
        profile.phone_number = "90 123 45 67"
        profile.save(update_fields=["phone_number"])

        listed = self.client.get(page("users"))
        form = self.client.get(page("users"), {"edit": edited.pk})

        self.assertContains(listed, "+998 90-123-45-67")
        self.assertContains(form, 'value="90-123-45-67"')

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


class HeadOwnApprovalsTests(SignedInAdminTestCase):
    """Qabul Qilingan Arizalar is a head's own approvals outside Xarid Bo`limi."""

    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        cls.purchasing = a_department("Xarid bo`limi")
        cls.purchasing.is_purchasing = True
        cls.purchasing.save(update_fields=["is_purchasing"])
        cls.elsewhere = a_department("Ishlab chiqarish")
        cls.head = make_user("own.head", user_type=BOLIM_BOSHLIGI, department=cls.elsewhere)
        cls.other_head = make_user(
            "own.other.head", user_type=BOLIM_BOSHLIGI, department=a_department("Buxgalteriya")
        )
        cls.xarid_head = make_user(
            "own.xarid.head", user_type=BOLIM_BOSHLIGI, department=cls.purchasing
        )
        cls.requester = make_user("own.requester", user_type=USERS, department=cls.elsewhere)
        cls.direktor = make_user("own.direktor", user_type=DIREKTOR)

    def approved_by_the_head(self) -> PurchaseApplication:
        request = a_purchase_application(self.requester, self.elsewhere, with_pdf=False)
        request.approve(by=self.head)
        request.refresh_from_db()
        return request

    def test_a_head_outside_the_purchasing_department_reads_their_own_approvals(self) -> None:
        request = self.approved_by_the_head()
        self.client.force_login(self.head)

        response = self.client.get(page("qabul-arizalar"))

        self.assertContains(response, "Tasdiqlangan Arizalar")
        self.assertContains(response, request.xarid_raqami)
        self.assertNotContains(response, "Qabul Qilingan Arizalar")

    def test_the_sidebar_entry_is_renamed_to_match_the_page(self) -> None:
        self.client.force_login(self.head)

        response = self.client.get(page("qabul-arizalar"))

        self.assertContains(response, ">Tasdiqlangan</span>")
        self.assertNotContains(response, ">Qabul Qilingan</span>")

    def test_the_head_of_the_purchasing_department_keeps_the_page_as_it_was(self) -> None:
        accepted = an_accepted_application(self.admin)
        self.client.force_login(self.xarid_head)

        response = self.client.get(page("qabul-arizalar"))

        self.assertContains(response, "Qabul Qilingan Arizalar")
        self.assertContains(response, accepted.ariza_raqami)
        self.assertContains(response, ">Qabul Qilingan</span>")

    def test_admin_keeps_the_page_as_it_was(self) -> None:
        accepted = an_accepted_application(self.admin)

        response = self.client.get(page("qabul-arizalar"))

        self.assertContains(response, "Qabul Qilingan Arizalar")
        self.assertContains(response, accepted.ariza_raqami)

    def test_one_head_does_not_read_another_head_s_approvals(self) -> None:
        mine = self.approved_by_the_head()
        self.client.force_login(self.other_head)

        response = self.client.get(page("qabul-arizalar"))

        self.assertNotContains(response, mine.xarid_raqami)
        self.assertContains(response, "Siz hali ariza tasdiqlamagansiz.")

    def test_a_request_the_direktor_went_on_to_refuse_is_still_listed(self) -> None:
        """A record of what this head did, not of how it turned out."""
        request = self.approved_by_the_head()
        request.reject(by=self.direktor, comment="Byudjet yetarli emas")
        self.client.force_login(self.head)

        response = self.client.get(page("qabul-arizalar"))

        self.assertContains(response, request.xarid_raqami)
        self.assertContains(response, "Inkor etilgan")

    def test_the_table_filters_by_what_became_of_the_request(self) -> None:
        refused = self.approved_by_the_head()
        refused.reject(by=self.direktor, comment="Byudjet yetarli emas")
        still_going = self.approved_by_the_head()
        self.client.force_login(self.head)

        response = self.client.get(page("qabul-arizalar"), {"bosqich": "rejected"})

        self.assertContains(response, refused.xarid_raqami)
        self.assertNotContains(response, still_going.xarid_raqami)
        # The drop-down offers the words the table prints, not the stored code.
        self.assertContains(response, "Inkor etilgan</option>")
        self.assertNotContains(response, ">rejected</option>")

    def test_the_table_filters_by_who_asked_for_it(self) -> None:
        somebody_else = make_user(
            "own.requester.two", user_type=USERS, department=self.elsewhere
        )
        mine = self.approved_by_the_head()
        theirs = a_purchase_application(somebody_else, self.elsewhere, with_pdf=False)
        theirs.approve(by=self.head)
        self.client.force_login(self.head)

        response = self.client.get(
            page("qabul-arizalar"), {"buyurtmachi": self.requester.pk}
        )

        self.assertContains(response, mine.xarid_raqami)
        self.assertNotContains(response, theirs.xarid_raqami)

    def test_the_table_still_filters_by_product_category(self) -> None:
        plastik = a_category(300055, "Plastik")
        chosen = a_purchase_application(
            self.requester, self.elsewhere, category=plastik, with_pdf=False
        )
        chosen.approve(by=self.head)
        other = self.approved_by_the_head()
        self.client.force_login(self.head)

        response = self.client.get(page("qabul-arizalar"), {"mahsulot": plastik.pk})

        self.assertContains(response, chosen.xarid_raqami)
        self.assertNotContains(response, other.xarid_raqami)

    def test_the_download_follows_whichever_table_the_page_showed(self) -> None:
        request = self.approved_by_the_head()
        self.client.force_login(self.head)

        rows = workbook_rows(self.client.get(page("qabul-arizalar-eksport", "xlsx")))

        self.assertEqual(rows[0][0], "Ariza raqami")
        self.assertEqual([row[0] for row in rows[1:]], [request.xarid_raqami])


class DirektorOwnApprovalsTests(SignedInAdminTestCase):
    """The same page read from the chain's second step (DEC-016)."""

    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        cls.purchasing = a_department("Xarid bo`limi")
        cls.purchasing.is_purchasing = True
        cls.purchasing.save(update_fields=["is_purchasing"])
        cls.elsewhere = a_department("Ishlab chiqarish")
        cls.head = make_user("dir.head", user_type=BOLIM_BOSHLIGI, department=cls.elsewhere)
        cls.requester = make_user("dir.requester", user_type=USERS, department=cls.elsewhere)
        cls.direktor = make_user("dir.direktor", user_type=DIREKTOR)

    def awaiting_the_direktor(self) -> PurchaseApplication:
        request = a_purchase_application(self.requester, self.elsewhere, with_pdf=False)
        request.approve(by=self.head)
        request.refresh_from_db()
        return request

    def test_approving_moves_the_request_onto_the_direktor_s_tasdiqlangan_page(self) -> None:
        """The whole point: Tasdiqlash on Kelib Tushgan, the row lands here."""
        request = self.awaiting_the_direktor()
        self.client.force_login(self.direktor)

        self.assertNotContains(self.client.get(page("qabul-arizalar")), request.xarid_raqami)

        self.client.post(page("xarid-ariza-tasdiqlash", request.pk))
        response = self.client.get(page("qabul-arizalar"))

        self.assertContains(response, "Tasdiqlangan Arizalar")
        self.assertContains(response, request.xarid_raqami)
        self.assertContains(response, "Tasdiqlangan")
        # And it has left the queue it was decided on.
        self.assertNotContains(
            self.client.get(page("kelib-arizalar")), "Direktor tasdig'ini kutmoqda"
        )

    def test_the_date_shown_is_the_direktor_s_own_step(self) -> None:
        """Not the head's: every row here carries both dates."""
        request = self.awaiting_the_direktor()
        PurchaseApplication.objects.filter(pk=request.pk).update(
            bolim_boshligi_sanasi=timezone.now() - timedelta(days=30)
        )
        request.refresh_from_db()
        request.approve(by=self.direktor)
        self.client.force_login(self.direktor)

        response = self.client.get(page("qabul-arizalar"))

        request.refresh_from_db()
        self.assertContains(response, localtime(request.direktor_sanasi).strftime("%d/%m/%Y"))
        self.assertNotContains(
            response, localtime(request.bolim_boshligi_sanasi).strftime("%d/%m/%Y")
        )

    def test_a_request_still_waiting_for_them_is_not_yet_listed(self) -> None:
        request = self.awaiting_the_direktor()
        self.client.force_login(self.direktor)

        response = self.client.get(page("qabul-arizalar"))

        self.assertNotContains(response, request.xarid_raqami)
        self.assertContains(response, "Siz hali ariza tasdiqlamagansiz.")

    def test_a_request_they_refused_is_not_one_they_approved(self) -> None:
        request = self.awaiting_the_direktor()
        request.reject(by=self.direktor, comment="Byudjet yetarli emas")
        self.client.force_login(self.direktor)

        self.assertNotContains(self.client.get(page("qabul-arizalar")), request.xarid_raqami)

    def test_the_sidebar_entry_is_renamed_for_the_direktor_too(self) -> None:
        self.client.force_login(self.direktor)

        response = self.client.get(page("qabul-arizalar"))

        self.assertContains(response, ">Tasdiqlangan</span>")
        self.assertNotContains(response, ">Qabul Qilingan</span>")

    def test_the_holati_filter_is_dropped_where_it_could_only_empty_the_table(self) -> None:
        """Theirs is the chain's last approval, so every row is approved."""
        self.client.force_login(self.direktor)

        response = self.client.get(page("qabul-arizalar"))

        self.assertNotContains(response, 'name="bosqich"')

    def test_the_download_follows_the_table_the_direktor_was_shown(self) -> None:
        request = self.awaiting_the_direktor()
        request.approve(by=self.direktor)
        self.client.force_login(self.direktor)

        rows = workbook_rows(self.client.get(page("qabul-arizalar-eksport", "xlsx")))

        self.assertEqual(rows[0][0], "Ariza raqami")
        self.assertEqual([row[0] for row in rows[1:]], [request.xarid_raqami])


class IncomingApplicationsTests(SignedInAdminTestCase):
    """Kelib tushgan Arizalar and its two decisions."""

    def test_the_queue_belongs_to_the_purchasing_department(self) -> None:
        """Its head and its Menejer work it; another department's head does not."""
        purchasing = a_department("Xarid bo`limi")
        purchasing.is_purchasing = True
        purchasing.save(update_fields=["is_purchasing"])
        elsewhere = a_department("Ishlab chiqarish")
        arrived = an_arrived_purchase_request(department=elsewhere)

        for user, sees in (
            (make_user("xarid.head", user_type=BOLIM_BOSHLIGI, department=purchasing), True),
            (make_user("xarid.menejer", user_type=MENEJER, department=purchasing), True),
            (make_user("other.boss", user_type=BOLIM_BOSHLIGI, department=elsewhere), False),
            (make_user("other.menejer", user_type=MENEJER, department=elsewhere), False),
        ):
            with self.subTest(user=user.get_username()):
                self.client.force_login(user)
                response = self.client.get(page("kelib-arizalar"))
                if sees:
                    self.assertContains(response, arrived.xarid_raqami)
                else:
                    self.assertNotContains(response, arrived.xarid_raqami)

    def test_admin_and_direktor_keep_the_whole_queue(self) -> None:
        purchasing = a_department("Xarid bo`limi")
        purchasing.is_purchasing = True
        purchasing.save(update_fields=["is_purchasing"])
        arrived = an_arrived_purchase_request()

        self.assertContains(self.client.get(page("kelib-arizalar")), arrived.xarid_raqami)

        self.client.force_login(make_user("the.direktor", user_type=DIREKTOR))
        self.assertContains(self.client.get(page("kelib-arizalar")), arrived.xarid_raqami)

    def test_nothing_narrows_until_a_purchasing_department_is_named(self) -> None:
        """The mark is a switch an administrator throws, not a default."""
        elsewhere = a_department("Ishlab chiqarish")
        arrived = an_arrived_purchase_request(department=elsewhere)
        self.client.force_login(
            make_user("unmarked.boss", user_type=BOLIM_BOSHLIGI, department=elsewhere)
        )

        self.assertContains(self.client.get(page("kelib-arizalar")), arrived.xarid_raqami)

    def test_the_list_holds_the_requests_that_arrived_and_not_the_ones_taken_up(self) -> None:
        """A row leaves the table the moment somebody accepts what it raised."""
        arrived = an_arrived_purchase_request()
        taken_up = an_arrived_purchase_request()
        taken_up.raised_application.accept(by=self.admin)

        response = self.client.get(page("kelib-arizalar"))

        self.assertContains(response, arrived.xarid_raqami)
        self.assertNotContains(response, taken_up.xarid_raqami)
        # And the row carries the two decisions this page has always offered.
        self.assertContains(response, page("ariza-qabul", arrived.raised_application.pk))
        self.assertContains(response, page("ariza-inkor", arrived.raised_application.pk))

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


class AcceptedApplicationDocumentTests(SignedInAdminTestCase):
    """The Izoh panel and the Ariza PDF beside the Ilova PDF (Qabul qilingan)."""

    def test_the_izoh_panel_says_who_accepted_it(self) -> None:
        application = an_application()
        self.client.post(page("ariza-qabul", application.pk))

        response = self.client.get(page("qabul-arizalar"))

        self.assertContains(response, f'id="qa-izoh-{application.pk}-overlay"')
        self.assertContains(response, f'data-open-drawer="qa-izoh-{application.pk}"')
        self.assertContains(response, "Qabul qildi")
        # Accepting is a button and carries no comment, so the entry says so
        # rather than showing an empty box.
        self.assertContains(response, "Izoh qoldirilmagan.")

    def test_the_two_pdf_columns_are_named_apart(self) -> None:
        """One is what arrived with the request, the other is the record."""
        application = an_accepted_application(self.admin)

        response = self.client.get(page("qabul-arizalar"))

        self.assertContains(response, "Ariza PDF")
        self.assertContains(response, "Ilova PDF")
        self.assertContains(response, page("ariza-hujjat-pdf", application.pk))

    def test_the_attachment_downloads_as_an_ilova_and_the_sheet_does_not(self) -> None:
        """The two columns download under two names, as they are two things."""
        application = an_accepted_application(self.admin, with_pdf=True)

        uploaded = self.client.get(page("ariza-pdf", application.pk))
        drawn = self.client.get(page("ariza-hujjat-pdf", application.pk))

        self.assertIn(
            f'filename="{application.ariza_raqami}-Ilova.pdf"', uploaded["Content-Disposition"]
        )
        self.assertIn(
            f'filename="{application.ariza_raqami}-ariza.pdf"', drawn["Content-Disposition"]
        )

    def test_the_ariza_pdf_is_there_when_nothing_was_attached(self) -> None:
        application = an_accepted_application(self.admin, with_pdf=False)

        response = self.client.get(page("ariza-hujjat-pdf", application.pk))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        text = pdf_text(response)
        self.assertIn("ARIZA", text)
        self.assertIn(application.ariza_raqami, text)
        self.assertIn(application.department.name, text)

    def test_the_ariza_pdf_signs_the_acceptance_of_one_nobody_raised(self) -> None:
        """Keyed in by hand, so the two approvals above it never happened.

        The sheet is still the request's own, because a reader should not
        have to learn a second layout for the same thing: the two steps it
        never went through are simply not on it.
        """
        specialist = make_user(
            "doc.spec", user_type=KATTA_MUTAXASIS, first_name="Dilnoza", last_name="Yusupova"
        )
        application = an_assigned_application(self.admin, specialist)

        response = self.client.get(page("ariza-hujjat-pdf", application.pk))
        text = pdf_text(response)

        self.assertIn("XARID ARIZASI", text)
        self.assertIn(application.ariza_raqami, text)
        self.assertIn("Xarid bo`lim boshlig`i", text)
        self.assertIn("Qabul qilingan", text)
        self.assertIn("Test Admin", text)
        # The acceptance is signed; nothing waits, because the two approval
        # steps are a request's and this was never one.
        self.assertEqual(pdf_image_count(response), 1)
        self.assertNotIn("Kutilmoqda", text)

    def test_the_ariza_pdf_follows_the_page_the_application_is_on(self) -> None:
        """The same DEC-019 rule as the attachment beside it."""
        application = an_application()
        self.client.force_login(make_user("doc.user", user_type=USERS))

        self.assertEqual(
            self.client.get(page("ariza-hujjat-pdf", application.pk)).status_code, 403
        )


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

    def test_a_taken_application_is_marked_in_a_colour_the_stylesheet_defines(self) -> None:
        """badge-success has no rule: it renders as no fill at all."""
        application = an_assigned_application(self.admin, self.specialist)
        application.accept_as_specialist(by=self.specialist)

        response = self.client.get(page("tayinlangan"))

        self.assertContains(response, "Qabul qilingan")
        self.assertContains(response, "badge-approved")
        self.assertNotContains(response, "badge-success")

    def test_the_table_carries_no_izoh_column(self) -> None:
        """It held a note and an icon that opened nothing, and is gone."""
        an_assigned_application(self.admin, self.specialist)

        response = self.client.get(page("tayinlangan"))

        self.assertNotContains(response, "comment-icon")
        self.assertNotContains(response, "bi-chat-left-text")
        self.assertNotContains(response, "<th>Izoh</th>")
        # And nothing was left half-removed: no drawer, no button for one.
        self.assertNotContains(response, "data-open-drawer")
        self.assertNotContains(response, "drawer-overlay")

    def test_the_two_pdf_columns_are_named_apart(self) -> None:
        """The same pair Qabul Qilingan Arizalar carries, for the same reason."""
        application = an_assigned_application(self.admin, self.specialist, with_pdf=True)

        response = self.client.get(page("tayinlangan"))

        self.assertContains(response, "Ariza PDF")
        self.assertContains(response, "Ilova PDF")
        self.assertContains(response, page("ariza-hujjat-pdf", application.pk))
        self.assertContains(response, page("ariza-pdf", application.pk))

    def test_the_ariza_pdf_is_offered_when_nothing_was_attached(self) -> None:
        """It is drawn from the record, so the column is never empty."""
        application = an_assigned_application(self.admin, self.specialist, with_pdf=False)

        response = self.client.get(page("tayinlangan"))

        self.assertContains(response, page("ariza-hujjat-pdf", application.pk))
        # Nothing arrived with it, so the Ilova cell says so instead.
        self.assertNotContains(response, page("ariza-pdf", application.pk))

    def test_both_types_who_work_the_page_read_both_documents(self) -> None:
        """The pair is for Xarid Bo`limi's own head and its specialists.

        The columns are only worth having if the links behind them open, so
        this follows each icon through to the download rather than stopping
        at the markup.
        """
        purchasing = a_department("Xarid bo`limi")
        purchasing.is_purchasing = True
        purchasing.save(update_fields=["is_purchasing"])
        head = make_user("xb.head", user_type=BOLIM_BOSHLIGI, department=purchasing)
        specialist = make_user("xb.spec", user_type=KATTA_MUTAXASIS, department=purchasing)
        application = an_assigned_application(self.admin, specialist, with_pdf=True)

        for reader in (head, specialist):
            with self.subTest(reader=reader.get_username()):
                self.client.force_login(reader)

                page_response = self.client.get(page("tayinlangan"))
                self.assertContains(page_response, "Ariza PDF")
                self.assertContains(page_response, "Ilova PDF")

                drawn = self.client.get(page("ariza-hujjat-pdf", application.pk))
                self.assertEqual(drawn.status_code, 200)
                self.assertEqual(drawn["Content-Type"], "application/pdf")
                self.assertIn(application.ariza_raqami, pdf_text(drawn))

                attached = self.client.get(page("ariza-pdf", application.pk))
                self.assertEqual(attached.status_code, 200)
                self.assertEqual(attached["Content-Type"], "application/pdf")

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
        """The holder's to move, so it is the holder who posts it."""
        application = an_assigned_application(self.admin, self.specialist)
        # Assigning put it at Tayinlangan, so the move the holder posts is
        # the one after it on the Ariza Status list.
        status = ArizaStatus.objects.get(name="Qabul qilingan")
        self.client.force_login(self.specialist)

        response = self.client.post(
            page("tayinlangan-holat", application.pk), {"status": status.pk}, follow=True
        )
        self.assertContains(response, f"holati: {status.name}.")

        nothing = self.client.post(
            page("tayinlangan-holat", application.pk), {"status": ""}, follow=True
        )
        self.assertContains(nothing, "holat tanlanishi shart")

    def test_assigning_and_taking_move_the_status_by_themselves(self) -> None:
        """Tayinlangan on the hand-out, Qabul qilingan when it is taken up."""
        application = an_assigned_application(self.admin, self.specialist)
        self.assertEqual(application.status.name, "Tayinlangan")

        self.client.force_login(self.specialist)
        self.client.post(page("tayinlangan-qabul", application.pk))

        application.refresh_from_db()
        self.assertEqual(application.status.name, "Qabul qilingan")

    def test_only_the_holder_may_move_the_status(self) -> None:
        """Xarid bo`limi's head reads the column; the specialist writes it."""
        application = an_assigned_application(self.admin, self.specialist)
        status = ShartnomaStatus.objects.get(name="Birjaga qo`yilgan")
        purchasing = a_department("Xarid bo`limi")
        purchasing.is_purchasing = True
        purchasing.save(update_fields=["is_purchasing"])
        head = make_user("holat.head", user_type=BOLIM_BOSHLIGI, department=purchasing)
        self.client.force_login(head)

        page_response = self.client.get(page("tayinlangan"))
        # The status is shown as a badge, and the control that would change
        # it is not drawn at all. Checked by the form's action, because the
        # route's name never appears in the markup.
        self.assertContains(page_response, ">Tayinlangan</span>")
        self.assertNotContains(page_response, page("tayinlangan-holat", application.pk))
        self.assertNotContains(page_response, 'name="status"')

        refused = self.client.post(
            page("tayinlangan-holat", application.pk), {"status": status.pk}
        )
        self.assertEqual(refused.status_code, 403)
        application.refresh_from_db()
        self.assertEqual(application.status.name, "Tayinlangan")


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
            # Typed in and matched on the number, not picked by id.
            "application": self.application.ariza_raqami,
            "supplier": self.supplier.name,
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
            "pdf": a_pdf("shartnoma.pdf"),
        }
        fields.update(overrides)
        return fields

    def test_the_ariza_raqami_is_typed_with_its_own_suggestion_list(self) -> None:
        """A box and a list drawn in the page, not a drop-down or a datalist.

        Drawn in the page because a browser renders a <datalist> popup
        itself, outside the document, so it cannot be told to show five rows
        and scroll the rest. The stylesheet does that to .combo-list, which
        only works if the markup below is what it is given.
        """
        response = self.client.get(page("kelishinlingan"))

        self.assertContains(response, 'name="application"')
        self.assertNotContains(response, '<select name="application"')
        # No datalist: two popups over one box is worse than none.
        self.assertNotContains(response, 'list="ariza-raqamlari"')
        self.assertContains(response, "data-combo")
        self.assertContains(response, "combo-list")
        self.assertContains(response, f'data-value="{self.application.ariza_raqami}"')
        # The suggestion carries what the number is recognised by.
        self.assertContains(response, self.application.department.name)

    def test_the_firma_nomi_is_typed_with_its_own_suggestion_list(self) -> None:
        """Searched like Ariza raqami, and still carrying the INN (DEC-011)."""
        response = self.client.get(page("kelishinlingan"))

        self.assertContains(response, 'name="supplier"')
        self.assertNotContains(response, '<select name="supplier"')
        self.assertContains(response, f'data-value="{self.supplier.name}"')
        # The INN rides on the suggestion, so picking a firm fills the box
        # beside it without another trip to the server.
        self.assertContains(response, f'data-inn="{self.supplier.inn}"')
        self.assertContains(response, "data-inn-source")

    def test_a_firm_is_matched_however_its_name_was_typed(self) -> None:
        response = self.client.post(
            page("shartnoma-yaratish"),
            self.contract_fields(supplier=f"  {self.supplier.name.upper()}  "),
            follow=True,
        )

        self.assertContains(response, "yaratildi.")
        self.assertEqual(Contract.objects.get().supplier, self.supplier)

    def test_a_firm_name_that_matches_nothing_is_refused(self) -> None:
        response = self.client.post(
            page("shartnoma-yaratish"),
            self.contract_fields(supplier="Yo`q Firma MCHJ"),
            follow=True,
        )

        self.assertContains(response, "topilmadi")
        self.assertFalse(Contract.objects.exists())

    def test_every_assignable_number_is_offered_however_many_there_are(self) -> None:
        """Five are shown at a time; the rest are there to be scrolled to."""
        for _ in range(7):
            an_assigned_application(self.admin, self.specialist)
        offered = Application.objects.filter(stage=Application.Stage.ASSIGNED)

        response = self.client.get(page("kelishinlingan"))

        self.assertEqual(offered.count(), 8)
        for application in offered:
            self.assertContains(response, f'data-value="{application.ariza_raqami}"')

    def test_a_number_is_matched_however_it_was_typed(self) -> None:
        """Read off another screen and typed as seen, case and spaces included."""
        response = self.client.post(
            page("shartnoma-yaratish"),
            self.contract_fields(
                application=f"  {self.application.ariza_raqami.lower()}  "
            ),
            follow=True,
        )

        self.assertContains(response, "yaratildi.")
        self.assertEqual(Contract.objects.get().application, self.application)

    def test_a_number_that_matches_nothing_is_refused(self) -> None:
        response = self.client.post(
            page("shartnoma-yaratish"),
            self.contract_fields(application="ARZ-2026-09999"),
            follow=True,
        )

        self.assertContains(response, "topilmadi")
        self.assertFalse(Contract.objects.exists())

    def test_typing_another_specialist_s_number_is_still_refused(self) -> None:
        """The box must not be a way round REQ-ROLE-007's own-work rule."""
        other = make_user("spec.other", user_type=KATTA_MUTAXASIS)
        theirs = an_assigned_application(self.admin, other)
        self.client.force_login(self.specialist)

        page_response = self.client.get(page("kelishinlingan"))
        self.assertNotContains(page_response, f'<option value="{theirs.ariza_raqami}">')

        response = self.client.post(
            page("shartnoma-yaratish"),
            self.contract_fields(application=theirs.ariza_raqami),
            follow=True,
        )

        self.assertContains(response, "topilmadi")
        self.assertFalse(Contract.objects.exists())

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
        """Both stages are on this page; a rejected one comes back to be resent.

        The rejection reason is not asserted here any more: since
        TASK-UZK-066 the Izoh column is an icon, and what it opens is built
        from the decision log rather than from this column.
        """
        self.client.post(page("shartnoma-yaratish"), self.contract_fields())
        rejected = Contract.objects.get()
        rejected.stage = Contract.Stage.REJECTED
        rejected.inkor_izohi = "Narx qayta ko'rilsin"
        rejected.save()

        response = self.client.get(page("kelishinlingan"))

        self.assertContains(response, rejected.shartnoma_raqami)
        self.assertContains(response, "Re-Send")

    def test_a_contract_entered_without_its_pdf_is_refused(self) -> None:
        """REQ-SHARTNOMA-010: the document comes with the row, or neither does."""
        response = self.client.post(
            page("shartnoma-yaratish"), self.contract_fields(pdf="")
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Shartnoma uchun PDF ilova yuklanishi shart.")
        self.assertFalse(Contract.objects.exists())

    def test_the_attachment_is_kept_against_the_contract(self) -> None:
        self.client.post(page("shartnoma-yaratish"), self.contract_fields())

        contract = Contract.objects.get()

        self.assertTrue(contract.pdf)
        self.assertIn("shartnomalar/", contract.pdf.name)

    def test_a_contract_attachment_that_is_not_a_pdf_is_refused(self) -> None:
        not_a_pdf = SimpleUploadedFile("shartnoma.txt", b"not a pdf", content_type="text/plain")

        response = self.client.post(
            page("shartnoma-yaratish"), self.contract_fields(pdf=not_a_pdf)
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Contract.objects.exists())

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
        """And it is on Kelib Tushgan, the page whoever is waited for works."""
        request = a_purchase_application(self.requester, self.department)

        self.client.force_login(self.head)
        self.assertContains(self.client.get(page("kelib-arizalar")), request.xarid_raqami)
        self.client.force_login(self.other_head)
        self.assertNotContains(self.client.get(page("kelib-arizalar")), request.xarid_raqami)
        self.client.force_login(self.direktor)
        self.assertNotContains(self.client.get(page("kelib-arizalar")), request.xarid_raqami)

        # One step along: it leaves the head's queue and reaches the Direktor's.
        request.approve(by=self.head)
        self.assertContains(self.client.get(page("kelib-arizalar")), request.xarid_raqami)
        self.client.force_login(self.head)
        self.assertNotContains(self.client.get(page("kelib-arizalar")), request.xarid_raqami)

    def test_the_queue_reads_the_order_lines_of_what_it_decides(self) -> None:
        """Buyurtma nomi, Soni and O'lchov: a row is one line of the request."""
        request = a_purchase_application(self.requester, self.department)
        request.items.create(
            mahsulot_turi=a_category(),
            buyurtma_nomi="Rozetka",
            buyurtma_soni="12",
            olchov_birligi="dona",
        )
        self.client.force_login(self.head)

        response = self.client.get(page("kelib-arizalar"))

        self.assertContains(response, "Kabel 4mm")
        self.assertContains(response, "Rozetka")
        self.assertContains(response, "dona")
        # Both lines belong to the one request, so its own cells span them and
        # the Tasdiqlash button is offered once rather than per line.
        self.assertContains(response, 'rowspan="2"')
        self.assertContains(response, page("xarid-ariza-tasdiqlash", request.pk), count=1)

    def test_the_queue_carries_what_the_earlier_step_decided(self) -> None:
        """The Izoh drawer travels with the request: why it got this far."""
        request = a_purchase_application(self.requester, self.department)

        self.client.force_login(self.head)
        self.client.post(page("xarid-ariza-tasdiqlash", request.pk))

        # Now it stands at the Direktor, who reads the head's step before deciding.
        self.client.force_login(self.direktor)
        response = self.client.get(page("kelib-arizalar"))

        self.assertContains(response, f'id="ka-izoh-{request.pk}-overlay"')
        self.assertContains(response, f'data-open-drawer="ka-izoh-{request.pk}"')
        self.assertContains(response, "Tasdiqladi")
        self.assertContains(response, "Izoh qoldirilmagan.")

    def test_a_queued_request_nobody_has_decided_has_an_empty_izoh_panel(self) -> None:
        request = a_purchase_application(self.requester, self.department)
        self.client.force_login(self.head)

        response = self.client.get(page("kelib-arizalar"))

        self.assertContains(response, f'id="ka-izoh-{request.pk}-overlay"')
        self.assertContains(response, "hali qaror qabul qilinmagan")
        self.assertNotContains(response, "Tasdiqladi")

    def test_the_queue_row_offers_the_request_itself_as_a_pdf(self) -> None:
        """Ariza PDF beside Ilova PDF, so a row is readable before deciding it."""
        request = a_purchase_application(self.requester, self.department)
        self.client.force_login(self.head)

        response = self.client.get(page("kelib-arizalar"))

        self.assertContains(response, page("xarid-ariza-hujjat-pdf", request.pk))
        self.assertEqual(
            self.client.get(page("xarid-ariza-hujjat-pdf", request.pk)).status_code, 200
        )

    def test_the_queue_is_no_longer_on_the_page_requests_are_raised_on(self) -> None:
        """Xarid Arizasi raises and tracks; Kelib Tushgan is where deciding happens."""
        a_purchase_application(self.requester, self.department)
        self.client.force_login(self.head)

        self.assertNotContains(
            self.client.get(page("xarid-ariza")), "Tasdiqlashni kutayotgan arizalar"
        )

    def test_a_decision_returns_to_the_page_it_was_taken_on(self) -> None:
        request = a_purchase_application(self.requester, self.department)
        self.client.force_login(self.head)

        approved = self.client.post(page("xarid-ariza-tasdiqlash", request.pk))

        self.assertRedirects(approved, reverse("xarid:kelib-arizalar"))

        second = a_purchase_application(self.requester, self.department)
        refused = self.client.post(
            page("xarid-ariza-inkor", second.pk), {"inkor_izohi": "Byudjet yetarli emas"}
        )

        self.assertRedirects(refused, reverse("xarid:kelib-arizalar"))

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
        """Both are uploads, so both say Ilova after the request's number."""
        request = a_purchase_application(self.requester, self.department)

        stamped = self.client.get(page("xarid-ariza-pdf", request.pk))
        self.assertEqual(stamped.status_code, 200)
        self.assertIn(
            f'filename="{request.xarid_raqami}-Ilova.pdf"', stamped["Content-Disposition"]
        )
        self.assertEqual(self.client.get(page("xarid-ariza-asl-pdf", request.pk)).status_code, 404)

        request.approve(by=self.head)
        request.approve(by=self.direktor)

        original = self.client.get(page("xarid-ariza-asl-pdf", request.pk))
        self.assertEqual(original.status_code, 200)
        self.assertIn(
            f'filename="{request.xarid_raqami}-asl-Ilova.pdf"', original["Content-Disposition"]
        )
        # The drawn sheet beside it is not an upload, so it is not an Ilova.
        drawn = self.client.get(page("xarid-ariza-hujjat-pdf", request.pk))
        self.assertIn(
            f'filename="{request.xarid_raqami}-ariza.pdf"', drawn["Content-Disposition"]
        )

    def test_a_request_without_an_attachment_has_nothing_to_download(self) -> None:
        request = a_purchase_application(self.requester, self.department, with_pdf=False)

        self.assertEqual(self.client.get(page("xarid-ariza-pdf", request.pk)).status_code, 404)

    def test_the_izoh_panel_holds_every_decision_the_log_kept(self) -> None:
        """The Izoh column's drawer: who decided, what they decided, when."""
        request = a_purchase_application(self.requester, self.department)

        self.client.force_login(self.head)
        self.client.post(page("xarid-ariza-tasdiqlash", request.pk))
        self.client.force_login(self.direktor)
        self.client.post(
            page("xarid-ariza-inkor", request.pk), {"inkor_izohi": "Byudjet yetarli emas"}
        )

        self.client.force_login(self.admin)
        response = self.client.get(page("xarid-ariza"))

        self.assertContains(response, f'id="xa-izoh-{request.pk}-overlay"')
        self.assertContains(response, f'data-open-drawer="xa-izoh-{request.pk}"')
        self.assertContains(response, "Tasdiqladi")
        self.assertContains(response, "Inkor etdi")
        self.assertContains(response, "Byudjet yetarli emas")
        # The approval was taken with a button and carries no comment of its
        # own, so the entry says so rather than showing an empty box.
        self.assertContains(response, "Izoh qoldirilmagan.")

    def test_a_request_nobody_has_decided_has_an_empty_izoh_panel(self) -> None:
        request = a_purchase_application(self.requester, self.department)

        response = self.client.get(page("xarid-ariza"))

        self.assertContains(response, f'id="xa-izoh-{request.pk}-overlay"')
        self.assertContains(response, "hali qaror qabul qilinmagan")
        self.assertNotContains(response, "Tasdiqladi")

    def test_the_purchasing_step_is_signed_when_the_department_accepts(self) -> None:
        """DEC-016's two approvals, then Xarid bo`limi taking it up: three codes."""
        purchasing = a_department("Xarid bo`limi")
        purchasing.is_purchasing = True
        purchasing.save(update_fields=["is_purchasing"])
        xarid_head = make_user(
            "xb.boss",
            user_type=BOLIM_BOSHLIGI,
            department=purchasing,
            first_name="Asosiy",
            last_name="Xodim",
        )
        request = a_purchase_application(self.requester, self.department, with_pdf=False)
        request.approve(by=self.head)
        request.approve(by=self.direktor)
        request.refresh_from_db()

        waiting = pdf_text(self.client.get(page("xarid-ariza-hujjat-pdf", request.pk)))
        self.assertIn("Xarid bo`lim boshlig`i", waiting)
        self.assertIn("Asosiy Xodim", waiting)
        self.assertIn("Kutilmoqda", waiting)

        request.raised_application.accept(by=xarid_head)
        request.refresh_from_db()

        response = self.client.get(page("xarid-ariza-hujjat-pdf", request.pk))
        text = pdf_text(response)

        self.assertIn("Qabul qilingan", text)
        self.assertNotIn("Kutilmoqda", text)
        # Two approvals and the acceptance, each carrying its own code.
        self.assertEqual(pdf_image_count(response), 3)

    def test_the_raised_application_is_drawn_on_its_request_s_sheet(self) -> None:
        """One request, two downloads, and they must not disagree."""
        request = a_purchase_application(self.requester, self.department, with_pdf=False)
        request.approve(by=self.head)
        request.approve(by=self.direktor)
        request.refresh_from_db()
        raised = request.raised_application

        response = self.client.get(page("ariza-hujjat-pdf", raised.pk))
        text = pdf_text(response)

        self.assertIn("XARID ARIZASI", text)
        self.assertIn(request.xarid_raqami, text)
        self.assertIn("Kabel xaridi", text)
        self.assertIn(self.head.get_username(), text)
        self.assertIn(self.direktor.get_username(), text)
        # The same sheet, not merely a similar one. Compared as text because
        # reportlab stamps each build with its own document id, so two draws
        # of one record are never byte-for-byte equal.
        self.assertEqual(
            text, pdf_text(self.client.get(page("xarid-ariza-hujjat-pdf", request.pk)))
        )

    def test_the_ariza_pdf_is_drawn_from_the_request_itself(self) -> None:
        """The Ariza PDF column: the record on paper, not the attachment."""
        request = a_purchase_application(self.requester, self.department)

        response = self.client.get(page("xarid-ariza-hujjat-pdf", request.pk))

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            f'filename="{request.xarid_raqami}-ariza.pdf"', response["Content-Disposition"]
        )
        text = pdf_text(response)
        self.assertIn(request.xarid_raqami, text)
        self.assertIn("Kabel xaridi", text)
        self.assertIn(self.department.name, text)
        self.assertIn("Kabel 4mm", text)

    def test_the_ariza_pdf_names_everybody_still_to_sign(self) -> None:
        """A step nobody has taken names all of DEC-016's candidates for it."""
        make_user(
            "deputy.head",
            user_type=BOLIM_BOSHLIGI,
            department=self.department,
            first_name="Sardor",
            last_name="Aliyev",
        )
        request = a_purchase_application(self.requester, self.department)

        response = self.client.get(page("xarid-ariza-hujjat-pdf", request.pk))
        text = pdf_text(response)

        self.assertIn("Kutilmoqda", text)
        self.assertIn("Sardor Aliyev", text)
        self.assertIn(self.head.get_username(), text)
        self.assertIn(self.direktor.get_username(), text)
        # Nobody has signed, so there is no code to draw yet.
        self.assertEqual(pdf_image_count(response), 0)

    def test_the_ariza_pdf_leaves_out_a_head_of_another_department(self) -> None:
        """DEC-016 waits for the requester's own head, so only theirs is named."""
        request = a_purchase_application(self.requester, self.department)

        text = pdf_text(self.client.get(page("xarid-ariza-hujjat-pdf", request.pk)))

        self.assertIn(self.head.get_username(), text)
        self.assertNotIn(self.other_head.get_username(), text)

    def test_a_step_that_was_taken_carries_its_approval_code(self) -> None:
        """The same DEC-027 payload the approval stamps onto the attachment."""
        request = a_purchase_application(self.requester, self.department)
        self.client.force_login(self.head)
        self.client.post(page("xarid-ariza-tasdiqlash", request.pk))

        self.client.force_login(self.admin)
        response = self.client.get(page("xarid-ariza-hujjat-pdf", request.pk))
        text = pdf_text(response)

        self.assertEqual(pdf_image_count(response), 1)
        self.assertIn("Tasdiqlangan", text)
        # The director's step is still open, so it still names its candidates.
        self.assertIn("Kutilmoqda", text)
        self.assertIn(self.direktor.get_username(), text)

    def test_a_refused_request_stops_naming_who_would_have_been_next(self) -> None:
        """The chain ended, so nobody is waiting and the refusal carries no code."""
        request = a_purchase_application(self.requester, self.department)
        self.client.force_login(self.head)
        self.client.post(page("xarid-ariza-tasdiqlash", request.pk))
        self.client.force_login(self.direktor)
        self.client.post(
            page("xarid-ariza-inkor", request.pk), {"inkor_izohi": "Byudjet yetarli emas"}
        )

        self.client.force_login(self.admin)
        response = self.client.get(page("xarid-ariza-hujjat-pdf", request.pk))
        text = pdf_text(response)

        self.assertIn("Byudjet yetarli emas", text)
        self.assertNotIn("Kutilmoqda", text)
        # Only the head's approval is stamped; a refusal is not an approval.
        self.assertEqual(pdf_image_count(response), 1)

    def test_the_ariza_pdf_is_there_when_nothing_was_attached(self) -> None:
        """Drawn from the record, so unlike the Ilova PDF it is always there."""
        request = a_purchase_application(self.requester, self.department, with_pdf=False)

        self.assertEqual(
            self.client.get(page("xarid-ariza-hujjat-pdf", request.pk)).status_code, 200
        )


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
            "integration",
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
