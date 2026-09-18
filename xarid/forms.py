"""Every form the application renders.

Master data forms share MasterDataForm, which refuses a duplicate name while
saying which kind of clash it hit - the name is in use, or it belongs to a
record somebody deleted and therefore cannot see (DEC-009 keeps deleted rows).

The three creation forms with order lines (application, purchase application,
contract) are a header form beside a model formset; the plus button in the
browser clones the formset's empty form.
"""

from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractBaseUser
from django.contrib.auth.password_validation import validate_password
from django.core.validators import RegexValidator
from django.db import transaction
from django.db.models import QuerySet
from django.utils.text import slugify

from xarid.attachments import validate_pdf
from xarid.models import (
    CATEGORY_NUMBER_VALIDATORS,
    SMALLEST_PRICE,
    SMALLEST_QUANTITY,
    UNPLACED,
    Application,
    ApplicationItem,
    ArizaStatus,
    Contract,
    ContractItem,
    Department,
    MahsulotTuri,
    PurchaseApplication,
    PurchaseApplicationItem,
    ShartnomaStatus,
    ShartnomaTuri,
    Supplier,
    UserProfile,
    UserSpecialty,
    UserType,
)

# ---------------------------------------------------------------------------
# Master data forms
# ---------------------------------------------------------------------------


def category_number_field(label: str = "Category Number") -> forms.IntegerField:
    """The optional six-digit Category Number a master data form may carry."""
    return forms.IntegerField(
        label=label,
        required=False,
        validators=list(CATEGORY_NUMBER_VALIDATORS),
        help_text="6 xonali son (masalan 100123).",
    )


def required_category_number_field(label: str = "Category Raqami") -> forms.IntegerField:
    """The Category Number a master data form insists on, same six-digit rule."""
    return forms.IntegerField(
        label=label,
        required=True,
        validators=list(CATEGORY_NUMBER_VALIDATORS),
        help_text="6 xonali kod (masalan 100042).",
    )


def position_form_field(label: str = "Tartib") -> forms.IntegerField:
    """The optional position a status form may offer; blank means the end."""
    return forms.IntegerField(
        label=label,
        required=False,
        min_value=1,
        help_text="Ro'yhatdagi tartib. Bo'sh qoldirilsa, oxiriga qo'shiladi.",
    )


class MasterDataForm(forms.ModelForm):
    """The validation every master data form shares."""

    NAME_ALREADY_USED = "Bu nom allaqachon mavjud."
    NAME_HELD_BY_DELETED_RECORD = "Bu nom o'chirilgan yozuvga tegishli. Boshqa nom kiriting."

    def clean_position(self) -> int:
        """Blank means the end of the list; only forms with a position call this."""
        return self.cleaned_data.get("position") or UNPLACED

    def refuse_a_clash(
        self,
        value,
        *,
        lookup: str,
        already_used: str,
        held_by_deleted_record: str,
    ):
        """Return value unchanged when it is free, or raise saying why not.

        Args:
            value: the submitted value.
            lookup: the queryset lookup that finds a clash, such as
                name__iexact or category_number.
            already_used: what to say when the clash is with a visible row.
            held_by_deleted_record: what to say when it is with a deleted one.

        Raises:
            forms.ValidationError: when the value is taken, either way.
        """
        taken = self._meta.model.objects.filter(**{lookup: value})
        if self.instance.pk is not None:
            taken = taken.exclude(pk=self.instance.pk)

        clash = taken.first()
        if clash is None:
            return value

        if clash.is_active:
            raise forms.ValidationError(already_used)

        raise forms.ValidationError(held_by_deleted_record)

    def clean_name(self) -> str:
        """Refuse a name already taken, case-insensitively."""
        return self.refuse_a_clash(
            self.cleaned_data["name"],
            lookup="name__iexact",
            already_used=self.NAME_ALREADY_USED,
            held_by_deleted_record=self.NAME_HELD_BY_DELETED_RECORD,
        )


class UserSpecialtyForm(MasterDataForm):
    """Capture one User Specialty."""

    category_number = category_number_field()

    class Meta:
        model = UserSpecialty
        fields = ("name", "category_number")


class UserTypeForm(MasterDataForm):
    """Capture one User Type; the name of a system role is read-only."""

    category_number = category_number_field()

    class Meta:
        model = UserType
        fields = ("name", "badge_colour", "category_number")

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        if self.instance.pk is not None and self.instance.is_system_role:
            self.fields["name"].disabled = True

    @property
    def name_is_fixed(self) -> bool:
        """Whether the page should render the name as read-only."""
        return self.fields["name"].disabled


class ArizaStatusForm(MasterDataForm):
    """Capture one application status."""

    position = position_form_field()
    category_number = category_number_field()

    class Meta:
        model = ArizaStatus
        fields = ("name", "badge_colour", "position", "category_number")


