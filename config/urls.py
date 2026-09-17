"""Root URL configuration for the Uz-Koram Xarid Xizmati application.

Every converted page is served here by name. The names match the template
filenames, which match the names the supplied static pages used, so a page can
be traced from the specification to the URL without a lookup table.

The pages are plain template views for now. A page grows a real view when the
task that gives it data arrives; TASK-UZK-009 and TASK-UZK-012 attach
authentication and permissions to these names.

Login and logout are Django's own views. Writing them by hand would mean
re-implementing session cycling and credential checking that django.contrib.auth
already does correctly.
"""

from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.views import LoginView, LogoutView
from django.urls import path
from django.views.generic import TemplateView

from accounts.permissions import require_page_permission
from accounts.specialty_views import (
    specialty_create,
    specialty_delete,
    specialty_list,
    specialty_update,
)
from accounts.type_views import (
    user_type_create,
    user_type_delete,
    user_type_list,
    user_type_update,
)
from accounts.views import (
    landing_page,
    user_contract_editing,
    user_create,
    user_delete,
    user_list,
    user_update,
)
from applications.views import (
    accept_application,
    accept_assigned_application,
    accepted_list,
    application_create,
    application_pdf,
    approve_purchase_application,
    assign_application,
    assigned_list,
    incoming_list,
    purchase_application_create,
    purchase_application_list,
    purchase_application_original_pdf,
    purchase_application_pdf,
    reject_application,
    reject_purchase_application,
    set_application_status,
)
from reference.ariza_status_views import ariza_status_page
from reference.department_views import department_page
from reference.mahsulot_turi_views import mahsulot_turi_page
from reference.shartnoma_status_views import shartnoma_status_page
from reference.shartnoma_turi_views import shartnoma_turi_page
from reference.supplier_views import supplier_page

# Every page except the dashboard, which answers at the site root. Each entry
# is (url path, URL name); the template is pages/<name>.html.
PAGE_ROUTES: tuple[tuple[str, str], ...] = (
    ("kelishinlingan/", "kelishinlingan"),
    ("tuzilgan/", "tuzilgan"),
    ("xodimlar-yuklamasi/", "xodimlar-yuklamasi"),
    ("bolimlar/", "bolimlar"),
    ("mahsulot-tur/", "mahsulot-tur"),
    ("mahsulotlar/", "mahsulotlar"),
    ("integration/", "integration"),
    ("logs/", "logs"),
)


def page_view(page_name: str) -> object:
    """A view rendering one converted page, open to the types DEC-015 permits."""
    return require_page_permission(page_name)(
        TemplateView.as_view(template_name=f"pages/{page_name}.html")
    )


