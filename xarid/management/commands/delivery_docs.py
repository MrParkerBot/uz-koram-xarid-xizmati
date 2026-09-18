"""Write the technical documents section 6.2 asks for (REQ-ACCEPT-002).

The BPMN, the UML and the database schema are generated rather than written,
because a document written by hand is accurate on the day it is written and
silently wrong at the next migration. The schema and the class diagram are
read out of the models themselves; the two flows are described here as data
and rendered as BPMN 2.0.

`--check` compares what is on disk with what would be written and fails when
they differ, so the test suite can hold the documents to the code.

The flows drawn are the ones the code runs. Section 4.2 of the assignment was
superseded by DEC-016, which put the department head and the director in front
of the purchasing department, and by DEC-031, which makes an application
created on the Qabul qilingan page already accepted.
"""

from __future__ import annotations

import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass, field
from pathlib import Path

from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import models

APPLICATION = "xarid"

# Where the delivery set lives, relative to the repository root.
DOCS = Path("docs")
SCHEMA_FILE = DOCS / "database-schema.md"
UML_FILE = DOCS / "uml" / "domain-model.puml"
PURCHASE_BPMN = DOCS / "bpmn" / "xarid-arizasi.bpmn"
CONTRACT_BPMN = DOCS / "bpmn" / "shartnoma.bpmn"

BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
BPMNDI_NS = "http://www.omg.org/spec/BPMN/20100524/DI"
DI_NS = "http://www.omg.org/spec/DD/20100524/DI"
DC_NS = "http://www.omg.org/spec/DD/20100524/DC"

# The layout a rendered diagram uses: elements on one row, left to right.
STEP_WIDTH = 180
TASK_SIZE = (120, 80)
EVENT_SIZE = (36, 36)
GATEWAY_SIZE = (50, 50)
ROW_TOP = 120


@dataclass(frozen=True)
class Step:
    """One element of a flow.

    Attributes:
        key: the element id, unique within its flow.
        label: what the diagram prints on it.
        kind: "start", "task", "gateway" or "end".
        to: the keys this step leads to, in order.
        guards: what each of those paths is called, for a gateway.
    """

    key: str
    label: str
    kind: str
    to: tuple[str, ...] = ()
    guards: tuple[str, ...] = ()


@dataclass(frozen=True)
class Flow:
    """One process: what it is called, and the steps it runs through."""

    key: str
    name: str
    steps: tuple[Step, ...] = field(default_factory=tuple)


# The purchase request, as DEC-016 sequences it and the code implements it.
PURCHASE_FLOW = Flow(
    key="xarid-arizasi",
    name="Xarid arizasi (DEC-016)",
    steps=(
        Step("start", "Xodim xarid arizasini yuboradi", "start", ("submit",)),
        Step("submit", "Ariza yaratiladi (PDF bilan)", "task", ("head",)),
        Step(
            "head",
            "Bo`lim boshlig`i qarori",
            "gateway",
            ("head_ok", "refused"),
            ("Tasdiq", "Inkor"),
        ),
        Step("head_ok", "Direktorga yuboriladi", "task", ("director",)),
        Step(
            "director",
            "Direktor qarori",
            "gateway",
            ("approved", "refused"),
            ("Tasdiq", "Inkor"),
        ),
        Step("approved", "QR kod bosiladi va ariza yaratiladi", "task", ("arrived",)),
        Step("arrived", "Xarid bo`limiga tushadi", "task", ("done",)),
        Step("refused", "Yuboruvchi izoh bilan xabardor qilinadi", "task", ("done",)),
        Step("done", "Tugadi", "end"),
    ),
)

# The contract, as TASK-UZK-037, 038 and 039 implement it.
CONTRACT_FLOW = Flow(
    key="shartnoma",
    name="Shartnoma (REQ-SHARTNOMA-002, DEC-010)",
    steps=(
        Step("start", "Ariza mutaxassisga tayinlangan", "start", ("raise",)),
        Step("raise", "Shartnoma kiritiladi (kelishilgan)", "task", ("send",)),
        Step("send", "Tasdiqlashga yuboriladi", "task", ("decide",)),
        Step(
            "decide",
            "Bo`lim boshlig`i qarori",
            "gateway",
            ("signed", "rejected"),
            ("Tasdiq", "Inkor"),
        ),
        Step("signed", "Tuzilgan shartnoma", "task", ("statuses",)),
        Step("statuses", "Holat zanjiri (master data)", "task", ("delivered",)),
        Step("delivered", "Tugallangan holat", "task", ("done",)),
        Step("rejected", "Mutaxassisga qaytariladi", "task", ("raise",)),
        Step("done", "Tugadi", "end"),
    ),
)

FLOWS = ((PURCHASE_FLOW, PURCHASE_BPMN), (CONTRACT_FLOW, CONTRACT_BPMN))


