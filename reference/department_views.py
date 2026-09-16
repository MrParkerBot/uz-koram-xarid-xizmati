"""The Bo`limlar master data page (DEC-018).

The one page in the application the specification does not describe. DEC-018
makes departments Admin-maintained master data, and master data an
administrator cannot reach is master data only a shell can create, so a page
had to exist. It is deliberately the plainest one here - a table of names and a
one-field form - so that it is easy to replace if the customer wants it to look
like something.

The existing bolimlar page is the Korhona xaridi report of TASK-UZK-045, which
reads this table. This page is bolim-royhati.
"""

from __future__ import annotations

from accounts.master_data import (
    MasterDataForm,
    MasterDataPage,
    category_number_field,
)
from reference.models import Department


class DepartmentForm(MasterDataForm):
    """Capture one department."""

    category_number = category_number_field()

    class Meta:
        model = Department
        fields = ("name", "category_number")


department_page = MasterDataPage(
    model=Department,
    form_class=DepartmentForm,
    template_name="pages/bolim-royhati.html",
    url_name="bolim-royhati",
    context_object_name="departments",
)
