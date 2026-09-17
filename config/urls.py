"""Root URL configuration for the Uz-Koram Xarid Xizmati application.

Every converted page is served by name. The names match the template
filenames, which match the names the supplied static pages used, so a page can
be traced from the specification to the URL without a lookup table.

Each application names the routes of the pages it owns in its own urls.py.
They are included here at no prefix and with no namespace, so a URL name is
global: the templates, the reverse() calls and the permission matrix refer to
a page by its name alone.

The pages are plain template views for now. A page grows a real view when the
task that gives it data arrives; TASK-UZK-009 and TASK-UZK-012 attach
authentication and permissions to these names.

Login and logout are Django's own views. Writing them by hand would mean
re-implementing session cycling and credential checking that django.contrib.auth
already does correctly.
"""

from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.views import LoginView, LogoutView
from django.urls import include, path
from django.views.generic import TemplateView

from accounts.permissions import require_page_permission
from accounts.views import landing_page

# Every page except the dashboard, which answers at the site root. Each entry
# is (url path, URL name); the template is pages/<name>.html.
PAGE_ROUTES: tuple[tuple[str, str], ...] = (
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
    # The pages each application owns, in the order the applications are
    # installed. Every path and every name is unchanged by the include: the
    # prefix is empty and no namespace is declared.
    path("", include("accounts.urls")),
    path("", include("reference.urls")),
    path("", include("applications.urls")),
]
