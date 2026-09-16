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

# The smallest order anybody can place: one thousandth, which is the finest
# the quantity column stores. Written as the smallest storable amount rather
# than as zero, so that the floor moves with decimal_places if that ever
# changes, and so that an order for none of something is refused too.
SMALLEST_QUANTITY = Decimal("0.001")


def next_ariza_raqami(today: date | None = None) -> str:
    """The next application number for this year (DEC-022).

    The sequence restarts annually, so the number is allocated by looking at
    what this year already has rather than by a global counter. Called inside
    the same transaction as the save, so two applications created at once
    cannot be handed the same number - and the unique column is what makes
    that a failure rather than a duplicate if they somehow are.

    The highest number is found by sorting as text, which is correct only
    because the sequence is zero-padded to a fixed width: ARZ-2026-00009 sorts
    below ARZ-2026-00010. It would stop being correct if a year ever needed a
    sixth digit, because ARZ-2026-100000 sorts below ARZ-2026-99999 and the
    number allocated next would already be taken. The unique column turns that
    into an error rather than a duplicate, and a department raising a hundred
    thousand applications a year is not this one - but the constraint is
    invisible otherwise, so it is written down here.
    """
    year = (today or date.today()).year
    prefix = f"{ARIZA_NUMBER_PREFIX}-{year}-"

    highest = (
        Application.objects.filter(ariza_raqami__startswith=prefix)
        .order_by("-ariza_raqami")
        .values_list("ariza_raqami", flat=True)
        .first()
    )
    used = int(highest.removeprefix(prefix)) if highest else 0

    return f"{prefix}{used + 1:0{ARIZA_NUMBER_DIGITS}d}"


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


class ApplicationItem(models.Model):
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
