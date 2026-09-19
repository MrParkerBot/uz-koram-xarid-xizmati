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
- **Dashboard**: the supplier count and the created and completed contract
  percentages measured against it are counted from the database. Which
  contract status means completed is marked on the Shartnoma Status page,
  because the statuses are editable master data. The spendings card adds up
  contract values: the total inside the period chosen in the bar, with the
  calendar year's agreed total under it, both in UZS. The period narrows that
  card alone - the other three report where the department stands now - and a
  contract is accounted under its own contract date, or the day it was raised
  when it has none. Savings has no formula yet (DEC-025) and says so. A panel
  gives the average processing time of the four stages the assignment names,
  in days. The charts, the top suppliers list, the category table and the
  activity list are still the supplied prototype's sample data. Its Top
  suppliers panel shows the first five of the Top suppliers page and links to
  it. The supplier category block counts how many distinct firms supply each
  product type - a type nobody supplies is listed with zero - beside the
  number of types actually delivered, meaning those that reached the status
  marked completed rather than those somebody merely has a contract for. Its
  bar chart draws the same rows as its table. A firm is credited with every
  type its application ordered, because a contract is against an application
  and not against one of its lines. A share is that type's count as a percentage of the table, so
  the column adds to a hundred; a firm supplying two types is counted under
  both, which the block says under it. REQ-DASH-009 words the share as a
  percentage of total firms instead, which is the same number only while no
  firm supplies more than one type.
- **Top suppliers** (`Hisobotlar / Top Yetkazib beruvchilar`): every firm
  ranked by what its contracts come to inside the chosen period (DEC-025),
  narrowed by the firm's Daraja. A firm with no contracts in the period is not
  ranked, and the page says so rather than padding the list with zeros. The
  page is not in the DEC-015 matrix, because the supplied sidebar had no such
  page; it is open to the types that may open the dashboard.

### What the processing-time stages are measured between

The assignment names four stages and no events, and DEC-025 decides only where
Invoice comes from. These definitions are this application's own; the panel
prints each one beside its figure so it can be argued with.

| Stage | From | To |
| --- | --- | --- |
| Buyurtma kiritish | the application arriving | the contract raised against it |
| Tasdiqlash | the contract being raised | it being approved |
| Yetkazib berish | approval | the first move into the status marked completed |
| Invoice | that same move | the invoice date on the contract |

Approval is measured from the raising rather than from `yuborilgan_sana`,
because a resend overwrites that column (DEC-024) and a contract sent twice
would report only the time since its last send. An average covers only the
contracts that recorded both of its ends: a stage nothing has completed prints
a dash, not nought days.
- **The log** (section 10): every create, edit and delete the application makes
  through its own pages writes one entry naming the acting user, their
  department at the time, the record, and when. An approval does not add a
  row - it completes the one the creation left, with the approver, their
  department, the comment and the time, which is the row section 10's columns
  describe. Entries are kept indefinitely and the application builds no way to
  edit or delete one (DEC-029); the Django admin registers the table for
  reading only, and deleting a user there is now refused while they hold
  entries. A record approved twice - a purchase request goes to the
  department head and then to the director (DEC-016) - gets a second entry
  rather than having the first approver overwritten, because the columns
  hold one approver. Writes made through the admin, a shell or a migration
  are not logged.
- **Notifications**: accepting an application tells its sender; refusing tells
  them the reason. Delivery is in-app and nothing else - an entry on the
  Bildirishnomalar page and a number on the bell in the header - with no email
  and no SMS (DEC-012). Opening the page marks what it showed as read. An
  application entered on the Qabul qilingan page has no sender behind it
  (DEC-031), so it tells nobody. The page is closed by `login_required` alone:
  it is not a page a user type may open, it is everybody's own.
- **The Logs page** (`Tizim / Logs`) lists those entries newest first with the
  nine columns section 10 names and a drop-down per column - user, department,
  form, action - beside the period. An entry nobody has decided leaves its
  four approval cells empty rather than labelling them. There is no export:
  section 10 is the one page that does not ask for one (DEC-029).
