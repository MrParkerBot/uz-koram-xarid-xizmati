# Uz-Koram | Xarid Xizmati Bo'limi

Department automation for the purchasing service of "Uz-Karam Co MCHJ QK".

Built from the technical assignment
"Xarid Xizmati Bo'limi - Automatlashtirish uchun Texnik vazifa".

Stack: Python 3.12, Django 5.1, SQLite, server-rendered templates over the
supplied Bootstrap front end.

Work is tracked as `TASK-UZK-<NNN>` and lands one pull request per task.

## Running it locally

```bash
python -m venv .venv
.venv\Scripts\activate        # PowerShell: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

The application answers at <http://127.0.0.1:8000/>.

## Running the checks

Both commands must pass before a pull request is opened.

```bash
pip install -r requirements.txt -r requirements-dev.txt
python manage.py test
ruff check .
```

The suite builds a test database from the migrations on every run, so a broken
database configuration fails the tests rather than surfacing later. It also
checks that no model change is missing a migration.

`ruff.toml` lists the enabled rule set explicitly rather than relying on ruff's
defaults, so upgrading ruff cannot silently change what the gate enforces.
Generated migrations are excluded, because rewriting them by hand is how
migrations get broken.

## Configuration

Settings that differ between machines are read from the environment, so no
secret is committed. `.env.example` lists every variable with placeholder
values as a reference. Nothing loads a `.env` file at runtime, so export the
variables in your shell or set them in your deployment's environment.

| Variable | Default | Notes |
| --- | --- | --- |
| `DJANGO_SECRET_KEY` | a key generated at startup | **Set this for any real deployment.** The generated fallback changes on every restart, which invalidates sessions. |
| `DJANGO_DEBUG` | off | Accepts `1`, `true`, `yes`, `on`. Anything unrecognised is treated as off. |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma separated. |
| `DJANGO_SECURE_COOKIES` | off | **Turn this on for any deployment reachable over HTTPS.** It marks the session and CSRF cookies https-only. Off by default because development runs over plain HTTP. |

Debug is off unless the environment turns it on, so an unconfigured deployment
is the safe one rather than the permissive one.

## Front-end assets

The Bootstrap build, icon font and JavaScript supplied with the technical
assignment live in `static/` and are served as supplied. They are deliberately
not rebuilt or minified again, so the interface the customer approved is the
one that ships.

One file is deliberately different. `js/main.js` shipped with a mock sign-in
that kept four usernames and passwords in a file served to every browser;
`TASK-UZK-008` removed it and its three call sites when real authentication
arrived. Everything else in that file, and every other supplied asset, is
byte for byte what was delivered.

`js/sidebar.js` is still served but no longer loaded: `TASK-UZK-007` moved the
navigation to the server.

```bash
python manage.py collectstatic
```

## Page templates

`templates/base.html` is the shell every page sits inside. Its markup is
transcribed from the supplied static pages rather than rewritten, so the
vendored `style.css` keeps working, and its asset references go through
`{% static %}` instead of the relative paths the standalone pages used.

A page extends it and fills the blocks it needs:

| Block | What it holds |
| --- | --- |
| `page_title` | The part of `<title>` before the ` - Uz-Koram` suffix. |
| `extra_head` | Stylesheets or head scripts only that page needs. |
| `breadcrumb` | The small grey trail in the top header, e.g. `Umumiy / Dashboard`. |
| `page_heading` | The bold line under the trail. |
| `content` | The page itself, inside `.page-wrap`. |
| `extra_scripts` | Scripts that run after the shared ones. |

The sidebar's navigation list is deliberately left empty: the vendored
`sidebar.js` fills it in the browser today, and `TASK-UZK-007` replaces that
with server-side navigation. The user shown in the header and the sidebar
footer is the placeholder from the supplied pages until `TASK-UZK-008` brings
real authentication.

`templates/pages/` holds one template per supplied page. Each extends
`base.html`, keeps its own markup in the `content` block, and puts its trailing
inline script in `extra_scripts`. Twenty of the twenty-one supplied pages are
here; `login.html` carries no shell and arrives with authentication in
`TASK-UZK-008`.

Every page has a URL and a name, listed in `config/urls.py`. The name matches
the template's filename, so a page can be traced from the sidebar to the URL
to the template without a lookup table. The dashboard answers at the site root.

## Navigation

`config/navigation.py` holds the sidebar: its groups, labels, icons and the URL
name each entry points at. The structure is the one the customer approved in
the supplied `sidebar.js`; what changed is that Django renders it, so a link
cannot point at a page that does not exist and the current page is marked on
the server.

`static/js/sidebar.js` is no longer loaded. It rebuilt the navigation in the
browser and would overwrite the rendered links. The file stays in `static/`
because it was supplied with the assignment and the asset tests assert it is
served.

Every entry is shown to everyone for now. Hiding the ones a role may not open
is `TASK-UZK-012`.

## Authentication

Every session is Django's own. `/login/` renders the supplied sign-in page and
`/logout/` ends the session on POST, so a link cannot sign somebody out.
Rejections carry one message whatever was wrong, because an error that
distinguishes an unknown username from a wrong password tells an attacker which
accounts exist.

The mocked sign-in that shipped with the front end is gone. It kept four
usernames and passwords in `main.js` - a file served to every browser - and
signed any visitor in as Admin when no session existed.

Until `TASK-UZK-011` builds user administration, accounts are created on the
command line:

```bash
python manage.py createsuperuser
```

`django.contrib.auth` provides that command; the Django admin site is still
deliberately absent.

Every page is closed. `LoginRequiredMiddleware` requires a session for every
view, and an anonymous request is redirected to `/login/` with the page it
wanted in `next`, so signing in returns the visitor to where they were going.
The login page is the only view that opts out, with `@login_not_required`.

A view added later is closed unless it says otherwise, which is the direction
worth defaulting to: forgetting the decorator locks a page, not opens it.

## Roles

The specification calls a role a **User Type** and gives it a master data page,
so it is a row rather than a constant. DEC-013 fixes the six the department
works with, and a migration seeds them:

Admin, Bo`lim Boshlig`i, Menejer, Katta Mutaxasis, Direktor and Users.

A user's type lives on `accounts.UserProfile`, not on the account, and
`accounts/roles.py` is the only place that reads it. It answers from the
database on every call, so changing somebody's type takes effect on their next
request rather than at their next sign-in.

A user with no type, a user whose type was deactivated, and an anonymous
visitor all resolve to no role, and every role check refuses them. Nobody is
waved through for want of an answer.

## Page permissions

`accounts/permissions.py` holds the matrix: which User Type may open which
page. It is DEC-015, which supersedes section 11 of the specification - section
11 lists three roles, numbered 3 and 4 with no 1 and 2, and assigns four pages
to nobody.

Admin opens everything. Every other type opens the pages the decision names and
receives **403** for the rest - not a redirect, because the visitor is signed
in and sending them back to the login page would suggest signing in again would
help. A user with no type opens nothing.

The sidebar shows only what the current user may open, and a group heading with
no visible entries is dropped rather than left standing over nothing.

Where DEC-015 says a role "additionally" has a page, the addition is read
against what section 11 gave that same role. **That is an assumption, not a
certainty** - DEC-013 splits "Bo`lim Boshligi - Menejer" into two roles that
section 11 wrote as one - and it is written out at the top of
`accounts/permissions.py`.

