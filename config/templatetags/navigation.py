"""Renders the sidebar navigation into the shared shell."""

from __future__ import annotations

from typing import Any

from django import template

from accounts.permissions import may_open
from config.navigation import SIDEBAR_NAVIGATION, NavigationGroup

register = template.Library()


def active_url_name(context: template.Context) -> str | None:
    """The URL name of the page being rendered, if there is a request.

    The shell is rendered without a request in several tests, and a page can
    be rendered to a string outside a view. Both must produce a navigation
    with nothing marked active rather than an error.
    """
    request = context.get("request")
    resolver_match = getattr(request, "resolver_match", None)
    return getattr(resolver_match, "url_name", None)


def groups_for(user: Any) -> list[NavigationGroup]:
    """The navigation this user may actually follow.

    A link to a page that answers 403 is worse than no link: it invites a
    visitor to discover what they are not allowed to do. Groups left with no
    entries are dropped, exactly as the supplied sidebar.js did, so that no
    heading stands over nothing.
    """
    permitted_groups = []
    for group in SIDEBAR_NAVIGATION:
        entries = tuple(
            entry for entry in group.entries if may_open(user, entry.url_name)
        )
        if entries:
            permitted_groups.append(NavigationGroup(group.label, entries))
    return permitted_groups


@register.inclusion_tag("navigation/sidebar.html", takes_context=True)
def sidebar_navigation(context: template.Context) -> dict[str, Any]:
    """Supply the sidebar groups and the name of the entry to mark active."""
    return {
        "navigation_groups": groups_for(context.get("user")),
        "active_url_name": active_url_name(context),
    }


@register.filter
def user_initials(user: Any) -> str:
    """The two letters the supplied design shows in the avatar circle.

    Built from the first and last name when the account has them, from the
    username otherwise, and left as a single neutral letter for a visitor who
    is not signed in - the circle is never empty in the supplied design.
    """
    first_name = getattr(user, "first_name", "") or ""
    last_name = getattr(user, "last_name", "") or ""
    if first_name and last_name:
        return (first_name[0] + last_name[0]).upper()

    username = getattr(user, "get_username", str)() or ""
    return username[:2].upper() or "U"
