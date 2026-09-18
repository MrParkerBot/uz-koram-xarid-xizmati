"""Tests for the routing: the namespace, the sidebar, static files and templates."""

from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path
from urllib.request import urlopen

from django.conf import settings
from django.contrib.staticfiles import finders
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import NoReverseMatch, resolve, reverse

from tests.support import SignedInAdminTestCase, page
from xarid.navigation import SIDEBAR_NAVIGATION, navigation_page_names
from xarid.permissions import all_known_pages
from xarid.urls import urlpatterns

TEMPLATE_DIR = Path(settings.BASE_DIR) / "xarid" / "templates"
STATIC_DIR = Path(settings.BASE_DIR) / "xarid" / "static" / "xarid"

# Every asset the pages ask for, and the content type a browser must receive.
NAMESPACED_ASSETS: dict[str, str] = {
    "xarid/css/bootstrap.min.css": "text/css",
    "xarid/css/bootstrap-icons.css": "text/css",
    "xarid/css/style.css": "text/css",
    "xarid/css/fonts/bootstrap-icons.woff": "font/woff",
    "xarid/css/fonts/bootstrap-icons.woff2": "font/woff2",
    "xarid/js/bootstrap.bundle.min.js": "text/javascript",
    "xarid/js/main.js": "text/javascript",
    "xarid/js/pages/dashboard.js": "text/javascript",
}

# An inline handler attribute and everything up to the quote that closes it.
INLINE_HANDLER = re.compile(
    r"""\bon[a-z]+\s*=\s*(?P<quote>["'])(?P<body>.*?)(?P=quote)""",
    re.IGNORECASE | re.DOTALL,
)
TEMPLATE_OUTPUT = re.compile(r"\{\{|\{%")
HTML_LINK = re.compile(r'href="[^"]*\.html"')
DYNAMIC_EVALUATION = re.compile(r"\beval\b|\bnew\s+Function\b")


def every_app_route_name() -> list[str]:
    """Every URL name the application declares."""
    return [pattern.name for pattern in urlpatterns]


class NamespaceTests(SimpleTestCase):
    def test_the_application_urls_are_namespaced(self) -> None:
        self.assertEqual(reverse("xarid:dashboard"), "/")
        self.assertEqual(resolve("/").namespace, "xarid")
        self.assertEqual(resolve("/users/").url_name, "users")

    def test_the_bare_names_no_longer_resolve_globally(self) -> None:
        with self.assertRaises(NoReverseMatch):
            reverse("dashboard")

    def test_the_authentication_and_admin_routes_exist(self) -> None:
        self.assertEqual(reverse("login"), "/accounts/login/")
        self.assertEqual(reverse("logout"), "/accounts/logout/")
        self.assertEqual(reverse("password_change"), "/accounts/password_change/")
        self.assertEqual(reverse("admin:index"), "/admin/")


class SidebarInventoryTests(SimpleTestCase):
    """The sidebar, the URLs and the permission matrix describe one set of pages."""

    def test_every_sidebar_entry_reverses(self) -> None:
        for page_name in navigation_page_names():
            with self.subTest(page=page_name):
                page(page_name)

    def test_the_permission_matrix_has_an_answer_for_every_sidebar_page(self) -> None:
        self.assertEqual(all_known_pages(), set(navigation_page_names()))

    def test_no_entry_appears_twice_and_no_group_is_empty(self) -> None:
        names = navigation_page_names()
        self.assertEqual(len(names), len(set(names)))
        for group in SIDEBAR_NAVIGATION:
            with self.subTest(group=group.label):
                self.assertTrue(group.entries)


class PageResponseTests(SignedInAdminTestCase):
    def test_every_sidebar_page_answers_for_an_administrator(self) -> None:
        for page_name in navigation_page_names():
            with self.subTest(page=page_name):
                response = self.client.get(page(page_name))

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "xarid/css/style.css")

    def test_the_current_page_is_the_only_active_sidebar_entry(self) -> None:
        for page_name in navigation_page_names():
            with self.subTest(page=page_name):
                rendered = self.client.get(page(page_name)).content.decode()
                active = re.findall(
                    r'class="nav-link active"[^>]*>.*?<span class="label-text">(.*?)</span>',
                    rendered,
                )
                self.assertEqual(len(active), 1)

        rendered = self.client.get(page("logs")).content.decode()
        self.assertIn('class="nav-link active"><i class="bi bi-journal-code"', rendered)

    def test_an_unknown_url_is_a_not_found_whether_or_not_signed_in(self) -> None:
        self.assertEqual(self.client.get("/no-such-page/").status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get("/no-such-page/").status_code, 404)

    def test_no_rendered_page_links_to_an_html_file(self) -> None:
        for page_name in navigation_page_names():
            with self.subTest(page=page_name):
                rendered = self.client.get(page(page_name)).content.decode()
                self.assertEqual(HTML_LINK.findall(rendered), [])


