"""The Shartnoma turi master data page (section 3.7).

The fourth page built out of MasterDataPage and the smallest of them: a table
of names, a form with one field, and nothing else the specification asks for.
"""

from __future__ import annotations

from accounts.master_data import (
    MasterDataForm,
    MasterDataPage,
    category_number_field,
)
from reference.models import ShartnomaTuri


class ShartnomaTuriForm(MasterDataForm):
    """Capture one contract type.

    Category Number is not on the supplied page and the specification does not
    give this table one. The field exists so an installation that wants it can
    show it without a migration, and DEC-023's six-digit rule applies the
    moment it is filled in - the same reasoning TASK-UZK-014 recorded.
    """

    category_number = category_number_field()

    class Meta:
        model = ShartnomaTuri
        fields = ("name", "category_number")


shartnoma_turi_page = MasterDataPage(
    model=ShartnomaTuri,
    form_class=ShartnomaTuriForm,
    template_name="pages/shartnoma-turi.html",
    url_name="shartnoma-turi",
    context_object_name="contract_types",
)
