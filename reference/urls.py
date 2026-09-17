"""The routes of the master data pages reference owns.

The statuses, the categories, the departments and the firms: the lists the
work is described with, each maintained on a page of its own.

Included by the root URL configuration at no prefix and with no namespace,
so every path and every name here is the one the templates, the reverse()
calls and the permission matrix already use.
"""

from django.urls import path

from accounts.permissions import require_page_permission
from reference.ariza_status_views import ariza_status_page
from reference.department_views import department_page
from reference.mahsulot_turi_views import mahsulot_turi_page
from reference.shartnoma_status_views import shartnoma_status_page
from reference.shartnoma_turi_views import shartnoma_turi_page
from reference.supplier_views import supplier_page

urlpatterns = [
    # The Ariza Status master data page (TASK-UZK-016), the first page built
    # out of MasterDataPage and the first table in the reference application.
    path(
        "ariza-status/",
        require_page_permission("ariza-status")(ariza_status_page.list_records),
        name="ariza-status",
    ),
    path(
        "ariza-status/add/",
        require_page_permission("ariza-status")(ariza_status_page.create_record),
        name="ariza-status-create",
    ),
    path(
        "ariza-status/<int:pk>/edit/",
        require_page_permission("ariza-status")(ariza_status_page.update_record),
        name="ariza-status-update",
    ),
    path(
        "ariza-status/<int:pk>/delete/",
        require_page_permission("ariza-status")(ariza_status_page.delete_record),
        name="ariza-status-delete",
    ),
    # The Shartnoma Status master data page (TASK-UZK-017). DEC-010 makes the
    # statuses editable, so the reports read this table rather than a constant.
    path(
        "shartnoma-status/",
        require_page_permission("shartnoma-status")(
            shartnoma_status_page.list_records
        ),
        name="shartnoma-status",
    ),
    path(
        "shartnoma-status/add/",
        require_page_permission("shartnoma-status")(
            shartnoma_status_page.create_record
        ),
        name="shartnoma-status-create",
    ),
    path(
        "shartnoma-status/<int:pk>/edit/",
        require_page_permission("shartnoma-status")(
            shartnoma_status_page.update_record
        ),
        name="shartnoma-status-update",
    ),
    path(
        "shartnoma-status/<int:pk>/delete/",
        require_page_permission("shartnoma-status")(
            shartnoma_status_page.delete_record
        ),
        name="shartnoma-status-delete",
    ),
    # The Mahsulot Turlari master data page (TASK-UZK-018). Ships empty: no
    # decision names a starting set of product categories.
    path(
        "mahsulot-turlari/",
        require_page_permission("mahsulot-turlari")(
            mahsulot_turi_page.list_records
        ),
        name="mahsulot-turlari",
    ),
    path(
        "mahsulot-turlari/add/",
        require_page_permission("mahsulot-turlari")(
            mahsulot_turi_page.create_record
        ),
        name="mahsulot-turlari-create",
    ),
    path(
        "mahsulot-turlari/<int:pk>/edit/",
        require_page_permission("mahsulot-turlari")(
            mahsulot_turi_page.update_record
        ),
        name="mahsulot-turlari-update",
    ),
    path(
        "mahsulot-turlari/<int:pk>/delete/",
        require_page_permission("mahsulot-turlari")(
            mahsulot_turi_page.delete_record
        ),
        name="mahsulot-turlari-delete",
    ),
    # The Shartnoma turi master data page (TASK-UZK-019). DEC-023 draws
    # contract type from here rather than fixing it to Import and Local.
    path(
        "shartnoma-turi/",
        require_page_permission("shartnoma-turi")(
            shartnoma_turi_page.list_records
        ),
        name="shartnoma-turi",
    ),
    path(
        "shartnoma-turi/add/",
        require_page_permission("shartnoma-turi")(
            shartnoma_turi_page.create_record
        ),
        name="shartnoma-turi-create",
    ),
    path(
        "shartnoma-turi/<int:pk>/edit/",
        require_page_permission("shartnoma-turi")(
            shartnoma_turi_page.update_record
        ),
        name="shartnoma-turi-update",
    ),
    path(
        "shartnoma-turi/<int:pk>/delete/",
        require_page_permission("shartnoma-turi")(
            shartnoma_turi_page.delete_record
        ),
        name="shartnoma-turi-delete",
    ),
    # The Bo`limlar master data page (TASK-UZK-020). DEC-018 makes departments
    # Admin-maintained, and the specification gives them no page, so this one
    # is invented. bolimlar is the TASK-UZK-045 report and stays that.
    path(
        "bolim-royhati/",
        require_page_permission("bolim-royhati")(department_page.list_records),
        name="bolim-royhati",
    ),
    path(
        "bolim-royhati/add/",
        require_page_permission("bolim-royhati")(department_page.create_record),
        name="bolim-royhati-create",
    ),
    path(
        "bolim-royhati/<int:pk>/edit/",
        require_page_permission("bolim-royhati")(department_page.update_record),
        name="bolim-royhati-update",
    ),
    path(
        "bolim-royhati/<int:pk>/delete/",
        require_page_permission("bolim-royhati")(department_page.delete_record),
        name="bolim-royhati-delete",
    ),
    # The Firmalar master data page (TASK-UZK-021). DEC-011 makes suppliers
    # master data; the specification gives them no page either.
    path(
        "firmalar/",
        require_page_permission("firmalar")(supplier_page.list_records),
        name="firmalar",
    ),
    path(
        "firmalar/add/",
        require_page_permission("firmalar")(supplier_page.create_record),
        name="firmalar-create",
    ),
    path(
        "firmalar/<int:pk>/edit/",
        require_page_permission("firmalar")(supplier_page.update_record),
        name="firmalar-update",
    ),
    path(
        "firmalar/<int:pk>/delete/",
        require_page_permission("firmalar")(supplier_page.delete_record),
        name="firmalar-delete",
    ),
]
