"""What MasterDataRecord promises every master data table.

Six tables inherit it across two applications, and the promise is small: a row
can be deactivated rather than deleted (DEC-009), it leaves objects.active()
when that happens, it stays in the table so anything already pointing at it
still resolves, and it prints as its name.

These walk the list of tables rather than testing one, so a seventh table that
forgets the base fails here instead of quietly not being covered. That is the
whole reason the base is worth having: the rule is written once and checked
everywhere, rather than being a habit each new table is trusted to keep.
"""

from __future__ import annotations

from django.apps import apps as django_apps
from django.test import TestCase

from accounts.models import MasterDataRecord

# What each table needs to build one row. Only the required fields: the base is
# what is being tested, not each table's own validation.
MASTER_DATA_FIXTURES = (
    ("accounts", "UserType", {"name": "Tekshiruvchi"}),
    ("accounts", "UserSpecialty", {"name": "Mexanik muhandis"}),
    ("reference", "ArizaStatus", {"name": "Tekshirilmoqda"}),
    ("reference", "ShartnomaStatus", {"name": "Imzolanmoqda"}),
    ("reference", "MahsulotTuri", {"name": "Sinov", "category_number": 900001}),
    ("reference", "ShartnomaTuri", {"name": "Framework"}),
)


def master_data_models() -> list[type[MasterDataRecord]]:
    """Every concrete model that inherits the base, found rather than listed."""
    return [
        model
        for model in django_apps.get_models()
        if issubclass(model, MasterDataRecord)
    ]


class InventoryTests(TestCase):
    """The fixtures above have to keep up with the tables."""

    def test_every_master_data_table_has_a_fixture(self) -> None:
        # Otherwise a new table would be added to the base and silently not
        # be covered by anything below.
        covered = {name for _, name, _ in MASTER_DATA_FIXTURES}
        found = {model.__name__ for model in master_data_models()}

        self.assertEqual(
            found,
            covered,
            "A table inherits MasterDataRecord but has no fixture here, or "
            "the other way round. Add it to MASTER_DATA_FIXTURES.",
        )

    def test_there_are_six_of_them(self) -> None:
        # A blunt count, so that the number in the pull request body and the
        # number in the database cannot drift apart unnoticed.
        self.assertEqual(len(master_data_models()), 6)


class SharedBehaviourTests(TestCase):
    """The same four promises, on every table that makes them."""

    def each_table(self):
        """Yield one freshly created row per master data table."""
        for app_label, model_name, fields in MASTER_DATA_FIXTURES:
            model = django_apps.get_model(app_label, model_name)
            yield model, model.objects.create(**fields)

    def test_a_new_row_is_active(self) -> None:
        for model, row in self.each_table():
            with self.subTest(table=model.__name__):
                self.assertTrue(row.is_active)

    def test_a_new_row_appears_in_the_active_queryset(self) -> None:
        for model, row in self.each_table():
            with self.subTest(table=model.__name__):
                self.assertIn(row, model.objects.active())

    def test_a_deactivated_row_leaves_the_active_queryset(self) -> None:
        # DEC-009 deletion, which is what every list and drop-down is built on.
        for model, row in self.each_table():
            with self.subTest(table=model.__name__):
                row.is_active = False
                row.save(update_fields=["is_active"])

                self.assertNotIn(row, model.objects.active())

    def test_a_deactivated_row_stays_in_the_table(self) -> None:
        # So an application or contract already pointing at it still resolves.
        for model, row in self.each_table():
            with self.subTest(table=model.__name__):
                row.is_active = False
                row.save(update_fields=["is_active"])

                self.assertTrue(model.objects.filter(pk=row.pk).exists())

    def test_a_row_knows_when_it_was_created(self) -> None:
        for model, row in self.each_table():
            with self.subTest(table=model.__name__):
                self.assertIsNotNone(row.created_at)

    def test_a_row_prints_as_something_containing_its_name(self) -> None:
        # Not equal to the name: Mahsulot Turlari prints its code as well,
        # because the department identifies a category by the code.
        for model, row in self.each_table():
            with self.subTest(table=model.__name__):
                self.assertIn(row.name, str(row))


class NameColumnTests(TestCase):
    """One length everywhere, which it was not before TASK-UZK-019."""

    def test_every_name_column_is_the_same_length(self) -> None:
        # It was 64 on three tables and 128 on two, which was arbitrary rather
        # than meaningful and left the next table with no basis for choosing.
        lengths = {
            model.__name__: model._meta.get_field("name").max_length
            for model in master_data_models()
        }

        self.assertEqual(set(lengths.values()), {128}, lengths)
