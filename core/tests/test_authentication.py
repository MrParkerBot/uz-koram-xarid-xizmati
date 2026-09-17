"""Tests for the login and logout delivered by TASK-UZK-008.

Authentication is the one place where a test that only proves the happy path
is worse than no test at all. These cover what must not happen as carefully as
what must: a rejection that reveals whether an account exists, a session that
survives logout, a session key that a pre-login visitor could fix, and a
password reaching a rendered page.
"""

from __future__ import annotations

from pathlib import Path
from urllib.request import urlopen

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import TestCase
from django.urls import reverse
from django.utils.crypto import get_random_string

from accounts.models import UserType
from accounts.roles import ADMIN, assign_user_type
from core.navigation import navigation_url_names

USERNAME = "b.toshmatov"
FIRST_NAME = "Bobur"
LAST_NAME = "Toshmatov"

# Generated per run rather than written here, so the repository never carries a
# password string that could be tried against a real deployment.
PASSWORD = get_random_string(24)
WRONG_PASSWORD = get_random_string(24)

REJECTION_MESSAGE = "Username yoki parol noto'g'ri"

# The passwords the supplied prototype shipped in files served to the browser.
# They must not survive anywhere in what this application sends.
SUPPLIED_DEMO_PASSWORDS = ("admin123", "manager123", "spec123", "dir123")


class AuthenticationTestCase(TestCase):
    """One real account, created the way the application will create them."""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.user = get_user_model().objects.create_user(
            username=USERNAME,
            password=PASSWORD,
            first_name=FIRST_NAME,
            last_name=LAST_NAME,
        )
        # Admin, because these tests are about signing in rather than about
        # who may open what: since TASK-UZK-012 an account with no type can
        # reach no page at all, which would make every assertion here a 403.
        assign_user_type(cls.user, UserType.objects.get(name=ADMIN))

    def sign_in(self, username: str = USERNAME, password: str = PASSWORD):
        """Post the login form and return the response."""
        return self.client.post(
            reverse("login"), {"username": username, "password": password}
        )


class LoginTests(AuthenticationTestCase):
    """Valid credentials get in; nothing else does."""

    def test_the_login_page_is_reachable(self) -> None:
        response = self.client.get(reverse("login"))

        self.assertEqual(response.status_code, 200)

    def test_valid_credentials_start_a_session(self) -> None:
        self.sign_in()

        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)

    def test_valid_credentials_land_on_a_page_the_user_may_open(self) -> None:
        # TASK-UZK-012 put a landing page between the login and the dashboard:
        # three of the six User Types may not open the dashboard, so signing in
        # correctly used to answer 403. This account is an Admin, so the
        # landing page sends it to the dashboard.
        response = self.sign_in()

        self.assertRedirects(
            response, reverse("landing-page"), target_status_code=302
        )
        self.assertRedirects(
            self.client.get(reverse("landing-page")), reverse("dashboard")
        )

    def test_a_wrong_password_is_rejected(self) -> None:
        response = self.sign_in(password=WRONG_PASSWORD)

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertContains(response, REJECTION_MESSAGE)

    def test_an_unknown_username_is_rejected(self) -> None:
        response = self.sign_in(username="nobody", password=WRONG_PASSWORD)

        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertContains(response, REJECTION_MESSAGE)

    def test_a_rejection_does_not_say_which_field_was_wrong(self) -> None:
        # An error that distinguishes "no such user" from "wrong password"
        # turns the form into a way of finding out who has an account.
        unknown_user = self.sign_in(username="nobody", password=WRONG_PASSWORD)
        wrong_password = self.sign_in(password=WRONG_PASSWORD)

        for response in (unknown_user, wrong_password):
            body = response.content.decode()
            with self.subTest(response=response):
                self.assertIn(REJECTION_MESSAGE, body)
                self.assertNotIn("Foydalanuvchi topilmadi", body)
                self.assertNotIn("Parol noto'g'ri", body)

    def test_an_empty_submission_is_rejected(self) -> None:
        response = self.client.post(reverse("login"), {})

        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(response.status_code, 200)

    def test_signing_in_changes_the_session_key(self) -> None:
        # Session fixation: a key handed to a visitor before they sign in must
        # not still identify them afterwards.
        self.client.get(reverse("login"))
        self.client.session.save()
        key_before = self.client.session.session_key

        self.sign_in()

        self.assertNotEqual(self.client.session.session_key, key_before)

    def test_an_authenticated_visitor_is_sent_on_rather_than_shown_the_form(
        self,
    ) -> None:
        self.sign_in()

        response = self.client.get(reverse("login"))

        self.assertRedirects(
            response, reverse("landing-page"), target_status_code=302
        )


