"""The routes of the purchasing department's pages, under the "xarid" namespace.

Every page name matches the name the sidebar (navigation.py) and the
permission matrix (permissions.py) use, so a page can be traced from the
sidebar to the URL to the template without a lookup table. Every view is
closed by require_page_permission(), which applies login_required and then
the DEC-015 matrix; the two exceptions say why below.
"""

from django.urls import path

from xarid import views
from xarid.permissions import require_page_permission

app_name = "xarid"


def master_data_routes(prefix: str, page_name: str, page: views.MasterDataPage) -> list:
    """The four routes one master data page needs: list, add, edit, delete."""
    permitted = require_page_permission(page_name)
    return [
        path(f"{prefix}/", permitted(page.list_records), name=page_name),
        path(f"{prefix}/add/", permitted(page.create_record), name=f"{page_name}-create"),
        path(
            f"{prefix}/<int:pk>/edit/",
            permitted(page.update_record),
            name=f"{page_name}-update",
        ),
        path(
            f"{prefix}/<int:pk>/delete/",
            permitted(page.delete_record),
            name=f"{page_name}-delete",
        ),
    ]


def prototype_route(route: str, page_name: str) -> path:
    """One prototype page, open to the types DEC-015 permits."""
    return path(
        route,
        require_page_permission(page_name)(views.prototype_page(page_name)),
        name=page_name,
    )


users = require_page_permission("users")
incoming = require_page_permission("kelib-arizalar")
accepted = require_page_permission("qabul-arizalar")
assigned = require_page_permission("tayinlangan")
contracts = require_page_permission("kelishinlingan")
workload = require_page_permission("xodimlar-yuklamasi")
departments_report = require_page_permission("bolimlar")
products_report = require_page_permission("mahsulotlar")
purchases = require_page_permission("xarid-ariza")

