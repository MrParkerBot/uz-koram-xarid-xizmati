"""Tests for authentication, page permissions and ownership.

Authentication is the one place where a test that only proves the happy path
is worse than no test at all, so these cover what must not happen as
carefully as what must.
"""

from __future__ import annotations

from django.conf import settings
from django.test import TestCase
from django.urls import reverse
from django.utils.crypto import get_random_string

from tests.support import (
    PASSWORD,
    SignedInAdminTestCase,
    a_department,
    a_purchase_application,
    an_accepted_application,
    an_application,
    an_assigned_application,
    make_user,
    page,
)
from xarid.models import (
    ADMIN,
    BOLIM_BOSHLIGI,
    DIREKTOR,
    KATTA_MUTAXASIS,
    MENEJER,
    USERS,
)
from xarid.navigation import navigation_page_names
from xarid.permissions import ADMIN_ONLY_PAGES, PAGES_BY_USER_TYPE

WRONG_PASSWORD = get_random_string(24)
REJECTION_MESSAGE = "Username yoki parol noto'g'ri"


class AuthenticationTestCase(TestCase):
    """One real account, created the way the application will create them."""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.user = make_user(
            "b.toshmatov", user_type=ADMIN, first_name="Bobur", last_name="Toshmatov"
        )

    def sign_in(self, username: str = "b.toshmatov", password: str = PASSWORD):
        return self.client.post(reverse("login"), {"username": username, "password": password})


