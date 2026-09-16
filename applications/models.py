"""The work the department does, rather than the lists that describe it.

accounts holds facts about people and reference holds the maintainable lists.
An application is neither: it is a record with a life cycle, and it is the
first thing here that has one.

TASK-UZK-022 builds the record and the incoming list; TASK-UZK-023 to
TASK-UZK-027 move it through the stages that follow.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.db import models, transaction

from applications.attachments import application_pdf_field

# DEC-022: ARZ-2026-00001, five digits, resetting each year.
ARIZA_NUMBER_PREFIX = "ARZ"
ARIZA_NUMBER_DIGITS = 5


def next_ariza_raqami(today: date | None = None) -> str:
    """The next application number for this year (DEC-022).

    The sequence restarts annually, so the number is allocated by looking at
    what this year already has rather than by a global counter. That read
    takes no lock, so two transactions running at once can see the same
    highest number and build the same candidate; being inside one transaction
    with the save does not prevent it. The unique column is what does - the
    second writer gets an IntegrityError rather than a duplicate number,
    which is the right way round, and a caller that expects to survive a
    collision has to retry.

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
    mahsulot_turi = models.ForeignKey(
        "reference.MahsulotTuri",
        on_delete=models.PROTECT,
        related_name="applications",
        verbose_name="Mahsulot Turi",
    )
    buyurtma_nomi = models.CharField("Buyurtma nomi", max_length=255)
    # Decimal rather than float: REQ-ARIZA-003 allows a fractional quantity,
    # and a quantity that is nearly 0.3 is not a quantity anybody ordered.
    buyurtma_soni = models.DecimalField(
        "Buyurtma soni", max_digits=12, decimal_places=3
    )
    olchov_birligi = models.CharField(
        "O`lchov birligi",
        max_length=16,
        help_text=(
            "ta, kg, m and so on. Free text: REQ-ARIZA-003 gives examples and "
            "no page maintains a list of units."
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
    kelib_tushgan_sana = models.DateTimeField(
        "Kelib tushgan sana", auto_now_add=True
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
        return f"{self.ariza_raqami} - {self.buyurtma_nomi}"

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

    @classmethod
    @transaction.atomic
    def raise_application(cls, **fields) -> Application:
        """Create an application, allocating its DEC-022 number.

        The only way an application should be created, so that nothing ends up
        without a number. Atomic with the number lookup, so two callers at once
        cannot read the same highest number and both use it.
        """
        return cls.objects.create(
            ariza_raqami=next_ariza_raqami(), **fields
        )