class ShartnomaStatusForm(MasterDataForm):
    """Capture one contract status."""

    position = position_form_field()
    category_number = category_number_field()

    class Meta:
        model = ShartnomaStatus
        fields = ("name", "badge_colour", "position", "category_number")


class MahsulotTuriForm(MasterDataForm):
    """Capture one product category; its number is required and unique."""

    NUMBER_ALREADY_USED = "Bu raqam allaqachon mavjud."
    NUMBER_HELD_BY_DELETED_RECORD = (
        "Bu raqam o'chirilgan kategoriyaga tegishli. Boshqa raqam kiriting."
    )

    category_number = required_category_number_field()

    class Meta:
        model = MahsulotTuri
        fields = ("category_number", "name", "description")

    def clean_category_number(self) -> int:
        """Refuse a number already taken, saying which kind of clash it is."""
        return self.refuse_a_clash(
            self.cleaned_data["category_number"],
            lookup="category_number",
            already_used=self.NUMBER_ALREADY_USED,
            held_by_deleted_record=self.NUMBER_HELD_BY_DELETED_RECORD,
        )


class ShartnomaTuriForm(MasterDataForm):
    """Capture one contract type."""

    category_number = category_number_field()

    class Meta:
        model = ShartnomaTuri
        fields = ("name", "category_number")


class DepartmentForm(MasterDataForm):
    """Capture one department."""

    category_number = category_number_field()

    class Meta:
        model = Department
        fields = ("name", "category_number")


class SupplierForm(MasterDataForm):
    """Capture one supplier; the INN is unique among those that have one."""

    INN_ALREADY_USED = "Bu INN allaqachon ro`yhatda bor."
    INN_HELD_BY_DELETED_RECORD = "Bu INN o'chirilgan firmaga tegishli. Boshqa INN kiriting."

    category_number = category_number_field()

    class Meta:
        model = Supplier
        fields = ("name", "inn", "daraja", "category_number")

    def clean_inn(self) -> str:
        """Refuse an INN already taken; an empty INN is never a clash."""
        inn = self.cleaned_data["inn"]
        if not inn:
            return inn

        return self.refuse_a_clash(
            inn,
            lookup="inn",
            already_used=self.INN_ALREADY_USED,
            held_by_deleted_record=self.INN_HELD_BY_DELETED_RECORD,
        )


# ---------------------------------------------------------------------------
# The Users page (section 3.3)
# ---------------------------------------------------------------------------

MAXIMUM_USERNAME_ATTEMPTS = 1000

# The format the page's own hint promises: "90 123 45 67". The +998 is printed
# by the page rather than stored.
PHONE_NUMBER_FORMAT = r"^\d{2} \d{3} \d{2} \d{2}$"


def derive_username(first_name: str, last_name: str) -> str:
    """A login name for somebody the form only gave a real name for.

    'Bobur' and 'Toshmatov' become 'bobur.toshmatov', and a second Bobur
    Toshmatov becomes 'bobur.toshmatov2'.

    Raises:
        ValueError: when no free username can be derived within the limit.
    """
    stem = slugify(f"{first_name} {last_name}").replace("-", ".") or "user"

    user_model = get_user_model()
    if not user_model.objects.filter(username=stem).exists():
        return stem

    for suffix in range(2, MAXIMUM_USERNAME_ATTEMPTS):
        candidate = f"{stem}{suffix}"
        if not user_model.objects.filter(username=candidate).exists():
            return candidate

    raise ValueError(f"Could not derive a free username from {stem!r}.")


