"""Tests for the per-role page permissions of TASK-UZK-012.

The matrix is walked in full - every User Type against every page - rather
than sampled, because a permission test that checks the interesting cases is
exactly the one that misses the page somebody forgot to restrict.

The expected sets here are written out literally rather than imported from
accounts/permissions.py. A test that reads the table it is testing proves only
that the table equals itself.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils.crypto import get_random_string

from accounts.models import UserType
from accounts.permissions import all_known_pages, may_open
from accounts.roles import (
    ADMIN,
    BOLIM_BOSHLIGI,
    DIREKTOR,
    KATTA_MUTAXASIS,
    MENEJER,
    USERS,
    assign_user_type,
)
from config.navigation import navigation_url_names

# DEC-015, written out by hand from the decision record.
EXPECTED_PAGES: dict[str, set[str]] = {
    BOLIM_BOSHLIGI: {
        "kelib-arizalar",
        "qabul-arizalar",
        "tayinlangan",
        "kelishinlingan",
        "xarid-ariza",
        "xodimlar-yuklamasi",
        "bolimlar",
        "mahsulot-tur",
        "mahsulotlar",
    },
    KATTA_MUTAXASIS: {
        "tayinlangan",
        "kelishinlingan",
        "xarid-ariza",
        "tuzilgan",
    },
    MENEJER: {
        "dashboard",
        "kelib-arizalar",
        "qabul-arizalar",
        "tayinlangan",
        "kelishinlingan",
        "tuzilgan",
        "xarid-ariza",
        "logs",
    },
    DIREKTOR: {
        "dashboard",
        "kelib-arizalar",
        "tuzilgan",
        "xarid-ariza",
        "logs",
    },
    USERS: {"xarid-ariza"},
}

# The four pages section 11 assigns to nobody, which DEC-015 resolves.
PAGES_SECTION_11_FORGOT = {"dashboard", "logs", "tuzilgan"}


def user_of_type(type_name: str):
    """An account holding one User Type.

    The username is random because several tests want two accounts of the
    same type, and a name derived from the type would collide.
    """
    user = get_user_model().objects.create_user(
        username=f"user.{get_random_string(8).lower()}",
        password=get_random_string(24),
        first_name="Test",
        last_name=type_name,
    )
    assign_user_type(user, UserType.objects.get(name=type_name))
    return user


def sidebar_of(page_markup: str) -> str:
    """Just the navigation, cut out of a rendered page.

    The page body has links of its own - the dashboard's quick tiles point at
    six pages - and they are not what this task filters. Checking the whole
    document would test the wrong thing and pass for the wrong reason.
    """
    navigation = page_markup.split('<nav class="sidebar-nav">', 1)[1]
    return navigation.split("</nav>", 1)[0]


class MatrixTests(TestCase):
    """Every type against every page, as a decision rather than a sample."""

    def test_each_type_may_open_exactly_the_pages_the_decision_names(self) -> None:
        for type_name, permitted in EXPECTED_PAGES.items():
            user = user_of_type(type_name)
            for page in navigation_url_names():
                with self.subTest(user_type=type_name, page=page):
                    self.assertEqual(may_open(user, page), page in permitted)

    def test_admin_may_open_every_page(self) -> None:
        administrator = user_of_type(ADMIN)

        for page in navigation_url_names():
            with self.subTest(page=page):
                self.assertTrue(may_open(administrator, page))

    def test_a_user_with_no_type_may_open_nothing(self) -> None:
        nobody = get_user_model().objects.create_user(
            username="no.type", password=get_random_string(24)
        )

        for page in navigation_url_names():
            with self.subTest(page=page):
                self.assertFalse(may_open(nobody, page))

    def test_every_page_in_the_application_appears_in_the_matrix(self) -> None:
        # A page added without a row here would be Admin-only by accident
        # rather than by decision.
        self.assertEqual(set(navigation_url_names()), set(all_known_pages()))

    def test_the_pages_section_11_forgot_are_decided(self) -> None:
        # UNKNOWN-030: section 11 assigns Dashboard, Logs and Tuzilgan
        # Shartnomalar to nobody. DEC-015 gives them to Menejer and Direktor.
        for page in PAGES_SECTION_11_FORGOT:
            with self.subTest(page=page):
                self.assertTrue(may_open(user_of_type(MENEJER), page))


class PageResponseTests(TestCase):
    """What the matrix means over HTTP."""

    def open_page(self, type_name: str, page: str):
        self.client.force_login(user_of_type(type_name))
        return self.client.get(reverse(page))

    def test_a_permitted_page_answers(self) -> None:
        self.assertEqual(self.open_page(MENEJER, "kelib-arizalar").status_code, 200)

    def test_a_forbidden_page_is_forbidden(self) -> None:
        # Not a redirect: the visitor is signed in, and sending them to the
        # login page would suggest signing in again would help.
        self.assertEqual(self.open_page(USERS, "users").status_code, 403)

    def test_every_forbidden_page_answers_403_for_every_type(self) -> None:
        for type_name, permitted in EXPECTED_PAGES.items():
            forbidden = set(navigation_url_names()) - permitted
            user = user_of_type(type_name)
            self.client.force_login(user)
            for page in sorted(forbidden):
                with self.subTest(user_type=type_name, page=page):
                    self.assertEqual(self.client.get(reverse(page)).status_code, 403)

    def test_changing_a_type_changes_what_opens_without_signing_in_again(
        self,
    ) -> None:
        user = user_of_type(USERS)
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 403)

        assign_user_type(user, UserType.objects.get(name=MENEJER))

        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)


class UsersPageActionTests(TestCase):
    """The Users page is Admin-only, and so is everything it does."""

    def setUp(self) -> None:
        self.requester = user_of_type(USERS)
        self.client.force_login(self.requester)

    def test_the_page_is_forbidden(self) -> None:
        self.assertEqual(self.client.get(reverse("users")).status_code, 403)

    def test_creating_a_user_is_forbidden(self) -> None:
        # The page being closed is not enough: an action reachable by its own
        # URL would let a requester make themselves an administrator.
        response = self.client.post(
            reverse("user-create"),
            {
                "first_name": "Naq",
                "last_name": "Admin",
                "password": get_random_string(24),
                "phone_number": "90 000 00 00",
                "user_type": UserType.objects.get(name=ADMIN).pk,
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(get_user_model().objects.filter(first_name="Naq").exists())

    def test_editing_a_user_is_forbidden(self) -> None:
        victim = user_of_type(ADMIN)

        response = self.client.post(
            reverse("user-update", args=[victim.pk]),
            {
                "first_name": "Taken",
                "last_name": "Over",
                "password": get_random_string(24),
                "phone_number": "90 000 00 00",
                "user_type": "",
            },
        )

        victim.refresh_from_db()

        self.assertEqual(response.status_code, 403)
        self.assertEqual(victim.first_name, "Test")

    def test_deleting_a_user_is_forbidden(self) -> None:
        victim = user_of_type(ADMIN)

        response = self.client.post(reverse("user-delete", args=[victim.pk]))

        victim.refresh_from_db()

        self.assertEqual(response.status_code, 403)
        self.assertTrue(victim.is_active)


class SidebarTests(TestCase):
    """A link to a page that answers 403 is worse than no link."""

    def navigation_seen_by(self, type_name: str) -> str:
        """The sidebar as one account of this type sees it."""
        self.client.force_login(user_of_type(type_name))
        landing_page = sorted(EXPECTED_PAGES[type_name])[0]
        return sidebar_of(self.client.get(reverse(landing_page)).content.decode())

    def test_a_type_sees_only_the_pages_it_may_open(self) -> None:
        for type_name, permitted in EXPECTED_PAGES.items():
            sidebar = self.navigation_seen_by(type_name)
            for page in navigation_url_names():
                link = f'href="{reverse(page)}"'
                with self.subTest(user_type=type_name, page=page):
                    self.assertEqual(link in sidebar, page in permitted)

    def test_an_admin_sees_every_page(self) -> None:
        self.client.force_login(user_of_type(ADMIN))

        sidebar = sidebar_of(
            self.client.get(reverse("dashboard")).content.decode()
        )

        for page in navigation_url_names():
            with self.subTest(page=page):
                self.assertIn(f'href="{reverse(page)}"', sidebar)

    def test_a_heading_never_stands_over_nothing(self) -> None:
        # A requester may open one page, in one group. The other five headings
        # must not be rendered above an empty space.
        self.client.force_login(user_of_type(USERS))

        sidebar = sidebar_of(
            self.client.get(reverse("xarid-ariza")).content.decode()
        )

        self.assertEqual(sidebar.count('class="nav-section-label"'), 1)
        self.assertEqual(sidebar.count('class="nav-link'), 1)
