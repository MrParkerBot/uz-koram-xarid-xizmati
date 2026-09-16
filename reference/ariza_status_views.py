"""The Ariza Status master data page (section 3.5).

The third page of this shape, and the first to be built out of MasterDataPage
rather than by repeating the four views a fourth time. Nothing about it differs
from User Specialty except the table, the form and the template, which is why
there is so little here.
"""

from __future__ import annotations

from accounts.master_data import (
    MasterDataForm,
    MasterDataPage,
    category_number_field,
    position_form_field,
)
from reference.models import ArizaStatus


class ArizaStatusForm(MasterDataForm):
    """Capture one application status.

    The supplied page offers a free colour picker; this offers the five badge
    colours the User Types page already offers, so the two pages agree and a
    status cannot be given a colour the stylesheet has no badge for.

    Category Number is not on the supplied page and the specification does not
    give this table one. The field exists so an installation that wants it can
    show it without a migration, and DEC-023's six-digit rule applies the
    moment it is filled in.
    """

    position = position_form_field()
    category_number = category_number_field()

    class Meta:
        model = ArizaStatus
        fields = ("name", "badge_colour", "position", "category_number")


ariza_status_page = MasterDataPage(
    model=ArizaStatus,
    form_class=ArizaStatusForm,
    template_name="pages/ariza-status.html",
    url_name="ariza-status",
    context_object_name="statuses",
)
