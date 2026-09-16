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
from reference.ariza_status_views import ariza_status_page
from reference.mahsulot_turi_views import mahsulot_turi_page
from reference.shartnoma_status_views import shartnoma_status_page
from reference.shartnoma_turi_views import shartnoma_turi_page

# Every page except the dashboard, which answers at the site root. Each entry
# is (url path, URL name); the template is pages/<name>.html.
PAGE_ROUTES: tuple[tuple[str, str], ...] = (
    ("kelib-arizalar/", "kelib-arizalar"),
    ("qabul-arizalar/", "qabul-arizalar"),
    ("tayinlangan/", "tayinlangan"),
    ("kelishinlingan/", "kelishinlingan"),
    ("tuzilgan/", "tuzilgan"),
    ("xodimlar-yuklamasi/", "xodimlar-yuklamasi"),
    ("bolimlar/", "bolimlar"),
    ("mahsulot-tur/", "mahsulot-tur"),
    ("mahsulotlar/", "mahsulotlar"),
    ("xarid-ariza/", "xarid-ariza"),
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
]
