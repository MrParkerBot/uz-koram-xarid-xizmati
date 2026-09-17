"""The contract agreed against an application (section 4.6).

The third record with a life cycle, and the first that carries money: a
contract's value is the total of the rows it covers, which is why the rounding
and the grouping an amount is read with are settled here.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.core.validators import MinValueValidator
from django.db import models, transaction

from applications.models.application import (
    SMALLEST_QUANTITY,
    OrderLine,
    next_number,
)

# DEC-022 names this one outright: SHT-2026-00001, the contract sequence.
CONTRACT_NUMBER_PREFIX = "SHT"


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


def next_shartnoma_raqami(today: date | None = None) -> str:
    """The next contract number for this year (DEC-022).

    Its own sequence, like the other two. DEC-022 names this one explicitly,
    which the purchase application's does not have and had to be inferred.
    """
    return next_number(
        CONTRACT_NUMBER_PREFIX, Contract, "shartnoma_raqami", today
    )


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
    yaratilingan_sana = models.DateTimeField(
        "Yaratilingan sana", auto_now_add=True
    )

    class Meta:
        ordering = ("-yaratilingan_sana", "-id")
        verbose_name = "Shartnoma"
        verbose_name_plural = "Shartnomalar"

    def __str__(self) -> str:
        return f"{self.shartnoma_raqami} - {self.supplier.name}"

    @property
    def is_rejected(self) -> bool:
        """Whether this contract was refused."""
        return self.stage == self.Stage.REJECTED

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
            ValueError: when items is empty, or when qiymati is passed. A
                contract with nothing on it has no value to have, and a caller
                supplying one would be a caller able to disagree with the rows.
        """
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
