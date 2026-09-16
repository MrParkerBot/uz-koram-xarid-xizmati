"""Tests for the page routing and sidebar navigation of TASK-UZK-007.

The sidebar used to be built in the browser from a list of .html filenames.
Now Django renders it from config/navigation.py, so the thing worth pinning is
that the navigation, the URL configuration and the templates on disk all still
describe the same set of pages - and that a link in the sidebar leads to a page
that answers.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings
from django.template.loader import render_to_string
from django.test import SimpleTestCase
from django.urls import NoReverseMatch, reverse

from config.navigation import SIDEBAR_NAVIGATION, navigation_url_names
from config.test_support import SignedInTestCase

PAGE_TEMPLATE_DIR = Path(settings.BASE_DIR) / "templates" / "pages"

HTML_LINK = re.compile(r'href="[^"]*\.html"')

# Pages that exist but do not belong in the sidebar. The login screen is
# the only one: it is where a visitor arrives before there is a sidebar to
# put a link in.
PAGES_OUTSIDE_THE_NAVIGATION = {"login"}


class NavigationInventoryTests(SimpleTestCase):
    """The navigation, the URLs and the templates describe one set of pages."""

    def test_every_navigation_entry_names_a_url_that_reverses(self) -> None:
        for url_name in navigation_url_names():
            with self.subTest(url_name=url_name):
                try:
                    reverse(url_name)
                except NoReverseMatch:  # pragma: no cover - failure path
                    self.fail(f"{url_name} is in the sidebar but has no URL.")

    def test_the_navigation_covers_every_page_template(self) -> None:
        templates_on_disk = {path.stem for path in PAGE_TEMPLATE_DIR.glob("*.html")}

        self.assertEqual(
            set(navigation_url_names()),
            templates_on_disk - PAGES_OUTSIDE_THE_NAVIGATION,
        )

    def test_no_entry_appears_in_the_sidebar_twice(self) -> None:
        url_names = navigation_url_names()

        self.assertEqual(len(url_names), len(set(url_names)))

    def test_every_group_has_at_least_one_entry(self) -> None:
        # An empty group renders a heading with nothing under it, which is what
        # the supplied script went out of its way to avoid.
        for group in SIDEBAR_NAVIGATION:
            with self.subTest(group=group.label):
                self.assertTrue(group.entries)


class PageResponseTests(SignedInTestCase):
    """Every page the sidebar offers has to answer."""

    def test_every_page_returns_ok(self) -> None:
        for url_name in navigation_url_names():
            with self.subTest(url_name=url_name):
                response = self.client.get(reverse(url_name))

                self.assertEqual(response.status_code, 200)

    def test_every_page_renders_its_own_template(self) -> None:
        for url_name in navigation_url_names():
            with self.subTest(url_name=url_name):
                response = self.client.get(reverse(url_name))

                self.assertTemplateUsed(response, f"pages/{url_name}.html")

    def test_an_unknown_url_returns_not_found(self) -> None:
        response = self.client.get("/no-such-page/")

        self.assertEqual(response.status_code, 404)

    def test_an_unknown_url_is_not_turned_into_a_login_prompt(self) -> None:
        # LoginRequiredMiddleware acts on resolved views, so a URL that matches
        # nothing must still be a 404 for a visitor with no session - otherwise
        # every typo becomes an invitation to sign in.
        self.client.logout()

        response = self.client.get("/no-such-page/")

        self.assertEqual(response.status_code, 404)


class ActiveEntryTests(SignedInTestCase):
    """The sidebar has to say which page you are looking at."""

    def active_labels(self, rendered_page: str) -> list[str]:
        """The labels of every sidebar entry marked active in this page."""
        return re.findall(
            r'class="nav-link active"[^>]*>.*?<span class="label-text">(.*?)</span>',
            rendered_page,
        )

    def test_the_current_page_is_the_only_active_entry(self) -> None:
        for url_name in navigation_url_names():
            with self.subTest(url_name=url_name):
                response = self.client.get(reverse(url_name))

                self.assertEqual(
                    len(self.active_labels(response.content.decode())), 1
                )

    def test_the_active_entry_is_the_one_for_the_current_page(self) -> None:
        response = self.client.get(reverse("logs"))

        self.assertEqual(self.active_labels(response.content.decode()), ["Logs"])

    def test_nothing_is_active_when_rendering_without_a_request(self) -> None:
        # A page rendered to a string outside a view has no resolved URL. It
        # must still produce a navigation rather than an error.
        shell = render_to_string("base.html")

        self.assertIn('class="nav-link"', shell)
        self.assertNotIn("nav-link active", shell)


class StaticLinkTests(SignedInTestCase):
    """Nothing may still point at a page as though it were a file."""

    def all_templates(self) -> list[Path]:
        return sorted(Path(settings.BASE_DIR).glob("templates/**/*.html"))

    def test_no_template_links_to_an_html_file(self) -> None:
        for template_path in self.all_templates():
            source = template_path.read_text(encoding="utf-8")
            with self.subTest(template=template_path.name):
                self.assertEqual(HTML_LINK.findall(source), [])

    def test_no_rendered_page_contains_an_html_link(self) -> None:
        # The templates could be clean while a script writes such a link at
        # runtime; this catches the ones written into the markup.
        for url_name in navigation_url_names():
            response = self.client.get(reverse(url_name))
            with self.subTest(url_name=url_name):
                self.assertEqual(
                    HTML_LINK.findall(response.content.decode()), []
                )
