"""Tahrirlash, O'chirish and Tiklash on the Kelishinlingan row (TASK-UZK-064).

Three actions and one rule behind them: the contract has to be this
person's, and it has to be one still on this page. Deleting keeps the row
and marks it, so O'chirilgan Shartnomalar can show it and an Admin can put
it back.
"""

from __future__ import annotations

from decimal import Decimal

from django.test import TestCase

from tests.support import (
    PASSWORD,
    SignedInAdminTestCase,
    a_contract,
    a_department,
    a_pdf,
    a_supplier,
    an_assigned_application,
    make_user,
    page,
)
from xarid.models import (
    ADMIN,
    AuditEntry,
    BOLIM_BOSHLIGI,
    KATTA_MUTAXASIS,
    MENEJER,
    Contract,
    ContractItem,
    ShartnomaStatus,
)


def edit_page(contract: Contract) -> str:
    return page("shartnoma-tahrirlash", contract.pk)


def delete_action(contract: Contract) -> str:
    return page("shartnoma-ochirish", contract.pk)


class EditFormTests(SignedInAdminTestCase):
    """The form that opens, and what saving it does."""

    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        cls.specialist = make_user("edit.specialist", user_type=KATTA_MUTAXASIS)
        cls.status = ShartnomaStatus.objects.active().first()

    def a_contract_to_edit(self) -> Contract:
        return a_contract(
            an_assigned_application(self.admin, self.specialist),
            self.specialist,
            status=self.status,
            with_pdf=True,
        )

    def fields_for(self, contract: Contract, **overrides) -> dict:
        """A complete POST for the edit form, filled from the contract."""
        rows = list(contract.items.all())
        posted = {
            "application": contract.application.ariza_raqami,
            "supplier": contract.supplier.name,
            "shartnoma_sanasi": "2026-02-01",
            "shartnoma_turi": "",
            "status": contract.status_id or "",
            "tolash_muddati": "",
            "muddat_talabi": "",
            "invoice_sanasi": "",
            "izoh": "",
            "form-TOTAL_FORMS": str(len(rows)),
            "form-INITIAL_FORMS": str(len(rows)),
            "form-MIN_NUM_FORMS": "1",
            "form-MAX_NUM_FORMS": "1000",
        }
        for index, row in enumerate(rows):
            posted |= {
                f"form-{index}-id": str(row.pk),
                f"form-{index}-buyurtma_nomi": row.buyurtma_nomi,
                f"form-{index}-part_number": row.part_number,
                f"form-{index}-buyurtma_soni": str(row.buyurtma_soni),
                f"form-{index}-olchov_birligi": row.olchov_birligi,
                f"form-{index}-narxi": str(row.narxi),
            }
        return posted | overrides

    def test_the_form_opens_filled_in(self) -> None:
        contract = self.a_contract_to_edit()

        response = self.client.get(edit_page(contract))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, contract.shartnoma_raqami)
        self.assertContains(response, contract.items.first().buyurtma_nomi)

    def test_the_two_combos_open_on_what_they_hold_not_on_an_id(self) -> None:
        """A ModelForm fills them from the primary key; they match on a name.

        Left alone, the form opens reading "1" where the contract says
        ARZ-2026-00001, and saving it unchanged saves a different contract.
        """
        contract = self.a_contract_to_edit()

        response = self.client.get(edit_page(contract))

        self.assertContains(
            response, f'name="application" value="{contract.application.ariza_raqami}"'
        )
        self.assertContains(
            response, f'name="supplier" value="{contract.supplier.name}"'
        )

    def test_a_date_opens_in_the_format_a_date_box_accepts(self) -> None:
        """An <input type="date"> shows nothing at all unless it is ISO.

        Under LANGUAGE_CODE "uz" Django writes 01.02.2026, which the browser
        discards - so every date came up blank and saving wrote the blanks
        back over the dates that were there.
        """
        contract = self.a_contract_to_edit()
        Contract.objects.filter(pk=contract.pk).update(
            shartnoma_sanasi="2026-02-01", tolash_muddati="2026-03-15"
        )

        response = self.client.get(edit_page(contract))

        self.assertContains(response, 'name="shartnoma_sanasi" value="2026-02-01"')
        self.assertContains(response, 'name="tolash_muddati" value="2026-03-15"')

    def test_saving_an_untouched_form_keeps_the_dates(self) -> None:
        """What the blank-date bug actually cost: a save that wiped them."""
        contract = self.a_contract_to_edit()
        Contract.objects.filter(pk=contract.pk).update(tolash_muddati="2026-03-15")
        contract.refresh_from_db()

        self.client.post(
            edit_page(contract),
            self.fields_for(contract, tolash_muddati="2026-03-15"),
        )

        contract.refresh_from_db()
        self.assertEqual(str(contract.tolash_muddati), "2026-03-15")

    def test_it_opens_the_same_dialog_creating_one_opens(self) -> None:
        """One way of filling a contract in, not two (TASK-UZK-065).

        The Kelishinlingan page comes back with its own dialog open and
        pointed at the edit action - the way it already comes back when a
        new contract fails validation - rather than a separate page.
        """
        contract = self.a_contract_to_edit()

        response = self.client.get(edit_page(contract))

        # The table is still behind it, and the dialog is not hidden.
        self.assertContains(response, 'id="kelish-table"')
        self.assertContains(response, 'id="sht-modal" class="modal-overlay"')
        self.assertContains(response, f'action="{edit_page(contract)}"')
        self.assertContains(response, "Shartnoma Tahrirlash")

    def test_creating_one_still_opens_it_pointed_at_the_create_action(self) -> None:
        self.a_contract_to_edit()

        response = self.client.get(page("kelishinlingan"))

        self.assertContains(response, f'action="{page("shartnoma-yaratish")}"')
        self.assertContains(response, "Shartnoma Kiritish")
        # Hidden until the button is pressed.
        self.assertContains(response, 'id="sht-modal" class="modal-overlay hidden"')

    def test_a_row_is_removed_by_a_button_and_not_a_tick(self) -> None:
        """The tick is what the server reads; the button is what is pressed.

        It stays in the document, hidden, because a formset counts its
        forms and one taken out from under it is missing data rather than a
        row somebody deleted.
        """
        contract = self.a_contract_to_edit()

        response = self.client.get(edit_page(contract))

        self.assertContains(response, "data-remove-row")
        self.assertContains(response, 'name="form-0-DELETE"')
        self.assertNotContains(response, ">O'chirish</span>")

    def test_the_creation_dialog_has_no_row_delete(self) -> None:
        """Nothing to delete yet: an unwanted row is one left empty."""
        response = self.client.get(page("kelishinlingan"))

        self.assertNotContains(response, "data-remove-row")

    def test_the_page_offers_the_link(self) -> None:
        contract = self.a_contract_to_edit()

        response = self.client.get(page("kelishinlingan"))

        self.assertContains(response, edit_page(contract))
        self.assertContains(response, "Tahrirlash")
        self.assertContains(response, "Amallar")

    def test_saving_changes_the_terms(self) -> None:
        contract = self.a_contract_to_edit()
        firma = a_supplier("Yangi Firma LLC", inn="987654321")

        response = self.client.post(
            edit_page(contract),
            self.fields_for(contract, supplier=firma.name, izoh="Narx qayta kelishildi."),
            follow=True,
        )

        contract.refresh_from_db()
        self.assertEqual(contract.supplier, firma)
        self.assertEqual(contract.izoh, "Narx qayta kelishildi.")
        self.assertContains(response, "saqlandi")

    def test_changing_a_price_recomputes_the_value(self) -> None:
        """The value is the sum of the rows, never a number the form sends."""
        contract = self.a_contract_to_edit()

        self.client.post(
            edit_page(contract),
            self.fields_for(contract, **{"form-0-narxi": "25", "form-0-buyurtma_soni": "4"}),
        )

        contract.refresh_from_db()
        self.assertEqual(contract.qiymati, Decimal("100.00"))

    def test_a_row_may_be_added(self) -> None:
        contract = self.a_contract_to_edit()
        posted = self.fields_for(contract) | {
            "form-TOTAL_FORMS": "2",
            "form-1-id": "",
            "form-1-buyurtma_nomi": "Gayka M12",
            "form-1-part_number": "",
            "form-1-buyurtma_soni": "10",
            "form-1-olchov_birligi": "ta",
            "form-1-narxi": "5",
        }

        self.client.post(edit_page(contract), posted)

        contract.refresh_from_db()
        self.assertEqual(
            [row.buyurtma_nomi for row in contract.items.all()],
            ["Bolt M12x50", "Gayka M12"],
        )
        self.assertEqual(contract.qiymati, Decimal("60.00"))

    def test_a_row_is_removed_by_ticking_it(self) -> None:
        """An emptied row fails its required fields; a ticked one goes away."""
        contract = self.a_contract_to_edit()
        posted = self.fields_for(contract) | {
            "form-TOTAL_FORMS": "2",
            "form-1-id": "",
            "form-1-buyurtma_nomi": "Gayka M12",
            "form-1-part_number": "",
            "form-1-buyurtma_soni": "10",
            "form-1-olchov_birligi": "ta",
            "form-1-narxi": "5",
            "form-0-DELETE": "on",
        }

        self.client.post(edit_page(contract), posted)

        contract.refresh_from_db()
        self.assertEqual([row.buyurtma_nomi for row in contract.items.all()], ["Gayka M12"])
        self.assertEqual(contract.qiymati, Decimal("50.00"))

    def test_removing_every_row_is_refused(self) -> None:
        contract = self.a_contract_to_edit()

        response = self.client.post(
            edit_page(contract), self.fields_for(contract, **{"form-0-DELETE": "on"})
        )

        contract.refresh_from_db()
        self.assertEqual(contract.items.count(), 1)
        self.assertEqual(response.status_code, 200)

    def test_an_empty_pdf_box_keeps_the_file_on_record(self) -> None:
        contract = self.a_contract_to_edit()
        was = contract.pdf.name

        self.client.post(edit_page(contract), self.fields_for(contract))

        contract.refresh_from_db()
        self.assertEqual(contract.pdf.name, was)

    def test_a_new_pdf_replaces_it(self) -> None:
        contract = self.a_contract_to_edit()
        was = contract.pdf.name

        self.client.post(
            edit_page(contract), self.fields_for(contract, pdf=a_pdf("yangi.pdf"))
        )

        contract.refresh_from_db()
        self.assertNotEqual(contract.pdf.name, was)

    def test_an_invalid_form_says_so_and_changes_nothing(self) -> None:
        contract = self.a_contract_to_edit()

        response = self.client.post(
            edit_page(contract), self.fields_for(contract, supplier="Yo`q firma")
        )

        contract.refresh_from_db()
        self.assertEqual(contract.supplier.name, "Texnoprom LLC")
        self.assertContains(response, "formani tekshiring")

    def test_a_sent_contract_may_not_be_edited(self) -> None:
        contract = self.a_contract_to_edit()
        contract.send_for_approval(by=self.specialist)

        response = self.client.get(edit_page(contract), follow=True)

        self.assertContains(response, "tasdiqlashga yuborilgan")

    def test_somebody_elses_contract_may_not_be_edited(self) -> None:
        other = make_user("edit.other", user_type=KATTA_MUTAXASIS)
        theirs = a_contract(an_assigned_application(self.admin, other), other)
        self.client.force_login(self.specialist)

        response = self.client.post(edit_page(theirs), self.fields_for(theirs), follow=True)

        theirs.refresh_from_db()
        self.assertContains(response, "sizning ishingizga tegishli emas")


