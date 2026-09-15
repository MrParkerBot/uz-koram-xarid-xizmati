"""Tests for the supplied front-end assets delivered by TASK-UZK-004.

The assets shipped with the technical assignment are served as-is rather than
rebuilt, so the interface the customer approved survives the move to Django.
These tests fetch each one over real HTTP, because a staticfiles configuration
that merely looks right is the kind that fails only in the browser.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from urllib.request import urlopen

from django.contrib.staticfiles import finders
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.management import call_command
from django.test import SimpleTestCase, override_settings

# Every asset supplied with the specification, and the content type a browser
# must receive for it. A woff2 served as text/plain is a font the browser
# refuses to use.
SUPPLIED_ASSETS: dict[str, str] = {
    "css/bootstrap.min.css": "text/css",
    "css/bootstrap-icons.css": "text/css",
    "css/style.css": "text/css",
    "css/fonts/bootstrap-icons.woff": "font/woff",
    "css/fonts/bootstrap-icons.woff2": "font/woff2",
    "js/bootstrap.bundle.min.js": "text/javascript",
    "js/main.js": "text/javascript",
    "js/sidebar.js": "text/javascript",
}


class SuppliedAssetDeliveryTests(StaticLiveServerTestCase):
    """Each supplied asset must come back over HTTP, not merely exist on disk.

    These go over the wire to the live server rather than through the test
    client, because the test client routes through the URL configuration and
    would answer with a 404 page instead of the file.
    """

    # Bind and connect over IPv4 explicitly. The default host "localhost"
    # resolves to ::1 first on Windows while the server listens on IPv4, so
    # every request waits out a connection timeout before falling back. That
    # alone took the suite from under a second to fifty.
    host = "127.0.0.1"

    def fetch_asset(self, asset_path: str):
        """Fetch one asset from the live server and return the open response."""
        return urlopen(f"{self.live_server_url}/static/{asset_path}")

    def test_every_supplied_asset_is_served(self) -> None:
        for asset_path in SUPPLIED_ASSETS:
            with (
                self.subTest(asset=asset_path),
                self.fetch_asset(asset_path) as response,
            ):
                self.assertEqual(response.status, 200)

    def test_every_supplied_asset_is_served_with_a_usable_content_type(self) -> None:
        for asset_path, expected_type in SUPPLIED_ASSETS.items():
            with (
                self.subTest(asset=asset_path),
                self.fetch_asset(asset_path) as response,
            ):
                served_type = response.headers["Content-Type"].split(";")[0]

                self.assertEqual(served_type, expected_type)

    def test_served_assets_are_not_empty(self) -> None:
        for asset_path in SUPPLIED_ASSETS:
            with (
                self.subTest(asset=asset_path),
                self.fetch_asset(asset_path) as response,
            ):
                self.assertGreater(len(response.read()), 0)


class IconFontResolutionTests(SimpleTestCase):
    """bootstrap-icons.css asks for its font files by a relative path, so the
    fonts have to sit beside the stylesheet or every icon renders as a box."""

    def test_the_icon_stylesheet_requests_fonts_from_a_relative_path(self) -> None:
        stylesheet_path = finders.find("css/bootstrap-icons.css")
        self.assertIsNotNone(stylesheet_path)

        stylesheet = Path(stylesheet_path).read_text(encoding="utf-8")

        self.assertIn("./fonts/bootstrap-icons.woff2", stylesheet)

    def test_both_icon_font_files_resolve_beside_the_stylesheet(self) -> None:
        for font_path in ("css/fonts/bootstrap-icons.woff",
                          "css/fonts/bootstrap-icons.woff2"):
            with self.subTest(font=font_path):
                self.assertIsNotNone(finders.find(font_path))


class StaticCollectionTests(SimpleTestCase):
    """Collection must gather the assets without anyone copying files by hand."""

    def test_collectstatic_gathers_every_supplied_asset(self) -> None:
        collection_root = Path(tempfile.mkdtemp())
        try:
            with override_settings(STATIC_ROOT=collection_root):
                call_command("collectstatic", interactive=False, verbosity=0)

            for asset_path in SUPPLIED_ASSETS:
                with self.subTest(asset=asset_path):
                    self.assertTrue((collection_root / asset_path).is_file())
        finally:
            shutil.rmtree(collection_root, ignore_errors=True)