- **Drafted contracts and the 1C integration screen** are still the supplied
  prototype pages with sample data.

## Project structure

```text
.
├── manage.py
├── docs/                     the section 6.2 deliverables, generated:
│   ├── bpmn/                 the purchase request and contract flows
│   ├── uml/                  a class diagram of every entity
│   └── database-schema.md    every table and column
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
│   ├── reports.py            the Hisobotlar counting: status columns, rows
│   │                         and totals
│   ├── dashboard.py          the Boshqaruv paneli counting: indicators,
│   │                         spendings, processing times, top suppliers
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
    ├── test_reports.py
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

## Filtering

Every list page carries the per-column filter bar the specification asks
for, built once in `xarid/filters.py`. A page declares which columns it
filters by; each drop-down's options are derived from the rows that page
already shows, so a specialist who sees only their own work is offered only
the departments and statuses of that work. The bar is a GET form, so the
chosen values travel in the query string and survive a re-render. A value that
is not among the options is refused with a message rather than dropped
silently.

The same bar carries a period and an ordering. A page declares the date it
narrows by, and the two `dan` and `gacha` inputs bound it inclusively: a
start alone means from that day onward, an end alone means up to and
including that day, and neither leaves the rows unnarrowed by date. A date
that cannot be read, and a start later than the end, are refused with a
message and no period is applied - the refused dates stay in the bar, and
`Tozalash` empties it. The `Tartib` drop-down orders the page by that same
date, newest first by default, and choosing the other direction reverses the
rows.

The Excel and PDF buttons beside the bar download the table as the page
shows it, filtered or whole, in the order it shows it, one row per order
line with the table's columns as headers (`xarid/exports.py`, routes `<page>/eksport/xlsx/` and
`<page>/eksport/pdf/` under the page's own permission). An empty list still
downloads a valid file with headers only.

## Reports

`Hisobotlar / Xodimlar Yuklamasi` counts what each specialist is carrying: a
row per account that may be assigned purchase work - including one holding
nothing, which is what the department head is reading the report for - their
phone number, how many applications are assigned to them, and one counter per
contract status, with a totals row that is the sum of each column.

The status columns are generated from the active `Shartnoma Status` rows in
their configured order, so adding a status adds a column and deactivating one
removes it, with no code change (DEC-010). The five seeded statuses are
examples, not a fixed set.

An application is counted under **every** status it has a contract in, and
once in its owner's assignment total. An application whose first contract was
refused and whose replacement was signed therefore appears under both, and
the counters may add up to more than the total: they say how much work stands
in each state, which is the question the report answers. An application with
no contract at all is counted in the total only.

An assignment is counted from the moment it is made, whatever happens to the
application afterwards: a specialist whose contract was signed did that work,
and the counters exist to say so. Only active accounts have a row, so work
held by somebody who has left the department stops being counted.

The period bar narrows by the date the assignment was made and behaves
exactly as it does on the list pages, refusals included. There is no default
period: the report opens on all time. The counting lives in
`xarid/reports.py` and is one query per report, not one per status.

`Hisobotlar / Bo'limlar Xaridi` (Korhona xaridi | Bo`limlar) counts the same
statuses per department instead of per employee: a row per active department,
how many purchase applications it raised, and how many of them stand in each
contract status, with the same totals row. The busiest department is first,
because which department consumes the most purchasing effort is the question
the page answers; a tie breaks by name. A department that raised nothing
still has a row of zeros, and a deactivated department has none.

A department's total counts every application it raised, including one
refused at intake, which can never appear under a status column because it
never reaches a contract. The gap between the total and the sum of the
counters therefore holds both work not yet contracted and work refused.

Both reports put the busiest row first, because both are read to find where
the load is; a tie breaks by name.

Both reports download as Excel or PDF from the same buttons the list pages
carry, holding the rows the page holds, narrowed by the same period and the
same department choice, with the totals as the last row of the file. The
status columns are generated into the file too, so adding a status adds a
column to the download. A report with no rows still downloads a valid file
with headers. Each download is open to exactly the types that may open its
page.