class SoftDeleteTests(SignedInAdminTestCase):
    """O'chirish takes the row off the page and keeps it."""

    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        cls.specialist = make_user("del.specialist", user_type=KATTA_MUTAXASIS)

    def a_contract_to_delete(self) -> Contract:
        return a_contract(
            an_assigned_application(self.admin, self.specialist), self.specialist
        )

    def test_deleting_takes_it_off_the_page_and_says_where_it_went(self) -> None:
        contract = self.a_contract_to_delete()

        response = self.client.post(delete_action(contract), follow=True)

        # The message names the contract, which is the point of it - so what
        # says the row is gone is that its controls are.
        self.assertNotContains(response, edit_page(contract))
        self.assertContains(response, "O`chirilgan Shartnomalar")

    def test_the_row_is_kept_and_marked(self) -> None:
        contract = self.a_contract_to_delete()

        self.client.post(delete_action(contract))

        kept = Contract.all_objects.get(pk=contract.pk)
        self.assertTrue(kept.is_deleted)
        self.assertEqual(kept.deleted_by, self.admin)

    def test_the_ordinary_manager_stops_seeing_it(self) -> None:
        """Every list, export and figure asks through this one."""
        contract = self.a_contract_to_delete()

        self.client.post(delete_action(contract))

        self.assertFalse(Contract.objects.filter(pk=contract.pk).exists())
        self.assertTrue(Contract.all_objects.filter(pk=contract.pk).exists())

    def test_its_goods_rows_are_kept_too(self) -> None:
        """A restored contract that lost its rows would be worth nothing."""
        contract = self.a_contract_to_delete()

        self.client.post(delete_action(contract))

        self.assertTrue(ContractItem.objects.filter(contract_id=contract.pk).exists())

    def test_a_second_delete_is_a_message_not_a_404(self) -> None:
        """A stale page: the row went while somebody had it open."""
        contract = self.a_contract_to_delete()
        contract.soft_delete(by=self.admin)

        response = self.client.post(delete_action(contract), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "allaqachon o`chirilgan")

    def test_a_sent_contract_may_not_be_deleted(self) -> None:
        """Deleting what somebody else is deciding on is not withdrawal."""
        contract = self.a_contract_to_delete()
        contract.send_for_approval(by=self.specialist)

        response = self.client.post(delete_action(contract), follow=True)

        contract.refresh_from_db()
        self.assertFalse(contract.is_deleted)
        self.assertContains(response, "tasdiqlashga yuborilgan")

    def test_somebody_elses_contract_may_not_be_deleted(self) -> None:
        other = make_user("del.other", user_type=KATTA_MUTAXASIS)
        theirs = a_contract(an_assigned_application(self.admin, other), other)
        self.client.force_login(self.specialist)

        response = self.client.post(delete_action(theirs), follow=True)

        theirs.refresh_from_db()
        self.assertFalse(theirs.is_deleted)
        self.assertContains(response, "sizning ishingizga tegishli emas")

    def test_the_action_refuses_a_get(self) -> None:
        contract = self.a_contract_to_delete()

        response = self.client.get(delete_action(contract))

        self.assertEqual(response.status_code, 405)

    def test_the_log_records_the_deletion(self) -> None:
        contract = self.a_contract_to_delete()

        self.client.post(delete_action(contract))

        entry = AuditEntry.objects.filter(action=AuditEntry.Action.DELETED).first()
        self.assertEqual(entry.actor, self.admin)
        self.assertIn(contract.shartnoma_raqami, entry.record_label)

    def test_a_refused_deletion_is_not_logged_as_one(self) -> None:
        """The row survives a soft delete, so the entry waits for the outcome.

        record_deleted() says to call it before the deletion, while the
        record can still say what it was. That is for a deletion that
        destroys the row; calling it first here logs deletions that were
        refused.
        """
        contract = self.a_contract_to_delete()
        contract.send_for_approval(by=self.specialist)

        self.client.post(delete_action(contract))

        self.assertFalse(
            AuditEntry.objects.filter(action=AuditEntry.Action.DELETED).exists()
        )

    def test_a_deleted_contract_is_off_the_tuzilgan_page_too(self) -> None:
        """One manager hides it, so no page has to remember to."""
        contract = self.a_contract_to_delete()
        contract.send_for_approval(by=self.specialist)
        Contract.all_objects.filter(pk=contract.pk).update(deleted_at="2026-01-01 00:00Z")

        response = self.client.get(page("tuzilgan"))

        self.assertNotContains(response, contract.shartnoma_raqami)