class LogoutTests(AuthenticationTestCase):
    """Logout has to end the session, and only on purpose."""

    def test_logout_ends_the_session(self) -> None:
        self.sign_in()

        self.client.post(reverse("logout"))

        self.assertNotIn("_auth_user_id", self.client.session)

    def test_logout_lands_on_the_login_page(self) -> None:
        self.sign_in()

        response = self.client.post(reverse("logout"))

        self.assertRedirects(response, reverse("login"))

    def test_a_get_request_does_not_end_the_session(self) -> None:
        # A logout reachable by GET can be triggered by any page that makes the
        # browser fetch the URL.
        self.sign_in()

        self.client.get(reverse("logout"))

        self.assertIn("_auth_user_id", self.client.session)


class PasswordHandlingTests(AuthenticationTestCase):
    """A password must be stored hashed and never rendered."""

    def test_the_stored_password_is_hashed(self) -> None:
        stored = self.user.password

        self.assertNotIn(PASSWORD, stored)
        self.assertTrue(stored.startswith("pbkdf2_"))
        self.assertTrue(self.user.check_password(PASSWORD))

    def test_no_password_appears_on_the_login_page(self) -> None:
        response = self.client.get(reverse("login"))

        self.assertNotContains(response, PASSWORD)

    def test_no_password_appears_after_a_failed_attempt(self) -> None:
        # The form re-renders with the username filled in. The password field
        # must come back empty rather than carrying what was typed.
        response = self.sign_in(password=WRONG_PASSWORD)

        self.assertNotContains(response, WRONG_PASSWORD)

    def test_no_password_appears_on_any_page_once_signed_in(self) -> None:
        self.sign_in()

        for url_name in ("dashboard", "users"):
            with self.subTest(page=url_name):
                response = self.client.get(reverse(url_name))

                self.assertNotContains(response, PASSWORD)

    def test_the_users_page_no_longer_carries_the_supplied_demo_passwords(
        self,
    ) -> None:
        # The supplied prototype shipped four accounts with their passwords in
        # the page and a control that revealed them. DEC-020 says the Password
        # column is not built; TASK-UZK-011 rebuilds this page on real data.
        self.sign_in()
        body = self.client.get(reverse("users")).content.decode()

        for supplied_password in SUPPLIED_DEMO_PASSWORDS:
            with self.subTest(password=supplied_password):
                self.assertNotIn(supplied_password, body)


class MockAuthenticationRemovalTests(TestCase):
    """The front end's own sign-in must be gone, not merely unused."""

    def shared_script(self) -> str:
        """The JavaScript every page loads, as it is served."""
        return Path(finders.find("js/main.js")).read_text(encoding="utf-8")

    def test_the_shared_script_no_longer_ships_credentials(self) -> None:
        source = self.shared_script()

        for supplied_password in SUPPLIED_DEMO_PASSWORDS:
            with self.subTest(password=supplied_password):
                self.assertNotIn(supplied_password, source)

    def test_the_shared_script_no_longer_signs_anyone_in(self) -> None:
        source = self.shared_script()

        self.assertNotIn("requireAuth", source)
        self.assertNotIn("sessionStorage.setItem('uzkoram_user'", source)


class SignedInIdentityTests(AuthenticationTestCase):
    """The page has to show who is signed in."""

    def test_the_signed_in_user_appears_in_the_header(self) -> None:
        self.sign_in()

        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, f"{FIRST_NAME} {LAST_NAME}")
        # TASK-UZK-010 put the User Type on the line that held the username.
        self.assertContains(response, ADMIN)

    def test_the_avatar_shows_the_user_initials(self) -> None:
        self.sign_in()

        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, ">BT<")