A page added to the application without a row in the matrix fails a test rather
than becoming Admin-only by accident, and a page view added without the
decorator fails another: the check is applied by hand, so something has to
verify it was applied.

Signing in lands on `/kirish/`, which forwards to the first page the user's
type may open, in the sidebar's own order. It is not the dashboard, because
three of the six types may not open that one - they would sign in correctly and
be told they are forbidden.

## Users

The Users page at `/users/` creates, edits and deletes accounts, and assigns
each one a User Type.

The specification's form captures a first name, a last name, a password, a
phone number and a type - but no username, although the login page asks for
one. A username is derived from the name (`Bobur Toshmatov` becomes
`bobur.toshmatov`, and a second one `bobur.toshmatov2`) and shown in the table,
since nobody can sign in with a name they were never told. **This is an open
question for the customer, not a decision:** they may want to enter usernames
themselves.

Passwords follow DEC-020: hashed, never rendered, and never returned to the
form. Editing a user leaves the password field empty, and leaving it empty
keeps the password they already have - changing somebody's phone number must
not lock them out.

Deleting follows DEC-009: the account is deactivated, so it leaves the list and
can no longer sign in while everything that already refers to it still
resolves. The page asks before doing it.

The Edit Permission column is rendered but inert; `TASK-UZK-013` owns the
toggle and the exclusivity rule behind it. The page is open to any signed-in
user until `TASK-UZK-012` restricts it to Admin.

## Templates

`templates/base_document.html` holds the document every page shares: the head,
the supplied stylesheets, the title convention and the scripts. `base.html`
adds the application chrome - sidebar, top header, page wrapper - on top of it.
The login screen extends the document directly, because the supplied design
gives it no sidebar.

## Project status

Every page renders and sits behind a real login - but the pages have no data
yet: their tables and forms are still the sample markup supplied with the
assignment, and every signed-in user sees all of them.
