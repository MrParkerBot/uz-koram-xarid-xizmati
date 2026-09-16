"""Showing a user's role in a template."""

from __future__ import annotations

from typing import Any

from django import template

from accounts.roles import user_type_name_of

register = template.Library()


@register.filter
def user_type_name(user: Any) -> str:
    """The signed-in user's User Type, or an empty string when they have none.

    Empty rather than a placeholder, so that the template decides what to show
    instead - the header falls back to the username.
    """
    return user_type_name_of(user)
