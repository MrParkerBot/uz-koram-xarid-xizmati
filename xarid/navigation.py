"""The sidebar navigation rendered on every page.

The structure - which pages appear, in which group, under which label and icon
- is the one the customer approved in the supplied prototype. Django renders it
from here so every entry points at a URL the application actually serves.

Entries name the bare page name; the URL is reversed under the "xarid"
namespace and the permission matrix in permissions.py is keyed by the same
names.
"""

from __future__ import annotations

from dataclasses import dataclass


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
        "Umumiy",
        (NavigationEntry("Dashboard", "bi-speedometer2", "dashboard"),),
    ),
    NavigationGroup(
        "Ma'lumotlar",
        (
            NavigationEntry("User Specialty", "bi-mortarboard", "user-specialty"),
            NavigationEntry("User Types", "bi-person-badge", "user-types"),
            NavigationEntry("Foydalanuvchilar", "bi-people", "users"),
            NavigationEntry("Ariza Status", "bi-flag", "ariza-status"),
            NavigationEntry("Shartnoma Status", "bi-clipboard-check", "shartnoma-status"),
            NavigationEntry("Mahsulot Turlari", "bi-collection", "mahsulot-turlari"),
            NavigationEntry("Shartnoma Turi", "bi-file-earmark-text", "shartnoma-turi"),
            # Not in the supplied sidebar: DEC-018 makes departments
            # Admin-maintained master data and the specification gives them
            # no page, so without this they could only be created from a shell.
            NavigationEntry("Bo'limlar", "bi-diagram-3", "bolim-royhati"),
            # Likewise for suppliers (DEC-011).
            NavigationEntry("Firmalar", "bi-shop", "firmalar"),
        ),
    ),
    NavigationGroup(
        "Arizalar",
        (
            NavigationEntry("Kelib Tushgan", "bi-inbox", "kelib-arizalar"),
            NavigationEntry("Qabul Qilingan", "bi-check2-circle", "qabul-arizalar"),
            NavigationEntry("Tayinlangan", "bi-pin-angle", "tayinlangan"),
        ),
    ),
    NavigationGroup(
        "Shartnomalar",
        (
            NavigationEntry("Kelishinlingan", "bi-file-earmark-check", "kelishinlingan"),
            NavigationEntry("Tuzilgan", "bi-journal-text", "tuzilgan"),
        ),
    ),
    NavigationGroup(
        "Hisobotlar",
        (
            NavigationEntry("Xodimlar Yuklamasi", "bi-graph-up-arrow", "xodimlar-yuklamasi"),
            NavigationEntry("Bo'limlar", "bi-buildings", "bolimlar"),
            NavigationEntry("Mahsulot Turi", "bi-box-seam", "mahsulot-tur"),
            NavigationEntry("Mahsulotlar", "bi-search", "mahsulotlar"),
            NavigationEntry("Xarid Arizasi", "bi-cart3", "xarid-ariza"),
        ),
    ),
    NavigationGroup(
        "Tizim",
        (
            NavigationEntry("1C Integratsiya", "bi-plug", "integration"),
            NavigationEntry("Logs", "bi-journal-code", "logs"),
        ),
    ),
)


def navigation_page_names() -> tuple[str, ...]:
    """Every page name the sidebar links to, in the order it renders them."""
    return tuple(entry.page_name for group in SIDEBAR_NAVIGATION for entry in group.entries)
