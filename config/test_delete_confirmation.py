"""A deleted record's name must never reach the browser as JavaScript source.

DEC-009 requires a confirmation before a master data record is deleted. The
supplied prototype asked for it with an inline handler:

    onsubmit="return confirm('{{ record.name }} o'chirilsinmi?');"

which cannot be made safe. Django escapes the name for HTML, so an apostrophe
becomes &#x27; - but a browser decodes character references in an attribute
value *before* the JavaScript engine parses the source. The engine is then
handed a string literal the name has closed early:

    return confirm('Ko'rib chiqilmoqda o'chirilsinmi?');

That is a syntax error, so the handler never runs and the form submits with no
confirmation at all - for exactly the names an Uzbek user is most likely to
type. A name written as   x'); alert(1); //   does not merely break: the rest
of it executes for whoever opens the page next.

The fix is not better escaping. It is to stop putting the name in JavaScript
source: a data-confirm attribute holds the question and the shared handler in
main.js reads it back, which is the context Django's autoescaping is correct
for.

These tests are here rather than in one page's file because the rule is the
same for every page that deletes something, and the next such page should fail
this rather than rediscover it.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

PAGE_TEMPLATE_DIR = Path(settings.BASE_DIR) / "templates" / "pages"
MAIN_JS = Path(settings.BASE_DIR) / "static" / "js" / "main.js"

# An inline handler attribute and everything up to the quote that closes it.
# The pages still carrying the prototype's own scripts have handlers like
# onclick="Modal.open('xa-modal')", which are constants and harmless. What is
# never safe is a template variable inside one, so that is what this looks for.
INLINE_HANDLER = re.compile(
    r"""\bon[a-z]+\s*=\s*(?P<quote>["'])(?P<body>.*?)(?P=quote)""",
    re.IGNORECASE | re.DOTALL,
)

TEMPLATE_OUTPUT = re.compile(r"\{\{|\{%")

# The two ways a browser turns a string back into JavaScript source. Written
# as a pattern rather than as literals so that this file, which is about
# keeping data out of source, does not itself read like a call to either.
DYNAMIC_EVALUATION = re.compile(r"\beval\b|\bnew\s+Function\b")


class NoRenderedValueInInlineHandlerTests(SimpleTestCase):
    """A template variable must never land inside an inline event handler."""

    def test_no_page_template_renders_a_value_into_a_handler(self) -> None:
        for template in sorted(PAGE_TEMPLATE_DIR.glob("*.html")):
            source = template.read_text(encoding="utf-8")
            for handler in INLINE_HANDLER.finditer(source):
                body = handler.group("body")
                with self.subTest(page=template.name, handler=body[:60]):
                    self.assertIsNone(
                        TEMPLATE_OUTPUT.search(body),
                        f"{template.name} renders a value into an inline "
                        f"event handler: {body[:80]!r}. The browser decodes "
                        "character references in an attribute before the "
                        "JavaScript engine parses it, so a name containing "
                        "an apostrophe closes the string literal - breaking "
                        "the handler, or running what follows. Put the value "
                        "in a data- attribute and read it in main.js.",
                    )


class ConfirmAttributeTests(SimpleTestCase):
    """The question survives the trip through an attribute intact."""

    def test_a_name_with_an_apostrophe_stays_one_string(self) -> None:
        # What the template emits, and what the HTML parser hands back. The
        # apostrophe returns as itself and closes nothing, because nothing
        # here is JavaScript source.
        emitted = 'data-confirm="Ko&#x27;rib chiqilmoqda o&#x27;chirilsinmi?"'

        value = html.unescape(re.search(r'data-confirm="([^"]*)"', emitted).group(1))

        self.assertEqual(value, "Ko'rib chiqilmoqda o'chirilsinmi?")

    def test_main_js_reads_the_attribute_rather_than_evaluating_it(self) -> None:
        # dataset.confirm is a string the handler hands to the browser's own
        # confirmation dialog. If it were ever evaluated instead, the
        # attribute would be JavaScript source again and the whole problem
        # would come back through another door.
        handler = MAIN_JS.read_text(encoding="utf-8")

        self.assertIn("form.dataset.confirm", handler)
        self.assertIsNone(DYNAMIC_EVALUATION.search(handler))
