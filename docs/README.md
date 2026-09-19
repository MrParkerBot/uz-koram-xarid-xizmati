# Technical documents

The deliverables section 6.2 of the assignment lists, beside the source
code itself (REQ-ACCEPT-002).

| File | What it is |
| --- | --- |
| [`xarid-arizasi.bpmn`](bpmn/xarid-arizasi.bpmn) | The purchase request flow, as DEC-016 sequences it. |
| [`shartnoma.bpmn`](bpmn/shartnoma.bpmn) | The contract flow: raised, sent, decided, then through its status chain. |
| [`domain-model.puml`](uml/domain-model.puml) | A class diagram of every entity, its fields and its relations. |
| [`database-schema.md`](database-schema.md) | Every table and column, with its type, its rules and what it refers to. |
| [`database-schema.sql`](database-schema.sql) | The same schema as SQLite DDL, emitted by the code that applies the migrations. |

## They are generated, not written

```bash
python manage.py delivery_docs          # write them
python manage.py delivery_docs --check  # fail if they are out of date
```

A document written by hand is accurate on the day it is written and quietly
wrong at the next migration. These are produced from the models and from the
flows as the code runs them, and `tests/test_documentation.py` runs the check,
so a change that leaves them behind fails the build.

## What they describe

The system that was built, not the assignment's section 4.2: DEC-016 put the
requester's department head and the director in front of the purchasing
department, and DEC-031 makes an application created on the Qabul qilingan
page already accepted. The BPMN files open in bpmn.io and Camunda Modeler;
the `.puml` renders with PlantUML.

The assignment also lists `DB SQL` among the deliverables. The schema is owned
by the migrations in `xarid/migrations/`, which are the executable definition,
so `database-schema.sql` is generated from them rather than written beside
them: a hand-kept second copy would be the one to go stale, and this one
cannot, because the same check guards it. It is SQLite DDL and documents the
schema (DEC-040); it is not meant to be run against another database.
