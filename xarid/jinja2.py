"""The Jinja2 environment every template renders in.

Django's Jinja2 backend passes request, csrf_input, csrf_token and the
configured context processors (user, messages) into every render. This adds
the globals and filters the templates need beyond that:

- url() and static(), the Jinja2 spellings of {% url %} and {% static %};
- date() and striptags, the two Django filters the pages relied on;
- now(), for the read-only dates the creation forms show;
- the sidebar groups, initials and User Type name the shell renders;
- the translations, so a template may say {{ _("Saqlash") }} and get the
  word in the language the reader chose. The catalogues are keyed by the
  Uzbek the pages are written in, so an untranslated string renders as what
  the author typed rather than as a key nobody can read.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, AnonymousUser
from django.template.defaultfilters import date as django_date
from django.templatetags.static import static
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.html import strip_tags
from jinja2 import Environment
from markupsafe import Markup

from xarid.models import UserProfile, user_type_name_of
from xarid.navigation import SIDEBAR_NAVIGATION, NavigationGroup
from xarid.permissions import permitted_pages, sees_own_approvals

# Day first, the way the pages print every date: 17/03/2026, 17/03/2026 14:32.
DATE_FORMAT = "d/m/Y"
DATETIME_FORMAT = "d/m/Y H:i"


def url(name: str, *args, **kwargs) -> str:
    """Reverse a URL by name, the way {% url %} does."""
    return reverse(name, args=args or None, kwargs=kwargs or None)


def formatted_date(value: datetime | None, format_string: str = DATE_FORMAT) -> str:
    """Django's date filter, converting an aware datetime to local time first."""
    if isinstance(value, datetime) and timezone.is_aware(value):
        value = timezone.localtime(value)

    return django_date(value, format_string)


def now(format_string: str = DATE_FORMAT) -> str:
    """The current local date or time, formatted the way {% now %} does."""
    return formatted_date(timezone.now(), format_string)


def striptags(value: object) -> Markup | str:
    """Django's striptags filter: drop the tags, keep already-safe text safe.

    A form's error list renders as HTML with its messages escaped; stripping
    the tags leaves text that must not be escaped a second time.
    """
    stripped = strip_tags(str(value))
    if hasattr(value, "__html__"):
        return Markup(stripped)
    return stripped


def user_initials(user: AbstractBaseUser | AnonymousUser | None) -> str:
    """The two letters the supplied design shows in the avatar circle."""
    first_name = getattr(user, "first_name", "") or ""
    last_name = getattr(user, "last_name", "") or ""
    if first_name and last_name:
        return (first_name[0] + last_name[0]).upper()

    username = getattr(user, "get_username", str)() or ""
    return username[:2].upper() or "U"


def display_name(user: AbstractBaseUser | AnonymousUser | None) -> str:
    """The full name when the account has one, otherwise the username."""
    if user is None or not getattr(user, "is_authenticated", False):
        return "Foydalanuvchi"

    return user.get_full_name() or user.get_username()


def profile_for(user: AbstractBaseUser | AnonymousUser | None) -> UserProfile | None:
    """The profile joined onto a listed user, or None when they have none.

    Reads the related object already fetched with select_related and never
    creates one: a template must not write to the database.
    """
    try:
        return user.profile
    except (UserProfile.DoesNotExist, AttributeError):
        return None


# A page whose link says something else to the people it means something else
# to. Qabul Qilingan Arizalar is a Bo`lim Boshlig`i's own approvals when they
# are outside the purchasing department, so their sidebar says so.
APPROVER_LABELS = {"qabul-arizalar": "Tasdiqlangan"}


def navigation_groups(user: AbstractBaseUser | AnonymousUser | None) -> list[NavigationGroup]:
    """The sidebar groups this user may actually follow.

    A link to a page that answers 403 invites a visitor to discover what they
    are not allowed to do. Groups left with no entries are dropped.

    An entry is relabelled where the page behind it is a different page for
    this reader, so the sidebar and the heading it leads to agree.
    """
    labels = APPROVER_LABELS if sees_own_approvals(user) else {}
    permitted = permitted_pages(user)

    permitted_groups = []
    for group in SIDEBAR_NAVIGATION:
        entries = tuple(
            replace(entry, label=labels[entry.page_name])
            if entry.page_name in labels
            else entry
            for entry in group.entries
            if entry.page_name in permitted
        )
        if entries:
            permitted_groups.append(NavigationGroup(group.label, entries))
    return permitted_groups


def unread_notification_count(user: AbstractBaseUser | AnonymousUser | None) -> int:
    """How many notifications this person has not been shown (DEC-012).

    Imported inside the function rather than at the top: xarid.notifications
    reaches the models, and this module is imported while the template
    environment is built, before the app registry is ready.
    """
    from xarid.notifications import unread_for

    return unread_for(user)


def phone_number(value: str | None) -> str:
    """A profile's number in the dashed form the Users form now writes.

    Imported inside the function for the same reason as the count above:
    xarid.forms reaches the models, and this module is imported while the
    template environment is built.
    """
    from xarid.forms import dashed_phone_number

    return dashed_phone_number(value or "")


def languages() -> list[tuple[str, str]]:
    """The languages the picker offers, as (code, name) in settings order."""
    return list(settings.LANGUAGES)


def language_code() -> str:
    """The language this page is being rendered in."""
    return translation.get_language() or settings.LANGUAGE_CODE


def environment(**options: Any) -> Environment:
    """Build the environment Django's Jinja2 backend asks for.

    The i18n extension is installed against Django's own translation module,
    so a template's _() follows the language LocaleMiddleware settled on for
    this request - and newstyle, so a marked string may carry the values it
    interpolates, and they are escaped as the rest of the template is.
    """
    options.setdefault("extensions", [])
    options["extensions"] = [*options["extensions"], "jinja2.ext.i18n"]
    env = Environment(**options)
    env.install_gettext_translations(translation, newstyle=True)
    env.globals.update(
        {
            "static": static,
            "url": url,
            "now": now,
            "navigation_groups": navigation_groups,
            "user_initials": user_initials,
            "user_type_name": user_type_name_of,
            "display_name": display_name,
            "profile_for": profile_for,
            "unread_notifications": unread_notification_count,
            "languages": languages,
            "language_code": language_code,
        }
    )
    env.filters.update(
        {"date": formatted_date, "striptags": striptags, "phone_number": phone_number}
    )
    return env
