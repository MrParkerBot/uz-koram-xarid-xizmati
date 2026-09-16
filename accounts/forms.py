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
from django.db import transaction
from django.utils.text import slugify

from accounts.models import UserProfile, UserType

MAXIMUM_USERNAME_ATTEMPTS = 1000


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
    phone_number = forms.CharField(label="Telefon Raqam", max_length=32)
    user_type = forms.ModelChoiceField(
        label="User Type",
        queryset=UserType.objects.none(),
        required=False,
    )

    def __init__(self, *args, edited_user: AbstractBaseUser | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.edited_user = edited_user
        # Resolved at construction rather than at import, so a type added
        # through the User Types page appears without a restart.
        self.fields["user_type"].queryset = UserType.objects.active()

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
        profile.phone_number = self.cleaned_data["phone_number"]
        profile.save(update_fields=["user_type", "phone_number"])

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
            },
        )
