"""The Mahsulot Turlari master data page (section 3.6).

The third page built out of MasterDataPage and the first whose fields are not
the two status tables' fields: a required six-digit code, a name and a
description, with no badge colour and no ordering position.

That it needed nothing added to MasterDataPage is the useful fact here. The
four views, the ?edit= handling, the invalid-save behaviour and the DEC-009
deletion did not care what the form contained.
"""

from __future__ import annotations

from accounts.master_data import (
    MasterDataForm,
    MasterDataPage,
    required_category_number_field,
)
from reference.models import MahsulotTuri


class MahsulotTuriForm(MasterDataForm):
    """Capture one product category.

    Category Raqami is required here, unlike on every other master data page.
    The supplied form marks it so and calls it a code, and TASK-UZK-046
    reports purchases by category: a category with no number would have
    nothing to report under.
    """

    NUMBER_ALREADY_USED = "Bu raqam allaqachon mavjud."
    NUMBER_HELD_BY_DELETED_RECORD = (
        "Bu raqam o'chirilgan kategoriyaga tegishli. Boshqa raqam kiriting."
    )

    category_number = required_category_number_field()

    def clean_category_number(self) -> int:
        """Refuse a number already taken, saying which kind of clash it is.

        The second unique column on this page, and the first anywhere in the
        application. Left to Django it would answer the same sentence whether
        the category holding the number is on the page or was deleted from it.
        """
        return self.refuse_a_clash(
            self.cleaned_data["category_number"],
            lookup="category_number",
            already_used=self.NUMBER_ALREADY_USED,
            held_by_deleted_record=self.NUMBER_HELD_BY_DELETED_RECORD,
        )

    class Meta:
        model = MahsulotTuri
        fields = ("category_number", "name", "description")


mahsulot_turi_page = MasterDataPage(
    model=MahsulotTuri,
    form_class=MahsulotTuriForm,
    template_name="pages/mahsulot-turlari.html",
    url_name="mahsulot-turlari",
    context_object_name="categories",
)
