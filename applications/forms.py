"""The Ariza Yaratish form of section 4.2 (TASK-UZK-026).

An application is a record with a header and a variable number of order lines,
so it is two forms rather than one: ApplicationForm for what the application
is, and an inline formset for what it orders. The plus button REQ-ARIZA-010
describes is the formset's extra row, added in the browser from the empty form
Django renders for exactly this purpose.

The attachment is the part worth reading carefully. REQ-ARIZA-009 makes the
PDF compulsory in order to create an application, and the column is optional -
deliberately, because DEC-016 lets Admin key in an application that arrived on
paper and has no file to attach. Those two are not in conflict: the
requirement is on this form, not on the record. Declaring the field here
rather than loosening the model keeps it that way.
"""

from __future__ import annotations

from django import forms

from applications.attachments import validate_pdf
from applications.models import (
    SMALLEST_QUANTITY,
    Application,
    ApplicationItem,
    PurchaseApplication,
    PurchaseApplicationItem,
)

# One row on an empty form, so the person sees a line to fill in rather than
# an order with nothing in it. More rows come from the plus button.
STARTING_ITEM_ROWS = 1


class ApplicationForm(forms.ModelForm):
    """What the application is, beside what it orders.

    Ariza raqami and Yaratilingan sana are on the form REQ-ARIZA-008
    describes and are not fields here: the number is allocated by DEC-022 at
    the moment of saving and the date is the moment itself. Both are shown on
    the page as text, because a number somebody can type is a number two
    applications can share.
    """

    pdf = forms.FileField(
        label="Ilova (PDF)",
        required=True,
        validators=[validate_pdf],
        help_text="PDF, eng ko`pi bilan 10 MB (DEC-019).",
        error_messages={"required": "Ariza uchun PDF ilova yuklanishi shart."},
        widget=forms.ClearableFileInput(
            attrs={"class": "form-control", "accept": ".pdf"}
        ),
    )

    class Meta:
        model = Application
        fields = ("department", "buyurtmachi_ismi", "izoh", "pdf")
        labels = {
            "department": "Bo`lim nomi",
            "buyurtmachi_ismi": "Buyurtmachi ismi",
            "izoh": "Izoh",
        }
        # The supplied stylesheet styles .form-control and nothing else, so
        # the class is on the widget rather than written out beside every
        # field in the template. The plus button clones a row Django renders,
        # which means a row the template never wrote by hand.
        widgets = {
            "department": forms.Select(attrs={"class": "form-control"}),
            "buyurtmachi_ismi": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "To`liq ism"}
            ),
            "izoh": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 2,
                    "placeholder": "Qo`shimcha izoh",
                }
            ),
        }

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        # Both are optional on the record and asked for on this form, because
        # a person filling in a creation form knows who asked for the order.
        self.fields["buyurtmachi_ismi"].required = True
        self.fields["department"].empty_label = "- Tanlang -"


class ApplicationItemForm(forms.ModelForm):
    """One order line: what is wanted, how much of it, and in what unit."""

    class Meta:
        model = ApplicationItem
        fields = (
            "mahsulot_turi",
            "buyurtma_nomi",
            "buyurtma_soni",
            "olchov_birligi",
        )
        labels = {
            "mahsulot_turi": "Mahsulot Turi",
            "buyurtma_nomi": "Buyurtma nomi",
            "buyurtma_soni": "Soni",
            "olchov_birligi": "O`lchov",
        }
        widgets = {
            "mahsulot_turi": forms.Select(attrs={"class": "form-control"}),
            "buyurtma_nomi": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Item nomi"}
            ),
            # The browser is told the same floor the column enforces, so
            # somebody typing a negative is stopped before they submit rather
            # than after. The rule lives on the column; this is the courtesy.
            "buyurtma_soni": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "step": "0.001",
                    "min": str(SMALLEST_QUANTITY),
                }
            ),
            "olchov_birligi": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "ta"}
            ),
        }

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fields["mahsulot_turi"].empty_label = "- Tanlang -"


ApplicationItemFormSet = forms.modelformset_factory(
    ApplicationItem,
    form=ApplicationItemForm,
    extra=STARTING_ITEM_ROWS,
    # An application with nothing ordered on it is not a record the
    # department has a use for, and nothing in the database can say so - a
    # foreign key cannot require the other side to exist. validate_min is
    # where that rule lives for the form, and raise_application() is where it
    # lives for everything else.
    min_num=1,
    validate_min=True,
)


# The three units REQ-ARIZA-015 names. Offered as suggestions rather than as
# the only choices: REQ-ARIZA-003 describes the same field as free text and
# the column is free text, so a closed list here would refuse a unit the other
# form accepts.
SUGGESTED_UNITS = ("ta", "kg", "m")


class PurchaseApplicationForm(forms.ModelForm):
    """The Xarid Arizasi form of section 4.9.

    Bo`lim nomi is not a field. DEC-018 fills the department from the
    signed-in user, and a field a requester could change would be filled in
    rather than filled from - which is a different thing, and the wrong one.

    Ariza raqami and Yaratilingan sana are not fields either, for the reason
    ApplicationForm gives: the number is allocated on save and the date is the
    moment of it.
    """

    pdf = forms.FileField(
        label="Ilova (PDF)",
        required=True,
        validators=[validate_pdf],
        help_text="PDF, eng ko`pi bilan 10 MB (DEC-019).",
        error_messages={"required": "Ariza uchun PDF ilova yuklanishi shart."},
        widget=forms.ClearableFileInput(
            attrs={"class": "form-control", "accept": ".pdf"}
        ),
    )

    class Meta:
        model = PurchaseApplication
        fields = ("shartnoma_nomi", "muddat_talabi", "izoh", "pdf")
        labels = {
            "shartnoma_nomi": "Shartnoma nomi",
            "muddat_talabi": "Muddat talabi",
            "izoh": "Izoh",
        }
        widgets = {
            "shartnoma_nomi": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Shartnoma nomi"}
            ),
            "muddat_talabi": forms.DateInput(
                attrs={"class": "form-control", "type": "date"}
            ),
            "izoh": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 2,
                    "placeholder": "Qo`shimcha izoh",
                }
            ),
        }

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fields["shartnoma_nomi"].required = True


class PurchaseApplicationItemForm(forms.ModelForm):
    """One line of what a purchase application asks for."""

    class Meta:
        model = PurchaseApplicationItem
        fields = (
            "mahsulot_turi",
            "buyurtma_nomi",
            "buyurtma_soni",
            "olchov_birligi",
        )
        labels = {
            "mahsulot_turi": "Mahsulot Turi",
            "buyurtma_nomi": "Buyurtma nomi",
            "buyurtma_soni": "Soni",
            "olchov_birligi": "O`lchov",
        }
        widgets = {
            "mahsulot_turi": forms.Select(attrs={"class": "form-control"}),
            "buyurtma_nomi": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Item nomi"}
            ),
            "buyurtma_soni": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "step": "0.001",
                    "min": str(SMALLEST_QUANTITY),
                }
            ),
            "olchov_birligi": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "ta",
                    "list": "olchov-birliklari",
                }
            ),
        }

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fields["mahsulot_turi"].empty_label = "- Tanlang -"


PurchaseApplicationItemFormSet = forms.modelformset_factory(
    PurchaseApplicationItem,
    form=PurchaseApplicationItemForm,
    extra=STARTING_ITEM_ROWS,
    min_num=1,
    validate_min=True,
)