class DeletedContractsPageTests(SignedInAdminTestCase):
    """Where a deleted contract goes, and the way back."""

    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        cls.specialist = make_user("restore.specialist", user_type=KATTA_MUTAXASIS)

    def a_deleted_contract(self) -> Contract:
        contract = a_contract(
            an_assigned_application(self.admin, self.specialist), self.specialist
        )
        contract.soft_delete(by=self.admin)
        return contract

    def test_the_page_lists_it_with_who_deleted_it(self) -> None:
        contract = self.a_deleted_contract()

        response = self.client.get(page("ochirilgan-shartnomalar"))

        self.assertContains(response, contract.shartnoma_raqami)
        self.assertContains(response, contract.supplier.name)
        self.assertContains(response, self.admin.get_full_name())

    def test_restoring_puts_it_back_on_kelishinlingan(self) -> None:
        contract = self.a_deleted_contract()

        self.client.post(page("shartnoma-tiklash", contract.pk), follow=True)

        contract.refresh_from_db()
        self.assertFalse(contract.is_deleted)
        self.assertContains(self.client.get(page("kelishinlingan")), contract.shartnoma_raqami)

    def test_a_restored_contract_leaves_the_deleted_page(self) -> None:
        contract = self.a_deleted_contract()

        response = self.client.post(page("shartnoma-tiklash", contract.pk), follow=True)

        # Again the message names it, so the row's own control is the test.
        self.assertNotContains(response, page("shartnoma-tiklash", contract.pk))
        self.assertContains(response, "tiklandi")

    def test_a_contract_that_was_not_deleted_is_a_message(self) -> None:
        contract = a_contract(
            an_assigned_application(self.admin, self.specialist), self.specialist
        )

        response = self.client.post(page("shartnoma-tiklash", contract.pk), follow=True)

        self.assertEqual(response.status_code, 200)

    def test_the_details_of_a_deleted_contract_can_still_be_read(self) -> None:
        """Ko'rish is on this page, so the fragment has to answer for it."""
        contract = self.a_deleted_contract()

        response = self.client.get(page("shartnoma-tafsilot", contract.pk))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, contract.shartnoma_raqami)

    def test_nobody_but_an_admin_opens_the_page(self) -> None:
        for user_type in (KATTA_MUTAXASIS, MENEJER, BOLIM_BOSHLIGI):
            with self.subTest(user_type=user_type):
                somebody = make_user(f"deleted.{user_type[:6]}", user_type=user_type)
                self.client.force_login(somebody)

                response = self.client.get(page("ochirilgan-shartnomalar"))

                self.assertEqual(response.status_code, 403)

    def test_nobody_but_an_admin_restores(self) -> None:
        contract = self.a_deleted_contract()
        specialist = make_user("restore.nobody", user_type=KATTA_MUTAXASIS)
        self.client.force_login(specialist)

        response = self.client.post(page("shartnoma-tiklash", contract.pk))

        self.assertEqual(response.status_code, 403)
        contract.refresh_from_db()
        self.assertTrue(contract.is_deleted)

    def test_a_deleted_contract_of_somebody_elses_is_still_readable_here(self) -> None:
        """The page is the Admin's, and so is everything on it."""
        other = make_user("restore.other", user_type=KATTA_MUTAXASIS)
        theirs = a_contract(an_assigned_application(self.admin, other), other)
        theirs.soft_delete(by=other)

        response = self.client.get(page("ochirilgan-shartnomalar"))

        self.assertContains(response, theirs.shartnoma_raqami)


