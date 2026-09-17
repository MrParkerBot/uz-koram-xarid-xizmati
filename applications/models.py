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

from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.utils import timezone

from applications.attachments import application_pdf_field

# DEC-022: ARZ-2026-00001, five digits, resetting each year.
ARIZA_NUMBER_PREFIX = "ARZ"
ARIZA_NUMBER_DIGITS = 5

# The section 4.9 purchase application. DEC-022 names the ARZ and SHT
# sequences and is silent about this one; XA is what the approved prototype
# shows, and it takes the same shape so all three read alike.
XARID_NUMBER_PREFIX = "XA"

# The smallest order anybody can place: one thousandth, which is the finest
# the quantity column stores. Written as the smallest storable amount rather
# than as zero, so that the floor moves with decimal_places if that ever
# changes, and so that an order for none of something is refused too.
SMALLEST_QUANTITY = Decimal("0.001")


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

    class Meta:
        # Newest first, like every other list here: a requester looks at what
        # they have just asked for, not at what they asked for last year.
        ordering = ("-yaratilingan_sana", "-id")
        verbose_name = "Xarid arizasi"
        verbose_name_plural = "Xarid arizalari"

    def __str__(self) -> str:
        return f"{self.xarid_raqami} - {self.shartnoma_nomi}"

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
