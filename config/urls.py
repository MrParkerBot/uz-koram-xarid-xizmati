"""Root URL configuration.

The admin, Django's own authentication views under /accounts/, and the
application's pages at the site root under the "xarid" namespace.

The login route is declared once by hand, before the include, so Django's
LoginView can be told to send an already signed-in visitor on rather than
show them the form again; everything else under /accounts/ is the stock set.
"""

from django.contrib import admin
from django.contrib.auth.views import LoginView
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path(
        "accounts/login/",
        LoginView.as_view(redirect_authenticated_user=True),
        name="login",
    ),
    path("accounts/", include("django.contrib.auth.urls")),
    path("", include("xarid.urls")),
]