class UserAdministrationForm(forms.Form):
    """Create or edit one user of the purchasing department.

    The password is hashed by Django, never displayed, and never returned to
    the page (DEC-020). Editing with an empty password keeps the current one.
    """

    first_name = forms.CharField(label="Ism", max_length=150)
    last_name = forms.CharField(label="Familiya", max_length=150)
    password = forms.CharField(
        label="Parol",
        widget=forms.PasswordInput(render_value=False),
        required=False,
        help_text="Leave empty when editing to keep the current password.",
    )
    phone_number = forms.CharField(
        label="Telefon Raqam",
        max_length=12,
        validators=[RegexValidator(PHONE_NUMBER_FORMAT, message="Format: 90 123 45 67")],
    )
    user_type = forms.ModelChoiceField(
        label="User Type", queryset=UserType.objects.none(), required=False
    )
    department = forms.ModelChoiceField(
        label="Bo`lim", queryset=Department.objects.none(), required=False
    )

    def __init__(self, *args, edited_user: AbstractBaseUser | None = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.edited_user = edited_user
        # Resolved at construction rather than at import, so a type or a
        # department added through its own page appears without a restart.
        self.fields["user_type"].queryset = UserType.objects.active()
        self.fields["department"].queryset = Department.objects.active()

    @property
    def is_creating(self) -> bool:
        """Whether this form makes a new account rather than editing one."""
        return self.edited_user is None

    def clean_password(self) -> str:
        """Require a password on creation; validate whatever was supplied."""
        password = self.cleaned_data.get("password", "")
        if not password:
            if self.is_creating:
                raise forms.ValidationError("Majburiy maydon")
            return ""

        validate_password(password)
        return password

    @transaction.atomic
    def save(self) -> AbstractBaseUser:
        """Create or update the account and its profile."""
        first_name = self.cleaned_data["first_name"]
        last_name = self.cleaned_data["last_name"]
        password = self.cleaned_data["password"]

        user = self.edited_user
        if user is None:
            user = get_user_model()(username=derive_username(first_name, last_name))

        user.first_name = first_name
        user.last_name = last_name
        if password:
            user.set_password(password)
        user.save()

        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.user_type = self.cleaned_data["user_type"]
        profile.department = self.cleaned_data["department"]
        profile.phone_number = self.cleaned_data["phone_number"]
        profile.save(update_fields=["user_type", "department", "phone_number"])

        return user

    @classmethod
    def for_user(cls, user: AbstractBaseUser) -> UserAdministrationForm:
        """A form filled in with this user's current values, minus the password."""
        profile, _ = UserProfile.objects.get_or_create(user=user)
        return cls(
            edited_user=user,
            initial={
                "first_name": user.first_name,
                "last_name": user.last_name,
                "phone_number": profile.phone_number,
                "user_type": profile.user_type_id,
                "department": profile.department_id,
            },
        )


# ---------------------------------------------------------------------------
# Applications, purchase applications and contracts with their order lines
# ---------------------------------------------------------------------------

# One row on an empty form; more rows come from the plus button.
STARTING_ITEM_ROWS = 1

# The three units REQ-ARIZA-015 names, offered as suggestions on a free-text
# field rather than as the only choices.
SUGGESTED_UNITS = ("ta", "kg", "m")

CONTROL = {"class": "form-control"}


def pdf_upload_field() -> forms.FileField:
    """The compulsory PDF attachment of the two application creation forms."""
    return forms.FileField(
        label="Ilova (PDF)",
        required=True,
        validators=[validate_pdf],
        help_text="PDF, eng ko`pi bilan 10 MB (DEC-019).",
        error_messages={"required": "Ariza uchun PDF ilova yuklanishi shart."},
        widget=forms.ClearableFileInput(attrs={"class": "form-control", "accept": ".pdf"}),
    )


def quantity_widget(extra_class: str = "") -> forms.NumberInput:
    """A quantity input that tells the browser the same floor the column has."""
    return forms.NumberInput(
        attrs={
            "class": f"form-control {extra_class}".strip(),
            "step": "0.001",
            "min": str(SMALLEST_QUANTITY),
        }
    )


class ApplicationForm(forms.ModelForm):
    """The header of the Ariza Yaratish form (section 4.2)."""

    pdf = pdf_upload_field()

    class Meta:
        model = Application
        fields = ("department", "buyurtmachi_ismi", "izoh", "pdf")
        labels = {
            "department": "Bo`lim nomi",
            "buyurtmachi_ismi": "Buyurtmachi ismi",
            "izoh": "Izoh",
        }
        widgets = {
            "department": forms.Select(attrs=CONTROL),
            "buyurtmachi_ismi": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "To`liq ism"}
            ),
            "izoh": forms.Textarea(
                attrs={"class": "form-control", "rows": 2, "placeholder": "Qo`shimcha izoh"}
            ),
        }

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fields["buyurtmachi_ismi"].required = True
        self.fields["department"].queryset = Department.objects.active()
        self.fields["department"].empty_label = "- Tanlang -"


class ApplicationItemForm(forms.ModelForm):
    """One order line: what is wanted, how much of it, and in what unit."""

    class Meta:
        model = ApplicationItem
        fields = ("mahsulot_turi", "buyurtma_nomi", "buyurtma_soni", "olchov_birligi")
        labels = {
            "mahsulot_turi": "Mahsulot Turi",
            "buyurtma_nomi": "Buyurtma nomi",
            "buyurtma_soni": "Soni",
            "olchov_birligi": "O`lchov",
        }
        widgets = {
            "mahsulot_turi": forms.Select(attrs=CONTROL),
            "buyurtma_nomi": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Item nomi"}
            ),
            "buyurtma_soni": quantity_widget(),
            "olchov_birligi": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "ta"}
            ),
        }

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fields["mahsulot_turi"].queryset = MahsulotTuri.objects.active()
        self.fields["mahsulot_turi"].empty_label = "- Tanlang -"