def domain_models() -> list[type[models.Model]]:
    """Every model the application declares, in a stable order."""
    return sorted(apps.get_app_config(APPLICATION).get_models(), key=lambda model: model.__name__)


def column_of(field_: models.Field) -> tuple[str, str, str, str]:
    """One row of the schema table: column, type, null, and what it refers to."""
    refers = ""
    if field_.many_to_one or field_.one_to_one:
        target = field_.related_model
        refers = f"-> `{target._meta.db_table}`"

    rules = []
    if field_.primary_key:
        rules.append("primary key")
    if field_.unique and not field_.primary_key:
        rules.append("unique")
    if field_.null:
        rules.append("null")

    return (
        f"`{field_.column}`",
        field_.get_internal_type(),
        ", ".join(rules),
        refers,
    )


def schema_document() -> str:
    """Every table and column, read from the models rather than transcribed."""
    lines = [
        "# Database schema",
        "",
        "Generated from the models by `python manage.py delivery_docs`. Do not edit by",
        "hand: `python manage.py delivery_docs --check` fails when this file and the",
        "code disagree, and the test suite runs that check.",
        "",
        "Deletion is deactivation everywhere (DEC-009), so no table here has rows",
        "removed by the application.",
        "",
    ]
    for model in domain_models():
        meta = model._meta
        lines.append(f"## `{meta.db_table}` - {meta.verbose_name}")
        lines.append("")
        lines.append("| Column | Type | Rules | References |")
        lines.append("| --- | --- | --- | --- |")
        for field_ in meta.concrete_fields:
            column, kind, rules, refers = column_of(field_)
            lines.append(f"| {column} | {kind} | {rules} | {refers} |")
        lines.append("")

    return "\n".join(lines)


def uml_document() -> str:
    """A PlantUML class diagram of the entities and how they relate."""
    lines = [
        "@startuml domain-model",
        "' Generated by `python manage.py delivery_docs`. Do not edit by hand.",
        "hide circle",
        "skinparam linetype ortho",
        "",
    ]
    relations = []
    for model in domain_models():
        meta = model._meta
        lines.append(f'class {model.__name__} <<{meta.db_table}>> {{')
        for field_ in meta.concrete_fields:
            lines.append(f"  {field_.name} : {field_.get_internal_type()}")
        lines.append("}")
        lines.append("")
        for field_ in meta.concrete_fields:
            if field_.many_to_one or field_.one_to_one:
                arrow = "--|>" if field_.one_to_one else "-->"
                relations.append(
                    f"{model.__name__} {arrow} {field_.related_model.__name__} : {field_.name}"
                )

    lines.extend(sorted(relations))
    lines.append("")
    lines.append("@enduml")

    return "\n".join(lines)


