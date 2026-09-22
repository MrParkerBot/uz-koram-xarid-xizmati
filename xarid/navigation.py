"""The sidebar navigation rendered on every page.

The structure - which pages appear, in which group, under which label and icon
- is the one the customer approved in the supplied prototype. Django renders it
from here so every entry points at a URL the application actually serves.

Entries name the bare page name; the URL is reversed under the "xarid"
namespace and the permission matrix in permissions.py is keyed by the same
names.

The labels are marked for translation and translated when they are drawn: the
tree is built once at import, and the reader's language is not known until a
request arrives.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.utils.translation import gettext_lazy


@dataclass(frozen=True)
class NavigationEntry:
    """One link in the sidebar."""

    label: str
    icon: str
    page_name: str


@dataclass(frozen=True)
class NavigationGroup:
    """A labelled run of links, rendered under a section heading."""

    label: str
    entries: tuple[NavigationEntry, ...]


SIDEBAR_NAVIGATION: tuple[NavigationGroup, ...] = (
    NavigationGroup(
        gettext_lazy("Umumiy"),
        (NavigationEntry(gettext_lazy("Dashboard"), "bi-speedometer2", "dashboard"),),
    ),
    NavigationGroup(
        gettext_lazy("Ma'lumotlar"),
        (
            NavigationEntry(gettext_lazy("User Specialty"), "bi-mortarboard", "user-specialty"),
            NavigationEntry(gettext_lazy("User Types"), "bi-person-badge", "user-types"),
            NavigationEntry(gettext_lazy("Foydalanuvchilar"), "bi-people", "users"),
            NavigationEntry(gettext_lazy("Ariza Status"), "bi-flag", "ariza-status"),
            NavigationEntry(gettext_lazy("Shartnoma Status"), "bi-clipboard-check", "shartnoma-status"),
            NavigationEntry(gettext_lazy("Mahsulot Turlari"), "bi-collection", "mahsulot-turlari"),
            NavigationEntry(gettext_lazy("Shartnoma Turi"), "bi-file-earmark-text", "shartnoma-turi"),
            # Not in the supplied sidebar: DEC-018 makes departments
            # Admin-maintained master data and the specification gives them
            # no page, so without this they could only be created from a shell.
            NavigationEntry(gettext_lazy("Bo'limlar"), "bi-diagram-3", "bolim-royhati"),
            # Likewise for suppliers (DEC-011).
            NavigationEntry(gettext_lazy("Firmalar"), "bi-shop", "firmalar"),
        ),
    ),
    NavigationGroup(
        gettext_lazy("Arizalar"),
        (
            NavigationEntry(gettext_lazy("Kelib Tushgan"), "bi-inbox", "kelib-arizalar"),
            NavigationEntry(gettext_lazy("Qabul Qilingan"), "bi-check2-circle", "qabul-arizalar"),
            NavigationEntry(gettext_lazy("Tayinlangan"), "bi-pin-angle", "tayinlangan"),
        ),
    ),
    NavigationGroup(
        gettext_lazy("Shartnomalar"),
        (
            NavigationEntry(gettext_lazy("Kelishinlingan"), "bi-file-earmark-check", "kelishinlingan"),
            NavigationEntry(gettext_lazy("Tuzilgan"), "bi-journal-text", "tuzilgan"),
            # Admin alone sees this one; the sidebar draws what the reader
            # may open, so for everybody else the group is two entries
            # (TASK-UZK-064).
            NavigationEntry(gettext_lazy("O'chirilgan"), "bi-trash", "ochirilgan-shartnomalar"),
        ),
    ),
    NavigationGroup(
        gettext_lazy("Hisobotlar"),
        (
            NavigationEntry(gettext_lazy("Xodimlar Yuklamasi"), "bi-graph-up-arrow", "xodimlar-yuklamasi"),
            NavigationEntry(gettext_lazy("Bo'limlar"), "bi-buildings", "bolimlar"),
            NavigationEntry(gettext_lazy("Mahsulot Turi"), "bi-box-seam", "mahsulot-tur"),
            NavigationEntry(gettext_lazy("Mahsulotlar"), "bi-search", "mahsulotlar"),
            # Not in the supplied sidebar: REQ-DASH-005 asks for Top suppliers
            # as a page of its own, and the dashboard panel links to it.
            NavigationEntry(gettext_lazy("Top Yetkazib beruvchilar"), "bi-trophy", "top-suppliers"),
            NavigationEntry(gettext_lazy("Xarid Arizasi"), "bi-cart3", "xarid-ariza"),
        ),
    ),
    NavigationGroup(
        gettext_lazy("Tizim"),
        (
            NavigationEntry(gettext_lazy("1C Integratsiya"), "bi-plug", "integration"),
            NavigationEntry(gettext_lazy("Logs"), "bi-journal-code", "logs"),
        ),
    ),
)


def navigation_page_names() -> tuple[str, ...]:
    """Every page name the sidebar links to, in the order it renders them."""
    return tuple(entry.page_name for group in SIDEBAR_NAVIGATION for entry in group.entries)
