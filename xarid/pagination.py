"""One page of a table, and the bar that moves between pages.

Every list page in the specification shows a table, and a table that grows
without limit is one nobody can read the end of. This is the mechanism, once:
a view hands its rows over, the reader says how many of them fit on a page,
and the same object slices the rows and renders the bar beneath them.

The reader's two choices travel in the query string beside the filter bar's,
so a page that is filtered, ordered and paged is one URL - it survives a
reload, a bookmark and the browser's back button, and every page link carries
the filters the table was narrowed by.

Neither choice is ever refused. A filter value that is not offered is a
question about rows that may exist, so filters.py reports it; a page number
past the end and a row count nobody offered are questions about nothing, and
the answer is the nearest page and the default count rather than a message
about a number the reader did not type.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from urllib.parse import urlencode

from django.core.paginator import Paginator

# The query string names of the two controls, which every page shares.
PAGE_PARAMETER = "sahifa"
PER_PAGE_PARAMETER = "qatorlar"

# What the drop-down offers, and what a page shows when nobody has chosen.
PER_PAGE_CHOICES = (15, 20, 30, 50, 100)
DEFAULT_PER_PAGE = 20

# How many page numbers sit either side of the current one, and how many at
# each end, before the bar elides the rest. A table of forty pages is a bar
# of nine buttons rather than forty.
NUMBERS_EITHER_SIDE = 2
NUMBERS_AT_THE_ENDS = 1

ELLIPSIS = Paginator.ELLIPSIS


class TablePage:
    """One page of a table's rows, and what the bar beneath it needs.

    Args:
        rows: everything the table would show unpaged - a queryset, which is
            counted and sliced by the database, or any sequence a report has
            already worked out.
        chosen: the request's query parameters, which carry the page number
            and the row count.
        kept: the choices every link has to carry - the filter bar's valid
            selections, its period and its ordering. Taken from the filter
            rather than from the request so that a refused filter is not
            carried into the next page as though it had been applied.
    """

    def __init__(
        self,
        rows: Sequence | object,
        chosen: Mapping[str, str] | None = None,
        *,
        kept: Mapping[str, str] | None = None,
    ) -> None:
        chosen = chosen or {}
        self.kept = dict(kept or {})
        self.per_page = self._per_page(chosen.get(PER_PAGE_PARAMETER))
        self.paginator = Paginator(rows, self.per_page)
        self.page = self.paginator.get_page(chosen.get(PAGE_PARAMETER))

    @staticmethod
    def _per_page(requested: str | int | None) -> int:
        """The row count the reader asked for, or the default.

        Anything that is not one of the offered numbers is the default: the
        drop-down is the only thing that sets this, so a value from anywhere
        else is not a choice a reader could have made.
        """
        try:
            asked = int(str(requested).strip())
        except (TypeError, ValueError):
            return DEFAULT_PER_PAGE

        return asked if asked in PER_PAGE_CHOICES else DEFAULT_PER_PAGE

    @property
    def rows(self) -> Sequence:
        """The rows of this page, which is what the table renders."""
        return self.page.object_list

    @property
    def total(self) -> int:
        """How many rows the table holds in all, which the bar reports."""
        return self.paginator.count

    @property
    def start_index(self) -> int:
        """Where this page starts in the whole table, counting from one.

        The "#" column counts through the table rather than restarting at
        every page: row 21 is row 21 whichever page it is being read on.
        """
        return self.page.start_index() if self.total else 0

    @property
    def number(self) -> int:
        """The page being read, counting from one."""
        return self.page.number

    @property
    def num_pages(self) -> int:
        return self.paginator.num_pages

    @property
    def choices(self) -> tuple[int, ...]:
        """What the row count drop-down offers."""
        return PER_PAGE_CHOICES

    @property
    def is_offered(self) -> bool:
        """Whether the bar is drawn at all.

        A table that fits on one page still draws it: the row count drop-down
        is how a reader asks for fewer rows, and the total is worth reading on
        a table of eight rows as much as on one of eight hundred. Only a table
        with nothing in it hides the bar, where both would say nothing.
        """
        return self.total > 0

    @property
    def has_previous(self) -> bool:
        return self.page.has_previous()

    @property
    def has_next(self) -> bool:
        return self.page.has_next()

    @property
    def numbers(self) -> tuple[int | str, ...]:
        """The page numbers the bar draws, with ELLIPSIS where it skips.

        Django works out the window; a single-page table gets a single button
        rather than the empty range its elided form would give.
        """
        if self.num_pages <= 1:
            return (1,)

        return tuple(
            self.paginator.get_elided_page_range(
                self.number,
                on_each_side=NUMBERS_EITHER_SIDE,
                on_ends=NUMBERS_AT_THE_ENDS,
            )
        )

    def query_for(self, number: int | str) -> str:
        """The query string of another page of this table, with a leading '?'.

        Everything the reader chose is carried: the filters, the period, the
        ordering and the row count. The first page leaves the page number out,
        so the table's own URL is the one a reader arrives back at.
        """
        chosen = dict(self.kept)
        if self.per_page != DEFAULT_PER_PAGE:
            chosen[PER_PAGE_PARAMETER] = str(self.per_page)
        if int(number) > 1:
            chosen[PAGE_PARAMETER] = str(number)

        return f"?{urlencode(chosen)}" if chosen else ""

    @property
    def previous_query(self) -> str:
        return self.query_for(self.page.previous_page_number() if self.has_previous else 1)

    @property
    def next_query(self) -> str:
        return self.query_for(self.page.next_page_number() if self.has_next else self.num_pages)

    @property
    def page_parameter(self) -> str:
        return PAGE_PARAMETER

    @property
    def per_page_parameter(self) -> str:
        return PER_PAGE_PARAMETER

    @property
    def ellipsis(self) -> str:
        """What the template compares a number against to draw a gap."""
        return ELLIPSIS