class WhoseContractItIsTests(SignedInAdminTestCase):
    """What "own" means to each type, now that it means three things."""

    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        cls.purchasing = a_department("Xarid bo`limi")
        cls.purchasing.is_purchasing = True
        cls.purchasing.save(update_fields=["is_purchasing"])
        cls.specialist = make_user(
            "whose.specialist", user_type=KATTA_MUTAXASIS, department=cls.purchasing
        )
        cls.menejer = make_user(
            "whose.menejer", user_type=MENEJER, department=cls.purchasing
        )
        cls.head = make_user(
            "whose.head", user_type=BOLIM_BOSHLIGI, department=cls.purchasing
        )

    def a_contract_of(self, author) -> Contract:
        return a_contract(
            an_assigned_application(self.admin, self.specialist), author
        )

    def controls_of(self, contract: Contract, response) -> bool:
        """Whether the row's form - what every control acts through - is drawn."""
        return f'id="sht-qator-{contract.pk}"' in response.content.decode()

    def test_a_menejer_acts_on_what_they_entered(self) -> None:
        theirs = self.a_contract_of(self.menejer)
        self.client.force_login(self.menejer)

        response = self.client.get(page("kelishinlingan"))

        self.assertTrue(self.controls_of(theirs, response))

    def test_a_menejer_reads_what_somebody_else_entered(self) -> None:
        someone_elses = self.a_contract_of(self.specialist)
        self.client.force_login(self.menejer)

        response = self.client.get(page("kelishinlingan"))

        self.assertFalse(self.controls_of(someone_elses, response))
        # Drawn, but dead: the row still says what could be done with it.
        self.assertContains(response, "Tahrirlash")
        self.assertContains(response, "disabled")

    def test_a_head_is_the_same(self) -> None:
        theirs = self.a_contract_of(self.head)
        someone_elses = self.a_contract_of(self.specialist)
        self.client.force_login(self.head)

        response = self.client.get(page("kelishinlingan"))

        self.assertTrue(self.controls_of(theirs, response))
        self.assertFalse(self.controls_of(someone_elses, response))

    def test_the_routes_ask_the_same_question(self) -> None:
        """A disabled button is a courtesy; the refusal is the route's."""
        someone_elses = self.a_contract_of(self.specialist)
        self.client.force_login(self.menejer)

        for action in (delete_action, edit_page):
            with self.subTest(action=action.__name__):
                response = self.client.post(action(someone_elses), follow=True)

                self.assertContains(response, "sizning ishingizga tegishli emas")

        someone_elses.refresh_from_db()
        self.assertFalse(someone_elses.is_deleted)

    def test_a_specialist_still_goes_by_assignment(self) -> None:
        """Their own work, whoever entered the contract against it."""
        entered_by_the_menejer = self.a_contract_of(self.menejer)
        self.client.force_login(self.specialist)

        response = self.client.get(page("kelishinlingan"))

        self.assertTrue(self.controls_of(entered_by_the_menejer, response))

    def test_an_admin_acts_on_everything(self) -> None:
        someone_elses = self.a_contract_of(self.specialist)

        response = self.client.get(page("kelishinlingan"))

        self.assertTrue(self.controls_of(someone_elses, response))


class TheSidebarTests(TestCase):
    """The deleted page is in the menu for the one type that may open it."""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.admin = make_user("side.admin", user_type=ADMIN)
        cls.menejer = make_user("side.menejer", user_type=MENEJER)

    def test_an_admin_sees_the_link(self) -> None:
        self.client.force_login(self.admin)

        response = self.client.get(page("kelishinlingan"))

        self.assertContains(response, page("ochirilgan-shartnomalar"))

    def test_nobody_else_does(self) -> None:
        self.client.force_login(self.menejer)

        response = self.client.get(page("kelishinlingan"))

        self.assertNotContains(response, page("ochirilgan-shartnomalar"))
