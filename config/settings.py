"""Django settings for the Uz-Koram Xarid Xizmati Bo'limi application.

Values that differ between machines are read from the environment so that no
deployment secret is ever committed. A `.env` beside manage.py is loaded into
that environment first, so configuring a development machine is filling in one
file; a variable the real environment already carries always wins over it. See
README.md for the variables a real deployment must set.
"""

from __future__ import annotations

import mimetypes
import os
import warnings
from pathlib import Path

from django.core.management.utils import get_random_secret_key
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Everything below reads the process environment, so the project's own .env
# goes into it first: filling in one file is then the whole of configuring a
# development machine, with nothing to export by hand and nothing to forget in
# the second terminal. The path is spelled out rather than searched for, so
# this can never pick up a .env belonging to some parent directory, and it is
# read as utf-8-sig because Notepad writes a BOM that the parser would
# otherwise read as part of the first variable's name.
#
# override=False is python-dotenv's default, written out because it is a
# decision and not an accident: a variable the environment already carries
# wins, so a .env that was copied onto a server by mistake cannot quietly
# replace what that deployment configured for itself.
load_dotenv(BASE_DIR / ".env", override=False, encoding="utf-8-sig")


# The spellings a boolean variable may be written in, kept as two sets rather
# than one so that a value which is neither can be told apart from a
# deliberate "off" and reported instead of being read as one.
TRUE_SPELLINGS = frozenset({"1", "true", "yes", "on"})
FALSE_SPELLINGS = frozenset({"0", "false", "no", "off"})


def read_boolean_setting(variable_name: str, default: bool) -> bool:
    """Read a boolean from the environment, accepting the usual spellings.

    Anything unrecognised falls back to `default` rather than being treated as
    true, so a typo cannot silently switch debugging on in production. It does
    not pass unremarked, though: a misspelt DJANGO_DEBUG reads as "off" and
    leaves every /static/ request a 404, which looks like a broken application
    rather than a broken setting, so an unreadable value says so on stderr.
    """
    raw_value = os.environ.get(variable_name)
    if raw_value is None:
        return default
    spelling = raw_value.strip().lower()
    if spelling in TRUE_SPELLINGS:
        return True
    if spelling in FALSE_SPELLINGS or not spelling:
        return False
    warnings.warn(
        f"{variable_name}={raw_value!r} is not a value this application can read, "
        f"so it is being ignored and {variable_name} is treated as unset. Write one of: "
        f"{', '.join(sorted(TRUE_SPELLINGS | FALSE_SPELLINGS))}.",
        stacklevel=2,
    )
    return default


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
    # After the session and before anything that renders: the chosen language
    # is kept in the session, so it follows a person from page to page and
    # from one device to the next rather than living in one browser.
    "django.middleware.locale.LocaleMiddleware",
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

# The three languages the pages are written in, Uzbek first because it is
# what the department works in and what every string is authored in. The
# codes are the ones the browser sends: "uz" is Uzbek in the Latin script,
# which is the only Uzbek this application is written in.
LANGUAGE_CODE = "uz"
LANGUAGES = [
    ("uz", "O`zbekcha"),
    ("ru", "Русский"),
    ("en", "English"),
]
# Where the catalogues live. One directory per language, each holding the
# django.po a translator edits and the django.mo the runtime reads, which
# `manage.py translations` compiles from it.
LOCALE_PATHS = [BASE_DIR / "locale"]
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
