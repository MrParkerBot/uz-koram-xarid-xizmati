"""Root URL configuration for the Uz-Koram Xarid Xizmati application."""

from django.contrib import admin
from django.urls import path

from config.views import service_root

urlpatterns = [
    path("", service_root, name="service-root"),
    path("admin/", admin.site.urls),
]
