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
    MahsulotTuri,
    Supplier,
)
from xarid.navigation import navigation_page_names
from xarid.permissions import (
    ADMIN_ONLY_PAGES,
    PAGES_BY_USER_TYPE,
    _PURCHASING_DEPARTMENT_PAGES as PURCHASING_DEPARTMENT_PAGES,
    decides_on_contracts,
)

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

    def test_signing_in_never_lands_on_a_refusal(self) -> None:
        """The report this answers: signing in correctly and getting a 403.

        The login page carries wherever the visitor was turned away from, and
        the browser is shared - one person signs out of a page and the next
        signs in on the same form. The address is somewhere the first account
        could go and the second cannot, and obeying it answers 403 to somebody
        who has just proved who they are.
        """
        for role, landing in (
            (KATTA_MUTAXASIS, "tayinlangan"),
            (USERS, "xarid-ariza"),
            (DIREKTOR, "dashboard"),
        ):
            with self.subTest(user_type=role):
                account = make_user(f"next.{role}".lower().replace(" ", "."), user_type=role)
                self.client.logout()

                landed = self.client.post(
                    f"{reverse('login')}?next={page('users')}",
                    {"username": account.get_username(), "password": PASSWORD},
                    follow=True,
                )

                self.assertEqual(landed.status_code, 200)
                self.assertEqual(landed.redirect_chain[-1][0], page(landing))

    def test_a_next_the_account_may_open_is_still_obeyed(self) -> None:
        """Dropping one that refuses is not dropping all of them."""
        landed = self.client.post(
            f"{reverse('login')}?next={page('users')}",
            {"username": "b.toshmatov", "password": PASSWORD},
            follow=True,
        )

        self.assertEqual(landed.redirect_chain[-1][0], page("users"))

    def test_a_next_that_is_not_a_matrix_page_is_left_alone(self) -> None:
        """Somebody's own notifications are not a page the matrix answers for."""
        account = make_user("next.notified", user_type=USERS)
        self.client.logout()

        landed = self.client.post(
            f"{reverse('login')}?next={page('notifications')}",
            {"username": account.get_username(), "password": PASSWORD},
            follow=True,
        )

        self.assertEqual(landed.redirect_chain[-1][0], page("notifications"))

    def test_the_site_root_sends_every_type_somewhere_they_may_work(self) -> None:
        """Typing the host is not asking for the dashboard by name."""
        for role, landing in (
            (ADMIN, None),
            (BOLIM_BOSHLIGI, None),
            (MENEJER, None),
            (DIREKTOR, None),
            (KATTA_MUTAXASIS, "tayinlangan"),
            (USERS, "xarid-ariza"),
        ):
            with self.subTest(user_type=role):
                self.client.force_login(
                    make_user(f"root.{role}".lower().replace(" ", "."), user_type=role)
                )

                landed = self.client.get("/", follow=True)

                self.assertEqual(landed.status_code, 200)
                if landing is None:
                    self.assertEqual(landed.redirect_chain, [])
                else:
                    self.assertEqual(landed.redirect_chain[-1][0], page(landing))

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
        """The matrix by type, with nobody in the purchasing department.

        The pages that are that department's own are held back here, because
        holding the type is not what opens them: these accounts have no
        department, and no department is marked as the purchasing one, so
        those pages fall closed. DepartmentHeadPagesTests is where they are
        asked for by somebody who is in it.
        """
        for type_name, granted in PAGES_BY_USER_TYPE.items():
            permitted = granted - PURCHASING_DEPARTMENT_PAGES
            account = make_user(type_name.lower().replace(" ", "."), user_type=type_name)
            self.client.force_login(account)
            for page_name in navigation_page_names():
                with self.subTest(user_type=type_name, page=page_name):
                    expected = 200 if page_name in permitted else 403
                    # The root is the one page that sends a refusal onwards
                    # rather than answering it: see page_or_landing().
                    if page_name == "dashboard" and expected == 403:
                        onwards = self.client.get(page(page_name), follow=True)
                        self.assertEqual(onwards.status_code, 200)
                        self.assertTrue(onwards.redirect_chain)
                        continue

                    self.assertEqual(self.client.get(page(page_name)).status_code, expected)

    def test_admin_only_pages_are_refused_to_every_other_type(self) -> None:
        for type_name in PAGES_BY_USER_TYPE:
            self.assertTrue(ADMIN_ONLY_PAGES.isdisjoint(PAGES_BY_USER_TYPE[type_name]))

    def test_an_account_with_no_type_opens_nothing(self) -> None:
        """Including the root, which has nowhere to send them."""
        self.client.force_login(make_user("untyped"))

        for page_name in navigation_page_names():
            with self.subTest(page=page_name):
                self.assertEqual(
                    self.client.get(page(page_name), follow=True).status_code, 403
                )

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


