"""Root URL configuration.

The admin, Django's own authentication views under /accounts/, and the
application's pages at the site root under the "xarid" namespace.

The login route is declared once by hand, before the include, so that it is
the application's own SignInView: it sends an already signed-in visitor on
rather than showing them the form again, and it drops a ?next= the account
may not open instead of landing somebody on a 403 for signing in correctly.
Everything else under /accounts/ is the stock set.

Django's own set_language view is included too: it is what the language
picker in the top bar posts to, and it writes the choice into the session
that LocaleMiddleware reads on the next request.
"""

from django.contrib import admin
from django.urls import include, path

from xarid.views import SignInView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/login/", SignInView.as_view(), name="login"),
    path("accounts/", include("django.contrib.auth.urls")),
    path("i18n/", include("django.conf.urls.i18n")),
    path("", include("xarid.urls")),
]