class LoginPageStructureTests(TestCase):
    """The login page shares the document but not the application chrome."""

    def test_it_renders_through_the_shared_document(self) -> None:
        response = self.client.get(reverse("login"))

        self.assertTemplateUsed(response, "base_document.html")
        self.assertContains(response, "<title>Kirish - Uz-Koram</title>")
        self.assertContains(response, "css/style.css")

    def test_it_does_not_carry_the_application_chrome(self) -> None:
        # The supplied design gives the sign-in page no sidebar and no header.
        response = self.client.get(reverse("login"))

        self.assertNotContains(response, 'class="sidebar"')
        self.assertNotContains(response, 'class="top-header"')

    def test_it_does_not_advertise_credentials(self) -> None:
        # The supplied page listed three usernames beside their passwords so a
        # backend-less prototype could be clicked through.
        response = self.client.get(reverse("login"))

        self.assertNotContains(response, "Demo foydalanuvchilar")
        self.assertNotContains(response, "fillDemo")

    def test_the_form_posts_with_a_csrf_token(self) -> None:
        response = self.client.get(reverse("login"))

        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.assertContains(response, 'method="post"')


class SessionCookieTests(TestCase):
    """The cookie now identifies a real user, so its flags matter."""

    def test_the_session_cookie_is_not_readable_from_javascript(self) -> None:
        self.assertTrue(settings.SESSION_COOKIE_HTTPONLY)

    def test_https_only_cookies_can_be_turned_on_from_the_environment(self) -> None:
        # Off by default because development runs over plain HTTP; a deployment
        # reachable over HTTPS sets DJANGO_SECURE_COOKIES.
        self.assertEqual(settings.SESSION_COOKIE_SECURE, settings.CSRF_COOKIE_SECURE)
        self.assertFalse(settings.SESSION_COOKIE_SECURE)


class ClosedApplicationTests(AuthenticationTestCase):
    """Every page is closed to a visitor with no session."""

    def test_every_page_redirects_an_anonymous_visitor_to_the_login_page(
        self,
    ) -> None:
        for url_name in navigation_url_names():
            with self.subTest(page=url_name):
                response = self.client.get(reverse(url_name))

                self.assertEqual(response.status_code, 302)
                self.assertTrue(response.url.startswith(reverse("login")))

    def test_the_redirect_remembers_where_the_visitor_was_going(self) -> None:
        # Otherwise signing in always lands on the dashboard and the visitor
        # has to find their way back.
        target = reverse("logs")

        response = self.client.get(target)

        self.assertIn(f"next={target}", response.url)

    def test_every_page_answers_once_signed_in(self) -> None:
        self.client.force_login(self.user)

        for url_name in navigation_url_names():
            with self.subTest(page=url_name):
                response = self.client.get(reverse(url_name))

                self.assertEqual(response.status_code, 200)

    def test_the_login_page_stays_open(self) -> None:
        # The one view that must not be closed: closing it would mean nobody
        # could ever sign in.
        response = self.client.get(reverse("login"))

        self.assertEqual(response.status_code, 200)

    def test_an_unknown_url_is_still_a_not_found(self) -> None:
        response = self.client.get("/no-such-page/")

        self.assertEqual(response.status_code, 404)

    def test_signing_in_returns_the_visitor_to_the_page_they_asked_for(self) -> None:
        target = reverse("tuzilgan")

        response = self.client.post(
            f"{reverse('login')}?next={target}",
            {"username": USERNAME, "password": PASSWORD},
        )

        self.assertRedirects(response, target)


class AnonymousAssetTests(StaticLiveServerTestCase):
    """The login page has to be able to style itself.

    Fetched over the wire without a session rather than checked in the
    markup: a page that merely asks for a stylesheet looks identical whether
    the stylesheet is served or redirected to the login form.
    """

    host = "127.0.0.1"

    def test_the_stylesheets_the_login_page_needs_are_served_anonymously(
        self,
    ) -> None:
        for asset in ("css/style.css", "css/bootstrap.min.css"):
            with (
                self.subTest(asset=asset),
                urlopen(f"{self.live_server_url}/static/{asset}") as response,
            ):
                self.assertEqual(response.status, 200)
                self.assertEqual(
                    response.headers["Content-Type"].split(";")[0], "text/css"
                )

    def test_the_login_page_asks_for_those_stylesheets(self) -> None:
        with urlopen(f"{self.live_server_url}{reverse('login')}") as response:
            page = response.read().decode()

        for asset in ("css/style.css", "css/bootstrap.min.css"):
            with self.subTest(asset=asset):
                self.assertIn(asset, page)