That report is narrowed by its `Bo'lim` drop-down and by a period over the
date an application arrived, which is the only date every application has.
The drop-down offers only departments the report has a row for.
A department name links to the Mahsulotlar page carrying `?bolim=<id>`, which
that page honours.

`Hisobotlar / Mahsulot Turi` (Korhona xaridi | Mahsulot Turi) counts the same
statuses per product type: a row per active type with its code, how many
purchase applications ordered something of that type, and one counter per
contract status, under the same totals row. A type is reached through the
order lines that name it, so the counts are distinct - an application
ordering two things of one type counts once for that type, and one ordering
two types counts once under each. `Ko'rish` opens the Mahsulotlar page
filtered to that type.

`Hisobotlar / Mahsulotlar` (Korhona xaridi | Mahsulotlar) is a list page
rather than a counter report: one row per ordered product line, with its
application, department, product type, quantity, unit, comment, the
application PDF, the acceptance date and where the work has got to. It
filters by department and product type, narrows by the date the application
arrived, and downloads as Excel or PDF like every other list page.

Its `Holati` column shows the status of the line's contract where there is
one, and the application's own stage otherwise. The specification's flow ends
in three contract statuses, and nothing in this codebase sets one yet
(TASK-UZK-037), so a row cannot reach those states today; the flow above the
table is drawn as a legend rather than as a claim about the rows.

The PDF cell follows DEC-019: a link appears only where one would work. An
application that has no attachment, or that was rejected and so is on no
page, shows a dash instead of a link that would answer 403.

A contract carries its own PDF on the same terms (REQ-SHARTNOMA-010). The
`Shartnoma Kiritish` form will not save without one: a contract is a document
before it is a row, and a row without the document it records is a claim
nobody can check. The column itself is optional, as the Ariza one is, so a
contract raised before the column existed stays readable and the admin can
still key one in.

## Contract statuses

A contract's status is moved from the `Kelishinlingan` page, by the specialist
whose application it was raised against. What is enforced is narrower than
"permitted transitions" sounds, and the narrowness is deliberate: DEC-010
makes the statuses rows an administrator invents and extends, and
`ShartnomaStatus` carries no code column, so nothing in the code may name a
particular status or draw a graph between two of them. A transition table over
names would be a table the `Shartnoma Status` page could invalidate.

So what `Contract.set_status()` enforces is what the data can say:

- the status must be one that is in use;
- the contract must still be in `Contract.EDITABLE_STAGES` - agreed or
  rejected, the two the page shows - so one awaiting approval is not moved
  underneath whoever is approving it;
- moving to the status it already has is not a move, and writes nothing.

**No order between two statuses in use is enforced.** The order the department
works to is not in the specification, and inventing one here would make an
open question look answered.

Every move writes a `ContractStatusChange` in the same transaction: the
previous status, the new one, who moved it and when. It is the first history
table in the application - everything else keeps current state only, because
DEC-024 puts history in the section 10 log - and it exists because "keeps
changing" is a sequence: a contract at `Yetkazib berilgan` with no record of
when it passed `Shartnoma tuzilgan` cannot answer what the department asks.
The update is conditional on the status being moved from, so two clicks
arriving together produce one move and one history row.

A specialist may move only a contract whose application is assigned to them,
asked through the assignment rather than through who created the contract:
DEC-024 lets an Admin re-assign at any time, and the contract goes with the
work. Everybody else the matrix lets onto the page may move any of them.

## Sending a contract for approval

`Yuborish` on the `Kelishinlingan` page sends a contract to the department
head. Sending takes it out of the specialist's hands, which takes it off that
page - the page is the contracts still theirs to work on - so the message
names where the contract went rather than only that it went: a row
disappearing with no explanation is how somebody concludes they deleted
something.

A second send is refused, and the refusal says **which** refusal it is. A
contract awaiting approval and one already approved are different answers, and
being told the wrong one sends whoever reads it looking for a queue the
contract left days ago.

After a rejection the control reads **Re-Send** (DEC-024), and the contract may
be corrected before it is resent. It is the same route: a resend is the same
act again. The rejection comment is **not** cleared by a resend - the approver
about to look at the contract again is the person most helped by seeing why it
came back, and the stage is what says it has moved on.

