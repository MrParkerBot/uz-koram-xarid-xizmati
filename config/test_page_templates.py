"""Tests for the page templates converted by TASK-UZK-006.

Twenty of the supplied static pages carry the shell and became templates here;
login.html is the twenty-first and has no shell, so TASK-UZK-008 owns it.

Every page's markup was copied out of the supplied file rather than retyped,
and the conversion was checked by comparing each rendered page with its source
line for line. What these tests pin is the part of that which must keep holding
as the pages change: that each one still renders, still goes through the shell,
and no longer carries a shell of its own.
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.template.loader import render_to_string
from django.test import SimpleTestCase

PAGE_TEMPLATE_DIR = Path(settings.BASE_DIR) / "templates" / "pages"

# The twenty supplied pages that carry the shell. Listed rather than globbed so
# that a template disappearing is a failure instead of a smaller test run.
CONVERTED_PAGES = (
    "ariza-status.html",
    # Not one of the twenty supplied pages: TASK-UZK-020 added it because
    # DEC-018 makes departments Admin-maintained and the specification gives
    # them no page. It carries the shell like the rest, so it is checked here.
    "bolim-royhati.html",
    # Also added rather than supplied: TASK-UZK-021, DEC-011.
    "firmalar.html",
    "bolimlar.html",
    "dashboard.html",
    "integration.html",
    "kelib-arizalar.html",
    "kelishinlingan.html",
    "logs.html",
    "mahsulot-tur.html",
    "mahsulot-turlari.html",
    "mahsulotlar.html",
    "qabul-arizalar.html",
    "shartnoma-status.html",
    "shartnoma-turi.html",
    "tayinlangan.html",
    "tuzilgan.html",
    "user-specialty.html",
    "user-types.html",
    "users.html",
    "xarid-ariza.html",
    "xodimlar-yuklamasi.html",
)

# Pages that render through the shared document but not the application
# chrome. The supplied design gives the sign-in screen no sidebar and no top
# header, so TASK-UZK-008 extended base_document.html instead of base.html.
PAGES_WITHOUT_CHROME = ("login.html",)

# Markup that belongs to base.html. A converted page carrying any of it would
# be rendering a second shell inside the first.
SHELL_MARKUP = (
    "<head>",
    "<!DOCTYPE html",
    '<aside class="sidebar"',
    '<header class="top-header"',
    '<div class="app-shell"',
)

SHELL_LANDMARKS = ("app-shell", "sidebar", "main-shell", "top-header", "page-wrap")


def render_page(template_name: str) -> str:
    """Render one converted page through the shell."""
    return render_to_string(f"pages/{template_name}")


class ConvertedPageInventoryTests(SimpleTestCase):
    """The set of converted pages is itself part of the contract."""

    def test_every_converted_page_has_a_template(self) -> None:
        for template_name in CONVERTED_PAGES:
            with self.subTest(page=template_name):
                self.assertTrue((PAGE_TEMPLATE_DIR / template_name).is_file())

    def test_no_page_template_is_unaccounted_for(self) -> None:
        on_disk = {path.name for path in PAGE_TEMPLATE_DIR.glob("*.html")}

        self.assertEqual(on_disk, set(CONVERTED_PAGES) | set(PAGES_WITHOUT_CHROME))


class ConvertedPageRenderingTests(SimpleTestCase):
    """Each page has to render, and to render through the shell."""

    def test_every_page_renders_without_raising(self) -> None:
        for template_name in CONVERTED_PAGES:
            with self.subTest(page=template_name):
                self.assertTrue(render_page(template_name).strip())

    def test_every_page_renders_inside_the_shell(self) -> None:
        for template_name in CONVERTED_PAGES:
            rendered = render_page(template_name)
            for landmark in SHELL_LANDMARKS:
                with self.subTest(page=template_name, landmark=landmark):
                    self.assertIn(f'class="{landmark}"', rendered)

    def test_no_page_carries_shell_markup_of_its_own(self) -> None:
        for template_name in CONVERTED_PAGES:
            source = (PAGE_TEMPLATE_DIR / template_name).read_text(encoding="utf-8")
            for markup in SHELL_MARKUP:
                with self.subTest(page=template_name, markup=markup):
                    self.assertNotIn(markup, source)

    def test_every_page_extends_the_shell_rather_than_including_it(self) -> None:
        for template_name in CONVERTED_PAGES:
            source = (PAGE_TEMPLATE_DIR / template_name).read_text(encoding="utf-8")
            with self.subTest(page=template_name):
                self.assertTrue(source.startswith('{% extends "base.html" %}'))

    def test_page_content_lands_inside_the_page_wrapper(self) -> None:
        # Every supplied page opens its body with a .page-header block, which
        # makes it a reliable marker for "the page's own markup starts here".
        for template_name in CONVERTED_PAGES:
            rendered = render_page(template_name)
            with self.subTest(page=template_name):
                self.assertLess(
                    rendered.index('class="page-wrap"'),
                    rendered.index('class="page-header"'),
                )


class PageAssetPlacementTests(SimpleTestCase):
    """A page's own scripts have to land where they still work."""

    def test_a_page_script_runs_after_the_shared_ones(self) -> None:
        # logs.html calls initTableSearch, which main.js defines. Running
        # first would mean calling a function that does not exist yet.
        rendered = render_page("logs.html")

        self.assertLess(
            rendered.index("js/main.js"), rendered.index("initTableSearch")
        )

    def test_the_dashboard_loads_its_charting_library_from_the_head(self) -> None:
        # The only supplied page that needs extra_head at all.
        rendered = render_page("dashboard.html")

        self.assertLess(rendered.index("chart.umd.min.js"), rendered.index("</head>"))
