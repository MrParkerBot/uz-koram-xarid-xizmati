"""What a requester asks the purchasing department for (section 4.9).

The other way in. DEC-016's chain of approvals decides it, and a fully
approved request raises the department's own application - which is where this
module hands the record back to application.py.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date

from django.db import models, transaction
from django.utils import timezone

from applications.attachments import application_pdf_field, attachment_storage
from applications.models.application import (
    SMALLEST_QUANTITY,
    Application,
    OrderLine,
    next_number,
)

# The section 4.9 purchase application. DEC-022 names the ARZ and SHT
# sequences and is silent about this one; XA is what the approved prototype
# shows, and it takes the same shape so all three read alike.
XARID_NUMBER_PREFIX = "XA"


def next_xarid_raqami(today: date | None = None) -> str:
    """The next purchase application number for this year.

    Its own sequence, independent of the ARZ one: the two are different
    records, and a shared counter would make either one's numbering depend on
    how busy the other had been.
    """
    return next_number(
        XARID_NUMBER_PREFIX, PurchaseApplication, "xarid_raqami", today
    )


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