class DepartmentHeadPagesTests(TestCase):
    """What a Bo`lim Boshlig`i keeps depends on which department they are in."""

    OUTSIDE = frozenset({"kelib-arizalar", "qabul-arizalar", "xarid-ariza"})

    @classmethod
    def setUpTestData(cls) -> None:
        cls.purchasing = a_department("Xarid bo`limi")
        cls.elsewhere = a_department("Ishlab chiqarish")

    def mark_the_purchasing_department(self) -> None:
        self.purchasing.is_purchasing = True
        self.purchasing.save(update_fields=["is_purchasing"])

    def test_a_head_outside_it_keeps_only_the_three_pages_that_are_theirs(self) -> None:
        self.mark_the_purchasing_department()
        self.client.force_login(
            make_user("outside.head", user_type=BOLIM_BOSHLIGI, department=self.elsewhere)
        )

        for page_name in navigation_page_names():
            with self.subTest(page=page_name):
                expected = 200 if page_name in self.OUTSIDE else 403
                # The root sends them to their own first page instead.
                if page_name == "dashboard":
                    self.assertEqual(
                        self.client.get(page(page_name), follow=True).status_code, 200
                    )
                    continue

                self.assertEqual(self.client.get(page(page_name)).status_code, expected)

    def test_a_head_inside_it_keeps_the_whole_of_section_11(self) -> None:
        self.mark_the_purchasing_department()
        self.client.force_login(
            make_user("inside.head", user_type=BOLIM_BOSHLIGI, department=self.purchasing)
        )

        for page_name in PAGES_BY_USER_TYPE[BOLIM_BOSHLIGI]:
            with self.subTest(page=page_name):
                self.assertEqual(self.client.get(page(page_name)).status_code, 200)

    def test_the_purchasing_head_reads_the_contracts_and_decides_them(self) -> None:
        """Tuzilgan Shartnomalar is theirs to read and theirs to decide.

        DEC-013 read REQ-SHARTNOMA-002's department head as Admin, because
        "Admin is the Xarid bo`lim boshlig`i". TASK-UZK-067 gives the
        decision to the head and the Menejer of the purchasing department
        as well, where it is staffed by accounts of their own types.
        """
        self.mark_the_purchasing_department()
        head = make_user("signing.head", user_type=BOLIM_BOSHLIGI, department=self.purchasing)
        self.client.force_login(head)

        self.assertEqual(self.client.get(page("tuzilgan")).status_code, 200)
        self.assertTrue(decides_on_contracts(head))

    def test_the_purchasing_head_maintains_the_product_categories(self) -> None:
        """Mahsulot Turlari is theirs to open, and theirs to add to.

        The categories are what every application and every report is written
        in terms of, and the purchasing department's head is who knows a new
        one is needed. A head elsewhere raises requests in the ones that
        already exist, so the page is not theirs.
        """
        self.mark_the_purchasing_department()
        self.client.force_login(
            make_user("category.head", user_type=BOLIM_BOSHLIGI, department=self.purchasing)
        )

        opened = self.client.get(page("mahsulot-turlari"))
        self.assertEqual(opened.status_code, 200)
        # And the sidebar offers it, rather than leaving them to guess the URL.
        self.assertContains(opened, "Mahsulot Turlari")

        added = self.client.post(
            page("mahsulot-turlari-create"), {"category_number": "", "name": "Kimyo"}
        )
        self.assertEqual(added.status_code, 302)
        self.assertEqual(MahsulotTuri.objects.get(name="Kimyo").category_number, 100000)

        self.client.force_login(
            make_user("elsewhere.head", user_type=BOLIM_BOSHLIGI, department=self.elsewhere)
        )
        self.assertEqual(self.client.get(page("mahsulot-turlari")).status_code, 403)
        self.assertEqual(
            self.client.post(
                page("mahsulot-turlari-create"), {"category_number": "", "name": "Metall"}
            ).status_code,
            403,
        )

    def test_the_purchasing_department_keeps_the_list_of_firms(self) -> None:
        """Firmalar is theirs to open and theirs to add to.

        Its head, its Menejer and its Katta Mutaxasis are the people who deal
        with the firms and who know when a new one is needed; the same three
        types in another department do not, so the page is not theirs.
        """
        self.mark_the_purchasing_department()

        for number, user_type in enumerate((BOLIM_BOSHLIGI, MENEJER, KATTA_MUTAXASIS)):
            with self.subTest(user_type=user_type, department="xarid"):
                self.client.force_login(
                    make_user(f"firma.in.{number}", user_type=user_type, department=self.purchasing)
                )

                self.assertEqual(self.client.get(page("firmalar")).status_code, 200)
                added = self.client.post(
                    page("firmalar-create"),
                    {"name": f"Firma {number}", "inn": f"12345678{number}"},
                )
                self.assertEqual(added.status_code, 302)

            with self.subTest(user_type=user_type, department="elsewhere"):
                self.client.force_login(
                    make_user(f"firma.out.{number}", user_type=user_type, department=self.elsewhere)
                )

                self.assertEqual(self.client.get(page("firmalar")).status_code, 403)
                refused = self.client.post(
                    page("firmalar-create"), {"name": "Boshqa", "inn": "999999999"}
                )
                self.assertEqual(refused.status_code, 403)

        self.assertEqual(Supplier.objects.count(), 3)

    def test_the_sidebar_offers_the_firms_to_the_purchasing_department(self) -> None:
        self.mark_the_purchasing_department()
        self.client.force_login(
            make_user("firma.menejer", user_type=MENEJER, department=self.purchasing)
        )

        rendered = self.client.get(page("kelishinlingan")).content.decode()

        self.assertIn(page("firmalar"), rendered)

    def test_a_head_outside_the_purchasing_department_decides_nothing(self) -> None:
        """Its own, not any: they cannot even open the page."""
        self.mark_the_purchasing_department()
        head = make_user("outside.signing", user_type=BOLIM_BOSHLIGI, department=self.elsewhere)

        self.assertFalse(decides_on_contracts(head))

    def test_the_purchasing_head_opens_the_dashboard_and_its_ranking(self) -> None:
        """The two travel together: the panel on one links to the other."""
        self.mark_the_purchasing_department()
        self.client.force_login(
            make_user("panel.head", user_type=BOLIM_BOSHLIGI, department=self.purchasing)
        )

        rendered = self.client.get(page("dashboard"))

        self.assertEqual(rendered.status_code, 200)
        # The Top suppliers panel's own link, which must not answer 403.
        self.assertContains(rendered, f'href="{page("top-suppliers")}"')
        self.assertEqual(self.client.get(page("top-suppliers")).status_code, 200)

    def test_a_head_outside_it_gets_neither(self) -> None:
        """Neither is theirs; the root sends them on rather than refusing."""
        self.mark_the_purchasing_department()
        self.client.force_login(
            make_user("nopanel.head", user_type=BOLIM_BOSHLIGI, department=self.elsewhere)
        )

        landed = self.client.get(page("dashboard"), follow=True)
        self.assertEqual(landed.redirect_chain[-1][0], page("kelib-arizalar"))
        self.assertEqual(self.client.get(page("top-suppliers")).status_code, 403)

    def test_a_head_outside_it_does_not_read_the_contracts(self) -> None:
        self.mark_the_purchasing_department()
        self.client.force_login(
            make_user("other.head", user_type=BOLIM_BOSHLIGI, department=self.elsewhere)
        )

        self.assertEqual(self.client.get(page("tuzilgan")).status_code, 403)

    def test_nothing_narrows_until_a_purchasing_department_is_named(self) -> None:
        """The same switch the arrived queue waits for.

        Except the pages that are the purchasing department's own, which fall
        closed rather than open: until somebody has been put in that
        department, editing the list of firms the company buys from stays
        where it was, with Admin.
        """
        self.client.force_login(
            make_user("unmarked.head", user_type=BOLIM_BOSHLIGI, department=self.elsewhere)
        )

        for page_name in PAGES_BY_USER_TYPE[BOLIM_BOSHLIGI] - PURCHASING_DEPARTMENT_PAGES:
            with self.subTest(page=page_name):
                self.assertEqual(self.client.get(page(page_name)).status_code, 200)

        for page_name in PURCHASING_DEPARTMENT_PAGES:
            with self.subTest(page=page_name, falls="closed"):
                self.assertEqual(self.client.get(page(page_name)).status_code, 403)

    def test_the_sidebar_offers_the_three_and_nothing_else(self) -> None:
        self.mark_the_purchasing_department()
        self.client.force_login(
            make_user("sidebar.head", user_type=BOLIM_BOSHLIGI, department=self.elsewhere)
        )

        rendered = self.client.get(page("xarid-ariza")).content.decode()

        for page_name in self.OUTSIDE:
            self.assertIn(f'href="{page(page_name)}"', rendered)
        for page_name in ("tayinlangan", "kelishinlingan", "xodimlar-yuklamasi"):
            self.assertNotIn(f'href="{page(page_name)}"', rendered)

    def test_the_kept_approval_page_is_still_where_they_approve(self) -> None:
        """Removing it would leave DEC-016's first step with nowhere to happen."""
        self.mark_the_purchasing_department()
        head = make_user("approving.head", user_type=BOLIM_BOSHLIGI, department=self.elsewhere)
        requester = make_user("their.requester", user_type=USERS, department=self.elsewhere)
        request = a_purchase_application(requester, self.elsewhere, with_pdf=False)
        self.client.force_login(head)

        self.assertContains(self.client.get(page("kelib-arizalar")), request.xarid_raqami)
        self.client.post(page("xarid-ariza-tasdiqlash", request.pk))

        request.refresh_from_db()
        self.assertEqual(request.tasdiqlagan_bolim_boshligi, head)


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

    def test_a_requester_reads_only_the_requests_they_raised(self) -> None:
        """Xarid Arizasi is the one page a Users account has, and it is theirs."""
        other_requester = make_user("requester2", user_type=USERS, department=self.department)
        mine = a_purchase_application(self.requester, self.department, with_pdf=False)
        theirs = a_purchase_application(other_requester, self.department, with_pdf=False)
        self.client.force_login(self.requester)

        response = self.client.get(page("xarid-ariza"))

        self.assertContains(response, mine.xarid_raqami)
        self.assertNotContains(response, theirs.xarid_raqami)

    def test_a_requester_cannot_download_another_requester_s_attachment(self) -> None:
        other_requester = make_user("requester3", user_type=USERS, department=self.department)
        theirs = a_purchase_application(other_requester, self.department)
        mine = a_purchase_application(self.requester, self.department)
        self.client.force_login(self.requester)

        self.assertEqual(self.client.get(page("xarid-ariza-pdf", mine.pk)).status_code, 200)
        self.assertEqual(self.client.get(page("xarid-ariza-pdf", theirs.pk)).status_code, 404)

    def test_a_requester_cannot_download_another_requester_s_ariza_pdf(self) -> None:
        """The generated sheet answers to the same rule as the attachment."""
        other_requester = make_user("requester4", user_type=USERS, department=self.department)
        theirs = a_purchase_application(other_requester, self.department)
        mine = a_purchase_application(self.requester, self.department)
        self.client.force_login(self.requester)

        self.assertEqual(
            self.client.get(page("xarid-ariza-hujjat-pdf", mine.pk)).status_code, 200
        )
        self.assertEqual(
            self.client.get(page("xarid-ariza-hujjat-pdf", theirs.pk)).status_code, 404
        )

    def test_admin_alone_still_reads_every_request(self) -> None:
        """The one account that maintains the rest keeps the whole table."""
        raised = a_purchase_application(self.requester, self.department, with_pdf=False)
        self.client.force_login(self.admin)

        self.assertContains(self.client.get(page("xarid-ariza")), raised.xarid_raqami)

    def test_no_other_type_reads_a_request_it_did_not_raise(self) -> None:
        """Xarid Arizasi is each reader's own work, whatever type they are.

        The approvers are here too: a Direktor decides on Kelib Tushgan
        Arizalar and reads back what they let through on Tasdiqlangan
        Arizalar, so this page owes them nothing of somebody else's.
        """
        somebody_elses = a_purchase_application(
            self.requester, self.department, with_pdf=False
        )
        menejer = make_user("menejer", user_type=MENEJER, department=self.department)

        for reader in (self.direktor, menejer, self.specialist, self.head):
            with self.subTest(reader=reader.get_username()):
                self.client.force_login(reader)
                self.assertNotContains(
                    self.client.get(page("xarid-ariza")), somebody_elses.xarid_raqami
                )

    def test_a_head_reads_only_their_own_requests_on_xarid_arizasi(self) -> None:
        """The page they raise from; the ones they decide are on their other two."""
        somebody_elses = a_purchase_application(
            self.requester, self.department, with_pdf=False
        )
        mine = a_purchase_application(self.head, self.department, with_pdf=False)
        self.client.force_login(self.head)

        response = self.client.get(page("xarid-ariza"))

        self.assertContains(response, mine.xarid_raqami)
        self.assertNotContains(response, somebody_elses.xarid_raqami)

    def test_a_head_still_opens_the_pdf_of_a_request_waiting_for_them(self) -> None:
        """Deciding a request blind is not deciding it."""
        waiting = a_purchase_application(self.requester, self.department)
        self.client.force_login(self.head)

        self.assertEqual(self.client.get(page("xarid-ariza-pdf", waiting.pk)).status_code, 200)
        self.assertEqual(
            self.client.get(page("xarid-ariza-hujjat-pdf", waiting.pk)).status_code, 200
        )

    def test_a_head_still_opens_the_pdf_of_a_request_they_approved(self) -> None:
        """Tasdiqlangan Arizalar shows both badges, so both have to open."""
        decided = a_purchase_application(self.requester, self.department)
        decided.approve(by=self.head)
        self.client.force_login(self.head)

        self.assertEqual(self.client.get(page("xarid-ariza-pdf", decided.pk)).status_code, 200)
        self.assertEqual(
            self.client.get(page("xarid-ariza-hujjat-pdf", decided.pk)).status_code, 200
        )

    def test_a_head_cannot_open_the_pdf_of_another_department_s_request(self) -> None:
        elsewhere = a_department("Moliya bo`limi")
        stranger = make_user("moliya.user", user_type=USERS, department=elsewhere)
        theirs = a_purchase_application(stranger, elsewhere)
        self.client.force_login(self.head)

        self.assertEqual(self.client.get(page("xarid-ariza-pdf", theirs.pk)).status_code, 404)
        self.assertEqual(
            self.client.get(page("xarid-ariza-hujjat-pdf", theirs.pk)).status_code, 404
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
