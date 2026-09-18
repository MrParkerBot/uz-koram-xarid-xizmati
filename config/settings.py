"""Django settings for the Uz-Koram Xarid Xizmati Bo'limi application.

Values that differ between machines are read from the environment so that no
deployment secret is ever committed. See README.md for the variables a real
deployment must set.
"""

from __future__ import annotations

import mimetypes
import os
from pathlib import Path

from django.core.management.utils import get_random_secret_key

BASE_DIR = Path(__file__).resolve().parent.parent


def read_boolean_setting(variable_name: str, default: bool) -> bool:
    """Read a boolean from the environment, accepting the usual spellings.

    Anything unrecognised falls back to `default` rather than being treated as
    true, so a typo cannot silently switch debugging on in production.
    """
    raw_value = os.environ.get(variable_name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def read_list_setting(variable_name: str, default: list[str]) -> list[str]:
    """Read a comma-separated list from the environment, falling back when empty."""
    raw_value = os.environ.get(variable_name, "")
    entries = [entry.strip() for entry in raw_value.split(",") if entry.strip()]
    return entries or default


# Off unless the environment explicitly turns it on, so that an unconfigured
# deployment is the safe one rather than the permissive one. Local development
# sets DJANGO_DEBUG=1 (see README.md).
DEBUG = read_boolean_setting("DJANGO_DEBUG", default=False)

# A generated key keeps the repository free of committed secrets. It changes on
# every restart, which invalidates sessions, so a real deployment must set
# DJANGO_SECRET_KEY.
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY") or get_random_secret_key()

ALLOWED_HOSTS = read_list_setting("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "xarid",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

# The application's own pages render through Jinja2, from xarid/templates.
# The Django engine stays for the admin, whose templates only exist in that
# syntax; it is listed second so an application template is never rendered by
# the wrong engine.
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.jinja2.Jinja2",
        "DIRS": [BASE_DIR / "xarid" / "templates"],
        "APP_DIRS": False,
        "OPTIONS": {
            "environment": "xarid.jinja2.environment",
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# The message framework's ERROR level is tagged "error" by default, and the
# vendored style.css calls that idea .alert-danger, as Bootstrap does. 40 is
# django.contrib.messages.ERROR, written as its value so that this module does
# not import the messages package while settings are still being decided.
MESSAGE_TAGS = {40: "danger"}

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# SQLite is the only database for this project (DEC-002).
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# Django's own authentication views answer under /accounts/. Signing in lands
# on the first page the user's type may open; signing out shows the
# registration/logged_out.html page.
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "xarid:landing"

# Off by default because development runs over plain HTTP; any deployment
# reachable over HTTPS must turn it on.
SESSION_COOKIE_SECURE = read_boolean_setting("DJANGO_SECURE_COOKIES", default=False)
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "uz"
TIME_ZONE = "Asia/Tashkent"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Where uploaded attachments live (DEC-019). Deliberately not MEDIA_ROOT, and
# there is deliberately no MEDIA_URL: an attachment is served only through a
# view that asks the permission matrix first. Outside the static tree, so
# nothing the static machinery collects or serves can reach it.
ATTACHMENT_ROOT = BASE_DIR / "attachments"

# Windows has no registry entry for web fonts, so mimetypes would serve the
# icon font as application/octet-stream and a strict browser would refuse it.
mimetypes.add_type("font/woff", ".woff", strict=True)
mimetypes.add_type("font/woff2", ".woff2", strict=True)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
