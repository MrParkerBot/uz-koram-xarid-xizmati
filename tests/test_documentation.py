"""Tests for the delivery documentation set (TASK-UZK-056, REQ-ACCEPT-002).

No test can say a diagram describes the business correctly. These say the
documents describe the code that exists: every table, every entity, and a
BPMN a viewer will actually open.
"""

from __future__ import annotations

import xml.etree.ElementTree as ElementTree
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.test import SimpleTestCase

from xarid.management.commands.delivery_docs import (
    BPMN_NS,
    BPMNDI_NS,
    CONTRACT_BPMN,
    DOCS,
    PURCHASE_BPMN,
    SCHEMA_FILE,
    SQL_FILE,
    UML_FILE,
    documents,
    domain_models,
)


class TheDocumentsMatchTheCodeTests(SimpleTestCase):
    """The check the build runs, and what it is checking."""

    # Writing the documents now needs the database: the SQL one is emitted by
    # the backend's own schema editor, which opens a cursor to turn constraint
    # checking off before it will describe a table. Nothing here writes rows.
    databases = {"default"}

    def test_every_document_on_disk_is_what_the_command_would_write(self) -> None:
        """The whole point: a migration that leaves them behind fails here."""
        for path, expected in documents().items():
            with self.subTest(document=str(path)):
                self.assertTrue(path.exists(), f"{path} has never been written.")
                self.assertEqual(path.read_text(encoding="utf-8"), expected)

    def test_the_check_command_passes_against_what_is_committed(self) -> None:
        call_command("delivery_docs", check=True)

    def test_the_check_command_fails_when_a_document_is_stale(self) -> None:
        """Against a copy: a run killed mid-test must not leave the tree dirty."""
        with TemporaryDirectory() as elsewhere:
            somewhere_else = Path(elsewhere)
            call_command("delivery_docs", root=str(somewhere_else))
            stale = somewhere_else / SCHEMA_FILE
            stale.write_text(
                stale.read_text(encoding="utf-8") + "\nA table nobody has.\n",
                encoding="utf-8",
            )

            with self.assertRaises(SystemExit):
                call_command("delivery_docs", root=str(somewhere_else), check=True)

    def test_the_check_command_reports_a_document_that_was_never_written(self) -> None:
        with TemporaryDirectory() as elsewhere, self.assertRaises(SystemExit):
            call_command("delivery_docs", root=elsewhere, check=True)


class TheSchemaDocumentTests(SimpleTestCase):
    """What the schema document has to name."""

    def written(self) -> str:
        return (DOCS / SCHEMA_FILE).read_text(encoding="utf-8")

    def test_it_lists_every_table_the_models_declare(self) -> None:
        written = self.written()

        for model in domain_models():
            with self.subTest(model=model.__name__):
                self.assertIn(f"`{model._meta.db_table}`", written)

    def test_it_names_a_column_of_every_table(self) -> None:
        written = self.written()

        for model in domain_models():
            with self.subTest(model=model.__name__):
                column = model._meta.concrete_fields[0].column
                self.assertIn(f"`{column}`", written)


class TheSchemaSqlDocumentTests(SimpleTestCase):
    """The DB SQL deliverable (DEC-040), generated rather than transcribed."""

    def written(self) -> str:
        return (DOCS / SQL_FILE).read_text(encoding="utf-8")

    def test_it_creates_every_table_the_models_declare(self) -> None:
        written = self.written()

        for model in domain_models():
            with self.subTest(model=model.__name__):
                self.assertIn(f'CREATE TABLE "{model._meta.db_table}"', written)

    def test_it_says_it_is_generated_and_which_dialect_it_is(self) -> None:
        """A reader who opens it alone must not take it for a portable script."""
        written = self.written()

        self.assertIn("delivery_docs", written)
        self.assertIn("SQLite DDL", written)

    def test_it_carries_a_column_added_by_a_later_migration(self) -> None:
        """The proof it follows the migrations rather than the first of them."""
        self.assertIn("is_signed", self.written())


