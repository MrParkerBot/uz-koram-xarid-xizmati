"""Compile the message catalogues, and check them against the code.

Django's own compilemessages shells out to GNU gettext's msgfmt, which is not
on a Windows workstation and is not something a department can be asked to
install before it can run the application. So the compiler is here, in Python:
it reads each locale/<language>/LC_MESSAGES/django.po and writes the django.mo
beside it that gettext reads at runtime.

    manage.py translations             compile every catalogue
    manage.py translations --check     report what is missing, write nothing

--check is what the test suite runs. It reads every string the code marks for
translation - _("...") and {% trans %} in the templates, gettext() and its lazy
forms in the Python - and reports any that no catalogue has an entry for, and
any entry that has been left with an empty translation. A string nobody has
translated is not an error at runtime, because gettext falls back to the msgid
and the msgid is the Uzbek the pages are written in; it is reported here so
that "not translated yet" is something the build says out loud rather than
something a reader discovers in Russian.
"""

from __future__ import annotations

import re
import struct
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

# The magic number gettext puts at the front of a little-endian .mo file, and
# the revision this writer produces.
MO_MAGIC = 0x950412DE
MO_REVISION = 0

CATALOGUE = Path("LC_MESSAGES") / "django.po"
COMPILED = Path("LC_MESSAGES") / "django.mo"

# Where the marked strings are. The templates render through Jinja2, so they
# carry _() and {% trans %}; the Python marks with gettext and its lazy form,
# which this project imports as gettext_lazy.
SOURCE_SUFFIXES = (".py", ".html")
# .ua is the scratch directory the authoring scripts live in; it holds the
# markers as data, which a scanner would otherwise read as marked strings.
SKIPPED_DIRECTORIES = {"migrations", "__pycache__", "node_modules", ".venv", ".ven", ".ua"}

# _("..."), _('...'), gettext("..."), gettext_lazy("...") and the {% trans %}
# tag's one-line form. Deliberately simple: a marked string is written as a
# plain literal in this codebase, and a scanner that tried to understand
# expressions would report the ones it could not parse as missing.
MARKERS = (
    re.compile(r"(?<![\w.])_\(\s*\"((?:[^\"\\]|\\.)*)\"\s*[,)]"),
    re.compile(r"(?<![\w.])_\(\s*'((?:[^'\\]|\\.)*)'\s*[,)]"),
    re.compile(r"(?<![\w.])gettext(?:_lazy)?\(\s*\"((?:[^\"\\]|\\.)*)\"\s*[,)]"),
    re.compile(r"(?<![\w.])gettext(?:_lazy)?\(\s*'((?:[^'\\]|\\.)*)'\s*[,)]"),
    re.compile(r"\{%\s*trans\s*%\}(.*?)\{%\s*endtrans\s*%\}", re.S),
)


class Command(BaseCommand):
    help = "Compile the .po catalogues into .mo, or check them against the code."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--check",
            action="store_true",
            help="Report missing and empty translations instead of compiling.",
        )

    def handle(self, *args, **options) -> None:
        catalogues = self.catalogues()
        if not catalogues:
            raise CommandError("No catalogues found under LOCALE_PATHS.")

        if options["check"]:
            self.report(catalogues)
            return

        for language, path in catalogues.items():
            entries = read_catalogue(path)
            written = path.parent.parent / COMPILED
            written.parent.mkdir(parents=True, exist_ok=True)
            written.write_bytes(compile_catalogue(entries))
            translated = sum(1 for value in entries.values() if value)
            self.stdout.write(
                f"{language}: {translated}/{len(entries)} translated -> {written}"
            )

    def catalogues(self) -> dict[str, Path]:
        """Every language's .po file, by language code."""
        found: dict[str, Path] = {}
        for root in settings.LOCALE_PATHS:
            for language, _name in settings.LANGUAGES:
                path = Path(root) / language / CATALOGUE
                if path.exists():
                    found[language] = path

        return found

    def report(self, catalogues: dict[str, Path]) -> None:
        """Say what is marked in the code and missing from the catalogues."""
        marked = marked_strings()
        self.stdout.write(f"{len(marked)} strings marked in the code.")

        complaints = 0
        for language, path in catalogues.items():
            entries = read_catalogue(path)
            # The language the strings are authored in needs no translation of
            # its own: gettext falls back to the msgid, which is that language.
            expects_translations = language != settings.LANGUAGE_CODE

            missing = sorted(marked - set(entries)) if expects_translations else []
            empty = sorted(key for key, value in entries.items() if not value and key)
            unused = sorted(set(entries) - marked - {""})

            for key in missing:
                self.stderr.write(f"{language}: no entry for {key!r}")
            if expects_translations:
                for key in empty:
                    self.stderr.write(f"{language}: {key!r} is not translated")
            for key in unused:
                self.stderr.write(f"{language}: {key!r} is in the catalogue but not in the code")

            complaints += len(missing) + len(unused)
            if expects_translations:
                complaints += len(empty)

        if complaints:
            raise CommandError(f"{complaints} catalogue problems.")

        self.stdout.write("Every marked string is translated in every language.")