class ClosedRouteTests(TestCase):
    """Every application route is closed to a visitor with no session."""

    def test_every_route_redirects_an_anonymous_visitor_to_the_login_page(self) -> None:
        for name in every_app_route_name():
            with self.subTest(route=name):
                try:
                    target = page(name)
                except NoReverseMatch:
                    target = page(name, 1)

                response = self.client.get(target)

                self.assertEqual(response.status_code, 302)
                self.assertTrue(response.url.startswith(reverse("login")))
                self.assertIn(f"next={target}", response.url)


class StaticAssetTests(StaticLiveServerTestCase):
    """The vendored assets are served under the application's namespace."""

    host = "127.0.0.1"

    def test_every_asset_is_served_with_a_usable_content_type(self) -> None:
        for asset_path, expected_type in NAMESPACED_ASSETS.items():
            with (
                self.subTest(asset=asset_path),
                urlopen(f"{self.live_server_url}/static/{asset_path}") as response,
            ):
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers["Content-Type"].split(";")[0], expected_type)
                self.assertGreater(len(response.read()), 0)

    def test_the_login_page_can_style_itself_anonymously(self) -> None:
        with urlopen(f"{self.live_server_url}{reverse('login')}") as response:
            rendered = response.read().decode()

        self.assertIn("/static/xarid/css/style.css", rendered)
        self.assertIn("/static/xarid/js/main.js", rendered)


class StaticLayoutTests(SimpleTestCase):
    def test_the_icon_font_sits_beside_its_stylesheet(self) -> None:
        stylesheet = Path(finders.find("xarid/css/bootstrap-icons.css")).read_text(
            encoding="utf-8"
        )

        self.assertIn("./fonts/bootstrap-icons.woff2", stylesheet)
        self.assertIsNotNone(finders.find("xarid/css/fonts/bootstrap-icons.woff2"))

    def test_nothing_is_served_from_an_un_namespaced_path(self) -> None:
        self.assertIsNone(finders.find("css/style.css"))
        self.assertIsNone(finders.find("js/main.js"))

    def test_collectstatic_gathers_every_asset(self) -> None:
        collection_root = Path(tempfile.mkdtemp())
        try:
            with override_settings(STATIC_ROOT=collection_root):
                call_command("collectstatic", interactive=False, verbosity=0)

            for asset_path in NAMESPACED_ASSETS:
                with self.subTest(asset=asset_path):
                    self.assertTrue((collection_root / asset_path).is_file())
        finally:
            shutil.rmtree(collection_root, ignore_errors=True)


class TemplateHygieneTests(SimpleTestCase):
    """A rendered value must never land in JavaScript source."""

    def all_templates(self) -> list[Path]:
        return sorted(TEMPLATE_DIR.glob("**/*.html"))

    def test_there_are_templates_to_check(self) -> None:
        self.assertGreater(len(self.all_templates()), 20)

    def test_no_template_renders_a_value_into_an_inline_handler(self) -> None:
        for template in self.all_templates():
            source = template.read_text(encoding="utf-8")
            for handler in INLINE_HANDLER.finditer(source):
                body = handler.group("body")
                with self.subTest(template=template.name, handler=body[:60]):
                    self.assertIsNone(TEMPLATE_OUTPUT.search(body))

    def test_no_template_carries_an_inline_script_block(self) -> None:
        for template in self.all_templates():
            with self.subTest(template=template.name):
                self.assertNotIn("<script>", template.read_text(encoding="utf-8"))

    def test_no_template_links_to_an_html_file(self) -> None:
        for template in self.all_templates():
            with self.subTest(template=template.name):
                self.assertEqual(HTML_LINK.findall(template.read_text(encoding="utf-8")), [])

    def test_every_page_template_extends_the_shared_base(self) -> None:
        for template in self.all_templates():
            if template.name in ("base.html", "_forms.html"):
                continue
            with self.subTest(template=template.name):
                self.assertIn(
                    '{% extends "xarid/base.html" %}', template.read_text(encoding="utf-8")
                )

    def test_the_shared_script_reads_the_confirmation_rather_than_evaluating_it(self) -> None:
        handler = (STATIC_DIR / "js" / "main.js").read_text(encoding="utf-8")

        self.assertIn("form.dataset.confirm", handler)
        self.assertIsNone(DYNAMIC_EVALUATION.search(handler))