class TheClassDiagramTests(SimpleTestCase):
    """What the UML has to cover."""

    def test_it_has_a_class_for_every_entity(self) -> None:
        written = (DOCS / UML_FILE).read_text(encoding="utf-8")

        for model in domain_models():
            with self.subTest(model=model.__name__):
                self.assertIn(f"class {model.__name__} ", written)

    def test_it_opens_and_closes_as_plantuml(self) -> None:
        written = (DOCS / UML_FILE).read_text(encoding="utf-8")

        self.assertTrue(written.startswith("@startuml"))
        self.assertTrue(written.rstrip().endswith("@enduml"))

    def test_it_draws_an_association_with_its_multiplicity(self) -> None:
        written = (DOCS / UML_FILE).read_text(encoding="utf-8")

        self.assertIn('Contract "*" --> "1" Supplier : supplier', written)

    def test_a_one_to_one_is_an_association_and_not_inheritance(self) -> None:
        """--|> would say a UserProfile is a kind of User, which it is not."""
        written = (DOCS / UML_FILE).read_text(encoding="utf-8")

        self.assertIn('UserProfile "1" -- "1" User : user', written)
        self.assertNotIn("--|>", written)


class TheBpmnFilesTests(SimpleTestCase):
    """A BPMN a viewer will open, describing the flows the code runs."""

    def parsed(self, path: Path) -> ElementTree.Element:
        return ElementTree.fromstring(path.read_text(encoding="utf-8"))

    def test_each_file_parses_and_declares_one_process(self) -> None:
        for path in (DOCS / PURCHASE_BPMN, DOCS / CONTRACT_BPMN):
            with self.subTest(document=str(path)):
                processes = self.parsed(path).findall(f"{{{BPMN_NS}}}process")

                self.assertEqual(len(processes), 1)

    def test_every_element_has_a_shape_so_a_viewer_can_draw_it(self) -> None:
        """Elements without diagram interchange open as an error, not a diagram."""
        for path in (DOCS / PURCHASE_BPMN, DOCS / CONTRACT_BPMN):
            with self.subTest(document=str(path)):
                root = self.parsed(path)
                process = root.find(f"{{{BPMN_NS}}}process")
                drawn = {
                    shape.get("bpmnElement")
                    for shape in root.iter(f"{{{BPMNDI_NS}}}BPMNShape")
                } | {edge.get("bpmnElement") for edge in root.iter(f"{{{BPMNDI_NS}}}BPMNEdge")}
                declared = {element.get("id") for element in process}

                self.assertEqual(declared - drawn, set())

    def test_every_sequence_flow_joins_two_declared_elements(self) -> None:
        for path in (DOCS / PURCHASE_BPMN, DOCS / CONTRACT_BPMN):
            with self.subTest(document=str(path)):
                process = self.parsed(path).find(f"{{{BPMN_NS}}}process")
                declared = {element.get("id") for element in process}

                for flow in process.findall(f"{{{BPMN_NS}}}sequenceFlow"):
                    self.assertIn(flow.get("sourceRef"), declared)
                    self.assertIn(flow.get("targetRef"), declared)

    def test_the_purchase_flow_has_both_approvals_dec_016_asks_for(self) -> None:
        """Section 4.2 was superseded: the head decides, then the director."""
        process = self.parsed(DOCS / PURCHASE_BPMN).find(f"{{{BPMN_NS}}}process")
        gateways = [
            gateway.get("name")
            for gateway in process.findall(f"{{{BPMN_NS}}}exclusiveGateway")
        ]

        self.assertEqual(len(gateways), 2)
        self.assertIn("Bo`lim boshlig`i qarori", gateways)
        self.assertIn("Direktor qarori", gateways)

    def test_the_contract_flow_returns_a_refused_contract_to_its_specialist(self) -> None:
        process = self.parsed(DOCS / CONTRACT_BPMN).find(f"{{{BPMN_NS}}}process")
        paths = {
            (flow.get("sourceRef"), flow.get("targetRef"))
            for flow in process.findall(f"{{{BPMN_NS}}}sequenceFlow")
        }

        self.assertIn(("decide", "rejected"), paths)
        self.assertIn(("rejected", "raise"), paths)