`yuborilgan_sana` and `yuborgan` hold the **last** send and are overwritten by
a resend; `yuborishlar_soni` counts them, because the log TASK-UZK-052 will
build cannot recover what was never recorded, and how many times a contract
came back is the question the department will actually ask.

Nothing is notified. The requirement names no notification, and
`Notification`'s constraint names two kinds of record, neither of them a
contract - a third would be building TASK-UZK-054's table early.

## The department head's decision

`Tuzilgan Shartnomalar` is where the contracts sent for approval arrive. Four
user types may open it and **one of them decides**: DEC-013 makes Admin the
Xarid bo`lim boshlig`i, the department head REQ-SHARTNOMA-002 gives the
decision to. The controls render for that one and **the route asks again** - a
page-level permission on its own would let a Menejer approve a contract that
binds the company.

**Accepting** marks the contract approved and records who and when.
REQ-SHARTNOMA-002 says an accepted contract goes to the next department and
DEC-028 says there is no such department, so nothing is built for it: the
contract continues through its status chain here, and the gap stays visible
rather than being filled with an invented integration. Accepting does not move
the status either - that chain is something a person chooses.

**Rejecting** demands a comment, refused in the model and not only on the page,
because a page is one way in. Where a rejection lands is the half worth
stating: *returned back* is not a stage of its own. It is the contract on the
`Kelishinlingan` page again, with its comment in the column REQ-SHARTNOMA-004
gives it and the `Re-Send` control DEC-024 names.

### Two questions that look like one

`EDITABLE_STAGES` says whether a contract's **terms** may change.
`MOVABLE_STAGES` says whether its **progress** may be reported. They were one
constant until this task, and sharing them would have frozen an approved
contract's status forever - so DEC-010's seeded *Yetkazib berilgan*, which
happens after a contract is signed, could never be reached, and DEC-028's
"continues through its status chain" would have been impossible.

`SENT` is the stage that refuses a status move: a contract awaiting a decision
must not change underneath the person making it. Which is why the status
control lives on both pages, and why the status route returns to whichever one
it was used from.

## A purchase request and its contract

The `Xarid Arizasi` list shows a request the state of the contract formed from
it. The chain is three hops - request, the department application it raised on
approval, the newest contract against that - and **any hop may be missing**:
a request that has not been approved raised no application, and one that has
may have no contract yet. Each missing hop is an ordinary state, and the
request then shows what it always showed.

**There is no mapping, and that is the mapping.** DEC-010 makes `Ariza Status`
and `Shartnoma Status` independent tables an administrator extends separately,
and defines no correspondence between them. A translation table written here
would be invented in the code and invalidated by the next row somebody adds on
either page. So the contract's status is shown **as it is** - and because the
two tables need not even look related, the row says the state came from the
contract, or a requester would have no way to tell why the word changed.

**Derived, never copied.** A column kept in step by a hook is out of step the
first time something writes around the hook, and this record needs no column:
the contract knows its status and the request knows its contract. The
request's own `status` is left exactly as it was, so the record still knows
what it was raised as.

The contract's **number** appears in that explanation only for somebody who may
open the page the contract is currently on — `Contract.page_showing` answers
where that is. DEC-015 gives Users this page and no contract page at all, so
naming the contract to them would hand over a fact from a page they cannot
open, and the list is deliberately not filtered by requester. It is the rule
the attachment download already follows.

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

## Technical documents

`docs/` holds the BPMN, the UML and the database schema that section 6.2 lists
as deliverables beside the code (REQ-ACCEPT-002). They are generated from the
models and from the flows as the code runs them, not written by hand:

```bash
python manage.py delivery_docs          # write them
python manage.py delivery_docs --check  # fail if they are out of date
```

`tests/test_documentation.py` runs that check, so a migration that leaves the
schema document behind fails the build rather than being noticed years later.
The flows drawn are the ones that were built - DEC-016 put the requester's
department head and the director in front of the purchasing department - and
not the assignment's superseded section 4.2.

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
