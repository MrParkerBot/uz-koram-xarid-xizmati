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

from django.contrib.auth.views import LoginView, LogoutView
from django.urls import path
from django.views.generic import TemplateView

# Every page except the dashboard, which answers at the site root. Each entry
# is (url path, URL name); the template is pages/<name>.html.
PAGE_ROUTES: tuple[tuple[str, str], ...] = (
    ("user-specialty/", "user-specialty"),
    ("user-types/", "user-types"),
    ("users/", "users"),
    ("ariza-status/", "ariza-status"),
    ("shartnoma-status/", "shartnoma-status"),
    ("mahsulot-turlari/", "mahsulot-turlari"),
    ("shartnoma-turi/", "shartnoma-turi"),
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
    """A view rendering one converted page through the shared shell."""
    return TemplateView.as_view(template_name=f"pages/{page_name}.html")


urlpatterns = [
    path(
        "login/",
        LoginView.as_view(
            template_name="pages/login.html",
            redirect_authenticated_user=True,
        ),
        name="login",
    ),
    # Django's LogoutView only accepts POST, so a link - or a page that
    # prefetches one - cannot end somebody's session.
    path("logout/", LogoutView.as_view(), name="logout"),
    path("", page_view("dashboard"), name="dashboard"),
    *(
        path(route, page_view(page_name), name=page_name)
        for route, page_name in PAGE_ROUTES
    ),
]
