"""What more than one of the three view modules has to ask.

The queries behind a page live with the views that render it. These are the
questions two of them ask, kept in one place so that two modules cannot come
to different answers: what an order line is made of, and whether somebody may
act only on the work they hold.
"""

from __future__ import annotations

from accounts.roles import KATTA_MUTAXASIS, has_user_type
from applications.forms import ApplicationItemFormSet

# The four columns one order line is made of, named once so the creation
# view and the line model cannot drift apart.
ORDER_LINE_FIELDS = (
    "mahsulot_turi",
    "buyurtma_nomi",
    "buyurtma_soni",
    "olchov_birligi",
)


def ordered_lines(items: ApplicationItemFormSet) -> list[dict[str, object]]:
    """The order lines somebody actually filled in, in the order they gave.

    A formset always carries at least one spare row - that is what the plus
    button clones - and a spare nobody typed into is not an order. Those come
    back with empty cleaned_data and are dropped here.

    Only the four order-line fields are taken. A model formset also puts a
    hidden id on every form, and passing that through to a new line would be
    handing the database a primary key from a form.
    """
    return [
        {field: line.cleaned_data[field] for field in ORDER_LINE_FIELDS}
        for line in items.forms
        if line.cleaned_data
    ]


def acts_on_own_work_only(user) -> bool:
    """Whether this person may only touch the applications they hold.

    A Katta Mutaxasis may. Everybody else DEC-015 lets onto the Tayinlangan
    page hands work out and may touch all of it. One function, so that what
    the page shows and what the page may do cannot drift apart - which they
    would the first time one of them was changed and the other was not.
    """
    return has_user_type(user, (KATTA_MUTAXASIS,))
