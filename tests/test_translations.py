"""Three languages, one set of records.

The chrome - the sidebar, the headings, the table headers, the buttons - is
written in Uzbek and translated from catalogues. What an administrator types
in is not: the statuses, the product types, the departments and the suppliers
are rows everybody shares, and a page that renamed them per reader would
disagree with the record it is showing.

What is tested here is that boundary, that the picker is where it was asked
for, and that the catalogues the runtime reads are the ones the code marks.
"""

from __future__ import annotations

from django.core.management import call_command
from django.test import TestCase
from django.utils import translation

from tests.support import (
    SignedInAdminTestCase,
    a_department,
    an_assigned_application,
    make_user,
    page,
)
from xarid.models import KATTA_MUTAXASIS, ArizaStatus, MahsulotTuri


class CatalogueTests(TestCase):
    """The compiler, and what it says about the catalogues."""

    def test_every_marked_string_is_translated_in_every_language(self) -> None:
        """What --check reports; it raises when anything is missing."""
        call_command("translations", check=True)

    def test_the_compiler_writes_a_catalogue_gettext_can_read(self) -> None:
        call_command("translations")

        with translation.override("ru"):
            self.assertEqual(translation.gettext("Saqlash"), "Сохранить")
        with translation.override("en"):
            self.assertEqual(translation.gettext("Saqlash"), "Save")

    def test_uzbek_is_the_language_the_strings_are_written_in(self) -> None:
        """No catalogue, and none needed: gettext falls back to the msgid."""
        with translation.override("uz"):
            self.assertEqual(translation.gettext("Saqlash"), "Saqlash")
            self.assertEqual(translation.gettext("Tuzilgan Shartnomalar"), "Tuzilgan Shartnomalar")


class LanguagePickerTests(SignedInAdminTestCase):
    """The globe in the top bar, and what pressing a language does."""

    def test_the_picker_sits_left_of_the_notification_bell(self) -> None:
        rendered = self.client.get(page("users")).content.decode()

        self.assertIn("data-language-chip", rendered)
        self.assertLess(rendered.index("data-language-chip"), rendered.index("bi-bell"))

    def test_it_offers_the_three_languages_and_marks_the_one_being_read(self) -> None:
        rendered = self.client.get(page("users")).content.decode()

        self.assertIn("O`zbekcha", rendered)
        self.assertIn("Русский", rendered)
        self.assertIn("English", rendered)
        # The one being read is a tick rather than a button to press.
        self.assertIn("is-current", rendered)

    def test_choosing_a_language_changes_the_chrome_and_stays_chosen(self) -> None:
        self.client.post(page_for_language(), {"language": "ru", "next": page("users")})

        first = self.client.get(page("users")).content.decode()
        self.assertIn("Пользователи", first)
        self.assertNotIn("Foydalanuvchilar Ro`yhati", first)

        # And the next page is in Russian too, without being asked again.
        second = self.client.get(page("tayinlangan")).content.decode()
        self.assertIn("Назначенные заявки", second)

    def test_english_is_the_third_choice(self) -> None:
        self.client.post(page_for_language(), {"language": "en", "next": page("tuzilgan")})

        rendered = self.client.get(page("tuzilgan")).content.decode()

        self.assertIn("Signed Contracts", rendered)
        self.assertIn("Search", rendered)

    def test_uzbek_is_what_a_reader_gets_without_choosing(self) -> None:
        rendered = self.client.get(page("tuzilgan")).content.decode()

        self.assertIn("Tuzilgan Shartnomalar", rendered)
        self.assertIn("Qidirish", rendered)

    def test_the_document_says_which_language_it_is_in(self) -> None:
        self.client.post(page_for_language(), {"language": "ru", "next": page("users")})

        self.assertContains(self.client.get(page("users")), '<html lang="ru">')


class NothingIsLeftInEnglishTests(SignedInAdminTestCase):
    """The pages were written with English in them, and it is translated too.

    Some of the supplied markup was English - the subtitle under each page
    title, "Dashboard", "User Types", the role tags. Those strings are marked
    like any other, and the Uzbek catalogue holds their Uzbek, so a reader who
    has chosen Uzbek is reading Uzbek rather than the msgid.
    """

    ENGLISH = (
        ("dashboard", "Dashboard", "Asosiy panel"),
        ("user-types", "User Types", "Foydalanuvchi turlari"),
        ("user-specialty", "User Specialty", "Mutaxassislik"),
        ("kelishinlingan", "Agreed Contracts", "Kelishilgan shartnomalar"),
        ("xodimlar-yuklamasi", "Employee Workload Report", "Xodimlar yuklamasi hisoboti"),
        ("ochirilgan-shartnomalar", "Deleted contracts", "O'chirilgan shartnomalar"),
        ("xarid-ariza", "Purchase Requests", "Xarid arizalari"),
    )

    def test_an_uzbek_reader_reads_uzbek(self) -> None:
        for page_name, english, uzbek in self.ENGLISH:
            with self.subTest(page=page_name):
                rendered = self.client.get(page(page_name)).content.decode()

                self.assertIn(uzbek, rendered)
                self.assertNotIn(english, rendered)

    def test_an_english_reader_reads_the_english(self) -> None:
        """The same strings, in the language they were written in."""
        self.client.post(page_for_language(), {"language": "en", "next": page("dashboard")})

        for page_name, english, _uzbek in self.ENGLISH:
            with self.subTest(page=page_name):
                self.assertIn(english, self.client.get(page(page_name)).content.decode())

    def test_a_russian_reader_reads_russian(self) -> None:
        self.client.post(page_for_language(), {"language": "ru", "next": page("dashboard")})

        rendered = self.client.get(page("user-types")).content.decode()

        self.assertIn("Типы пользователей", rendered)
        self.assertNotIn("User Types", rendered)


class RecordsAreNotTranslatedTests(SignedInAdminTestCase):
    """The boundary: chrome from the catalogue, records from the database."""

    def test_master_data_reads_the_same_in_every_language(self) -> None:
        MahsulotTuri.objects.create(category_number=100777, name="Metallurgiya")

        for language in ("uz", "ru", "en"):
            with self.subTest(language=language):
                self.client.post(
                    page_for_language(),
                    {"language": language, "next": page("mahsulot-turlari")},
                )
                rendered = self.client.get(page("mahsulot-turlari")).content.decode()

                # The record, untouched.
                self.assertIn("Metallurgiya", rendered)
                self.assertIn("100777", rendered)

    def test_a_status_keeps_its_name_while_the_column_is_translated(self) -> None:
        specialist = make_user("tr.spec", user_type=KATTA_MUTAXASIS)
        an_assigned_application(self.admin, specialist, department=a_department())
        tayinlangan = ArizaStatus.objects.get(name="Tayinlangan")

        self.client.post(
            page_for_language(), {"language": "ru", "next": page("tayinlangan")}
        )
        rendered = self.client.get(page("tayinlangan")).content.decode()

        # The page's own words are Russian.
        self.assertIn("Назначенные заявки", rendered)
        # The status the record holds is the row's name, in the one spelling
        # everybody shares.
        self.assertIn(tayinlangan.name, rendered)


def page_for_language() -> str:
    """Django's own set_language route, which the picker posts to."""
    return "/i18n/setlang/"
