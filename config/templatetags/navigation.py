"""Renders the sidebar navigation into the shared shell."""

from __future__ import annotations

from typing import Any

from django import template

from config.navigation import SIDEBAR_NAVIGATION

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


@register.inclusion_tag("navigation/sidebar.html", takes_context=True)
def sidebar_navigation(context: template.Context) -> dict[str, Any]:
    """Supply the sidebar groups and the name of the entry to mark active."""
    return {
        "navigation_groups": SIDEBAR_NAVIGATION,
        "active_url_name": active_url_name(context),
    }
