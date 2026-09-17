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

TASK-UZK-035 adds the third form of the same shape, for the contract of
section 4.8. It differs from the two above in one way that matters: its rows
carry a price, so the total is computed from them rather than typed, and there
is no field for it at all.
"""

from __future__ import annotations

from django import forms

from applications.attachments import validate_pdf
from applications.models import (
    SMALLEST_PRICE,
    SMALLEST_QUANTITY,
    Application,
    ApplicationItem,
    Contract,
    ContractItem,
    PurchaseApplication,
    PurchaseApplicationItem,
)
from reference.models import ShartnomaStatus, ShartnomaTuri, Supplier

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
            "pdf": "Ilova (PDF)",
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


class ApplicationChoiceField(forms.ModelChoiceField):
    """The Ariza raqami drop-down, labelled so a person can tell them apart.

    Application.__str__ is the number, which is right on a record and wrong in
    a list of them: a specialist choosing which request to commit the company
    to a supplier for is the one person who did not pick it by its number. The
    department and the goods are what they recognise it by, which is also what
    the select_related on the queryset was already paying for.

    Found by the review of #52.
    """

    def label_from_instance(self, obj) -> str:
        lines = list(obj.items.all())
        ordered = lines[0].buyurtma_nomi if lines else "-"
        if len(lines) > 1:
            ordered = f"{ordered} +{len(lines) - 1}"

        return f"{obj.ariza_raqami} - {obj.department.name} - {ordered}"


class SupplierSelect(forms.Select):
    """A Firma drop-down whose options carry the firm's INN.

    REQ-SHARTNOMA-006 puts Firma nomi and Firma INN raqami side by side on
    this form, and DEC-011 made the supplier master data precisely so neither
    is typed into a contract: two contracts naming the same firm would be two
    unrelated strings, and the dashboard counts suppliers.

    So the INN is shown rather than asked for. The option carries it, the
    template renders a read-only field beside the drop-down, and a small
    script copies one into the other - which means the page shows both fields
    the document asks for and stores one fact.
    """

    def create_option(self, name, value, label, selected, index, **kwargs):
        option = super().create_option(
            name, value, label, selected, index, **kwargs
        )
        supplier = getattr(value, "instance", None)
        if supplier is not None:
            option["attrs"]["data-inn"] = supplier.inn

        return option


class ContractForm(forms.ModelForm):
    """The header of the Shartnoma Kiritish form (REQ-SHARTNOMA-006).

    Shartnoma raqami and Yaratilingan sana are not fields, for the reason the
    other two creation forms give: the number is allocated by DEC-022 at the
    moment of saving and the creation date is that moment. Shartnoma sanasi is
    a field, because it is a different fact - the date the agreement carries.

    Shartnoma qiymati is not a field either, and that is the one worth saying
    out loud: REQ-SHARTNOMA-006 defines it as the total price for everything,
    so it is the sum of the rows rather than a number somebody types beside
    them.

    The applications that may be chosen are passed in rather than queried
    here. REQ-ROLE-007 has the specialist forming a contract on the basis of
    the application assigned to them, which is a question about who is asking,
    and a form is the wrong place to ask it.
    """

    class Meta:
        model = Contract
        fields = (
            "application",
            "supplier",
            "shartnoma_turi",
            "status",
            "shartnoma_sanasi",
            "tolash_muddati",
            "muddat_talabi",
            "izoh",
            "pdf",
        )
        field_classes = {"application": ApplicationChoiceField}
        labels = {
            "application": "Ariza raqami",
            "supplier": "Firma nomi",
            "shartnoma_turi": "Shartnoma turi",
            "status": "Status",
            "shartnoma_sanasi": "Shartnoma sanasi",
            "tolash_muddati": "To`lash muddati",
            "muddat_talabi": "Muddat talabi",
            "izoh": "Izoh",
        }
        widgets = {
            "application": forms.Select(attrs={"class": "form-control"}),
            "supplier": SupplierSelect(attrs={"class": "form-control"}),
            "shartnoma_turi": forms.Select(attrs={"class": "form-control"}),
            "status": forms.Select(attrs={"class": "form-control"}),
            "shartnoma_sanasi": forms.DateInput(
                attrs={"class": "form-control", "type": "date"}
            ),
            "tolash_muddati": forms.DateInput(
                attrs={"class": "form-control", "type": "date"}
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
            # FileInput rather than ClearableFileInput, which is the whole of
            # how "and also when it is edited" is built. A clear checkbox is
            # a way to leave a contract without the document
            # REQ-SHARTNOMA-003 says it must carry, and a rule enforced by
            # refusing afterwards is a rule the page offers to break.
            "pdf": forms.FileInput(
                attrs={"class": "form-control", "accept": ".pdf"}
            ),
        }
        error_messages = {
            "pdf": {
                "required": "Shartnoma uchun PDF ilova yuklanishi shart."
            }
        }

    def __init__(self, *args, applications, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        # Keyword-only and with no default, so a caller cannot forget it and
        # quietly offer every application in the database.
        self.fields["application"].queryset = applications
        self.fields["application"].empty_label = "- Tanlang -"
        self.fields["application"].required = True

        # Deleting master data deactivates it (DEC-009), so a retired firm
        # stays resolvable on the contracts already naming it and leaves the
        # drop-down for new ones.
        self.fields["supplier"].queryset = Supplier.objects.active()
        self.fields["supplier"].empty_label = "- Tanlang -"
        self.fields["supplier"].required = True

        self.fields["shartnoma_turi"].queryset = ShartnomaTuri.objects.active()
        self.fields["shartnoma_turi"].empty_label = "- Tanlang -"

        self.fields["status"].queryset = ShartnomaStatus.objects.active()
        self.fields["status"].empty_label = "- Tanlang -"

        # Required here and nullable on the column, the split ApplicationForm
        # also makes: a person filling in a contract knows the date it
        # carries, and the contracts that existed before this form have no
        # way to supply one.
        self.fields["shartnoma_sanasi"].required = True

        # Status and Shartnoma turi are deliberately not required, although
        # the document lists both. Both columns are nullable because DEC-009
        # and DEC-010 let an administrator retire every row, and a master data
        # page must not be able to stop a contract being recorded.

        # The attachment is required and nothing here says so, which is worth
        # a sentence because it looks like an omission. REQ-SHARTNOMA-003
        # asks for it on entry and on edit, and Django's FileField.clean()
        # returns the stored file when nothing is uploaded - so one required
        # field covers both: a new contract has no stored file and is
        # refused, an edit keeps the one it has, and an edit of a contract
        # that somehow has none is refused too.


class ContractItemForm(forms.ModelForm):
    """One row of goods: what, how many, in what unit, and at what price."""

    class Meta:
        model = ContractItem
        fields = (
            "buyurtma_nomi",
            "part_number",
            "buyurtma_soni",
            "olchov_birligi",
            "narxi",
        )
        labels = {
            "buyurtma_nomi": "Buyurtma nomi",
            "part_number": "Part Number",
            "buyurtma_soni": "Miqdori",
            "olchov_birligi": "Birligi",
            "narxi": "Narxi",
        }
        widgets = {
            "buyurtma_nomi": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Item nomi"}
            ),
            "part_number": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "PN-0001"}
            ),
            # The browser is told the same floors the columns enforce, so
            # somebody typing a negative is stopped before they submit rather
            # than after. The rules live on the columns; these are the
            # courtesy.
            "buyurtma_soni": forms.NumberInput(
                attrs={
                    "class": "form-control js-qator-soni",
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
            "narxi": forms.NumberInput(
                attrs={
                    "class": "form-control js-qator-narxi",
                    "step": "0.01",
                    "min": str(SMALLEST_PRICE),
                }
            ),
        }


ContractItemFormSet = forms.modelformset_factory(
    ContractItem,
    form=ContractItemForm,
    extra=STARTING_ITEM_ROWS,
    # A contract with no goods on it has no value to have, which is the rule
    # the two application forms carry for the same reason: a foreign key
    # cannot require the other side to exist. raise_contract() holds it for
    # every other path into the table.
    min_num=1,
    validate_min=True,
)