urlpatterns = [
    # Where signing in lands: the first page the user's type may open.
    path("kirish/", views.landing_page, name="landing"),
    # The dashboard answers at the site root.
    prototype_route("", "dashboard"),
    # The Users page and everything it does answer to the page's permission.
    path("users/", users(views.user_list), name="users"),
    path("users/add/", users(views.user_create), name="user-create"),
    path("users/<int:pk>/edit/", users(views.user_update), name="user-update"),
    path("users/<int:pk>/delete/", users(views.user_delete), name="user-delete"),
    path(
        "users/<int:pk>/contract-editing/",
        users(views.user_contract_editing),
        name="user-contract-editing",
    ),
    # The eight master data pages of sections 3.2 and 3.5-3.8, DEC-018 and
    # DEC-011.
    *master_data_routes("user-specialty", "user-specialty", views.specialty_page),
    *master_data_routes("user-types", "user-types", views.user_type_page),
    *master_data_routes("ariza-status", "ariza-status", views.ariza_status_page),
    *master_data_routes("shartnoma-status", "shartnoma-status", views.shartnoma_status_page),
    *master_data_routes("mahsulot-turlari", "mahsulot-turlari", views.mahsulot_turi_page),
    *master_data_routes("shartnoma-turi", "shartnoma-turi", views.shartnoma_turi_page),
    *master_data_routes("bolim-royhati", "bolim-royhati", views.department_page),
    *master_data_routes("firmalar", "firmalar", views.supplier_page),
    # Applications: the incoming list and its two decisions.
    path("kelib-arizalar/", incoming(views.incoming_list), name="kelib-arizalar"),
    path(
        "kelib-arizalar/<int:pk>/qabul/",
        incoming(views.accept_application),
        name="ariza-qabul",
    ),
    path(
        "kelib-arizalar/<int:pk>/inkor/",
        incoming(views.reject_application),
        name="ariza-inkor",
    ),
    # The accepted list, the creation form and assignment.
    path("qabul-arizalar/", accepted(views.accepted_list), name="qabul-arizalar"),
    path(
        "qabul-arizalar/yaratish/",
        accepted(views.application_create),
        name="ariza-yaratish",
    ),
    path(
        "qabul-arizalar/<int:pk>/tayinlash/",
        accepted(views.assign_application),
        name="ariza-tayinlash",
    ),
    # The assigned list, the specialist's acceptance and status.
    path("tayinlangan/", assigned(views.assigned_list), name="tayinlangan"),
    path(
        "tayinlangan/<int:pk>/qabul/",
        assigned(views.accept_assigned_application),
        name="tayinlangan-qabul",
    ),
    path(
        "tayinlangan/<int:pk>/holat/",
        assigned(views.set_application_status),
        name="tayinlangan-holat",
    ),
    # Not wrapped in a page permission: the view asks about the page that
    # currently shows this application (DEC-019). login_required is on the
    # view itself.
    path("arizalar/<int:pk>/pdf/", views.application_pdf, name="ariza-pdf"),
    # Contracts.
    path("kelishinlingan/", contracts(views.agreed_contracts_list), name="kelishinlingan"),
    path(
        "kelishinlingan/yaratish/",
        contracts(views.contract_create),
        name="shartnoma-yaratish",
    ),
    # Purchase applications and the approval chain.
    path("xarid-ariza/", purchases(views.purchase_application_list), name="xarid-ariza"),
    path(
        "xarid-ariza/yaratish/",
        purchases(views.purchase_application_create),
        name="xarid-ariza-yaratish",
    ),
    path(
        "xarid-ariza/<int:pk>/tasdiqlash/",
        purchases(views.approve_purchase_application),
        name="xarid-ariza-tasdiqlash",
    ),
    path(
        "xarid-ariza/<int:pk>/inkor/",
        purchases(views.reject_purchase_application),
        name="xarid-ariza-inkor",
    ),
    path(
        "xarid-ariza/<int:pk>/pdf/",
        purchases(views.purchase_application_pdf),
        name="xarid-ariza-pdf",
    ),
    path(
        "xarid-ariza/<int:pk>/asl-pdf/",
        purchases(views.purchase_application_original_pdf),
        name="xarid-ariza-asl-pdf",
    ),
    # Hisobotlar: the reports that read the database.
    path(
        "xodimlar-yuklamasi/",
        workload(views.staff_workload_report),
        name="xodimlar-yuklamasi",
    ),
    path(
        "bolimlar/",
        departments_report(views.department_purchasing_report),
        name="bolimlar",
    ),
    # Each report downloads under its own page's permission, named so the
    # shared export_links macro reverses it (REQ-YUKLAMA-001, REQ-XARID-001).
    path(
        "xodimlar-yuklamasi/eksport/<str:file_format>/",
        workload(views.staff_workload_export),
        name="xodimlar-yuklamasi-eksport",
    ),
    path(
        "bolimlar/eksport/<str:file_format>/",
        departments_report(views.department_purchasing_export),
        name="bolimlar-eksport",
    ),
    path("mahsulotlar/", products_report(views.products_list), name="mahsulotlar"),
    path(
        "mahsulotlar/eksport/<str:file_format>/",
        products_report(views.products_export),
        name="mahsulotlar-eksport",
    ),
    # The pages that are still the supplied prototype.
    prototype_route("tuzilgan/", "tuzilgan"),
    prototype_route("mahsulot-tur/", "mahsulot-tur"),
    prototype_route("integration/", "integration"),
    prototype_route("logs/", "logs"),
    # Yuklab olish: each list page's table as Excel or PDF, under the page's
    # own permission and with the page's own filters (REQ-ARIZA-002).
    path(
        "kelib-arizalar/eksport/<str:file_format>/",
        incoming(views.incoming_export),
        name="kelib-arizalar-eksport",
    ),
    path(
        "qabul-arizalar/eksport/<str:file_format>/",
        accepted(views.accepted_export),
        name="qabul-arizalar-eksport",
    ),
    path(
        "tayinlangan/eksport/<str:file_format>/",
        assigned(views.assigned_export),
        name="tayinlangan-eksport",
    ),
    path(
        "kelishinlingan/eksport/<str:file_format>/",
        contracts(views.contracts_export),
        name="kelishinlingan-eksport",
    ),
    path(
        "xarid-ariza/eksport/<str:file_format>/",
        purchases(views.purchase_export),
        name="xarid-ariza-eksport",
    ),
]
