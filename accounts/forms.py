"""The form behind the Users page.

The specification's form (section 3.3) captures First Name, Last Name,
Password and Phone number, and the supplied page adds User Type. It does not
capture a username, although the login page asks for one - so one is derived
from the name here and shown in the table, which is recorded as UNKNOWN for
the customer rather than decided silently.

DEC-020 governs the password: it is hashed, never displayed, and never
returned to the page. Editing a user leaves the password field empty, and
leaving it empty keeps the password they already have.
"""

from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractBaseUser
from django.contrib.auth.password_validation import validate_password
from django.core.validators import RegexValidator
from django.db import models, transaction
from django.utils.text import slugify

from accounts.models import UserProfile, UserType
from reference.models import Department

MAXIMUM_USERNAME_ATTEMPTS = 1000

# The format the page's own hint promises: "90 123 45 67". The +998 is printed
# by the page rather than stored, so a number that carried it would render as
# +998 +998 90 123 45 67.
PHONE_NUMBER_FORMAT = r"^\d{2} \d{3} \d{2} \d{2}$"


def derive_username(first_name: str, last_name: str) -> str:
    """A login name for somebody the form only gave us a real name for.

    'Bobur' and 'Toshmatov' become 'bobur.toshmatov', and a second Bobur
    Toshmatov becomes 'bobur.toshmatov2'. Transliteration is left to slugify,
    which drops the diacritics Uzbek names carry.
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



def still_offered(manager, assigned_pk: int | None):
    """The active rows, plus the one already assigned however deleted it is.

    A drop-down that offers only the active rows silently loses a deleted
    assignment: the select has no option for it, so an edit that touched
    nothing else posts an empty value and the field, being optional, is
    overwritten with None. That is the opposite of what DEC-009 deletion
    promises - a record already pointing at a deleted row keeps resolving -
    and it costs somebody their department, or their user type and with it
    every page they could open, without anybody choosing to.

    So the row somebody already holds stays in their own drop-down. It is not
    offered to anybody else, because it is not in the active set, which is the
    whole point of DEC-009: the assignment survives, the choice is gone.

    Args:
        manager: the master data manager to ask, such as UserType.objects.
        assigned_pk: the row this user currently holds, or None.
    """
    if assigned_pk is None:
        return manager.active()

    return manager.filter(models.Q(is_active=True) | models.Q(pk=assigned_pk))


class UserAdministrationForm(forms.Form):
    """Create or edit one user of the purchasing department."""

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
            RegexValidator(
                PHONE_NUMBER_FORMAT,
                message="Format: 90 123 45 67",
            )
        ],
        help_text="Uzbek national number without the +998 the page prints.",
    )
    user_type = forms.ModelChoiceField(
        label="User Type",
        queryset=UserType.objects.none(),
        required=False,
    )
    department = forms.ModelChoiceField(
        label="Bo`lim",
        queryset=Department.objects.none(),
        required=False,
        help_text=(
            "DEC-018 says everybody belongs to one, but the field is optional "
            "here: the users who existed before departments did have none, "
            "and refusing to save them would be worse than the gap."
        ),
    )

    def __init__(self, *args, edited_user: AbstractBaseUser | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.edited_user = edited_user

        profile = self.profile_being_edited()
        # Resolved at construction rather than at import, so a type or a
        # department added through its own page appears without a restart.
        self.fields["user_type"].queryset = still_offered(
            UserType.objects, profile.user_type_id if profile else None
        )
        self.fields["department"].queryset = still_offered(
            Department.objects, profile.department_id if profile else None
        )

    def profile_being_edited(self) -> UserProfile | None:
        """The profile of the user this form edits, or None when creating one."""
        if self.edited_user is None:
            return None

        return UserProfile.objects.filter(user=self.edited_user).first()

    @property
    def is_creating(self) -> bool:
        """Whether this form makes a new account rather than editing one."""
        return self.edited_user is None

    def clean_password(self) -> str:
        """Require a password on creation; validate whatever was supplied.

        An edit with an empty password is how somebody changes a phone number
        without also resetting the person's credentials.
        """
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
            user = get_user_model()(
                username=derive_username(first_name, last_name)
            )

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
