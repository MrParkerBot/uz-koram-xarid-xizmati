"""The work the department does, rather than the lists that describe it.

accounts holds facts about people and reference holds the maintainable lists.
An application is neither: it is a record with a life cycle, and it is the
first thing here that has one.

TASK-UZK-022 builds the record and the incoming list; TASK-UZK-023 and
TASK-UZK-024 are the two decisions taken on it there, and TASK-UZK-025 to
TASK-UZK-027 carry an accepted one onward.

TASK-UZK-026 splits the record in two. What an application orders is an
ApplicationItem now rather than four columns on the application, because
REQ-ARIZA-010's plus button means one application can order several things.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.utils import timezone

from applications.attachments import (
    application_pdf_field,
    attachment_storage,
    contract_pdf_field,
)

# DEC-022: ARZ-2026-00001, five digits, resetting each year.
ARIZA_NUMBER_PREFIX = "ARZ"
ARIZA_NUMBER_DIGITS = 5

# The section 4.9 purchase application. DEC-022 names the ARZ and SHT
# sequences and is silent about this one; XA is what the approved prototype
# shows, and it takes the same shape so all three read alike.
XARID_NUMBER_PREFIX = "XA"

# DEC-022 names this one outright: SHT-2026-00001, the contract sequence.
CONTRACT_NUMBER_PREFIX = "SHT"

# The smallest order anybody can place: one thousandth, which is the finest
# the quantity column stores. Written as the smallest storable amount rather
# than as zero, so that the floor moves with decimal_places if that ever
# changes, and so that an order for none of something is refused too.
SMALLEST_QUANTITY = Decimal("0.001")

# The same idea for money, in the currency DEC-026 fixes: one tiyin, which is
# the finest a money column here stores. A line priced at nothing is not a
# line somebody agreed a price for.
SMALLEST_PRICE = Decimal("0.01")

# What every money amount is rounded to before it is stored or added up. A
# quantity has three decimal places and a price has two, so their product has
# five, and five decimal places of a soum is not an amount anybody pays.
SOUM = Decimal("0.01")


def money_display(amount: Decimal) -> str:
    """An amount of soums, grouped so a person can read it.

    A contract here runs to hundreds of millions, and Django renders
    125000000.00 under LANGUAGE_CODE uz as "125000000,00" - which a reader can
    take as twelve and a half billion, because a comma is a thousands
    separator in most of the world. The same trap soni_display was written
    for, with more zeros in front of it.

    Grouped and separated with a comma, which is the Uzbek convention:
    125 000 000,00. The group separator is a non-breaking space so
    that a browser cannot wrap an amount across two lines and show half of it
    at the end of one.

    One function rather than one per model: a contract's value is the sum of
    its line totals, and a page that renders the parts one way and the whole
    another invites somebody to check the arithmetic and find it wrong.
    """
    whole, _, fraction = f"{amount:.2f}".partition(".")

    return f"{int(whole):,}".replace(",", " ") + f",{fraction}"


def next_number(prefix: str, model, field: str, today: date | None = None) -> str:
    """The next number in one year's sequence (DEC-022).

    Shared by every DEC-022 sequence, so a mistake in the allocation is one
    mistake rather than one per record type. TASK-UZK-030 is what made it
    worth extracting; before there was a second sequence, the general version
    would have been a guess about what the second one needed.

    The sequence restarts annually, so the number is allocated by looking at
    what this year already has rather than by a global counter. Called inside
    the same transaction as the save, so two records created at once cannot be
    handed the same number - and the unique column is what makes that a
    failure rather than a duplicate if they somehow are.

    The highest number is found by sorting as text, which is correct only
    because the sequence is zero-padded to a fixed width: ARZ-2026-00009 sorts
    below ARZ-2026-00010. It would stop being correct if a year ever needed a
    sixth digit, because ARZ-2026-100000 sorts below ARZ-2026-99999 and the
    number allocated next would already be taken. The unique column turns that
    into an error rather than a duplicate, and a department raising a hundred
    thousand applications a year is not this one - but the constraint is
    invisible otherwise, so it is written down here.

    Args:
        prefix: the letters in front of the year, such as ARZ or XA.
        model: the model holding the sequence.
        field: the name of its number column.
        today: the date the year is taken from.
    """
    year = (today or date.today()).year
    start = f"{prefix}-{year}-"

    highest = (
        model.objects.filter(**{f"{field}__startswith": start})
        .order_by(f"-{field}")
        .values_list(field, flat=True)
        .first()
    )
    used = int(highest.removeprefix(start)) if highest else 0

    return f"{start}{used + 1:0{ARIZA_NUMBER_DIGITS}d}"


def next_ariza_raqami(today: date | None = None) -> str:
    """The next department application number for this year (DEC-022)."""
    return next_number(ARIZA_NUMBER_PREFIX, Application, "ariza_raqami", today)


def next_xarid_raqami(today: date | None = None) -> str:
    """The next purchase application number for this year.

    Its own sequence, independent of the ARZ one: the two are different
    records, and a shared counter would make either one's numbering depend on
    how busy the other had been.
    """
    return next_number(
        XARID_NUMBER_PREFIX, PurchaseApplication, "xarid_raqami", today
    )


def next_shartnoma_raqami(today: date | None = None) -> str:
    """The next contract number for this year (DEC-022).

    Its own sequence, like the other two. DEC-022 names this one explicitly,
    which the purchase application's does not have and had to be inferred.
    """
    return next_number(
        CONTRACT_NUMBER_PREFIX, Contract, "shartnoma_raqami", today
    )


class Application(models.Model):
    """One purchase application, as section 4.1 describes it.

    The stage is a code this application stores, not one of the Ariza Status
    rows DEC-017 makes editable master data. The two are different things and
    this is where they separate: a status is what a person reads on the page
    and an administrator may rename or delete, while a stage is what the
    workflow branches on. The TASK-UZK-015 review established the principle -
    a name the code depends on is a name that can be pulled out from under it -
    and the TASK-UZK-016 review recorded that this task would be where it
    mattered. TASK-UZK-023 sets the status alongside the stage.

    DEC-016 puts a requester, their Bo`lim Boshlig`i and a Direktor in front of
    this record before it reaches the incoming list. None of that is built, so
    an application here is simply one that has arrived; sender is nullable
    until the chain that identifies them exists.
    """

    class Stage(models.TextChoices):
        """Where an application has got to, in terms the code may rely on."""

        INCOMING = "incoming", "Kelib tushgan"
        ACCEPTED = "accepted", "Qabul qilingan"
        ASSIGNED = "assigned", "Tayinlangan"
        REJECTED = "rejected", "Inkor etilgan"

    ariza_raqami = models.CharField("Ariza raqami", max_length=32, unique=True)
    department = models.ForeignKey(
        "reference.Department",
        on_delete=models.PROTECT,
        related_name="applications",
        verbose_name="Bo`lim nomi",
    )
    buyurtmachi_ismi = models.CharField(
        "Buyurtmachi ismi",
        max_length=255,
        blank=True,
        help_text=(
            "Who asked for this, as REQ-ARIZA-008 collects it: a name typed "
            "on the form rather than a user chosen from a list. DEC-016's "
            "approval chain would identify a person, and it is not built - "
            "which is the same reason sender is nullable. Blank because every "
            "application that existed before the form predates the question."
        ),
    )
    izoh = models.TextField("Izoh", blank=True)
    pdf = application_pdf_field()
    sender = models.ForeignKey(
        "auth.User",
        on_delete=models.PROTECT,
        related_name="submitted_applications",
        null=True,
        blank=True,
        verbose_name="Yuboruvchi",
        help_text=(
            "Who TASK-UZK-023 and TASK-UZK-024 notify. Nullable because the "
            "DEC-016 approval chain that would identify them is not built."
        ),
    )
    status = models.ForeignKey(
        "reference.ArizaStatus",
        on_delete=models.PROTECT,
        related_name="applications",
        null=True,
        blank=True,
        verbose_name="Status",
        help_text=(
            "What a person reads, beside the stage the workflow branches on. "
            "Nullable because DEC-017 lets an administrator delete every "
            "status, and a master data page must not be able to stop an "
            "application being accepted."
        ),
    )
    kelib_tushgan_sana = models.DateTimeField(
        "Kelib tushgan sana", auto_now_add=True
    )
    qabul_qilingan_sana = models.DateTimeField(
        "Qabul qilingan sana", null=True, blank=True
    )
    accepted_by = models.ForeignKey(
        "auth.User",
        on_delete=models.PROTECT,
        related_name="accepted_applications",
        null=True,
        blank=True,
        verbose_name="Qabul qilgan",
    )
    inkor_izohi = models.TextField(
        "Inkor izohi",
        blank=True,
        help_text=(
            "Why it was rejected. REQ-ARIZA-005 makes this compulsory at the "
            "moment of rejection, which reject() enforces; the column is "
            "blank rather than null because an application that was never "
            "rejected has no comment, and that is an empty string."
        ),
    )
    inkor_qilingan_sana = models.DateTimeField(
        "Inkor qilingan sana", null=True, blank=True
    )
    rejected_by = models.ForeignKey(
        "auth.User",
        on_delete=models.PROTECT,
        related_name="rejected_applications",
        null=True,
        blank=True,
        verbose_name="Inkor qilgan",
    )
    assigned_to = models.ForeignKey(
        "auth.User",
        on_delete=models.PROTECT,
        related_name="assigned_applications",
        null=True,
        blank=True,
        verbose_name="Tayinlangan xodim",
        help_text=(
            "The Katta Mutaxasis this application is for (REQ-ARIZA-007). "
            "Null until somebody is chosen, which is what an unassigned row "
            "on the Qabul qilingan page is."
        ),
    )
    xodim_qabul_qilgan_sana = models.DateTimeField(
        "Xodim qabul qilgan sana",
        null=True,
        blank=True,
        help_text=(
            "When the assigned specialist took the work (REQ-ARIZA-013). A "
            "different fact from qabul_qilingan_sana, which is when the "
            "department accepted the application itself - one column meaning "
            "both would make the Qabul qilingan date unreadable. Cleared when "
            "the application moves to somebody else, because the next holder "
            "has not taken anything yet."
        ),
    )
    tayinlangan_sana = models.DateTimeField(
        "Tayinlangan sana",
        null=True,
        blank=True,
        help_text=(
            "When the current assignment was made. Re-assignment replaces it "
            "rather than keeping the first, because DEC-024 makes the "
            "assignment a fact about now and the history belongs in the "
            "section 10 log."
        ),
    )
    assigned_by = models.ForeignKey(
        "auth.User",
        on_delete=models.PROTECT,
        related_name="applications_assigned_by_me",
        null=True,
        blank=True,
        verbose_name="Tayinlagan",
        help_text=(
            "Who made the current assignment. Recorded here because DEC-024 "
            "wants every move in the log and TASK-UZK-052 builds the log: "
            "the record knows who and when, so the entry can be written when "
            "there is somewhere to write it."
        ),
    )
    stage = models.CharField(
        max_length=16, choices=Stage.choices, default=Stage.INCOMING
    )

    class Meta:
        # Newest first: the department head works through what has just
        # arrived, not through what has been sitting there longest.
        ordering = ("-kelib_tushgan_sana", "-id")
        verbose_name = "Ariza"
        verbose_name_plural = "Arizalar"

    def __str__(self) -> str:
        return self.ariza_raqami

    @property
    def is_incoming(self) -> bool:
        """Whether this application is still waiting to be decided."""
        return self.stage == self.Stage.INCOMING

    @property
    def is_assigned(self) -> bool:
        """Whether somebody is currently working on this application."""
        return self.stage == self.Stage.ASSIGNED

    @transaction.atomic
    def accept(self, by) -> bool:
        """Accept this application, once.

        Moves it to the ACCEPTED stage, stamps the date TASK-UZK-025 shows as
        Qabul qilingan sana, records who decided, and attaches the status the
        department reads for an accepted application when one can be found.

        The status is found by its code, not its name: DEC-017 lets an
        administrator rename any status row, and a lookup by name is one that
        stops working the day somebody exercises the page. If every status has
        been deleted the application is still accepted, with no status - a
        master data page must not be able to stop the workflow.

        Args:
            by: the user accepting it, recorded as the acceptor.

        Returns:
            True when this call accepted it, and False when somebody else
            already had - whether before this call started or while it was
            running. False rather than an exception because the second click
            of a double click is not an error, and the caller wants to say
            "already accepted" rather than show a crash.

            The transition is a conditional write, so exactly one of two
            simultaneous callers is told True.

        Raises:
            ValueError: when the application is at a stage acceptance makes no
                sense from - a rejected one. That is not a double click; it is
                a request for something that should not happen.
        """
        # Whatever the caller is holding may be a moment old - the view
        # fetched it before this call started. Decide on the row as it is now,
        # and leave the caller holding that too: they are about to render a
        # page from this instance.
        self.refresh_from_db()

        if self.stage == self.Stage.ACCEPTED:
            return False

        if not self.is_incoming:
            raise ValueError(
                f"{self.ariza_raqami} is {self.stage}, not incoming, "
                "so it cannot be accepted."
            )

        from reference.models import ArizaStatus

        decided_at = timezone.now()
        status = ArizaStatus.objects.filter(
            code=ArizaStatus.Code.ACCEPTED, is_active=True
        ).first()

        # The condition is part of the write, not a question asked before it.
        # A check followed by an unconditional save decides on a row that
        # another request may already have moved, and the loser of that race
        # overwrites the winner's date and acceptor - so the record would name
        # the wrong person, and both callers would be told they accepted it.
        # Here the database compares the stage while it holds the row, and the
        # count it returns is the answer to "did this call do it".
        accepted = type(self).objects.filter(
            pk=self.pk, stage=self.Stage.INCOMING
        ).update(
            stage=self.Stage.ACCEPTED,
            qabul_qilingan_sana=decided_at,
            accepted_by=by,
            status=status,
        )

        if not accepted:
            # Somebody else got there between the read above and this write.
            # Whatever they did, this call did not accept it.
            self.refresh_from_db()
            return False

        self.stage = self.Stage.ACCEPTED
        self.qabul_qilingan_sana = decided_at
        self.accepted_by = by
        self.status = status

        return True

    @transaction.atomic
    def reject(self, by, comment: str) -> bool:
        """Reject this application, once, with a reason.

        REQ-ARIZA-005 makes the comment the point of the action rather than a
        decoration on it: the sender is told why, so a rejection with no
        reason is not a rejection this method will perform. The check is here
        and not only in the form, because the reason has to exist wherever the
        rejection is made from.

        The cancelled status is found by its code, for the reason accept()
        gives: DEC-017 invites an administrator to rename these rows.

        Args:
            by: the user rejecting it, recorded as the decider.
            comment: why. Stored with its surrounding whitespace stripped.

        Returns:
            True when this call rejected it, and False when somebody else
            already had - the second click of a double click, which is not an
            error. The transition is a conditional write, so exactly one of
            two simultaneous callers is told True.

        Raises:
            ValueError: when the comment is empty or only whitespace, or when
                the application is at a stage rejection makes no sense from.
                Both leave the record exactly as it was.
        """
        reason = (comment or "").strip()
        if not reason:
            raise ValueError(
                f"{self.ariza_raqami} cannot be rejected without a comment."
            )

        # Decide on the row as it is now, not as the caller last saw it, and
        # leave the caller holding that. Same reason as accept(): the view
        # fetched this instance before the call started.
        self.refresh_from_db()

        if self.stage == self.Stage.REJECTED:
            return False

        if not self.is_incoming:
            raise ValueError(
                f"{self.ariza_raqami} is {self.stage}, not incoming, "
                "so it cannot be rejected."
            )

        from reference.models import ArizaStatus

        decided_at = timezone.now()
        status = ArizaStatus.objects.filter(
            code=ArizaStatus.Code.CANCELLED, is_active=True
        ).first()

        # The condition is part of the write, for the reason accept() gives at
        # length: a check followed by an unconditional save lets the loser of
        # a race overwrite the winner's decision.
        rejected = type(self).objects.filter(
            pk=self.pk, stage=self.Stage.INCOMING
        ).update(
            stage=self.Stage.REJECTED,
            inkor_izohi=reason,
            inkor_qilingan_sana=decided_at,
            rejected_by=by,
            status=status,
        )

        if not rejected:
            self.refresh_from_db()
            return False

        self.stage = self.Stage.REJECTED
        self.inkor_izohi = reason
        self.inkor_qilingan_sana = decided_at
        self.rejected_by = by
        self.status = status

        return True

    @transaction.atomic
    def assign(self, by, specialist) -> bool:
        """Give this application to a specialist, or to a different one.

        Not a one-way move the way accept() is. DEC-024 lets Admin re-assign
        at any time, including after the specialist has accepted, so the
        assigned stage is both a destination and a starting point and the
        same method does both.

        The stamp is replaced rather than added to: tayinlangan_sana is when
        the current assignment was made, and who held it before belongs in
        the section 10 log that TASK-UZK-052 builds. The record carries who
        and when so that entry can be written when there is a log.

        Args:
            by: the user making the assignment, recorded on the record.
            specialist: who it is for. Must be one of the people
                assignable_specialists() names.

        Returns:
            True when this call moved it, and False when it was already with
            that specialist - the second click of a double click, which is
            not an error and does not re-stamp the date.

        Raises:
            ValueError: when the specialist is not a Katta Mutaxasis, or the
                application is at a stage assignment makes no sense from.
                Both leave the record exactly as it was.
        """
        from accounts.roles import assignable_specialists

        if specialist is None or not assignable_specialists().filter(
            pk=specialist.pk
        ).exists():
            raise ValueError(
                f"{specialist} is not a Katta Mutaxasis, so "
                f"{self.ariza_raqami} cannot be assigned to them."
            )

        # Decide on the row as it is now, not as the caller last saw it. Same
        # reason accept() gives: the view fetched this instance before the
        # call started.
        self.refresh_from_db()

        if self.assigned_to_id == specialist.pk:
            return False

        assignable = (self.Stage.ACCEPTED, self.Stage.ASSIGNED)
        if self.stage not in assignable:
            raise ValueError(
                f"{self.ariza_raqami} is {self.stage}, so it cannot be "
                "assigned: only an accepted application is given out, and "
                "only an assigned one is given to somebody else."
            )

        decided_at = timezone.now()

        # The condition is part of the write, for the reason accept() gives at
        # length. Here it also carries the specialist: two managers assigning
        # the same application to two different people at once must not both
        # be told they did it, and the row the second one updates no longer
        # matches the stage and holder it read.
        assigned = type(self).objects.filter(
            pk=self.pk, stage__in=assignable, assigned_to=self.assigned_to
        ).update(
            stage=self.Stage.ASSIGNED,
            assigned_to=specialist,
            assigned_by=by,
            tayinlangan_sana=decided_at,
            # The acceptance belonged to whoever held it before. DEC-024
            # allows this move after they accepted, and leaving their
            # acceptance on the record would say the new holder agreed to
            # take work they have not seen. Cleared here rather than by every
            # caller, because forgetting it is silent.
            xodim_qabul_qilgan_sana=None,
        )

        if not assigned:
            self.refresh_from_db()
            return False

        self.stage = self.Stage.ASSIGNED
        self.assigned_to = specialist
        self.assigned_by = by
        self.tayinlangan_sana = decided_at
        self.xodim_qabul_qilgan_sana = None

        return True

    @transaction.atomic
    def accept_as_specialist(self, by) -> bool:
        """Record that the holder took this application (REQ-ARIZA-013).

        The stage does not move. Nothing in the specification names a stage
        after assigned, and DEC-024 needs assign() to keep working afterwards
        - a new stage would quietly close a door the decision holds open. What
        changes is that the record now says the work was taken, not only given.

        Args:
            by: the user accepting. Must be the specialist currently holding
                it; a manager acting on their behalf passes the holder.

        Returns:
            True when this call recorded it, False when it was already
            recorded - the second click of a double click, which does not
            re-stamp the date.

        Raises:
            ValueError: when the application is not assigned to this person,
                or is not at the assigned stage at all.
        """
        self.refresh_from_db()

        if self.stage != self.Stage.ASSIGNED:
            raise ValueError(
                f"{self.ariza_raqami} is {self.stage}, not assigned, so "
                "there is nothing for a specialist to accept."
            )

        if by is None or self.assigned_to_id != getattr(by, "pk", None):
            raise ValueError(
                f"{self.ariza_raqami} is not assigned to {by}, so they "
                "cannot accept it."
            )

        if self.xodim_qabul_qilgan_sana is not None:
            return False

        accepted_at = timezone.now()

        # Conditional on the acceptance still being empty as well as on the
        # holder, so two clicks landing together produce one stamp and one
        # notification rather than two of each.
        taken = type(self).objects.filter(
            pk=self.pk,
            stage=self.Stage.ASSIGNED,
            assigned_to=by,
            xodim_qabul_qilgan_sana__isnull=True,
        ).update(xodim_qabul_qilgan_sana=accepted_at)

        if not taken:
            self.refresh_from_db()
            return False

        self.xodim_qabul_qilgan_sana = accepted_at

        return True

    @property
    def is_taken(self) -> bool:
        """Whether the holder has accepted this application."""
        return self.xodim_qabul_qilgan_sana is not None

    @transaction.atomic
    def set_status(self, status) -> bool:
        """Mark the state this application is currently in (REQ-ARIZA-013).

        A status a person chose, beside the ones accept() and reject() set by
        code. DEC-017 makes the rows editable master data, so what may be
        chosen is whatever is active now - and an application already holding
        a row that has since been deactivated keeps it, because DEC-009 keeps
        the row for exactly that.

        Args:
            status: the ArizaStatus to move to. Must be active.

        Returns:
            True when this call changed it, False when it was already that
            status.

        Raises:
            ValueError: when status is None, when it is not active, or when
                this application is not one somebody is working on. Choosing
                nothing is not a way of clearing the status, an inactive row
                is one an administrator has taken out of use, and an
                application nobody holds has no progress to report.
        """
        if status is None:
            raise ValueError(
                f"{self.ariza_raqami} needs a status to be set to."
            )

        if not status.is_active:
            raise ValueError(
                f"{status.name} is not in use, so {self.ariza_raqami} "
                "cannot be moved to it."
            )

        self.refresh_from_db()

        # The stage check belongs here rather than in the view, which is what
        # the #40 review found: the route is on the Tayinlangan page and had
        # nothing stopping it writing an application that page never shows. A
        # manager could move a rejected application to a status, and a
        # rejected application is off the workflow entirely. accept_as_
        # specialist() already guards this way; this is the same rule for the
        # other half of REQ-ARIZA-013.
        if self.stage != self.Stage.ASSIGNED:
            raise ValueError(
                f"{self.ariza_raqami} is {self.stage}, not assigned, so "
                "there is no work in progress to report a status for."
            )

        if self.status_id == status.pk:
            return False

        type(self).objects.filter(pk=self.pk).update(status=status)
        self.status = status

        return True

    @classmethod
    @transaction.atomic
    def raise_application(
        cls, items: Sequence[Mapping[str, object]], **fields
    ) -> Application:
        """Create an application and its order lines, in one transaction.

        The only way an application should be created, so that nothing ends up
        without a number. Atomic with the number lookup, so two callers at once
        cannot read the same highest number and both use it - and atomic with
        the lines, so a failure part way through the order leaves no
        application rather than one nobody can fill.

        Args:
            items: one mapping of ApplicationItem fields per order line, in
                the order they should be read. REQ-ARIZA-010's plus button is
                what produces more than one.
            **fields: the application's own columns.

        Returns:
            The created application. Its lines are written but not fetched;
            read them through .items.

        Raises:
            ValueError: when items is empty. An application with nothing
                ordered on it is not a record this department has a use for,
                and the form refuses it too - here as well, because the
                database has no way to express "at least one row".
        """
        if not items:
            raise ValueError(
                "An application needs at least one order line (REQ-ARIZA-010)."
            )

        application = cls.objects.create(
            ariza_raqami=next_ariza_raqami(), **fields
        )
        ApplicationItem.objects.bulk_create(
            [
                ApplicationItem(application=application, **line)
                for line in items
            ]
        )

        return application


class OrderLine(models.Model):
    """One line of what somebody ordered: what, how much, in what unit.

    Abstract, and shared by the department application's lines and the
    purchase application's. The columns describe the same thing in both
    places, and REQ-ARIZA-010 and REQ-ARIZA-015 both put a plus button in
    front of them.

    Abstract rather than one table with two foreign keys: a line belongs to
    exactly one application of exactly one kind, and a shared table would need
    a nullable key per kind plus a constraint saying exactly one is set. It is
    also why extracting this does not touch applications_applicationitem - an
    abstract base leaves the columns exactly where they already are.

    The quantity floor is repeated as a constraint on each concrete model
    rather than declared here. A constraint on an abstract base needs a name
    template, and adopting one would rename the constraint
    applications_applicationitem already carries: a migration against live
    data to change nothing.
    """

    buyurtma_nomi = models.CharField("Buyurtma nomi", max_length=255)
    # Decimal rather than float: REQ-ARIZA-003 allows a fractional quantity,
    # and a quantity that is nearly 0.3 is not a quantity anybody ordered.
    #
    # The floor is on the column rather than on the form, because the rule is
    # about what an order line may be and not about what one page accepts.
    # The #33 review found the form's min attribute doing this job alone,
    # which meant a posted -5 was stored as an order for minus five bolts.
    # SMALLEST_QUANTITY excludes zero as well: an order for none of something
    # is not an order, it is a line somebody meant to delete.
    buyurtma_soni = models.DecimalField(
        "Buyurtma soni",
        max_digits=12,
        decimal_places=3,
        validators=[MinValueValidator(SMALLEST_QUANTITY)],
    )
    olchov_birligi = models.CharField(
        "O`lchov birligi",
        max_length=16,
        help_text=(
            "ta, kg, m and so on. Free text: REQ-ARIZA-003 gives examples and "
            "no page maintains a list of units."
        ),
    )

    class Meta:
        abstract = True

    @property
    def soni_display(self) -> Decimal:
        """The quantity without the trailing zeros the column stores.

        Three decimal places are stored because REQ-ARIZA-003 allows a
        fractional quantity, but rendering them always is actively
        misleading here: LANGUAGE_CODE is uz, so the decimal separator is a
        comma, and 2.500 prints as "2,500" - which reads as two and a half
        thousand rather than as two and a half.

        normalize() strips the zeros, and the quantize guards the other end:
        it turns Decimal("500").normalize(), which is 5E+2, back into 500.
        """
        quantity = self.buyurtma_soni.normalize()
        if quantity.as_tuple().exponent > 0:
            return quantity.quantize(Decimal(1))

        return quantity


class ApplicationItem(OrderLine):
    """One line of what an application orders (REQ-ARIZA-010).

    These four fields sat on Application until TASK-UZK-026, because until
    there was a form there was no way to enter a second line and one order per
    application was indistinguishable from the truth. The plus button is what
    separates them: a person adding a row means one application, several
    things ordered, and columns on the record cannot hold that.

    CASCADE rather than PROTECT, which is the opposite of how this module
    treats every other relation: a line is part of its application rather than
    a thing the application refers to, and an order line outliving the order
    is not a record worth keeping. The category it points at is PROTECTed as
    usual, because that is master data somebody else maintains.
    """

    application = models.ForeignKey(
        Application,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="Ariza",
    )
    mahsulot_turi = models.ForeignKey(
        "reference.MahsulotTuri",
        on_delete=models.PROTECT,
        related_name="application_items",
        verbose_name="Mahsulot Turi",
    )

    class Meta:
        # The order they were entered in, which is the order the person who
        # wrote the application meant them to be read.
        ordering = ("id",)
        verbose_name = "Ariza qatori"
        verbose_name_plural = "Ariza qatorlari"
        # The validator above is what a person filling in the form sees, and
        # it only runs when something calls full_clean(). raise_application()
        # does not - it bulk_creates - so the validator alone would leave the
        # #33 finding half fixed: refused on the page, accepted from code.
        # The constraint is the rule itself, held by the database on every
        # path into the table.
        constraints = (
            models.CheckConstraint(
                condition=models.Q(buyurtma_soni__gte=SMALLEST_QUANTITY),
                name="order_line_quantity_is_positive",
                violation_error_message=(
                    "Buyurtma soni noldan katta bo`lishi kerak."
                ),
            ),
        )

    def __str__(self) -> str:
        return f"{self.buyurtma_nomi} - {self.soni_display} {self.olchov_birligi}"


class PurchaseApplication(models.Model):
    """What a requester asks the purchasing department for (section 4.9).

    The other way in. DEC-016 describes two: Admin keying in an application
    that arrived on paper, which is Application and the section 4.2 form, and
    a Users requester submitting this. They are different records rather than
    one record with a flag - this one carries a contract title and a deadline,
    which the department's own application has no use for, and it has not
    entered the department's workflow yet. DEC-016's approval chain is what
    carries it there, and TASK-UZK-031 builds that.

    The department is not something the requester types. DEC-018 fills it from
    their own account, which is why there is no department field on the form
    and why a requester with no department cannot raise one at all.
    """

    class Stage(models.TextChoices):
        """Where in DEC-016's approval chain this request has got to.

        A code the workflow branches on, separate from the ArizaStatus name a
        person reads - the same split Application makes, and for the same
        reason: DEC-017 lets an administrator rename any status row.

        The order is the requirement. An application at AWAITING_DIREKTOR has
        been approved by the requester's own department head and by nobody
        else, and reaching that state any other way is the failure this chain
        exists to prevent.
        """

        AWAITING_HEAD = "awaiting_head", "Bo`lim boshlig`i tasdig`ini kutmoqda"
        AWAITING_DIREKTOR = "awaiting_direktor", "Direktor tasdig`ini kutmoqda"
        APPROVED = "approved", "Tasdiqlangan"
        REJECTED = "rejected", "Inkor etilgan"

    xarid_raqami = models.CharField(
        "Ariza raqami", max_length=32, unique=True
    )
    shartnoma_nomi = models.CharField(
        "Shartnoma nomi",
        max_length=255,
        help_text="What the purchase is for (REQ-ARIZA-015).",
    )
    department = models.ForeignKey(
        "reference.Department",
        on_delete=models.PROTECT,
        related_name="purchase_applications",
        verbose_name="Bo`lim nomi",
        help_text=(
            "Filled from the requester's own account (DEC-018), never typed."
        ),
    )
    muddat_talabi = models.DateField(
        "Muddat talabi",
        null=True,
        blank=True,
        help_text="When it is needed by (REQ-ARIZA-015).",
    )
    izoh = models.TextField("Izoh", blank=True)
    pdf = application_pdf_field()
    asl_pdf = models.FileField(
        "Asl ilova (PDF)",
        upload_to="arizalar/%Y/%m",
        storage=attachment_storage,
        blank=True,
        help_text=(
            "The attachment exactly as it was uploaded. Blank until an "
            "approval stamps pdf, and from then on it names the original "
            "file where it already sits - it points at that file rather than "
            "storing a second copy of it, which is why upload_to matches the "
            "path the upload used. The #46 review found this declaring a "
            "directory nothing ever writes to."
        ),
    )
    status = models.ForeignKey(
        "reference.ArizaStatus",
        on_delete=models.PROTECT,
        related_name="purchase_applications",
        null=True,
        blank=True,
        verbose_name="Xozirgi holati",
        help_text=(
            "Nullable for the reason Application.status is: DEC-017 lets an "
            "administrator delete every status, and a master data page must "
            "not be able to stop somebody raising a request."
        ),
    )
    created_by = models.ForeignKey(
        "auth.User",
        on_delete=models.PROTECT,
        related_name="purchase_applications",
        verbose_name="Yaratgan",
    )
    yaratilingan_sana = models.DateTimeField(
        "Yaratilingan sana", auto_now_add=True
    )
    stage = models.CharField(
        max_length=24, choices=Stage.choices, default=Stage.AWAITING_HEAD
    )
    tasdiqlagan_bolim_boshligi = models.ForeignKey(
        "auth.User",
        on_delete=models.PROTECT,
        related_name="purchase_applications_approved_as_head",
        null=True,
        blank=True,
        verbose_name="Tasdiqlagan bo`lim boshlig`i",
    )
    bolim_boshligi_sanasi = models.DateTimeField(
        "Bo`lim boshlig`i tasdiqlagan sana", null=True, blank=True
    )
    tasdiqlagan_direktor = models.ForeignKey(
        "auth.User",
        on_delete=models.PROTECT,
        related_name="purchase_applications_approved_as_direktor",
        null=True,
        blank=True,
        verbose_name="Tasdiqlagan direktor",
    )
    direktor_sanasi = models.DateTimeField(
        "Direktor tasdiqlagan sana", null=True, blank=True
    )
    inkor_izohi = models.TextField(
        "Inkor izohi",
        blank=True,
        help_text=(
            "Why it was refused. REQ-ARIZA-020 makes this the point of the "
            "action rather than a decoration on it: the requester is told "
            "why, so a rejection with no reason is not one reject() performs."
        ),
    )
    inkor_qilgan = models.ForeignKey(
        "auth.User",
        on_delete=models.PROTECT,
        related_name="purchase_applications_rejected",
        null=True,
        blank=True,
        verbose_name="Inkor qilgan",
    )
    inkor_sanasi = models.DateTimeField(
        "Inkor qilingan sana", null=True, blank=True
    )
    raised_application = models.OneToOneField(
        "applications.Application",
        on_delete=models.PROTECT,
        related_name="raised_from",
        null=True,
        blank=True,
        verbose_name="Yaratilgan ariza",
        help_text=(
            "The department's own application this request became when "
            "Direktor approved it (DEC-016). Null until then, and the only "
            "thing connecting a requester's record to the department's."
        ),
    )

    class Meta:
        # Newest first, like every other list here: a requester looks at what
        # they have just asked for, not at what they asked for last year.
        ordering = ("-yaratilingan_sana", "-id")
        verbose_name = "Xarid arizasi"
        verbose_name_plural = "Xarid arizalari"

    def __str__(self) -> str:
        return f"{self.xarid_raqami} - {self.shartnoma_nomi}"

    @property
    def contract(self) -> Contract | None:
        """The contract formed from this request, or None while there is none.

        Three hops, any of which can be missing, and each missing hop is an
        ordinary state rather than a fault: a request that has not been
        approved has raised no department application, and one that has may
        have no contract against it yet.

        The newest when there is more than one. REQ-SHARTNOMA-004 gives a
        contract one Ariza raqami and nothing forbids a second contract
        against the same application, so the ordering Contract already
        declares is what decides - written as a list rather than a slice, so
        that a page prefetching the contracts pays nothing here.
        """
        if self.raised_application_id is None:
            return None

        contracts = list(self.raised_application.contracts.all())

        return contracts[0] if contracts else None

    @property
    def status_follows_contract(self) -> bool:
        """Whether what this request shows comes from its contract.

        The page asks, so that it can say so. A status that silently changed
        from one table's word to another table's word would leave a requester
        with no way to tell why - and the two tables are independent, so the
        words need not even look related.
        """
        contract = self.contract

        return contract is not None and contract.status_id is not None

    @property
    def shown_status(self):
        """The state this request is currently in (REQ-ARIZA-017).

        Section 4.9 says the current status changes according to the
        contract's state, and the interesting part is what it does not say.
        UNKNOWN-005 asked which statuses exist and how they correspond, and
        DEC-010 answered the half it answered: they are editable master data
        and the document's examples are examples. It defines no mapping
        between an ArizaStatus and a ShartnomaStatus, and the two tables are
        extended independently by an administrator - so a translation table
        here would be a table invented in the code and invalidated by the next
        row somebody adds on either page.

        So the contract's status is shown as it is. That is the whole mapping,
        and status_follows_contract is how the page says which table the word
        came from.

        Derived rather than copied. A column kept in step by a hook is a
        column that is out of step the first time something writes around the
        hook - and this needs no column: the contract knows its status and the
        request knows its contract.

        The consequence is worth stating rather than discovering. The status
        column keeps saying what the request was raised as, so this page and
        anything counting the column give different answers for the same
        record - both correct, and different. DEC-010 has TASK-UZK-044 and
        TASK-UZK-045 generate one counter per active status and count records
        into them; a request whose page says Shartnoma tuzilgan is counted
        under Yangi unless those tasks decide otherwise. The review of #58
        asked for that to be written here, before the query is written rather
        than after somebody reports the disagreement as a fault.
        """
        if self.status_follows_contract:
            return self.contract.status

        return self.status

    @property
    def awaits_approval(self) -> bool:
        """Whether somebody still has to decide about this request."""
        return self.stage in (
            self.Stage.AWAITING_HEAD,
            self.Stage.AWAITING_DIREKTOR,
        )

    def awaits(self, user) -> bool:
        """Whether this request is waiting for this particular person.

        The whole of the authorisation question in one place, so the queue and
        the two actions cannot disagree about it. DEC-016 names the
        requester's own Bo`lim Boshlig`i and then Direktor - own being the
        part that matters, because a department head approving another
        department's spending is the thing the chain exists to prevent.
        """
        from accounts.roles import (
            BOLIM_BOSHLIGI,
            DIREKTOR,
            department_of,
            has_user_type,
        )

        if self.stage == self.Stage.AWAITING_HEAD:
            return (
                has_user_type(user, (BOLIM_BOSHLIGI,))
                and department_of(user) == self.department
            )

        if self.stage == self.Stage.AWAITING_DIREKTOR:
            return has_user_type(user, (DIREKTOR,))

        return False

    def moved_past(self, user) -> bool:
        """Whether this request has gone beyond the step this person decides.

        The #44 review asked for a stale button to be told rather than denied,
        and this is the line between the two. Past is not the same as not
        waiting: a request that has not yet reached somebody is out of order,
        and approving out of order is the failure the whole chain exists to
        prevent. A Direktor reaching for one still waiting for the department
        head is refused; a department head reaching for one that has already
        gone to Direktor is simply late.

        Decided counts as past for both of them, because there is nothing left
        to do either way.
        """
        from accounts.roles import (
            BOLIM_BOSHLIGI,
            DIREKTOR,
            department_of,
            has_user_type,
        )

        decided = (self.Stage.APPROVED, self.Stage.REJECTED)

        if (
            has_user_type(user, (BOLIM_BOSHLIGI,))
            and department_of(user) == self.department
        ):
            # Their step is the first one, so anything else is past it.
            return self.stage != self.Stage.AWAITING_HEAD

        if has_user_type(user, (DIREKTOR,)):
            # Their step is the second. Still waiting for the head is before
            # them, not behind them.
            return self.stage in decided

        return False

    @transaction.atomic
    def approve(self, by) -> bool:
        """Take this request one step along DEC-016's chain.

        One step, never two. The department head's approval moves it to
        Direktor and no further, and Direktor's approval is what creates the
        department's own application - the moment DEC-016 describes, when a
        request stops being one department asking and becomes work in the
        purchasing department's queue.

        Both records are written together or neither is. An approved request
        with nothing in the department's queue is a requester told their
        purchase is happening when nobody has been given it.

        Args:
            by: the approver. Must be the person this request is waiting for.

        Returns:
            True when this call moved it, False when somebody else already
            had - the second click of a double click.

        Raises:
            ValueError: when this request is not waiting for this person,
                which covers approving out of order as well as approving for
                somebody else's department.
        """
        self.refresh_from_db()

        if not self.awaits(by):
            raise ValueError(
                f"{self.xarid_raqami} is not waiting for {by} to approve it."
            )

        decided_at = timezone.now()
        was = self.stage

        if was == self.Stage.AWAITING_HEAD:
            moved = type(self).objects.filter(pk=self.pk, stage=was).update(
                stage=self.Stage.AWAITING_DIREKTOR,
                tasdiqlagan_bolim_boshligi=by,
                bolim_boshligi_sanasi=decided_at,
            )
            if not moved:
                self.refresh_from_db()
                return False

            self.stage = self.Stage.AWAITING_DIREKTOR
            self.tasdiqlagan_bolim_boshligi = by
            self.bolim_boshligi_sanasi = decided_at

            return True

        # Stamped before the department's application is created, so what
        # that record shares is the approved document rather than the one the
        # requester uploaded. Stamped before the stage is written too: this
        # raises rather than returning a failure, and an approval that
        # swallowed it would mark an application approved with an unstamped
        # document, which REQ-ARIZA-019 is precisely about.
        self.stamp_approval(by, decided_at)

        raised = self.raise_department_application()
        moved = type(self).objects.filter(pk=self.pk, stage=was).update(
            stage=self.Stage.APPROVED,
            tasdiqlagan_direktor=by,
            direktor_sanasi=decided_at,
            raised_application=raised,
        )
        if not moved:
            # Somebody else approved between the read and this write. The
            # application just created belongs to nothing, so it goes with the
            # decision that did not happen.
            raised.delete()
            self.refresh_from_db()
            return False

        self.stage = self.Stage.APPROVED
        self.tasdiqlagan_direktor = by
        self.direktor_sanasi = decided_at
        self.raised_application = raised

        return True

    def stamp_approval(self, by, approved_at) -> bool:
        """Put the approval onto the document (REQ-ARIZA-019, DEC-027).

        The original is kept in asl_pdf the first time this runs, because the
        stamp rewrites what the requester uploaded and that should still be
        producible.

        Args:
            by: the approving manager, whose name goes into the code.
            approved_at: when they approved it.

        Returns:
            True when a stamp was applied, and False when there was nothing to
            stamp. An application with no attachment is not refused over it:
            DEC-016 lets a paper application through the department's own
            form, and refusing an approval here would make the attachment
            compulsory somewhere nothing says it is.
        """
        from applications.stamping import approval_payload, stamp_with_qr

        if not self.pdf:
            return False

        payload = approval_payload(self.xarid_raqami, by, approved_at)
        stamped = stamp_with_qr(
            self.pdf, payload, f"{self.xarid_raqami}-tasdiqlangan.pdf"
        )

        if not self.asl_pdf:
            # Point at the same stored file rather than copying its bytes:
            # it is the file, and the stamped one is written beside it.
            self.asl_pdf.name = self.pdf.name

        self.pdf.save(stamped.name, stamped, save=False)
        type(self).objects.filter(pk=self.pk).update(
            pdf=self.pdf.name, asl_pdf=self.asl_pdf.name
        )

        return True

    def raise_department_application(self) -> Application:
        """Turn this request into the department's own application.

        What DEC-016 means by "and only then does it appear in the purchasing
        department head's Kelib tushgan Arizalar": the department's record is
        created at the incoming stage, which is what that list reads.

        Nothing in the specification says what the new record inherits. These
        are the fields both records have - the department, the lines, the
        comment and the attachment - and the requester becomes its sender,
        which is the column Application has carried since TASK-UZK-022 and
        has never had a value in.

        The attachment is shared rather than copied: both records name the
        same stored file, because it is the same document and copying it
        would make two that could drift. It is also why the race path in
        approve() can delete the application it just created without taking a
        file with it - the file was never that record's own. The #44 review
        asked for this to be written down rather than discovered.
        """
        return Application.raise_application(
            items=[
                {
                    "mahsulot_turi": line.mahsulot_turi,
                    "buyurtma_nomi": line.buyurtma_nomi,
                    "buyurtma_soni": line.buyurtma_soni,
                    "olchov_birligi": line.olchov_birligi,
                }
                for line in self.items.all()
            ],
            department=self.department,
            buyurtmachi_ismi=(
                self.created_by.get_full_name() or self.created_by.username
            ),
            izoh=self.izoh,
            pdf=self.pdf,
            sender=self.created_by,
        )

    @transaction.atomic
    def reject(self, by, comment: str) -> bool:
        """Refuse this request, with a reason (REQ-ARIZA-020).

        The comment is what the requester is told, so a refusal without one is
        not a refusal this method performs - the same rule Application.reject()
        holds, and here for the same reason.

        Args:
            by: the approver refusing it.
            comment: why. Stored with its surrounding whitespace stripped.

        Returns:
            True when this call refused it, False when it was already refused.

        Raises:
            ValueError: when the comment is empty or only whitespace, or when
                this request is not waiting for this person.
        """
        from applications.notifications import notify_requester_of_rejection
        from reference.models import ArizaStatus

        reason = (comment or "").strip()
        if not reason:
            raise ValueError(
                f"{self.xarid_raqami} cannot be refused without a comment."
            )

        self.refresh_from_db()

        if self.stage == self.Stage.REJECTED:
            return False

        if not self.awaits(by):
            raise ValueError(
                f"{self.xarid_raqami} is not waiting for {by} to decide it."
            )

        decided_at = timezone.now()
        refused = type(self).objects.filter(pk=self.pk, stage=self.stage).update(
            stage=self.Stage.REJECTED,
            inkor_izohi=reason,
            inkor_qilgan=by,
            inkor_sanasi=decided_at,
            # Cancelled, found by code rather than by name for the reason
            # Application.reject() gives at length.
            status=ArizaStatus.objects.filter(
                code=ArizaStatus.Code.CANCELLED, is_active=True
            ).first(),
        )

        if not refused:
            self.refresh_from_db()
            return False

        self.refresh_from_db()
        notify_requester_of_rejection(self)

        return True

    @classmethod
    @transaction.atomic
    def raise_purchase_application(
        cls, items: Sequence[Mapping[str, object]], **fields
    ) -> PurchaseApplication:
        """Create a purchase application and its order lines, in one write.

        The only way one should be created, for the reason
        Application.raise_application() gives: nothing should end up without a
        number, and a failure part way through the order should leave no
        request rather than one nobody can fill.

        Args:
            items: one mapping of PurchaseApplicationItem fields per line.
            **fields: the application's own columns.

        Returns:
            The created purchase application.

        Raises:
            ValueError: when items is empty.
        """
        if not items:
            raise ValueError(
                "A purchase application needs at least one order line "
                "(REQ-ARIZA-015)."
            )

        application = cls.objects.create(
            xarid_raqami=next_xarid_raqami(), **fields
        )
        PurchaseApplicationItem.objects.bulk_create(
            [
                PurchaseApplicationItem(application=application, **line)
                for line in items
            ]
        )

        return application


class PurchaseApplicationItem(OrderLine):
    """One line of what a purchase application asks for (REQ-ARIZA-015).

    The same four columns as ApplicationItem, from the same abstract base, and
    a separate table: a line belongs to one application of one kind.
    """

    application = models.ForeignKey(
        PurchaseApplication,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="Xarid arizasi",
    )
    mahsulot_turi = models.ForeignKey(
        "reference.MahsulotTuri",
        on_delete=models.PROTECT,
        related_name="purchase_application_items",
        verbose_name="Mahsulot Turi",
    )

    class Meta:
        ordering = ("id",)
        verbose_name = "Xarid arizasi qatori"
        verbose_name_plural = "Xarid arizasi qatorlari"
        # The same rule as ApplicationItem carries, named for this table. It
        # is repeated rather than declared on OrderLine because a constraint
        # on an abstract base needs a name template, and adopting one would
        # rename the constraint the other table already has.
        constraints = (
            models.CheckConstraint(
                condition=models.Q(buyurtma_soni__gte=SMALLEST_QUANTITY),
                name="purchase_order_line_quantity_is_positive",
                violation_error_message=(
                    "Buyurtma soni noldan katta bo`lishi kerak."
                ),
            ),
        )

    def __str__(self) -> str:
        return f"{self.buyurtma_nomi} - {self.soni_display} {self.olchov_birligi}"


class Contract(models.Model):
    """One contract, as section 4.6 describes it.

    The third record with a life cycle, and the one the reference module has
    been waiting for. Supplier (DEC-011), ShartnomaStatus (DEC-010) and
    ShartnomaTuri (DEC-023) were built by TASK-UZK-021, TASK-UZK-017 and
    TASK-UZK-019 and nothing has ever pointed at them - which means deleting
    one has been free until now, and is PROTECTed from here on.

    A contract fulfils one application. REQ-SHARTNOMA-004 gives a row one
    Ariza raqami, and what the department asked for is that application's
    order lines. What the supplier agreed to deliver, at what price, is a
    ContractItem: TASK-UZK-035 adds those, because a contract has a part
    number and a price per item and an application has neither.

    The stage is a code the workflow branches on, beside the ShartnomaStatus
    name a person reads and an administrator may rename - the same separation
    Application makes, and for the reason DEC-010 gives: the statuses are
    examples the department is expected to extend, so nothing may depend on
    one being there.
    """

    class Stage(models.TextChoices):
        """Where a contract has got to, in terms the code may rely on."""

        AGREED = "agreed", "Kelishinlingan"
        SENT = "sent", "Tasdiqlashga yuborilgan"
        SIGNED = "signed", "Tuzilgan"
        REJECTED = "rejected", "Inkor etilgan"

    shartnoma_raqami = models.CharField(
        "Shartnoma raqami", max_length=32, unique=True
    )
    application = models.ForeignKey(
        "applications.Application",
        on_delete=models.PROTECT,
        related_name="contracts",
        verbose_name="Ariza",
        help_text=(
            "The application this contract fulfils. PROTECT rather than "
            "CASCADE: a contract is an agreement with a supplier and deleting "
            "the request behind it should not take it with them."
        ),
    )
    supplier = models.ForeignKey(
        "reference.Supplier",
        on_delete=models.PROTECT,
        related_name="contracts",
        verbose_name="Firma nomi",
    )
    shartnoma_turi = models.ForeignKey(
        "reference.ShartnomaTuri",
        on_delete=models.PROTECT,
        related_name="contracts",
        null=True,
        blank=True,
        verbose_name="Shartnoma turi",
        help_text=(
            "DEC-023 draws this from master data. Nullable because "
            "REQ-SHARTNOMA-004 does not list it as a column and the "
            "TASK-UZK-035 entry form is what asks for it."
        ),
    )
    qiymati = models.DecimalField(
        "Shartnoma qiymati",
        max_digits=18,
        decimal_places=2,
        validators=[MinValueValidator(SMALLEST_PRICE)],
        help_text=(
            "In UZS (DEC-026). Eighteen digits because a contract in soums "
            "runs to billions, and two decimal places because money has them. "
            "Stored rather than summed on every read, because the lists and "
            "every later money report sort and total on it - and written by "
            "raise_contract() from the goods rows rather than supplied, "
            "because REQ-SHARTNOMA-006 makes it the total of everything."
        ),
    )
    status = models.ForeignKey(
        "reference.ShartnomaStatus",
        on_delete=models.PROTECT,
        related_name="contracts",
        null=True,
        blank=True,
        verbose_name="Holati",
        help_text=(
            "Nullable for the reason Application.status is: DEC-010 lets an "
            "administrator retire every status, and a master data page must "
            "not be able to stop a contract being recorded."
        ),
    )
    stage = models.CharField(
        max_length=16, choices=Stage.choices, default=Stage.AGREED
    )
    inkor_izohi = models.TextField(
        "Izoh (Inkor etilgan)",
        blank=True,
        help_text=(
            "Why it was refused, which REQ-SHARTNOMA-004 gives a column of "
            "its own. Empty until TASK-UZK-038 rejects one; the column is "
            "rendered from the start so that task has nowhere left to put it."
        ),
    )
    created_by = models.ForeignKey(
        "auth.User",
        on_delete=models.PROTECT,
        related_name="contracts",
        verbose_name="Kim shartnoma qilgan",
    )
    shartnoma_sanasi = models.DateField(
        "Shartnoma sanasi",
        null=True,
        blank=True,
        help_text=(
            "The date on the contract itself, which REQ-SHARTNOMA-006 lists "
            "beside Yaratilingan sana. Two fields because they are two facts: "
            "when the agreement is dated, and when somebody typed it in. "
            "Nullable because every contract that existed before the entry "
            "form predates the question."
        ),
    )
    tolash_muddati = models.DateField(
        "To`lash muddati",
        null=True,
        blank=True,
        help_text="When payment falls due (REQ-SHARTNOMA-006).",
    )
    muddat_talabi = models.DateField(
        "Muddat talabi",
        null=True,
        blank=True,
        help_text=(
            "The deadline the customer set (REQ-SHARTNOMA-006). Optional, as "
            "it is on the purchase application: nothing says a contract must "
            "carry one."
        ),
    )
    izoh = models.TextField("Izoh", blank=True)
    pdf = contract_pdf_field()
    yuborilgan_sana = models.DateTimeField(
        "Tasdiqlashga yuborilgan sana",
        null=True,
        blank=True,
        help_text=(
            "When this contract was last sent for approval. Overwritten by a "
            "resend rather than kept per attempt: DEC-024 makes a resend the "
            "same act again, and the history of the attempts belongs in the "
            "section 10 log TASK-UZK-052 builds."
        ),
    )
    yuborgan = models.ForeignKey(
        "auth.User",
        on_delete=models.PROTECT,
        related_name="sent_contracts",
        null=True,
        blank=True,
        verbose_name="Kim yuborgan",
    )
    tasdiqlagan = models.ForeignKey(
        "auth.User",
        on_delete=models.PROTECT,
        related_name="approved_contracts",
        null=True,
        blank=True,
        verbose_name="Kim tasdiqlagan",
    )
    tasdiqlangan_sana = models.DateTimeField(
        "Tasdiqlangan sana", null=True, blank=True
    )
    inkor_qilgan = models.ForeignKey(
        "auth.User",
        on_delete=models.PROTECT,
        related_name="rejected_contracts",
        null=True,
        blank=True,
        verbose_name="Kim inkor qilgan",
    )
    inkor_sanasi = models.DateTimeField(
        "Inkor qilingan sana", null=True, blank=True
    )
    yuborishlar_soni = models.PositiveIntegerField(
        "Necha marta yuborilgan",
        default=0,
        help_text=(
            "How many times this contract has gone for approval. The two "
            "columns above hold the last send and are overwritten by a "
            "resend, and the review of #60 pointed out that the log "
            "TASK-UZK-052 builds cannot recover what was never recorded - a "
            "contract rejected and resent three times before that task ships "
            "would show one send and no sign of the other two. How many times "
            "it came back is the question the department will actually ask, "
            "and a count answers it without building that log early."
        ),
    )
    yaratilingan_sana = models.DateTimeField(
        "Yaratilingan sana", auto_now_add=True
    )

    class Meta:
        ordering = ("-yaratilingan_sana", "-id")
        verbose_name = "Shartnoma"
        verbose_name_plural = "Shartnomalar"

    def __str__(self) -> str:
        return f"{self.shartnoma_raqami} - {self.supplier.name}"

    # Which page shows a contract at each stage. On the model rather than in
    # the views because two readers ask and one of them is a template: the
    # download view asks so an attachment stops being reachable when the row
    # stops being visible, and the Xarid Arizasi row asks so it does not print
    # a contract number to somebody who may not open a contract page at all.
    #
    # TASK-UZK-038 is what moves a contract from the first page to the second.
    PAGE_SHOWING_STAGE: dict[str, str] = {
        "agreed": "kelishinlingan",
        "rejected": "kelishinlingan",
        "sent": "tuzilgan",
        "signed": "tuzilgan",
    }

    @property
    def page_showing(self) -> str | None:
        """The page this contract is currently on, or None when no page is.

        None is a real answer rather than an error: a stage no page shows is a
        contract nobody can reach, and a caller has to decide what that means
        rather than be handed a page name that does not apply.
        """
        return self.PAGE_SHOWING_STAGE.get(self.stage)

    @property
    def is_rejected(self) -> bool:
        """Whether this contract was refused."""
        return self.stage == self.Stage.REJECTED

    @property
    def is_sent(self) -> bool:
        """Whether this contract is with the department head."""
        return self.stage == self.Stage.SENT

    @property
    def send_label(self) -> str:
        """What the send control reads (DEC-024).

        The decision settles UNKNOWN-028: the document names Re-Send and then
        says the Send button appears, which describes two different things.
        Re-Send after a rejection, and the wording is decided here rather than
        in the template, because it is a rule from a decision rather than a
        choice of words.
        """
        return "Re-Send" if self.is_rejected else "Yuborish"

    @property
    def awaits_approval(self) -> bool:
        """Whether the department head still has to decide on this."""
        return self.stage == self.Stage.SENT

    @property
    def is_signed(self) -> bool:
        """Whether the department head approved this contract."""
        return self.stage == self.Stage.SIGNED

    @transaction.atomic
    def accept(self, by) -> bool:
        """Approve this contract (REQ-SHARTNOMA-002).

        The department head's half of the send. REQ-SHARTNOMA-002 says an
        accepted contract is sent to the next department, and DEC-028 says
        there is no such department: nothing is built for it, the contract
        continues through the status chain TASK-UZK-037 gave it, and the gap
        stays visible rather than being filled with an invented integration.

        The status is not moved here either. DEC-028 has the contract continue
        through its chain, and TASK-UZK-037 made that chain something a person
        chooses rather than a consequence of somebody else's decision.

        Args:
            by: the user approving it, recorded as the decider.

        Returns:
            True when this call approved it, False when it was already
            approved - the second click of a double click.

        Raises:
            ValueError: when the contract is not awaiting approval. A contract
                still with its specialist has not been offered to anybody, and
                a rejected one has been decided already.
        """
        self.refresh_from_db()

        if self.is_signed:
            return False

        if not self.awaits_approval:
            raise ValueError(
                f"{self.shartnoma_raqami} is {self.stage}, not awaiting "
                "approval, so there is nothing to approve."
            )

        decided_at = timezone.now()

        # The condition is part of the write, for the reason
        # Application.accept() gives at length: a check followed by an
        # unconditional save lets the loser of a race overwrite the winner.
        approved = type(self).objects.filter(
            pk=self.pk, stage=self.Stage.SENT
        ).update(
            stage=self.Stage.SIGNED,
            tasdiqlagan=by,
            tasdiqlangan_sana=decided_at,
        )
        if not approved:
            self.refresh_from_db()
            return False

        self.stage = self.Stage.SIGNED
        self.tasdiqlagan = by
        self.tasdiqlangan_sana = decided_at

        return True

    @transaction.atomic
    def reject(self, by, comment: str) -> bool:
        """Send this contract back to its specialist, with a reason.

        REQ-SHARTNOMA-002 makes the comment the point of the action rather
        than a decoration on it - the specialist is told why - so a rejection
        with no reason is not a rejection this method will perform. The check
        is here and not only in the page, because the reason has to exist
        wherever the rejection is made from. Application.reject() holds the
        same rule for the same requirement one section earlier.

        Where it lands matters as much as that it lands. The rejected stage is
        on the Kelishinlingan page, which renders the comment in the column
        REQ-SHARTNOMA-004 gives it and offers the Re-Send control DEC-024
        names - so "the data is returned back" is a contract the specialist
        finds where they left it.

        Args:
            by: the user rejecting it, recorded as the decider.
            comment: why. Stored with its surrounding whitespace stripped.

        Returns:
            True when this call rejected it, False when it was already
            rejected.

        Raises:
            ValueError: when the comment is empty or only whitespace, or when
                the contract is not awaiting approval. Both leave the record
                exactly as it was.
        """
        reason = (comment or "").strip()
        if not reason:
            raise ValueError(
                f"{self.shartnoma_raqami} cannot be rejected without a "
                "comment."
            )

        self.refresh_from_db()

        if self.is_rejected:
            return False

        if not self.awaits_approval:
            raise ValueError(
                f"{self.shartnoma_raqami} is {self.stage}, not awaiting "
                "approval, so there is nothing to reject."
            )

        decided_at = timezone.now()

        rejected = type(self).objects.filter(
            pk=self.pk, stage=self.Stage.SENT
        ).update(
            stage=self.Stage.REJECTED,
            inkor_izohi=reason,
            inkor_qilgan=by,
            inkor_sanasi=decided_at,
        )
        if not rejected:
            self.refresh_from_db()
            return False

        self.stage = self.Stage.REJECTED
        self.inkor_izohi = reason
        self.inkor_qilgan = by
        self.inkor_sanasi = decided_at

        return True

    @transaction.atomic
    def send_for_approval(self, by) -> bool:
        """Submit this contract to the department head (REQ-SHARTNOMA-005).

        The move out of the specialist's hands. A contract at the agreed stage
        has not been anywhere; a rejected one is coming back for a second
        time, which DEC-024 describes and which is the same act rather than a
        different one.

        The rejection comment is not cleared. REQ-SHARTNOMA-004 gives it a
        column, and the approver about to look at this contract again is the
        person most helped by seeing why it came back. DEC-024 says nothing
        either way, so the comment stays and the stage is what says the
        contract has moved on.

        Args:
            by: the user sending it, recorded against the send.

        Returns:
            True when this call sent it, False when somebody else sent it
            between the read and the write.

        Raises:
            ValueError: when the contract is not at a stage its specialist
                still holds - which is what a second send is, because the
                first one moved it.
        """
        self.refresh_from_db()

        if not self.is_editable:
            raise ValueError(
                f"{self.shartnoma_raqami} is {self.stage}, so there is "
                "nothing to send."
            )

        sent_at = timezone.now()

        # Conditional on the stage, for the reason set_status() gives: two
        # clicks landing together should send one contract once.
        moved = type(self).objects.filter(
            pk=self.pk, stage__in=self.EDITABLE_STAGES
        ).update(
            stage=self.Stage.SENT,
            yuborilgan_sana=sent_at,
            yuborgan=by,
            yuborishlar_soni=models.F("yuborishlar_soni") + 1,
        )
        if not moved:
            self.refresh_from_db()
            return False

        self.stage = self.Stage.SENT
        self.yuborilgan_sana = sent_at
        self.yuborgan = by
        self.yuborishlar_soni += 1

        return True

    @property
    def qiymati_display(self) -> str:
        """The contract value, grouped so a person can read it.

        One implementation for every amount on a contract page, in
        money_display: a contract's value is the sum of its line totals, and a
        page that renders the parts one way and the whole another invites
        somebody to check the arithmetic and find it wrong.
        """
        return money_display(self.qiymati)

    @classmethod
    @transaction.atomic
    def raise_contract(
        cls, items: Sequence[Mapping[str, object]], **fields
    ) -> Contract:
        """Create a contract and its goods rows, in one transaction.

        The only way one should be created, for the reason the other two
        records give: nothing should end up without a number, and the
        allocation belongs in the same transaction as the insert.

        The contract value is not a field a caller passes. REQ-SHARTNOMA-006
        defines it as the total price for everything, so it is computed from
        the rows here - and the lines are built before the contract, so the
        total is known at the insert rather than written and then corrected.

        Args:
            items: one mapping of ContractItem fields per row of goods, in the
                order they should be read. REQ-SHARTNOMA-007's plus button is
                what produces more than one.
            **fields: the contract's own columns, without qiymati.

        Returns:
            The created contract. Its lines are written but not fetched; read
            them through .items.

        Raises:
            ValueError: when items is empty, when qiymati is passed, or when
                no document is attached. A contract with nothing on it has no
                value to have; a caller supplying a value would be a caller
                able to disagree with the rows; and REQ-SHARTNOMA-003 makes
                the attachment a rule about the contract rather than about the
                form, so the rule is here as well as there.
        """
        if not fields.get("pdf"):
            raise ValueError(
                "A contract carries its PDF (REQ-SHARTNOMA-003, DEC-019)."
            )

        if "qiymati" in fields:
            raise ValueError(
                "A contract value is the sum of its rows "
                "(REQ-SHARTNOMA-006), not a field a caller sets."
            )

        if not items:
            raise ValueError(
                "A contract needs at least one row of goods "
                "(REQ-SHARTNOMA-007)."
            )

        lines = [ContractItem(**line) for line in items]
        contract = cls.objects.create(
            shartnoma_raqami=next_shartnoma_raqami(),
            qiymati=contract_value_of(lines),
            **fields,
        )
        for line in lines:
            line.contract = contract
        ContractItem.objects.bulk_create(lines)

        return contract

    @property
    def last_status_change(self) -> ContractStatusChange | None:
        """The most recent move, or None while there has been none.

        Reads the whole list rather than slicing it, so a page that
        prefetched status_changes pays nothing here: a queryset sliced in a
        property is a query per row, which is the cost the review of #38
        found on a list page.
        """
        changes = list(self.status_changes.all())

        return changes[0] if changes else None

    # The stages at which a contract's terms may still be changed. DEC-024
    # describes correcting a rejected contract and resending it, and an agreed
    # one has not gone anywhere yet. A contract awaiting somebody's approval,
    # or already approved, having its rows or its price rewritten is not
    # something the document describes.
    #
    # On the model, because three callers ask: the edit form, the send and the
    # template. The review of #56 found the first of them with a copy of its
    # own in the views.
    EDITABLE_STAGES = (Stage.AGREED, Stage.REJECTED)

    # The stages at which its state may still be reported, which is a
    # different question and was the same one until the review of #62.
    #
    # REQ-ROLE-008 has the specialist keep changing a contract's status for
    # the life of the agreement, and DEC-010 seeds Yetkazib berilgan - a
    # contract is delivered after it is signed, not before. Sharing
    # EDITABLE_STAGES meant approving a contract froze its status forever, so
    # the seeded status for delivery could never be reached and DEC-028's
    # "continues through its status chain" was impossible. Nothing noticed
    # because until TASK-UZK-039 nothing wrote SIGNED.
    #
    # SENT is the stage that refuses: a contract awaiting a decision must not
    # change underneath the person making it.
    MOVABLE_STAGES = (Stage.AGREED, Stage.REJECTED, Stage.SIGNED)

    @property
    def is_editable(self) -> bool:
        """Whether this contract's terms may still be changed."""
        return self.stage in self.EDITABLE_STAGES

    @property
    def status_may_move(self) -> bool:
        """Whether this contract's state may still be reported.

        Not the same question as is_editable, although it was until the review
        of #62: a signed contract's terms are settled and its progress is not.
        """
        return self.stage in self.MOVABLE_STAGES

    @transaction.atomic
    def set_status(self, status, by) -> bool:
        """Move this contract to a status (REQ-ROLE-008, REQ-SHTSTATUS-001).

        What "permitted" means here is worth stating, because the obvious
        reading is not available. DEC-010 makes the statuses rows an
        administrator invents and extends, and ShartnomaStatus carries no code
        column - deliberately, unlike ArizaStatus - so no code here can name a
        particular status, let alone draw a graph between them. A transition
        table over names would be a table the master data page could
        invalidate, which is the thing DEC-010 exists to prevent.

        So what is enforced is what the data can say: the status has to be one
        that is in use, the contract has to be one whose progress is still
        being reported, and moving to the status it already has is not a move.
        The ordering the department works to is recorded as an open point
        rather than invented here.

        "Still being reported" is MOVABLE_STAGES rather than EDITABLE_STAGES,
        which the review of #62 separated: a signed contract's terms are
        settled and its progress is not, and DEC-010 seeds a status for
        delivery, which happens after signing.

        Every move writes a ContractStatusChange in this transaction, so a
        contract cannot arrive at a status with no record of how.

        Args:
            status: the ShartnomaStatus to move to. Must be active.
            by: the user making the move, recorded against it.

        Returns:
            True when this call moved it, False when it was already there -
            the second click of a double click, which writes no history.

        Raises:
            ValueError: when status is None, when it is not active, or when
                the contract has left the page its specialist works on.
                Choosing nothing is not a way of clearing a status, an
                inactive row is one an administrator has taken out of use,
                and a contract awaiting approval is not one to move.
        """
        if status is None:
            raise ValueError(
                f"{self.shartnoma_raqami} needs a status to be moved to."
            )

        if not status.is_active:
            raise ValueError(
                f"{status.name} is not in use, so {self.shartnoma_raqami} "
                "cannot be moved to it."
            )

        self.refresh_from_db()

        if not self.status_may_move:
            raise ValueError(
                f"{self.shartnoma_raqami} is {self.stage}, so its status is "
                "not its specialist's to change."
            )

        if self.status_id == status.pk:
            return False

        was = self.status_id

        # Conditional on the status it is moving from, so two clicks landing
        # together produce one move and one history row rather than two of
        # each - the guard accept_as_specialist() carries, on a table whose
        # whole purpose is to answer when a contract passed a status. The
        # check above is the cheap answer for an ordinary second click; this
        # is the one that holds when both arrive at once.
        moved = type(self).objects.filter(pk=self.pk, status_id=was).update(
            status=status
        )
        if not moved:
            self.refresh_from_db()
            return False

        ContractStatusChange.objects.create(
            contract=self,
            from_status_id=was,
            to_status=status,
            changed_by=by,
        )
        self.status = status

        return True

    @transaction.atomic
    def revise(self, items: Sequence[Mapping[str, object]], **fields) -> None:
        """Replace this contract's rows and header (REQ-SHARTNOMA-005).

        The rows are replaced rather than matched up, because the entry form
        sends what the contract should now consist of rather than a list of
        edits. What that costs is the rows' identity, and nothing has one: a
        ContractItem is read through its contract and never referred to from
        anywhere else.

        The value is recomputed here rather than by the caller, which is the
        point of the method. An edit that rewrote the rows and left qiymati
        alone would leave a contract whose total disagreed with what is on
        it, and no view should be able to forget that.

        Args:
            items: one mapping of ContractItem fields per row, as
                raise_contract() takes them.
            **fields: the contract's own columns, without qiymati.

        Raises:
            ValueError: for the same three reasons raise_contract() refuses -
                no rows, a supplied value, or no document.
            TypeError: when a keyword is not a column on this model.
                raise_contract() goes through objects.create(), which raises
                for a misspelled field before anything is written; this used
                to set the attribute, save, and lose it in silence. The review
                of #54 asked for the two halves of one rule to fail the same
                way.
        """
        columns = {field.name for field in self._meta.concrete_fields}
        unknown = sorted(set(fields) - columns)
        if unknown:
            raise TypeError(
                f"Contract has no column {', '.join(unknown)}."
            )

        if "qiymati" in fields:
            raise ValueError(
                "A contract value is the sum of its rows "
                "(REQ-SHARTNOMA-006), not a field a caller sets."
            )

        if not items:
            raise ValueError(
                "A contract needs at least one row of goods "
                "(REQ-SHARTNOMA-007)."
            )

        # The document may be left alone by an edit, so this asks what the
        # contract will have rather than what the caller passed.
        if not fields.get("pdf", self.pdf):
            raise ValueError(
                "A contract carries its PDF (REQ-SHARTNOMA-003, DEC-019)."
            )

        for name, value in fields.items():
            setattr(self, name, value)

        self.items.all().delete()
        lines = [ContractItem(contract=self, **line) for line in items]
        ContractItem.objects.bulk_create(lines)

        self.qiymati = contract_value_of(lines)
        self.save()


