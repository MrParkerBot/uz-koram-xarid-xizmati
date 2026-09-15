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
    """Read a comma-separated list from the environment.

    A variable that is unset, empty, or only separators falls back to
    `default`, because an empty ALLOWED_HOSTS would reject every request.
    """
    raw_value = os.environ.get(variable_name, "")
    entries = [entry.strip() for entry in raw_value.split(",") if entry.strip()]
    return entries or default


# Off unless the environment explicitly turns it on, so that an unconfigured
# deployment is the safe one rather than the permissive one.
DEBUG = read_boolean_setting("DJANGO_DEBUG", default=False)

# A generated key keeps the repository free of committed secrets. It changes on
# every restart, which invalidates sessions, so a real deployment must set
# DJANGO_SECRET_KEY.
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY") or get_random_secret_key()

ALLOWED_HOSTS = read_list_setting(
    "DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"]
)

# The Django admin is deliberately absent. The specification defines its own
# role model and administration pages in section 11, and a second parallel
# administration surface would sit outside the permission matrix TASK-UZK-012
# builds. Add it only if a requirement asks for it.
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
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

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
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

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# SQLite is the only database for this project (DEC-002).
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

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

# The Bootstrap build, icon font and JavaScript supplied with the technical
# assignment. They are served as-is rather than rebuilt, so the interface the
# customer approved survives the move to Django (DEC-005).
STATICFILES_DIRS = [BASE_DIR / "static"]

# Windows has no registry entry for web fonts, so mimetypes serves them as
# application/octet-stream. Browsers usually sniff past that, but a strict
# Content-Type policy will refuse the font and every icon renders as a box.
mimetypes.add_type("font/woff", ".woff", strict=True)
mimetypes.add_type("font/woff2", ".woff2", strict=True)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
