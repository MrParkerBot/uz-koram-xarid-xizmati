"""The Firmalar master data page (DEC-011).

The second page the specification does not describe, after the departments
page of TASK-UZK-020, and for the same kind of reason: the dashboard counts
suppliers and ranks the top ones, and the contract form types the firm's name
into every contract, so without a table there is nothing to count.

The INN needs the same treatment the Mahsulot Turlari category number got in
TASK-UZK-018: it is a second unique column, and left to Django a clash would
say the same sentence whether the firm holding it is on the page or was
deleted from it.
"""

from __future__ import annotations

from accounts.master_data import (
    MasterDataForm,
    MasterDataPage,
    category_number_field,
)
from reference.models import Supplier


class SupplierForm(MasterDataForm):
    """Capture one supplier."""

    INN_ALREADY_USED = "Bu INN allaqachon ro`yhatda bor."
    INN_HELD_BY_DELETED_RECORD = (
        "Bu INN o'chirilgan firmaga tegishli. Boshqa INN kiriting."
    )

    category_number = category_number_field()

    class Meta:
        model = Supplier
        fields = ("name", "inn", "daraja", "category_number")

    def clean_inn(self) -> str:
        """Refuse an INN already taken, and say which kind of clash it is.

        An empty INN is not a clash: DEC-023 seeds an Import contract type, so
        foreign suppliers are expected and the supplied form leaves the field
        optional. Several firms may have none.
        """
        inn = self.cleaned_data["inn"]
        if not inn:
            return inn

        return self.refuse_a_clash(
            inn,
            lookup="inn",
            already_used=self.INN_ALREADY_USED,
            held_by_deleted_record=self.INN_HELD_BY_DELETED_RECORD,
        )


supplier_page = MasterDataPage(
    model=Supplier,
    form_class=SupplierForm,
    template_name="pages/firmalar.html",
    url_name="firmalar",
    context_object_name="suppliers",
)
