# Uz-Koram | Xarid Xizmati Bo'limi

Department automation for the purchasing service of "Uz-Karam Co MCHJ QK",
built from the technical assignment "Xarid Xizmati Bo'limi - Automatlashtirish
uchun Texnik vazifa".

One Django project (`config`) and one Django application (`xarid`, Uzbek for
"purchase"), rendered server-side through Jinja2 over the Bootstrap front end
supplied with the assignment, on SQLite, behind Django's own authentication.

## What it does

- **Master data** (Admin only): User Specialty, User Types, Ariza Status,
  Shartnoma Status, Mahsulot Turlari, Shartnoma Turi, Bo'limlar and Firmalar,
  each a table beside a form. Deleting deactivates: the record leaves the lists
  while anything that already refers to it still resolves.
- **Users** (Admin only): create, edit and deactivate accounts, assign each a
  User Type and a department, and grant the exclusive contract-editing
  permission.
- **Applications**: incoming applications are accepted or rejected with a
  reason; accepted ones are created, listed and assigned to a senior
  specialist, who takes the work and reports its status.
- **Contracts**: a contract with priced goods rows is entered against an
  assigned application; its value is the total of the rows.
- **Purchase applications**: a requester raises one against their own
  department, the department head approves, then the director approves - which
  stamps a QR code onto the PDF and raises the department's own application.
- **Reports, drafted contracts, 1C integration and logs** are still the
  supplied prototype pages with sample data.

## Project structure

```text
.
├── manage.py
├── requirements.txt          runtime dependencies
├── requirements-dev.txt      ruff, for the lint gate
├── .env.example              every environment variable, with placeholders
├── config/                   project configuration only
│   ├── settings.py
│   ├── urls.py               admin/, accounts/ (Django auth), and the app
│   ├── asgi.py
│   └── wsgi.py
├── xarid/                    the one application
│   ├── models.py             master data, people, applications, contracts,
│   │                         purchase applications, notifications
│   ├── forms.py              master data forms, the users form, the three
│   │                         creation forms with their order-line formsets
│   ├── views.py              every page and action
│   ├── urls.py               app_name = "xarid"; every page by its name
│   ├── admin.py              every model registered in the Django admin
│   ├── permissions.py        who may open which page; contract editing
│   ├── navigation.py         the sidebar
│   ├── attachments.py        PDF storage outside the web root; the QR stamp
│   ├── jinja2.py             the template environment (url, static, date...)
│   ├── migrations/           0001 schema, 0002 seeded master data
│   ├── static/xarid/
│   │   ├── css/              vendored Bootstrap, icons, fonts and style.css
│   │   └── js/               main.js and one script per prototype page
│   └── templates/
│       ├── xarid/            base.html, index.html, _forms.html, pages/
│       └── registration/     login, logged_out, password change
└── tests/
    ├── support.py            fixtures shared by the test modules
    ├── test_models.py
    ├── test_views.py
    ├── test_urls.py
    └── test_auth.py
```

## Requirements

- Python 3.12
- The packages in `requirements.txt`: Django 5.1, Jinja2, qrcode, Pillow and
  pypdf.

## Running it locally

```bash
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
export DJANGO_DEBUG=1             # Windows PowerShell: $env:DJANGO_DEBUG="1"
python manage.py runserver
```

The application answers at <http://127.0.0.1:8000/>. `DJANGO_DEBUG=1` is what
lets the development server serve the static files; it is off by default so
that an unconfigured deployment is the safe one.

`migrate` seeds the master data the application cannot start without: the
six User Types, the four application statuses, the five contract statuses and
the two contract types. The superuser may open every page and the admin.

## Authentication

Every page requires a session, applied with Django's `login_required` through
`xarid.permissions.require_page_permission`, which then asks the page
permission matrix. An anonymous visitor is redirected to the login page and
returned to the page they asked for after signing in.

| Route | What it does |
| --- | --- |
| `/accounts/login/` | Django's `LoginView` on the supplied sign-in design. Signing in lands on `/kirish/`, which forwards to the first page the user's type may open. |
| `/accounts/logout/` | Django's `LogoutView`, POST only; shows `registration/logged_out.html`. |
| `/accounts/password_change/` | Django's `PasswordChangeView`, for a signed-in user's own password. |
| `/admin/` | The Django admin, for staff accounts. |

Login rejections carry one message whatever was wrong, so the form cannot be
used to discover which accounts exist. Passwords are hashed by Django and
never rendered.

### Roles and page permissions

A user's role is their **User Type**, a master data row held on
`xarid.UserProfile`. Six are seeded and marked as system roles: Admin, Bo`lim
Boshlig`i, Menejer, Katta Mutaxasis, Direktor and Users. `xarid/permissions.py`
holds the matrix of which type may open which page; Admin and Django
superusers open everything, and an account with no type opens nothing. A
signed-in visitor of the wrong type gets **403**; the sidebar shows only what
the current user may open.

Ownership is checked in the views where the page alone cannot say: a
specialist may only act on the applications assigned to them, a department
head may only decide their own department's purchase requests, and an
application's PDF is downloadable by whoever may open the page it is
currently on.

New accounts are created on the Users page (or in the admin). A user made with
`createsuperuser` has no User Type but, being a superuser, may open every page.

## Attachments

Application PDFs live under `ATTACHMENT_ROOT` (`attachments/`, gitignored),
outside anything the web server publishes, and are served only through views
that check permission first. There is deliberately no `MEDIA_URL`.

## Templates and static files

Every page is a Jinja2 template extending `xarid/templates/xarid/base.html`,
which holds the document, the sidebar and the top header for signed-in users
and a bare document with a link strip for anonymous ones. `_forms.html` holds
the form-field macros the pages share. The Jinja2 environment in
`xarid/jinja2.py` provides `url()`, `static()`, `now()`, the `date` and
`striptags` filters, and the sidebar and identity helpers.

Static files are namespaced under `xarid/static/xarid/`. The Bootstrap build,
icon font and stylesheet supplied with the assignment are served as supplied;
`main.js` holds the shared behaviours (modals, confirmations, formset rows,
the contract calculator) and `js/pages/` the sample-data scripts of the
prototype pages.

```bash
python manage.py collectstatic
```

## Configuration

Settings that differ between machines are read from the environment.
`.env.example` lists every variable; nothing loads a `.env` file at runtime.

| Variable | Default | Notes |
| --- | --- | --- |
| `DJANGO_SECRET_KEY` | a key generated at startup | **Set this for any real deployment.** The generated fallback changes on every restart, which invalidates sessions. |
| `DJANGO_DEBUG` | off | Accepts `1`, `true`, `yes`, `on`. Turn it on for local development. |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma separated. |
| `DJANGO_SECURE_COOKIES` | off | **Turn this on for any deployment reachable over HTTPS.** Marks the session and CSRF cookies https-only. |

## Running the checks

```bash
pip install -r requirements.txt -r requirements-dev.txt
python manage.py check
python manage.py makemigrations --check
python manage.py test
ruff check .
```

The suite builds a test database from the migrations on every run, fetches the
static files over a live server, and covers the models, the pages, the routing
and authentication, permissions and ownership.
