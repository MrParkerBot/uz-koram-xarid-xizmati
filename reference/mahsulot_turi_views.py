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

    category_number = required_category_number_field()

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
