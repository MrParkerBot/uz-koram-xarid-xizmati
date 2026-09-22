"""Writing the section 10 log (REQ-LOG-001, DEC-029).

One call per thing the application does, made *after* the work succeeded.
That ordering is the whole design: a refused action, an action that raised,
and the second click of a double click all return before the call is reached,
so the log cannot claim something happened that did not.

An approval does not add a row. REQ-LOG-001's columns carry the creation and
its approval together - who made it and when, then who approved it, from
which department, with what comment and when - so `record_decision()`
completes the row the creation left behind.

What is not logged: anything written through the Django admin, a shell or a
migration. This module is called by the application's own pages, and only
those. The admin registers the log read-only (DEC-029), but nothing here can
see a write made around the outside of the pages.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from django.contrib.auth.models import AbstractBaseUser
from django.db import models
from django.utils import timezone

from xarid.models import LABEL_LENGTH, AuditEntry, department_of

# What an approval decided, for the log's own column.
APPROVED = "approved"
REFUSED = "refused"


# What the log calls a model whose own verbose name would not do. Django's
# User answers with whatever its translation catalogue holds - "foydalanuvchi"
# under uz, "user" under en - and a column UZK-053 filters by cannot have its
# values change with a setting.
FORM_NAMES: dict[str, str] = {
    "auth.user": "Foydalanuvchi",
}


def form_name_of(record: models.Model) -> str:
    """What kind of record this is, as the log's Forma nomi column prints it.

    The application's own models answer with the Uzbek Meta name they were
    given. A model from Django itself answers through its translation
    catalogue, which would make the stored value depend on LANGUAGE_CODE at
    the moment of writing, so those are named here instead.
    """
    named = FORM_NAMES.get(record_type_of(record))

    return named if named else str(record._meta.verbose_name)


def record_type_of(record: models.Model) -> str:
    """The model's label, such as xarid.supplier, for matching an approval."""
    return record._meta.label_lower


def write(
    action: str,
    *,
    by: AbstractBaseUser,
    record: models.Model,
) -> AuditEntry:
    """One entry saying this person did this to this record.

    Args:
        action: one of AuditEntry.Action.
        by: the person who did it. Their department is recorded as it is now,
            so a later transfer does not rewrite what the log says.
        record: what was written. Its label is taken now, while it still says
            what it said at the time.

    Returns:
        The entry.
    """
    return AuditEntry.objects.create(
        actor=by,
        actor_department=department_of(by),
        form_name=form_name_of(record),
        record_label=str(record)[:LABEL_LENGTH],
        record_type=record_type_of(record),
        record_id=record.pk,
        action=action,
    )


def record_created(by: AbstractBaseUser, record: models.Model) -> AuditEntry:
    """Log that this person created this record."""
    return write(AuditEntry.Action.CREATED, by=by, record=record)


def record_edited(by: AbstractBaseUser, record: models.Model) -> AuditEntry:
    """Log that this person changed this record.

    Everything that moves a record along is an edit: assigning an application,
    sending a contract for approval, moving it to another status. The
    specification offers three words - created, edited, deleted - and those
    acts are edits of the record, which is the only honest of the three.
    """
    return write(AuditEntry.Action.EDITED, by=by, record=record)


def record_deleted(by: AbstractBaseUser, record: models.Model) -> AuditEntry:
    """Log that this person deleted this record.

    Call before the deletion, while the record can still say what it was: the
    entry keeps its label, not a pointer to it.
    """
    return write(AuditEntry.Action.DELETED, by=by, record=record)


def entry_for(record: models.Model) -> AuditEntry | None:
    """The entry a decision about this record should complete, or None.

    The oldest entry that is still waiting for one: a record is created once,
    and its approval belongs to that row.

    An entry that already carries a decision is passed over. DEC-016 gives a
    purchase application two approvals - the department head, then the
    director - and REQ-LOG-001's columns hold one approver, so the second
    decision cannot share the first's row without erasing it. It gets a row
    of its own instead, and the log keeps both names.

    None for a record made before this log existed, or by a path that does
    not write to it, or one whose creation entry is already decided.
    """
    return (
        AuditEntry.objects.filter(
            record_type=record_type_of(record),
            record_id=record.pk,
            action=AuditEntry.Action.CREATED,
            approved_at__isnull=True,
        )
        .order_by("created_at", "id")
        .first()
    )


def record_decision(
    by: AbstractBaseUser,
    record: models.Model,
    *,
    approved: bool,
    comment: str = "",
) -> AuditEntry:
    """Log that this person approved or refused this record.

    Completes the entry the record's creation left, because REQ-LOG-001 puts
    both halves on one row. When there is no such entry - a record created
    before this log existed - the approval gets a row of its own rather than
    being lost, marked as an edit, which is what a decision does to a record.

    Args:
        by: the approver. Their department is recorded as the log's
            Tasdiqlovchi Bo`lim.
        record: what was decided.
        approved: True for an approval, False for a refusal.
        comment: the decision's comment. A refusal always carries one; an
            approval may not.

    Returns:
        The entry carrying the decision.
    """
    entry = entry_for(record) or write(AuditEntry.Action.EDITED, by=by, record=record)

    entry.approver = by
    entry.approver_department = department_of(by)
    entry.approval_comment = comment
    entry.approved_at = timezone.now()
    entry.approval_outcome = APPROVED if approved else REFUSED
    entry.save(
        update_fields=[
            "approver",
            "approver_department",
            "approval_comment",
            "approved_at",
            "approval_outcome",
        ]
    )

    return entry


@dataclass(frozen=True)
class Decision:
    """One decision somebody took about a record, as a page shows it.

    Read out of the log rather than off the record itself, because the record
    keeps only the last word - who approved it and who refused it - while the
    log kept every step of DEC-016's chain in the order it happened.

    Attributes:
        by: who decided. None for a decision taken before the log recorded
            the approver, which the page prints rather than hides.
        approved: True for an approval, False for a refusal.
        comment: what they wrote. A refusal always carries one; an approval
            is taken with a button and no comment box, so it rarely does.
        at: when they decided.
    """

    by: AbstractBaseUser | None
    approved: bool
    comment: str
    at: datetime


def decisions_for(records: Iterable[models.Model]) -> dict[int, list[Decision]]:
    """Every decision taken about these records, oldest first, by record id.

    One query for the whole page, so a table of a hundred rows costs the same
    as a table of one. Every record given is in the answer, those with no
    decision yet mapping to an empty list, so a caller never has to ask
    whether a key is there.

    Args:
        records: records of one and the same model - a page's table holds one
            kind - of which the first names the type the log is asked about.
    """
    records = list(records)
    if not records:
        return {}

    entries = (
        AuditEntry.objects.filter(
            record_type=record_type_of(records[0]),
            record_id__in=[record.pk for record in records],
            approved_at__isnull=False,
        )
        .select_related("approver")
        .order_by("approved_at", "id")
    )

    decisions: dict[int, list[Decision]] = {record.pk: [] for record in records}
    for entry in entries:
        decisions[entry.record_id].append(
            Decision(
                by=entry.approver,
                approved=entry.approval_outcome == APPROVED,
                comment=entry.approval_comment,
                at=entry.approved_at,
            )
        )

    return decisions