ApplicationItemFormSet = forms.modelformset_factory(
    ApplicationItem,
    form=ApplicationItemForm,
    extra=STARTING_ITEM_ROWS,
    min_num=1,
    validate_min=True,
)


class PurchaseApplicationForm(forms.ModelForm):
    """The header of the Xarid Arizasi form (section 4.9).

    Bo`lim nomi is not a field: DEC-018 fills the department from the
    signed-in user, and a field a requester could change would be filled in
    rather than filled from.
    """

    pdf = pdf_upload_field()

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
            "muddat_talabi": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "izoh": forms.Textarea(
                attrs={"class": "form-control", "rows": 2, "placeholder": "Qo`shimcha izoh"}
            ),
        }

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fields["shartnoma_nomi"].required = True


class PurchaseApplicationItemForm(forms.ModelForm):
    """One line of what a purchase application asks for."""

    class Meta:
        model = PurchaseApplicationItem
        fields = ("mahsulot_turi", "buyurtma_nomi", "buyurtma_soni", "olchov_birligi")
        labels = {
            "mahsulot_turi": "Mahsulot Turi",
            "buyurtma_nomi": "Buyurtma nomi",
            "buyurtma_soni": "Soni",
            "olchov_birligi": "O`lchov",
        }
        widgets = {
            "mahsulot_turi": forms.Select(attrs=CONTROL),
            "buyurtma_nomi": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Item nomi"}
            ),
            "buyurtma_soni": quantity_widget(),
            "olchov_birligi": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "ta", "list": "olchov-birliklari"}
            ),
        }

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fields["mahsulot_turi"].queryset = MahsulotTuri.objects.active()
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

    The number alone means little to a specialist choosing which request to
    commit the company to a supplier for; the department and the goods are
    what they recognise it by.
    """

    def label_from_instance(self, obj: Application) -> str:
        lines = list(obj.items.all())
        ordered = lines[0].buyurtma_nomi if lines else "-"
        if len(lines) > 1:
            ordered = f"{ordered} +{len(lines) - 1}"

        return f"{obj.ariza_raqami} - {obj.department.name} - {ordered}"


class SupplierSelect(forms.Select):
    """A Firma drop-down whose options carry the firm's INN.

    The INN is shown beside the drop-down rather than typed (DEC-011): the
    option carries it and a small script copies it into a read-only field.
    """

    def create_option(self, name, value, label, selected, index, **kwargs) -> dict:
        option = super().create_option(name, value, label, selected, index, **kwargs)
        supplier = getattr(value, "instance", None)
        if supplier is not None:
            option["attrs"]["data-inn"] = supplier.inn

        return option


class ContractForm(forms.ModelForm):
    """The header of the Shartnoma Kiritish form (REQ-SHARTNOMA-006).

    Shartnoma qiymati is not a field: it is the sum of the rows. The
    applications that may be chosen are passed in, because which ones this
    person may contract against is a question about who is asking.
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
            "application": forms.Select(attrs=CONTROL),
            "supplier": SupplierSelect(attrs=CONTROL),
            "shartnoma_turi": forms.Select(attrs=CONTROL),
            "status": forms.Select(attrs=CONTROL),
            "shartnoma_sanasi": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "tolash_muddati": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "muddat_talabi": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "izoh": forms.Textarea(
                attrs={"class": "form-control", "rows": 2, "placeholder": "Qo`shimcha izoh"}
            ),
        }

    def __init__(self, *args, applications: QuerySet[Application], **kwargs) -> None:
        """Build the form.

        Args:
            applications: the applications this person may contract against.
                Keyword-only with no default, so a caller cannot forget it and
                quietly offer every application in the database.
        """
        super().__init__(*args, **kwargs)

        self.fields["application"].queryset = applications
        self.fields["application"].empty_label = "- Tanlang -"
        self.fields["application"].required = True

        self.fields["supplier"].queryset = Supplier.objects.active()
        self.fields["supplier"].empty_label = "- Tanlang -"
        self.fields["supplier"].required = True

        self.fields["shartnoma_turi"].queryset = ShartnomaTuri.objects.active()
        self.fields["shartnoma_turi"].empty_label = "- Tanlang -"

        self.fields["status"].queryset = ShartnomaStatus.objects.active()
        self.fields["status"].empty_label = "- Tanlang -"

        self.fields["shartnoma_sanasi"].required = True


class ContractItemForm(forms.ModelForm):
    """One row of goods: what, how many, in what unit, and at what price."""

    class Meta:
        model = ContractItem
        fields = ("buyurtma_nomi", "part_number", "buyurtma_soni", "olchov_birligi", "narxi")
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
            "buyurtma_soni": quantity_widget("js-qator-soni"),
            "olchov_birligi": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "ta", "list": "olchov-birliklari"}
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
    min_num=1,
    validate_min=True,
)