class LoginTests(AuthenticationTestCase):
    def test_the_login_page_is_reachable_and_uses_the_shared_base(self) -> None:
        response = self.client.get(reverse("login"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<title>Kirish - Uz-Koram</title>")
        self.assertContains(response, "xarid/css/style.css")
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.assertContains(response, 'method="post"')
        self.assertContains(response, 'class="login-body"')

    def test_the_login_page_has_no_application_chrome(self) -> None:
        response = self.client.get(reverse("login"))

        self.assertNotContains(response, 'class="sidebar"')
        self.assertNotContains(response, 'class="top-header"')
        self.assertContains(response, 'class="anon-nav"')

    def test_valid_credentials_start_a_session_and_land_on_a_permitted_page(self) -> None:
        response = self.sign_in()

        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)
        self.assertRedirects(response, page("landing"), target_status_code=302)
        self.assertRedirects(self.client.get(page("landing")), page("dashboard"))

    def test_a_wrong_password_and_an_unknown_username_are_rejected_alike(self) -> None:
        wrong_password = self.sign_in(password=WRONG_PASSWORD)
        unknown_user = self.sign_in(username="nobody", password=WRONG_PASSWORD)

        for response in (wrong_password, unknown_user):
            with self.subTest(response=response):
                self.assertEqual(response.status_code, 200)
                self.assertNotIn("_auth_user_id", self.client.session)
                self.assertContains(response, REJECTION_MESSAGE)
                self.assertNotContains(response, "Foydalanuvchi topilmadi")
                self.assertNotContains(response, WRONG_PASSWORD)

    def test_an_empty_submission_is_rejected(self) -> None:
        response = self.client.post(reverse("login"), {})

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_signing_in_changes_the_session_key(self) -> None:
        self.client.get(reverse("login"))
        self.client.session.save()
        key_before = self.client.session.session_key

        self.sign_in()

        self.assertNotEqual(self.client.session.session_key, key_before)

    def test_an_authenticated_visitor_is_sent_on_rather_than_shown_the_form(self) -> None:
        self.sign_in()

        response = self.client.get(reverse("login"))

        self.assertRedirects(response, page("landing"), target_status_code=302)

    def test_signing_in_returns_the_visitor_to_the_page_they_asked_for(self) -> None:
        target = page("tuzilgan")

        response = self.client.post(
            f"{reverse('login')}?next={target}",
            {"username": "b.toshmatov", "password": PASSWORD},
        )

        self.assertRedirects(response, target)


class LogoutTests(AuthenticationTestCase):
    def test_logout_ends_the_session_and_shows_the_logged_out_page(self) -> None:
        self.sign_in()

        response = self.client.post(reverse("logout"))

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertContains(response, "Qayta kirish")
        self.assertContains(response, reverse("login"))

    def test_a_get_request_does_not_end_the_session(self) -> None:
        self.sign_in()

        response = self.client.get(reverse("logout"))

        self.assertEqual(response.status_code, 405)
        self.assertIn("_auth_user_id", self.client.session)


class ProtectedPageTests(AuthenticationTestCase):
    def test_every_page_redirects_an_anonymous_visitor_to_the_login_page(self) -> None:
        for page_name in navigation_page_names():
            with self.subTest(page=page_name):
                response = self.client.get(page(page_name))

                self.assertEqual(response.status_code, 302)
                self.assertTrue(response.url.startswith(reverse("login")))

    def test_the_redirect_remembers_where_the_visitor_was_going(self) -> None:
        target = page("logs")

        response = self.client.get(target)

        self.assertIn(f"next={target}", response.url)

    def test_every_page_answers_once_signed_in(self) -> None:
        self.client.force_login(self.user)

        for page_name in navigation_page_names():
            with self.subTest(page=page_name):
                self.assertEqual(self.client.get(page(page_name)).status_code, 200)

    def test_the_password_change_page_requires_a_session(self) -> None:
        anonymous = self.client.get(reverse("password_change"))
        self.assertEqual(anonymous.status_code, 302)

        self.client.force_login(self.user)
        signed_in = self.client.get(reverse("password_change"))
        self.assertEqual(signed_in.status_code, 200)
        self.assertContains(signed_in, 'class="sidebar"')

    def test_a_user_can_change_their_own_password(self) -> None:
        self.client.force_login(self.user)
        new_password = get_random_string(24)

        response = self.client.post(
            reverse("password_change"),
            {
                "old_password": PASSWORD,
                "new_password1": new_password,
                "new_password2": new_password,
            },
        )

        self.assertRedirects(response, reverse("password_change_done"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(new_password))


class PasswordHandlingTests(AuthenticationTestCase):
    def test_the_stored_password_is_hashed(self) -> None:
        self.assertNotIn(PASSWORD, self.user.password)
        self.assertTrue(self.user.password.startswith("pbkdf2_"))
        self.assertTrue(self.user.check_password(PASSWORD))

    def test_no_password_appears_on_any_page(self) -> None:
        self.assertNotContains(self.client.get(reverse("login")), PASSWORD)
        self.client.force_login(self.user)

        for page_name in ("dashboard", "users"):
            with self.subTest(page=page_name):
                self.assertNotContains(self.client.get(page(page_name)), PASSWORD)

    def test_the_session_cookie_flags(self) -> None:
        self.assertTrue(settings.SESSION_COOKIE_HTTPONLY)
        self.assertEqual(settings.SESSION_COOKIE_SECURE, settings.CSRF_COOKIE_SECURE)


class SignedInIdentityTests(AuthenticationTestCase):
    def test_the_header_shows_who_is_signed_in_and_their_type(self) -> None:
        self.client.force_login(self.user)

        response = self.client.get(page("dashboard"))

        self.assertContains(response, "Bobur Toshmatov")
        self.assertContains(response, ADMIN)
        self.assertContains(response, ">BT<")
        self.assertContains(response, reverse("logout"))
        self.assertContains(response, reverse("password_change"))


class PagePermissionTests(TestCase):
    """DEC-015: which User Type may open which page."""

    def test_each_type_opens_its_pages_and_is_refused_the_rest(self) -> None:
        for type_name, permitted in PAGES_BY_USER_TYPE.items():
            account = make_user(type_name.lower().replace(" ", "."), user_type=type_name)
            self.client.force_login(account)
            for page_name in navigation_page_names():
                with self.subTest(user_type=type_name, page=page_name):
                    expected = 200 if page_name in permitted else 403
                    self.assertEqual(self.client.get(page(page_name)).status_code, expected)

    def test_admin_only_pages_are_refused_to_every_other_type(self) -> None:
        for type_name in PAGES_BY_USER_TYPE:
            self.assertTrue(ADMIN_ONLY_PAGES.isdisjoint(PAGES_BY_USER_TYPE[type_name]))

    def test_an_account_with_no_type_opens_nothing(self) -> None:
        self.client.force_login(make_user("untyped"))

        for page_name in navigation_page_names():
            with self.subTest(page=page_name):
                self.assertEqual(self.client.get(page(page_name)).status_code, 403)

    def test_a_superuser_opens_everything(self) -> None:
        self.client.force_login(make_user("root", is_staff=True, is_superuser=True))

        for page_name in navigation_page_names():
            with self.subTest(page=page_name):
                self.assertEqual(self.client.get(page(page_name)).status_code, 200)

    def test_the_sidebar_shows_only_what_the_user_may_open(self) -> None:
        self.client.force_login(make_user("requester", user_type=USERS))

        rendered = self.client.get(page("xarid-ariza")).content.decode()

        self.assertIn(page("xarid-ariza"), rendered)
        self.assertNotIn(f'href="{page("users")}"', rendered)
        self.assertNotIn("Ma'lumotlar", rendered)

    def test_an_action_answers_to_the_permission_of_its_page(self) -> None:
        self.client.force_login(make_user("requester", user_type=USERS))
        application = an_application()

        self.assertEqual(self.client.post(page("ariza-qabul", application.pk)).status_code, 403)
        self.assertEqual(self.client.post(page("user-create"), {}).status_code, 403)


class OwnershipTests(SignedInAdminTestCase):
    """A user may not act on another user's private records."""

    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        cls.specialist = make_user("spec", user_type=KATTA_MUTAXASIS)
        cls.other_specialist = make_user("spec2", user_type=KATTA_MUTAXASIS)
        cls.department = a_department("Texnik bo`lim")
        cls.other_department = a_department("Moliya bo`limi")
        cls.requester = make_user("requester", user_type=USERS, department=cls.department)
        cls.head = make_user("head", user_type=BOLIM_BOSHLIGI, department=cls.department)
        cls.other_head = make_user(
            "other.head", user_type=BOLIM_BOSHLIGI, department=cls.other_department
        )
        cls.direktor = make_user("direktor", user_type=DIREKTOR)

    def test_a_specialist_cannot_take_or_report_on_another_specialist_s_work(self) -> None:
        theirs = an_assigned_application(self.admin, self.other_specialist)
        self.client.force_login(self.specialist)

        self.assertEqual(self.client.post(page("tayinlangan-qabul", theirs.pk)).status_code, 403)
        self.assertEqual(
            self.client.post(page("tayinlangan-holat", theirs.pk), {"status": "1"}).status_code,
            403,
        )
        theirs.refresh_from_db()
        self.assertFalse(theirs.is_taken)

    def test_a_department_head_cannot_decide_another_department_s_request(self) -> None:
        request = a_purchase_application(self.requester, self.department, with_pdf=False)
        self.client.force_login(self.other_head)

        self.assertEqual(
            self.client.post(page("xarid-ariza-tasdiqlash", request.pk)).status_code, 403
        )
        self.assertEqual(
            self.client.post(
                page("xarid-ariza-inkor", request.pk), {"inkor_izohi": "No"}
            ).status_code,
            403,
        )
        request.refresh_from_db()
        self.assertTrue(request.awaits(self.head))

    def test_a_direktor_cannot_approve_out_of_order(self) -> None:
        request = a_purchase_application(self.requester, self.department, with_pdf=False)
        self.client.force_login(self.direktor)

        self.assertEqual(
            self.client.post(page("xarid-ariza-tasdiqlash", request.pk)).status_code, 403
        )

    def test_a_requester_cannot_approve_their_own_request(self) -> None:
        request = a_purchase_application(self.requester, self.department, with_pdf=False)
        self.client.force_login(self.requester)

        self.assertEqual(
            self.client.post(page("xarid-ariza-tasdiqlash", request.pk)).status_code, 403
        )

    def test_an_attachment_follows_the_page_its_application_is_on(self) -> None:
        application = an_application(with_pdf=True)
        self.client.force_login(self.direktor)

        # Direktor may open Kelib tushgan, so an incoming application's PDF
        # is theirs to download - until it is accepted and leaves that page.
        self.assertEqual(self.client.get(page("ariza-pdf", application.pk)).status_code, 200)
        application.accept(by=self.admin)
        self.assertEqual(self.client.get(page("ariza-pdf", application.pk)).status_code, 403)

        self.client.force_login(make_user("manager", user_type=MENEJER))
        self.assertEqual(self.client.get(page("ariza-pdf", application.pk)).status_code, 200)

    def test_a_rejected_application_s_attachment_is_on_no_page(self) -> None:
        application = an_application(with_pdf=True)
        application.reject(by=self.admin, comment="Narx")

        self.assertEqual(self.client.get(page("ariza-pdf", application.pk)).status_code, 403)

    def test_an_anonymous_visitor_cannot_download_an_attachment(self) -> None:
        application = an_accepted_application(self.admin, with_pdf=True)
        self.client.logout()

        response = self.client.get(page("ariza-pdf", application.pk))

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(reverse("login")))


class AdminSiteTests(TestCase):
    """The Django admin uses its own staff check, not the page matrix."""

    def test_the_admin_requires_a_staff_session(self) -> None:
        anonymous = self.client.get(reverse("admin:index"))
        self.assertEqual(anonymous.status_code, 302)
        self.assertIn("/admin/login/", anonymous.url)

        self.client.force_login(make_user("clerk", user_type=ADMIN))
        not_staff = self.client.get(reverse("admin:index"))
        self.assertEqual(not_staff.status_code, 302)

        self.client.force_login(make_user("root", is_staff=True, is_superuser=True))
        staff = self.client.get(reverse("admin:index"))
        self.assertEqual(staff.status_code, 200)
        self.assertContains(staff, "Xarid Xizmati")

    def test_the_application_models_are_registered(self) -> None:
        self.client.force_login(make_user("root", is_staff=True, is_superuser=True))

        for model_name in (
            "usertype",
            "arizastatus",
            "application",
            "contract",
            "purchaseapplication",
        ):
            with self.subTest(model=model_name):
                response = self.client.get(reverse(f"admin:xarid_{model_name}_changelist"))
                self.assertEqual(response.status_code, 200)