def laid_out(flow: Flow) -> dict[str, tuple[int, int, int, int]]:
    """A box per step, in one row, left to right in declaration order."""
    sizes = {
        "start": EVENT_SIZE,
        "end": EVENT_SIZE,
        "gateway": GATEWAY_SIZE,
        "task": TASK_SIZE,
    }
    boxes = {}
    for index, step in enumerate(flow.steps):
        width, height = sizes[step.kind]
        left = 120 + index * STEP_WIDTH
        boxes[step.key] = (left, ROW_TOP + (TASK_SIZE[1] - height) // 2, width, height)

    return boxes


def bpmn_document(flow: Flow) -> str:
    """One flow as BPMN 2.0, with the diagram a viewer needs to render it.

    The elements alone are a valid process and an empty picture: bpmn.io and
    Camunda Modeler draw from the BPMNDI shapes and edges, and a file without
    them opens as an error rather than as a diagram.
    """
    ElementTree.register_namespace("bpmn", BPMN_NS)
    ElementTree.register_namespace("bpmndi", BPMNDI_NS)
    ElementTree.register_namespace("di", DI_NS)
    ElementTree.register_namespace("dc", DC_NS)

    definitions = ElementTree.Element(
        f"{{{BPMN_NS}}}definitions",
        {"id": f"definitions-{flow.key}", "targetNamespace": "http://uz-koram/xarid"},
    )
    process = ElementTree.SubElement(
        definitions,
        f"{{{BPMN_NS}}}process",
        {"id": flow.key, "name": flow.name, "isExecutable": "false"},
    )

    tags = {
        "start": "startEvent",
        "end": "endEvent",
        "gateway": "exclusiveGateway",
        "task": "task",
    }
    edges = []
    for step in flow.steps:
        ElementTree.SubElement(
            process,
            f"{{{BPMN_NS}}}{tags[step.kind]}",
            {"id": step.key, "name": step.label},
        )
        for index, target in enumerate(step.to):
            guard = step.guards[index] if index < len(step.guards) else ""
            edges.append((f"{step.key}-{target}", step.key, target, guard))

    for edge_id, source, target, guard in edges:
        ElementTree.SubElement(
            process,
            f"{{{BPMN_NS}}}sequenceFlow",
            {"id": edge_id, "sourceRef": source, "targetRef": target, "name": guard},
        )

    diagram = ElementTree.SubElement(
        definitions, f"{{{BPMNDI_NS}}}BPMNDiagram", {"id": f"diagram-{flow.key}"}
    )
    plane = ElementTree.SubElement(
        diagram, f"{{{BPMNDI_NS}}}BPMNPlane", {"id": f"plane-{flow.key}", "bpmnElement": flow.key}
    )
    boxes = laid_out(flow)
    for step in flow.steps:
        left, top, width, height = boxes[step.key]
        shape = ElementTree.SubElement(
            plane,
            f"{{{BPMNDI_NS}}}BPMNShape",
            {"id": f"shape-{step.key}", "bpmnElement": step.key},
        )
        ElementTree.SubElement(
            shape,
            f"{{{DC_NS}}}Bounds",
            {"x": str(left), "y": str(top), "width": str(width), "height": str(height)},
        )

    for edge_id, source, target, _guard in edges:
        edge = ElementTree.SubElement(
            plane,
            f"{{{BPMNDI_NS}}}BPMNEdge",
            {"id": f"edge-{edge_id}", "bpmnElement": edge_id},
        )
        for key in (source, target):
            left, top, width, height = boxes[key]
            ElementTree.SubElement(
                edge,
                f"{{{DI_NS}}}waypoint",
                {"x": str(left + width // 2), "y": str(top + height // 2)},
            )

    ElementTree.indent(definitions, space="  ")

    return ElementTree.tostring(definitions, encoding="unicode", xml_declaration=True) + "\n"


def index_document() -> str:
    """What the delivery set holds, and how to produce it again."""
    return "\n".join(
        [
            "# Technical documents",
            "",
            "The deliverables section 6.2 of the assignment lists, beside the source",
            "code itself (REQ-ACCEPT-002).",
            "",
            "| File | What it is |",
            "| --- | --- |",
            f"| [`{PURCHASE_BPMN.name}`](bpmn/{PURCHASE_BPMN.name}) | The purchase "
            "request flow, as DEC-016 sequences it. |",
            f"| [`{CONTRACT_BPMN.name}`](bpmn/{CONTRACT_BPMN.name}) | The contract "
            "flow: raised, sent, decided, then through its status chain. |",
            f"| [`{UML_FILE.name}`](uml/{UML_FILE.name}) | A class diagram of every "
            "entity, its fields and its relations. |",
            f"| [`{SCHEMA_FILE.name}`]({SCHEMA_FILE.name}) | Every table and column, "
            "with its type, its rules and what it refers to. |",
            "",
            "## They are generated, not written",
            "",
            "```bash",
            "python manage.py delivery_docs          # write them",
            "python manage.py delivery_docs --check  # fail if they are out of date",
            "```",
            "",
            "A document written by hand is accurate on the day it is written and quietly",
            "wrong at the next migration. These are produced from the models and from the",
            "flows as the code runs them, and `tests/test_documentation.py` runs the check,",
            "so a change that leaves them behind fails the build.",
            "",
            "## What they describe",
            "",
            "The system that was built, not the assignment's section 4.2: DEC-016 put the",
            "requester's department head and the director in front of the purchasing",
            "department, and DEC-031 makes an application created on the Qabul qilingan",
            "page already accepted. The BPMN files open in bpmn.io and Camunda Modeler;",
            "the `.puml` renders with PlantUML.",
            "",
            "The assignment also lists `DB SQL` among the deliverables. The schema is owned",
            "by the migrations in `xarid/migrations/`, which are the executable definition;",
            "`database-schema.md` describes what they produce rather than repeating them in",
            "a second dialect that would be the one to go stale.",
            "",
        ]
    )


def documents() -> dict[Path, str]:
    """Every file of the delivery set, by path."""
    written = {
        DOCS / "README.md": index_document(),
        SCHEMA_FILE: schema_document(),
        UML_FILE: uml_document(),
    }
    for flow, path in FLOWS:
        written[path] = bpmn_document(flow)

    return written


class Command(BaseCommand):
    """Write the delivery documentation set, or check that it is up to date."""

    help = "Write docs/ from the models and the flows, or --check that it is current."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--check",
            action="store_true",
            help="Write nothing; fail when a document differs from what would be written.",
        )

    def handle(self, *args, **options) -> None:
        stale = []
        for path, content in documents().items():
            if options["check"]:
                current = path.read_text(encoding="utf-8") if path.exists() else ""
                if current != content:
                    stale.append(str(path))
                continue

            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            self.stdout.write(f"wrote {path}")

        if stale:
            raise SystemExit(
                "These documents no longer describe the code. Run "
                "`python manage.py delivery_docs`:\n  " + "\n  ".join(stale)
            )

        if options["check"]:
            self.stdout.write("The delivery documents are up to date.")