urlpatterns = [
    # The one view that stays open. Everything else is closed by
    # LoginRequiredMiddleware, including logout: an anonymous request there has
    # no session to end and is simply sent back here.
    path(
        "login/",
        login_not_required(
            LoginView.as_view(
                template_name="pages/login.html",
                redirect_authenticated_user=True,
            )
        ),
        name="login",
    ),
    # Django's LogoutView only accepts POST, so a link - or a page that
    # prefetches one - cannot end somebody's session.
    path("logout/", LogoutView.as_view(), name="logout"),
    path("", page_view("dashboard"), name="dashboard"),
    # Where signing in lands. Not the dashboard: three of the six types may
    # not open it, so signing in correctly used to answer 403.
    path("kirish/", landing_page, name="landing-page"),
    *(
        path(route, page_view(page_name), name=page_name)
        for route, page_name in PAGE_ROUTES
    ),
    # The Users page has real views rather than a template: it is the first
    # page with data behind it (TASK-UZK-011). The list keeps the name the
    # sidebar and the page inventory already use.
    # The Users page and everything it does answer to the same permission as
    # the page itself: an action must not be reachable by somebody who may not
    # open the page that offers it.
    path("users/", require_page_permission("users")(user_list), name="users"),
    path(
        "users/add/",
        require_page_permission("users")(user_create),
        name="user-create",
    ),
    path(
        "users/<int:pk>/edit/",
        require_page_permission("users")(user_update),
        name="user-update",
    ),
    path(
        "users/<int:pk>/delete/",
        require_page_permission("users")(user_delete),
        name="user-delete",
    ),
    # The User Specialty master data page (TASK-UZK-014), the first of the
    # eight pages section 3 describes in the same shape.
    path(
        "user-specialty/",
        require_page_permission("user-specialty")(specialty_list),
        name="user-specialty",
    ),
    path(
        "user-specialty/add/",
        require_page_permission("user-specialty")(specialty_create),
        name="user-specialty-create",
    ),
    path(
        "user-specialty/<int:pk>/edit/",
        require_page_permission("user-specialty")(specialty_update),
        name="user-specialty-update",
    ),
    path(
        "user-specialty/<int:pk>/delete/",
        require_page_permission("user-specialty")(specialty_delete),
        name="user-specialty-delete",
    ),
    # The User Types master data page (TASK-UZK-015). A type is also a role,
    # so the six DEC-013 fixes cannot be renamed or deleted here.
    path(
        "user-types/",
        require_page_permission("user-types")(user_type_list),
        name="user-types",
    ),
    path(
        "user-types/add/",
        require_page_permission("user-types")(user_type_create),
        name="user-types-create",
    ),
    path(
        "user-types/<int:pk>/edit/",
        require_page_permission("user-types")(user_type_update),
        name="user-types-update",
    ),
    path(
        "user-types/<int:pk>/delete/",
        require_page_permission("user-types")(user_type_delete),
        name="user-types-delete",
    ),
    path(
        "users/<int:pk>/contract-editing/",
        require_page_permission("users")(user_contract_editing),
        name="user-contract-editing",
    ),
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
    # The Kelib tushgan Arizalar page (TASK-UZK-022), the first page with a
    # record that has a life cycle rather than a name. The PDF answers to the
    # same permission as the page, so an attachment is reachable by exactly
    # the people who may see the row it belongs to (DEC-019).
    path(
        "kelib-arizalar/",
        require_page_permission("kelib-arizalar")(incoming_list),
        name="kelib-arizalar",
    ),
    # The Qabul qilingan Arizalar page (TASK-UZK-025). It left PAGE_ROUTES
    # when it stopped being a template with no data behind it; the path and
    # the name are the ones the sidebar and PAGE_SHOWING_STAGE already use.
    path(
        "qabul-arizalar/",
        require_page_permission("qabul-arizalar")(accepted_list),
        name="qabul-arizalar",
    ),
    # The Tayinlangan Arizalar page (TASK-UZK-028). It left PAGE_ROUTES when
    # it stopped being a template with no data behind it; the path and the
    # name are the ones the sidebar, the permission matrix and
    # PAGE_SHOWING_STAGE already use.
    path(
        "tayinlangan/",
        require_page_permission("tayinlangan")(assigned_list),
        name="tayinlangan",
    ),
    # The specialist taking the work, and marking where it has got to
    # (TASK-UZK-029). Both are offered on the Tayinlangan page and answer to
    # its permission; which rows a caller may act on is decided in the view,
    # because a specialist may open the page and may not touch somebody
    # else's row.
    path(
        "tayinlangan/<int:pk>/qabul/",
        require_page_permission("tayinlangan")(accept_assigned_application),
        name="tayinlangan-qabul",
    ),
    path(
        "tayinlangan/<int:pk>/holat/",
        require_page_permission("tayinlangan")(set_application_status),
        name="tayinlangan-holat",
    ),
    # The Xarid Arizasi page of section 4.9 (TASK-UZK-030). It left
    # PAGE_ROUTES when it stopped being a template with no data behind it; the
    # path and the name are the ones the sidebar and the permission matrix
    # already use. It is the only page a Users requester has.
    path(
        "xarid-ariza/",
        require_page_permission("xarid-ariza")(purchase_application_list),
        name="xarid-ariza",
    ),
    path(
        "xarid-ariza/yaratish/",
        require_page_permission("xarid-ariza")(purchase_application_create),
        name="xarid-ariza-yaratish",
    ),
    # DEC-016's approval chain (TASK-UZK-031). Both actions are offered in
    # the queue on the Xarid Arizasi page and answer to its permission;
    # whether this person is the one the request is waiting for is decided in
    # the view, because both approvers may open the page and only one of them
    # is waiting on any given request.
    path(
        "xarid-ariza/<int:pk>/tasdiqlash/",
        require_page_permission("xarid-ariza")(approve_purchase_application),
        name="xarid-ariza-tasdiqlash",
    ),
    path(
        "xarid-ariza/<int:pk>/inkor/",
        require_page_permission("xarid-ariza")(reject_purchase_application),
        name="xarid-ariza-inkor",
    ),
    path(
        "xarid-ariza/<int:pk>/pdf/",
        require_page_permission("xarid-ariza")(purchase_application_pdf),
        name="xarid-ariza-pdf",
    ),
    # The attachment as it was uploaded, before an approval stamped it
    # (TASK-UZK-032). Same permission as the stamped one: anybody who may see
    # the approved document may see what it was approved from.
    path(
        "xarid-ariza/<int:pk>/asl-pdf/",
        require_page_permission("xarid-ariza")(
            purchase_application_original_pdf
        ),
        name="xarid-ariza-asl-pdf",
    ),
    # Creating an application (TASK-UZK-026). The form is on the Qabul
    # qilingan page, so it answers to that page's permission like every other
    # action: whoever may not see the page may not create a record on it.
    path(
        "qabul-arizalar/yaratish/",
        require_page_permission("qabul-arizalar")(application_create),
        name="ariza-yaratish",
    ),
    # Not wrapped in require_page_permission: the view asks about the page
    # that currently shows this application, because the attachment has to
    # stop being reachable when the row stops being visible.
    path(
        "arizalar/<int:pk>/pdf/",
        application_pdf,
        name="ariza-pdf",
    ),
    # Accepting is offered on the incoming page, so it answers to that page's
    # permission: an action is never reachable by somebody who may not see
    # the row offering it (TASK-UZK-023).
    path(
        "kelib-arizalar/<int:pk>/qabul/",
        require_page_permission("kelib-arizalar")(accept_application),
        name="ariza-qabul",
    ),
    # Assigning and re-assigning, offered on the Qabul qilingan page and
    # answering to its permission (TASK-UZK-027). One route for both, because
    # DEC-024 makes them the same act.
    path(
        "qabul-arizalar/<int:pk>/tayinlash/",
        require_page_permission("qabul-arizalar")(assign_application),
        name="ariza-tayinlash",
    ),
    # Rejecting, for the same reason and under the same permission
    # (TASK-UZK-024).
    path(
        "kelib-arizalar/<int:pk>/inkor/",
        require_page_permission("kelib-arizalar")(reject_application),
        name="ariza-inkor",
    ),
]
