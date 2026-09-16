"""The Shartnoma Status master data page (section 3.5).

The second page built out of MasterDataPage, and the reason it exists: the
only thing that differs from Ariza Status is the table, the form and the
template.
"""

from __future__ import annotations

from accounts.master_data import (
    MasterDataForm,
    MasterDataPage,
    category_number_field,
    position_form_field,
)
from reference.models import ShartnomaStatus


class ShartnomaStatusForm(MasterDataForm):
    """Capture one contract status.

    The five badge colours the other master data pages offer, rather than the
    prototype's free colour picker, so a status cannot be given a colour the
    stylesheet has no badge for.
    """

    position = position_form_field()
    category_number = category_number_field()

    class Meta:
        model = ShartnomaStatus
        fields = ("name", "badge_colour", "position", "category_number")


shartnoma_status_page = MasterDataPage(
    model=ShartnomaStatus,
    form_class=ShartnomaStatusForm,
    template_name="pages/shartnoma-status.html",
    url_name="shartnoma-status",
    context_object_name="statuses",
)