def contract_value_of(lines: Iterable[ContractItem]) -> Decimal:
    """What everything on a contract comes to (REQ-SHARTNOMA-006).

    Takes the lines rather than the contract, so that the entry form can total
    rows nobody has saved yet and raise_contract() can total the same rows a
    moment before the contract they belong to exists. A version reading
    contract.items would only work on the second of those.
    """
    return sum((line.umumiy_narx for line in lines), Decimal("0")).quantize(
        SOUM, rounding=ROUND_HALF_UP
    )


class ContractStatusChange(models.Model):
    """One move of a contract from one status to another (REQ-ROLE-010).

    The first history table in the application. Everything else here keeps
    the current state and nothing else - an application's status is a column
    that gets overwritten - because DEC-024 puts the history in the section 10
    log and TASK-UZK-052 builds that.

    This one is not waiting for it. REQ-ROLE-008 has the specialist keep
    changing a contract's state and REQ-ROLE-010 says the same thing again,
    and "keeps changing" is a sequence: a contract that is at Yetkazib
    berilgan with no record of when it passed Shartnoma tuzilgan cannot
    answer the question the department is actually asking. When TASK-UZK-052
    builds the general log, this is what it reads for contracts rather than
    something it replaces.
    """

    contract = models.ForeignKey(
        Contract,
        on_delete=models.CASCADE,
        related_name="status_changes",
        verbose_name="Shartnoma",
    )
    from_status = models.ForeignKey(
        "reference.ShartnomaStatus",
        on_delete=models.PROTECT,
        related_name="moves_away",
        null=True,
        blank=True,
        verbose_name="Oldingi holat",
        help_text=(
            "Null for the first move. Contract.status is nullable because "
            "DEC-010 lets an administrator retire every status, so a contract "
            "can be entered with none - and the move away from nothing is the "
            "one most worth recording, not the one to refuse."
        ),
    )
    to_status = models.ForeignKey(
        "reference.ShartnomaStatus",
        on_delete=models.PROTECT,
        related_name="moves_here",
        verbose_name="Yangi holat",
    )
    changed_by = models.ForeignKey(
        "auth.User",
        on_delete=models.PROTECT,
        related_name="contract_status_changes",
        verbose_name="Kim o`zgartirgan",
    )
    changed_at = models.DateTimeField("O`zgartirilgan sana", auto_now_add=True)

    class Meta:
        # Newest first, so contract.status_changes.first() is the last move -
        # which is what the page shows beside the drop-down.
        ordering = ("-changed_at", "-id")
        verbose_name = "Shartnoma holati o`zgarishi"
        verbose_name_plural = "Shartnoma holati o`zgarishlari"

    def __str__(self) -> str:
        was = self.from_status.name if self.from_status_id else "-"

        return f"{self.contract.shartnoma_raqami}: {was} -> {self.to_status}"


