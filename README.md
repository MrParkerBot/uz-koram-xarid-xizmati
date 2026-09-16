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

Debug is off unless the environment turns it on, so an unconfigured deployment
is the safe one rather than the permissive one.

## Front-end assets

The Bootstrap build, icon font and JavaScript supplied with the technical
assignment live in `static/` and are served as-is. They are deliberately not
rebuilt or minified again, so the interface the customer approved is the one
that ships.

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

## Project status

This is the application skeleton plus the shared page shell. The root URL
still serves a placeholder; the real pages arrive in `TASK-UZK-006` and
`TASK-UZK-007`.