def marked_strings(root: Path | None = None) -> set[str]:
    """Every string the code marks for translation."""
    base = Path(root or settings.BASE_DIR)
    found: set[str] = set()

    for path in base.rglob("*"):
        if path.suffix not in SOURCE_SUFFIXES:
            continue
        if SKIPPED_DIRECTORIES & set(path.parts):
            continue
        # This module spells the markers out to explain them, and a scanner
        # that read its own examples would ask for a translation of "...".
        if path.resolve() == Path(__file__).resolve():
            continue

        text = path.read_text(encoding="utf-8")
        for marker in MARKERS:
            found.update(match.group(1).strip() for match in marker.finditer(text))

    return {entry for entry in found if entry}


def read_catalogue(path: Path) -> dict[str, str]:
    """One .po file as {msgid: msgstr}, joining the multi-line forms.

    Enough of the format for a catalogue a person maintains by hand: comments,
    msgid and msgstr, each of which may be followed by continuation lines. The
    header entry keeps its empty msgid, so a writer can put it in the .mo where
    gettext looks for the charset.
    """
    entries: dict[str, str] = {}
    key: str | None = None
    collecting: str | None = None
    parts: list[str] = []

    def close() -> None:
        nonlocal key, collecting, parts
        if collecting == "msgid":
            key = "".join(parts)
        elif collecting == "msgstr" and key is not None:
            entries[key] = "".join(parts)
            key = None
        collecting, parts = None, []

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            close()
            continue

        if stripped.startswith("msgid "):
            close()
            collecting, parts = "msgid", [unquote(stripped[len("msgid ") :])]
        elif stripped.startswith("msgstr "):
            close()
            collecting, parts = "msgstr", [unquote(stripped[len("msgstr ") :])]
        elif stripped.startswith('"'):
            parts.append(unquote(stripped))
        else:
            close()

    close()

    return entries


def unquote(value: str) -> str:
    """One quoted .po string as its text, with the escapes it may carry."""
    value = value.strip()
    if value.startswith('"') and value.endswith('"') and len(value) >= 2:
        value = value[1:-1]

    return (
        value.replace('\\"', '"')
        .replace("\\n", "\n")
        .replace("\\t", "\t")
        .replace("\\\\", "\\")
    )


def compile_catalogue(entries: dict[str, str]) -> bytes:
    """The .mo file gettext reads, from {msgid: msgstr}.

    The format is a header, two tables of (length, offset) pairs - one for the
    ids and one for the translations - and the strings themselves. The ids are
    sorted because gettext binary-searches them.

    An entry with no translation is left out rather than written empty: an
    empty translation means "this msgid has no text" to gettext, and the
    fallback that prints the Uzbek is what an untranslated string wants.
    """
    translated = {key: value for key, value in entries.items() if value or key == ""}
    keys = sorted(translated)

    ids = b"\x00".join(key.encode("utf-8") for key in keys) + b"\x00"
    texts = b"\x00".join(translated[key].encode("utf-8") for key in keys) + b"\x00"

    count = len(keys)
    id_table_offset = 7 * 4
    text_table_offset = id_table_offset + count * 8
    ids_offset = text_table_offset + count * 8
    texts_offset = ids_offset + len(ids)

    id_table = bytearray()
    text_table = bytearray()
    at = ids_offset
    for key in keys:
        encoded = key.encode("utf-8")
        id_table += struct.pack("<II", len(encoded), at)
        at += len(encoded) + 1
    at = texts_offset
    for key in keys:
        encoded = translated[key].encode("utf-8")
        text_table += struct.pack("<II", len(encoded), at)
        at += len(encoded) + 1

    header = struct.pack(
        "<IIIIIII",
        MO_MAGIC,
        MO_REVISION,
        count,
        id_table_offset,
        text_table_offset,
        0,  # hash table size: none, which gettext accepts
        0,  # hash table offset
    )

    return bytes(header + id_table + text_table + ids + texts)