class ContractItem(OrderLine):
    """One row of goods a contract covers (REQ-SHARTNOMA-006).

    The first order line in the application that carries a price, which is the
    whole reason it is not an ApplicationItem. An application says what the
    department wants; a contract says what a supplier agreed to deliver, under
    which part number and for how much. The first three columns are the same
    question asked twice, so they come from OrderLine; the last two are what
    makes this a contract rather than a request.

    CASCADE for the reason ApplicationItem gives: a line is part of its
    contract rather than something the contract refers to.

    There is no Mahsulot Turi here, and the review of #52 asked for the
    consequence to be written where the task that meets it will read it: these
    are the only priced rows in the application, and they are not categorised.
    TASK-UZK-046 reports purchases by category and TASK-UZK-047 by product, and
    neither can reach a price through ApplicationItem, which has a category and
    no money. The column is absent because REQ-SHARTNOMA-006 does not put one
    on the contract form, so adding it here would be inventing it; those tasks
    have to either reach the category through the contract's application or ask
    the customer for one on this row.
    """

    contract = models.ForeignKey(
        Contract,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="Shartnoma",
    )
    part_number = models.CharField(
        "Part Number",
        max_length=64,
        blank=True,
        help_text=(
            "The supplier's own code for this item. Free text and optional: "
            "REQ-SHARTNOMA-006 gives it a plain input, and not every firm "
            "catalogues what it sells."
        ),
    )
    narxi = models.DecimalField(
        "Narxi",
        max_digits=18,
        decimal_places=2,
        validators=[MinValueValidator(SMALLEST_PRICE)],
        help_text=(
            "The price of one, in UZS (DEC-026). The floor is on the column "
            "as well as on the form, which is what the review of #33 settled "
            "about order quantities: a rule on a form is a rule on one page."
        ),
    )

    class Meta:
        # The order they were entered in, which is the order the person who
        # agreed the contract meant them to be read.
        ordering = ("id",)
        verbose_name = "Shartnoma qatori"
        verbose_name_plural = "Shartnoma qatorlari"
        constraints = (
            models.CheckConstraint(
                condition=models.Q(buyurtma_soni__gte=SMALLEST_QUANTITY),
                name="contract_line_quantity_is_positive",
                violation_error_message="Miqdori noldan katta bo`lishi kerak.",
            ),
            models.CheckConstraint(
                condition=models.Q(narxi__gte=SMALLEST_PRICE),
                name="contract_line_price_is_positive",
                violation_error_message="Narxi noldan katta bo`lishi kerak.",
            ),
        )

    def __str__(self) -> str:
        return f"{self.buyurtma_nomi} - {self.umumiy_narx_display}"

    @property
    def umumiy_narx(self) -> Decimal:
        """Umumiy Narx: the price of one times how many (REQ-SHARTNOMA-006).

        Rounded to the soum rather than left as it falls out. A quantity has
        three decimal places and a price has two, so the product has five, and
        a total carried at five would make the contract value disagree with
        the rows a person can add up on the page.
        """
        return (self.narxi * self.buyurtma_soni).quantize(
            SOUM, rounding=ROUND_HALF_UP
        )

    @property
    def umumiy_narx_display(self) -> str:
        """The line total, grouped the way the contract value is."""
        return money_display(self.umumiy_narx)

    @property
    def narxi_display(self) -> str:
        """The unit price, grouped the way the line total is."""
        return money_display(self.narxi)
