"""Tests for the shared page shell delivered by TASK-UZK-005.

The shell is transcribed from the static pages supplied with the technical
assignment, and the vendored style.css keys off those exact class names. A
dropped class produces no error anywhere - it just renders wrong - so the
landmarks, the block positions and the asset references are pinned here.
"""

from __future__ import annotations

import re

from django.contrib.staticfiles import finders
from django.template import Context, Template
from django.template.loader import render_to_string
from django.templatetags.static import static
from django.test import SimpleTestCase

# The elements the supplied pages are built around. Each appears as the sole
# class on its element, which is why an exact attribute match is safe here.
SHELL_LANDMARKS = (
    "app-shell",
    "sidebar",
    "main-shell",
    "top-header",
    "page-wrap",
)

# Marker text used by the child template below, kept distinct so that a search
# for it cannot collide with the shell's own markup.
CHILD_CONTENT_MARKER = "child-page-marker"
CHILD_HEAD_ASSET = "https://example.invalid/page-only.css"
CHILD_SCRIPT_ASSET = "https://example.invalid/page-only.js"

# A page that fills every block, standing in for the real ones converted in
# TASK-UZK-006. Written as concatenation rather than a formatted string,
# because a template tag's "{%" is not something str.format or an f-string can
# carry.
CHILD_TEMPLATE = (
    '{% extends "base.html" %}'
    "{% block page_title %}Bo'limlar Xaridi{% endblock %}"
    "{% block breadcrumb %}Hisobotlar / Bo'limlar Xaridi{% endblock %}"
    "{% block page_heading %}Bo'limlar Xaridi{% endblock %}"
    '{% block extra_head %}<link rel="stylesheet" href="'
    + CHILD_HEAD_ASSET
    + '"/>{% endblock %}'
    '{% block content %}<p class="'
    + CHILD_CONTENT_MARKER
    + '">Sahifa tarkibi</p>{% endblock %}'
    '{% block extra_scripts %}<script src="'
    + CHILD_SCRIPT_ASSET
    + '"></script>{% endblock %}'
)

# Matches either quoting style. The shell is written with double quotes
# throughout, but a guard that only sees one of the two would pass on
# exactly the edit it exists to catch.
REFERENCE_PATTERN = re.compile(r"""(?:href|src)=["']([^"']+)["']""")


def render_shell() -> str:
    """Render base.html on its own, with no page extending it."""
    return render_to_string("base.html")


def render_child_page() -> str:
    """Render a page that extends the shell and fills every block."""
    return Template(CHILD_TEMPLATE).render(Context())


def referenced_urls(markup: str) -> list[str]:
    """Every URL the markup links to or loads, in document order."""
    return REFERENCE_PATTERN.findall(markup)


def locally_served_assets(markup: str) -> list[str]:
    """The asset paths the markup loads from this application's static files.

    Returns each path as the static finders know it - 'css/style.css' rather
    than '/static/css/style.css' - so it can be handed straight to a finder.
    """
    static_prefix = static("")
    return [
        url.removeprefix(static_prefix)
        for url in referenced_urls(markup)
        if url.startswith(static_prefix)
    ]


class ShellRenderingTests(SimpleTestCase):
    """The shell has to stand on its own before anything can extend it."""

    def test_the_shell_renders_without_a_page_extending_it(self) -> None:
        shell = render_shell()

        for landmark in SHELL_LANDMARKS:
            with self.subTest(landmark=landmark):
                self.assertIn(f'class="{landmark}"', shell)

    def test_the_shell_survives_a_page_extending_it(self) -> None:
        page = render_child_page()

        for landmark in SHELL_LANDMARKS:
            with self.subTest(landmark=landmark):
                self.assertIn(f'class="{landmark}"', page)

    def test_the_navigation_list_is_left_for_a_later_task_to_fill(self) -> None:
        # TASK-UZK-007 owns navigation. Until then the vendored sidebar.js
        # fills this element, exactly as it does in the supplied pages.
        self.assertIn('<nav class="sidebar-nav"></nav>', render_shell())


class PageBlockTests(SimpleTestCase):
    """Each block has to land in the part of the shell that page needs."""

    def test_the_page_title_completes_the_shared_title_suffix(self) -> None:
        self.assertIn(
            "<title>Bo'limlar Xaridi - Uz-Koram</title>", render_child_page()
        )

    def test_the_title_has_a_usable_default(self) -> None:
        self.assertIn(
            "<title>Xarid Xizmati Bo'limi - Uz-Koram</title>", render_shell()
        )

    def test_the_breadcrumb_and_heading_land_in_the_top_header(self) -> None:
        page = render_child_page()
        header_start = page.index('class="top-header"')
        header_end = page.index("</header>")
        header = page[header_start:header_end]

        self.assertIn("Hisobotlar / Bo'limlar Xaridi", header)
        self.assertIn('class="fw-semibold">Bo\'limlar Xaridi', header)

    def test_the_page_content_lands_inside_the_page_wrapper(self) -> None:
        page = render_child_page()

        content_position = page.index(CHILD_CONTENT_MARKER)

        self.assertLess(page.index('class="page-wrap"'), content_position)
        self.assertLess(content_position, page.index("</main>"))

    def test_extra_head_content_lands_inside_the_document_head(self) -> None:
        # The dashboard loads Chart.js from its head, so a page needs somewhere
        # to put a head asset without editing the shell.
        page = render_child_page()

        self.assertLess(page.index(CHILD_HEAD_ASSET), page.index("</head>"))

    def test_extra_scripts_run_after_the_shared_scripts(self) -> None:
        # A page script that ran before main.js would find none of the helpers
        # the supplied pages call.
        page = render_child_page()

        self.assertLess(
            page.index(static("js/main.js")), page.index(CHILD_SCRIPT_ASSET)
        )
        self.assertLess(page.index(CHILD_SCRIPT_ASSET), page.index("</body>"))


class ShellAssetReferenceTests(SimpleTestCase):
    """Asset references have to go through the static mechanism.

    The supplied pages link their assets by relative path, which works only
    because every page sits in one flat directory. Copied into a template
    unchanged, those paths resolve against the page URL and break on every
    page that is not served from the site root.
    """

    def test_every_supplied_shell_asset_is_referenced(self) -> None:
        expected_assets = {
            "css/bootstrap.min.css",
            "css/bootstrap-icons.css",
            "css/style.css",
            "js/bootstrap.bundle.min.js",
            "js/main.js",
            "js/sidebar.js",
        }

        self.assertEqual(set(locally_served_assets(render_shell())), expected_assets)

    def test_every_referenced_asset_is_found_by_the_static_finders(self) -> None:
        for asset_path in locally_served_assets(render_shell()):
            with self.subTest(asset=asset_path):
                self.assertIsNotNone(
                    finders.find(asset_path),
                    f"{asset_path} is referenced by the shell but is not a "
                    "static file this application serves.",
                )

    def test_no_asset_is_referenced_by_a_path_relative_to_the_page(self) -> None:
        for url in referenced_urls(render_shell()):
            with self.subTest(url=url):
                self.assertFalse(
                    url.startswith(("css/", "js/", "./", "../")),
                    f"{url} resolves against the page URL rather than "
                    "STATIC_URL and breaks outside the site root.",
                )
