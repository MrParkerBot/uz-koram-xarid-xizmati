"""Every form the application renders.

Master data forms share MasterDataForm, which refuses a duplicate name while
saying which kind of clash it hit - the name is in use, or it belongs to a
record somebody deleted and therefore cannot see (DEC-009 keeps deleted rows).

The three creation forms with order lines (application, purchase application,
contract) are a header form beside a model formset; the plus button in the
browser clones the formset's empty form.
"""

from __future__ import annotations

import re

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


def generated_category_number_field(label: str = "Category Raqami") -> forms.IntegerField:
    """The Category Number a category takes, typed in or left to the model.

    Optional in the form and never empty in the record: blank means "the next
    one", which MahsulotTuri.save() fills in. A number that is typed is still
    held to the six-digit rule, and to being free.
    """
    return forms.IntegerField(
        label=label,
        required=False,
        validators=list(CATEGORY_NUMBER_VALIDATORS),
        help_text="6 xonali kod (masalan 100042). Bo'sh qoldirilsa, avtomatik beriladi.",
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
    """Capture one contract status, including which one means completed."""

    position = position_form_field()
    category_number = category_number_field()

    class Meta:
        model = ShartnomaStatus
        fields = (
            "name",
            "badge_colour",
            "position",
            "category_number",
            "is_completed",
            "is_signed",
        )


class MahsulotTuriForm(MasterDataForm):
    """Capture one product category; its number is unique, and may be left out."""

    NUMBER_ALREADY_USED = "Bu raqam allaqachon mavjud."
    NUMBER_HELD_BY_DELETED_RECORD = (
        "Bu raqam o'chirilgan kategoriyaga tegishli. Boshqa raqam kiriting."
    )

    category_number = generated_category_number_field()

    class Meta:
        model = MahsulotTuri
        fields = ("category_number", "name", "description")

    def clean_category_number(self) -> int | None:
        """Refuse a number already taken, saying which kind of clash it is.

        An empty box is not a clash with anything. On a new category it means
        None, and MahsulotTuri.save() takes the next number; on one being
        edited it means the number it already has. Emptying the box is how a
        number is left alone, not how a category is renumbered behind the
        reader - the code is what the department knows the category by, and
        changing it is something to ask for rather than to be given.
        """
        typed = self.cleaned_data.get("category_number")
        if typed is None:
            return self.instance.category_number if self.instance.pk else None

        return self.refuse_a_clash(
            typed,
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
    """Capture one department, and which one works the arrived applications."""

    ALREADY_A_PURCHASING_DEPARTMENT = (
        "Xarid bo`limi allaqachon belgilangan: avval {name} dan olib tashlang."
    )

    category_number = category_number_field()

    class Meta:
        model = Department
        fields = ("name", "category_number", "is_purchasing")

    def clean_is_purchasing(self) -> bool:
        """Refuse a second purchasing department, naming the one that holds it.

        The database constraint would refuse it too, with an IntegrityError
        that reaches the reader as a server error. This turns the same rule
        into a sentence beside the field.
        """
        wants_it = self.cleaned_data["is_purchasing"]
        if not wants_it:
            return wants_it

        others = Department.objects.filter(is_purchasing=True).exclude(pk=self.instance.pk)
        held_by = others.first()
        if held_by is not None:
            raise forms.ValidationError(
                self.ALREADY_A_PURCHASING_DEPARTMENT.format(name=held_by.name)
            )

        return wants_it


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

# The format the page's own mask produces: "90-123-45-67", the nine digits
# of __-___-__-__. The +998 is printed beside the field rather than stored.
PHONE_NUMBER_FORMAT = r"^\d{2}-\d{3}-\d{2}-\d{2}$"
PHONE_NUMBER_EXAMPLE = "90-123-45-67"


def dashed_phone_number(value: str) -> str:
    """A stored number in the dashed form the page shows.

    Accounts created before the mask hold "90 123 45 67". Editing one must
    not fail over a separator the person never typed, and the list must not
    print two spellings of the same number in one column. Anything that is
    not nine digits is handed back untouched for the validator to reject.
    """
    digits = re.sub(r"\D", "", value or "")
    if len(digits) != 9:
        return value or ""

    return f"{digits[:2]}-{digits[2:5]}-{digits[5:7]}-{digits[7:]}"


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
        validators=[
            RegexValidator(PHONE_NUMBER_FORMAT, message=f"Format: {PHONE_NUMBER_EXAMPLE}")
        ],
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
                "phone_number": dashed_phone_number(profile.phone_number),
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


def pdf_upload_field(
    missing: str = "Ariza uchun PDF ilova yuklanishi shart.",
) -> forms.FileField:
    """The compulsory PDF attachment of a creation form.

    Compulsory here rather than on the column: the record stays readable
    without one, because a contract raised before the column existed has
    none, while every form that creates one asks for it.

    Args:
        missing: what to say when nobody attached a file. It names the thing
            being created, so the contract form does not tell its user that
            an Ariza needs an attachment.
    """
    return forms.FileField(
        label="Ilova (PDF)",
        required=True,
        validators=[validate_pdf],
        help_text="PDF, eng ko`pi bilan 10 MB (DEC-019).",
        error_messages={"required": missing},
        widget=forms.ClearableFileInput(attrs={"class": "form-control", "accept": ".pdf"}),
    )


def date_widget() -> forms.DateInput:
    """A date box whose value an <input type="date"> will accept.

    The format has to be said. Django renders a date in the active locale's
    first DATE_INPUT_FORMATS entry, which under LANGUAGE_CODE "uz" is
    %d.%m.%Y - and a date input whose value is not YYYY-MM-DD is one the
    browser shows as empty. On a form that creates something nothing is
    filled in and the fault is invisible; on one that edits something every
    date comes up blank and saving writes the blanks back.
    """
    return forms.DateInput(
        attrs={"class": "form-control", "type": "date"}, format="%Y-%m-%d"
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
            "shartnoma_nomi": "Ariza nomi",
            "muddat_talabi": "Muddat talabi",
            "izoh": "Izoh",
        }
        widgets = {
            "shartnoma_nomi": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Ariza nomi"}
            ),
            "muddat_talabi": date_widget(),
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
    """The Ariza raqami box: typed in, and matched against the number.

    Typed rather than picked because the list runs long and whoever is
    entering a contract has the number in front of them. Still a
    ModelChoiceField, though, and still holding the queryset of what this
    person may contract against: matching happens against those rows and no
    others, so typing a number is not a way past a rule the drop-down used
    to enforce by simply not offering it.

    to_field_name makes the number the value, so what is typed, what is
    suggested and what is matched are all one string.
    """

    def describe(self, application: Application) -> str:
        """What a number is recognised by, for the suggestion beside it.

        The number alone means little to a specialist choosing which request
        to commit the company to a supplier for; the department and the goods
        are what they know it by.
        """
        lines = list(application.items.all())
        ordered = lines[0].buyurtma_nomi if lines else "-"
        if len(lines) > 1:
            ordered = f"{ordered} +{len(lines) - 1}"

        return f"{application.department.name} - {ordered}"

    def label_from_instance(self, obj: Application) -> str:
        return f"{obj.ariza_raqami} - {self.describe(obj)}"

    def to_python(self, value: object) -> Application | None:
        """Match a typed number, forgiving the case and stray spaces.

        Somebody reading a number off another screen types it as they see it,
        and a form that refuses "arz-2026-00001" is being pedantic about the
        one thing it could fix itself.
        """
        if isinstance(value, str):
            value = value.strip().upper()

        return super().to_python(value)


class SupplierChoiceField(forms.ModelChoiceField):
    """The Firma nomi box: typed in, and matched against the firm's name.

    A list of firms outgrows a drop-down the way the applications did, so it
    is searched rather than scrolled. Still a ModelChoiceField holding the
    firms this form offers, so what is typed is matched against those rows
    and a name that is not one of them is refused.

    The INN is still shown beside the box rather than typed (DEC-011); the
    suggestion carries it and a small script copies it across.
    """

    def describe(self, supplier: Supplier) -> str:
        """What tells two firms apart when their names look alike."""
        return f"INN {supplier.inn}" if supplier.inn else "INN kiritilmagan"

    def label_from_instance(self, obj: Supplier) -> str:
        return obj.name

    def to_python(self, value: object) -> Supplier | None:
        """Match a typed name, forgiving the case and stray spaces.

        A name is not a code, so it cannot simply be upper-cased the way a
        number can: the canonical spelling is looked up and then matched, so
        "tayyor mahsulot mchj" finds the firm without the row having to be
        stored twice.
        """
        if isinstance(value, str) and value.strip():
            typed = value.strip()
            named = self.queryset.filter(name__iexact=typed).first()
            value = named.name if named is not None else typed

        return super().to_python(value)


class ContractForm(forms.ModelForm):
    """The header of the Shartnoma Kiritish form (REQ-SHARTNOMA-006).

    Shartnoma qiymati is not a field: it is the sum of the rows. The
    applications that may be chosen are passed in, because which ones this
    person may contract against is a question about who is asking.

    A PDF is compulsory here (REQ-SHARTNOMA-010): a contract is a document
    before it is a row, and the row without the document it records is a
    claim nobody can check.
    """

    application = ApplicationChoiceField(
        # Replaced in __init__ with what this person may contract against.
        # Empty here so that a caller who forgets is offered nothing rather
        # than everything.
        queryset=Application.objects.none(),
        to_field_name="ariza_raqami",
        label="Ariza raqami",
        widget=forms.TextInput(
            attrs={
                **CONTROL,
                "placeholder": "ARZ-2026-00001",
                # No list= attribute: the suggestions are drawn in the page
                # (see the combo macro), and a datalist as well would put a
                # second popup over the first.
                "autocomplete": "off",
                "role": "combobox",
                "aria-autocomplete": "list",
                "aria-expanded": "false",
            }
        ),
        error_messages={
            "invalid_choice": (
                "%(value)s raqamli tayinlangan ariza topilmadi. "
                "Ro`yxatdan tanlang yoki raqamni tekshiring."
            )
        },
    )
    supplier = SupplierChoiceField(
        # Every firm, as the generated drop-down offered before this: which
        # firms exist is not a question about who is asking, so unlike the
        # applications above it is not narrowed per person.
        queryset=Supplier.objects.all(),
        to_field_name="name",
        label="Firma nomi",
        widget=forms.TextInput(
            attrs={
                **CONTROL,
                "placeholder": "Firma nomini yozing",
                "autocomplete": "off",
                "role": "combobox",
                "aria-autocomplete": "list",
                "aria-expanded": "false",
            }
        ),
        error_messages={
            "invalid_choice": (
                "%(value)s nomli firma topilmadi. "
                "Ro`yxatdan tanlang yoki nomni tekshiring."
            )
        },
    )
    pdf = pdf_upload_field("Shartnoma uchun PDF ilova yuklanishi shart.")

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
            "invoice_sanasi",
            "izoh",
            "pdf",
        )
        labels = {
            "shartnoma_turi": "Shartnoma turi",
            "status": "Status",
            "shartnoma_sanasi": "Shartnoma sanasi",
            "tolash_muddati": "To`lash muddati",
            "muddat_talabi": "Muddat talabi",
            "invoice_sanasi": "Invoice sanasi",
            "izoh": "Izoh",
        }
        widgets = {
            "shartnoma_turi": forms.Select(attrs=CONTROL),
            "status": forms.Select(attrs=CONTROL),
            "shartnoma_sanasi": date_widget(),
            "tolash_muddati": date_widget(),
            "muddat_talabi": date_widget(),
            "invoice_sanasi": date_widget(),
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


class ContractEditForm(ContractForm):
    """The same form again, for a contract that already exists (TASK-UZK-064).

    One difference: the attachment is optional. Creation demands a PDF
    because a contract is a document before it is a row, and that argument
    does not carry over to correcting a mistyped price on a contract whose
    document is already on file. Leaving the box empty keeps the file that
    is there; choosing one replaces it.
    """

    # FileInput, not the ClearableFileInput the creation form uses: a
    # clearable input renders a link to the file it already has, and an
    # attachment has no URL by design (DEC-019) - asking for one raises. The
    # page links to the download view instead, which checks permission.
    pdf = forms.FileField(
        label="Ilova (PDF)",
        required=False,
        validators=[validate_pdf],
        help_text="Yangi fayl tanlansa, avvalgisi almashtiriladi (DEC-019).",
        widget=forms.FileInput(attrs={"class": "form-control", "accept": ".pdf"}),
    )

    def __init__(self, *args, **kwargs) -> None:
        """Open the two combos on what they hold rather than on its id.

        Both are choice fields matched on a name - the ariza number and the
        firm's name - drawn as boxes somebody types into. A ModelForm fills
        its initial values from model_to_dict, which gives the primary key,
        so without this the form opens reading "1" where the contract says
        ARZ-2026-00001, and saving it unchanged is a different contract or
        no contract at all.
        """
        super().__init__(*args, **kwargs)

        if self.instance.pk:
            self.initial["application"] = self.instance.application.ariza_raqami
            self.initial["supplier"] = self.instance.supplier.name


# The rows of a contract being edited. extra=0 because the rows already
# exist and a blank one is added by the page's own button, and can_delete
# because a row is removed by saying so rather than by being emptied: a
# cleared row of a model formset fails its required fields instead of going
# away.
ContractItemEditFormSet = forms.modelformset_factory(
    ContractItem,
    form=ContractItemForm,
    extra=0,
    min_num=1,
    validate_min=True,
    can_delete=True,
)
