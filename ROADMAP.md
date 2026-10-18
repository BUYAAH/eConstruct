# Roadmap — self-hosted build

Written 2026-08-06, after two decisions that invalidate large parts of
`SPEC.md` and `PLAN.md`:

1. **The Microsoft tenant is being retired.** The Buyaah trial is cancelled
   before it converts to paid. No SharePoint, no Graph, no SSO.
2. **The pitch is off the near-term path — this is now a real product
   build.** "Prefer shipping over architecture" (SPEC.md §1) no longer
   applies unqualified; hardcoded demo data and mock-ups are scaffolding to
   be replaced, not deliverables.

`SPEC.md` and `PLAN.md` stay as the historical record of the pitch MVP — they
document *why* things are the way they are, and much of the reasoning still
holds. **This file supersedes them for anything forward-looking.**

---

## 1. Where the code actually is

Worth being blunt about this, because the mock-ups make the app look further
along than it is.

**Real and working** (built against a live tenant, verified end-to-end):

- Pin-note viewer: PDF.js one-page renderer, percent-positioned pin overlay,
  HTMX note sheet, layer filter chips. `static/js/viewer.js`,
  `templates/core/viewer.html`, the `core/partials/note_*` family.
- Note CRUD with photo upload; `core/images.py` already does the Pillow
  work (EXIF rotation, downscale to 1600px, JPEG re-encode).
- PDF annotation export: `core/pdf_export.py` stamps notes into a PDF in two
  modes, and handles the non-zero-origin CAD page boxes correctly (a real
  gotcha that cost time — see PLAN.md).
- Layer CRUD, user activate/admin toggle, company scoping on every query.

**Real but about to be orphaned** (works, but only against a tenant):

- `accounts/microsoft.py`, `accounts/views.py`, `accounts/middleware.py` —
  MSAL auth-code flow, encrypted token cache, silent refresh. **This is the
  only way to log in.** With the tenant gone, nobody can reach the app
  except through `createsuperuser` + Django admin.
- `core/graph.py` and the views that use it: folder picker, folder browsing,
  `open_document`, `document_pdf`, `export_document`.
- `FolderLink` (pure SharePoint pointer) and the Graph half of `Document`
  (`drive_id`/`item_id`/`etag`).

**Mock-up only** (convincing HTML, zero model behind it):

- `/projects/` and `/projects/<slug>/` — driven by `_DEMO_PROJECTS` and
  `_DEMO_REGISTRATIONS` dicts in `core/views.py`. The project detail page
  even renders a PDF, but it's a hardcoded `static/img/3 - 1. ETAGE.pdf`.
- `/`, `/registrations/`, `/reports/` — all render `core/placeholder.html`.

**Absent:**

- Tests. `core/tests.py` and `accounts/tests.py` are 3-line stubs. For a
  pitch demo that was a defensible trade; for a product it isn't.

**Local data is trivial** — 1 company, 3 layers, 3 documents, 8 notes, 1
user. Nothing here is worth a careful data migration. Model changes can be
aggressive.

## 2. What the mock-ups already decided

The Projekter/project-detail mock-ups aren't just layout — they encode a
product design that is a real step beyond SPEC.md, and the plan below is
mostly a matter of making the models catch up to them.

Reading `_DEMO_REGISTRATIONS` as a spec, a **Registrering** is much richer
than a `Note`. A Note is `{page, x, y, layer, text, author, photo}`. A
registration is all of that **plus** a faggruppe, an assignee, a deadline,
an open/resolved status, and a location that points at a drawing *and* a
page. That is the actual domain object of the product; the pin-note is just
how one gets created.

Likewise the sidebar's placeholder entries stop being vague:

- **Registreringer** = the field observations above, listed across projects.
- **Rapporter** = generated PDFs of those registrations. `pdf_export.py`
  already does ~80% of this; it just currently uploads the result to
  SharePoint instead of handing it back.
- **Oversigt** = KPIs over registrations (open, overdue, by project) —
  answerable once Registration is a real model, and not before.

**Project becomes the spine.** Everything (drawings, documents,
registrations, reports) hangs off it. Mapper (`core:folders`) is the pitch-
era stand-in and gets absorbed and deleted.

## 3. Target model

Additive where possible; `Note` and `Document` are the two that genuinely
change shape.

```
Organization       Company, renamed (D6). The tenant boundary.
                   ms_tenant_id dropped.
User               unchanged minus Microsoft (ms_object_id + MsToken die).

Project            NEW. organization, name, slug, case_no, address, status,
                   manager -> User, members -> M2M User, created/updated.
                   Fields are lifted straight from _DEMO_PROJECTS so the
                   existing template keeps working.

Drawing            REPLACES Document. project, name, file (FileField),
                   page_count, uploaded_by, created. No drive_id/item_id.

Discipline         Layer, renamed (D2). Faggruppe: Konstruktion, Brand,
                   El, VVS, Kvalitet. organization, name, color,
                   sort_order.

Registration       EVOLVES Note. project, drawing (nullable), page_number,
                   x_pct, y_pct, discipline, text, author, assignee,
                   deadline, status, created/updated.

RegistrationPhoto  NEW. registration, image, + derived renditions.
                   Note.photo is single; the mock-up implies several.

Report             NEW, phase 5. project, file, created_by, created,
                   filter criteria used.
```

Two shape notes:

- **`Drawing.file` is a plain `FileField`, not S3-specific.** Django's
  `STORAGES` setting swaps local disk for S3 as a config change, so
  `storage_plan.md` stays valid without being a prerequisite. Do not start
  on S3 — start on disk.
- **`Registration.drawing` is nullable.** Every demo registration has a
  drawing location, but a field worker photographing a defect with no
  drawing open is an obvious real case, and nullable costs nothing now
  versus a migration later.

## 4. Phases

Ordered by dependency, not by appeal. Phase 1 is not optional — until it's
done, the app has no working front door.

### Phase 1 — Local auth (unblocks everything) — ✅ DONE 2026-08-06

Built together with phase 3, because deleting the Graph code and giving the
app its own front door were the same change. What landed:

- Django `LoginView`/`LogoutView` on a styled Danish login page;
  `OrgAuthenticationForm` in `accounts/forms.py`.
- `Invitation` model + `accounts/emails.py`. An org admin invites from
  `/users/`; the invitee gets a link, sets a password, and is logged
  straight in. Tokens are `secrets.token_urlsafe(32)`, single-use, 14-day
  expiry; a dead link renders one identical 410 page regardless of *why*
  it's dead, since the token is the only credential.
- Username **is** the email address, so an address belongs to exactly one
  organization. Worth revisiting if someone ever works for two.
- 30-day sliding sessions, so field workers don't re-authenticate mid-shift.
- `manage.py seed_demo` creates an organization, five Danish disciplines, an
  admin (`admin@demo.dk` / `demo1234`) and a first drawing — a fresh clone
  is runnable without touching Django admin.
- Deleted: `accounts/microsoft.py`, `accounts/middleware.py`, `core/graph.py`,
  `MsToken`, `ms_object_id`, `ms_tenant_id`, all MSAL settings, the folder
  picker/browse templates, and `msal`/`requests`/`cryptography` from
  requirements.

Original plan, for reference:

- Django's `LoginView`/`LogoutView` with a styled template matching the
  dashboard shell. `AUTHENTICATION_BACKENDS` back to plain `ModelBackend`.
- Company admins invite users by email; invite creates an inactive User +
  a signed token link where they set a password. Keeps the B2B shape
  (`Company` scoping, `is_company_admin`) that's already everywhere.
- Long `SESSION_COOKIE_AGE` with `SESSION_SAVE_EVERY_REQUEST` — field
  workers on phones should not re-authenticate on a scaffold.
- Delete `MsToken`, `ms_object_id`, `accounts/microsoft.py`,
  `accounts/middleware.py`, the MSAL settings, and `msal` from
  requirements. See decision D4 on how aggressively.
- A management command to seed a company + users, so a fresh clone is
  runnable without clicking through admin.

Ends with: someone can clone, migrate, seed, log in, and see the dashboard
with no external dependency.

### Phase 2 — Project model — ✅ DONE 2026-08-06

Built with phase 4 in one pass, since Registration hangs off Project and the
mock dicts covered both. `_DEMO_PROJECTS` / `_DEMO_REGISTRATIONS` are gone;
the card layout agreed during the mock-up phase survived intact and is now
fed by annotations. `Project.progress` is derived from the approved share of
registrations rather than a number someone maintains by hand — a manual
percentage is the first thing to go stale on a project board.

### Phase 4 — Registrations — ✅ DONE 2026-08-06

`Note` became `Registration`, gaining number, subject/description,
contractor, responsible, deadline and status. `Contractor` and
`RegistrationPhoto` are new. Drawings moved under Project.

Worth knowing:

- **`Drawing` deletion is `SET_NULL` on the registration, not CASCADE.** An
  observation outlives the drawing it was pinned to, or deleting a
  superseded revision would erase site history. Tested.
- **Numbers are allocated under `select_for_update` on the project row.**
  A no-op on SQLite (writes serialize anyway), correct on Postgres.
- **Test media goes to a temp dir.** The database rolls back between tests
  but the filesystem does not, so file-mutating suites rebuild their
  fixtures per test rather than in `setUpTestData`. This was a real failure,
  not a precaution.

Still open from the original phase-4 plan: nothing. Phase 5 (Rapporter and
the KPI overview) is next — the overview already has real counts, so what
remains there is the report generator.

Original plan, for reference:

Turn the mock-up into real data with minimal template churn:

- Add `Project`, plus admin registration and company-scoped querysets.
- Rewrite `core.views.projects` / `project_detail` to query it; delete
  `_DEMO_PROJECTS`. The templates read `project.name`, `project.case_no`
  etc., so the dict keys become model fields and the HTML barely moves.
  The stat counts (`drawings`, `documents`, `registrations`) become
  annotations.
- Project CRUD for company admins.
- The project detail sub-nav (`Oversigt`/`Tegninger`/`Dokumenter`/
  `Registreringer`) becomes real HTMX tab loads instead of inert
  `<button>`s.

### Phase 3 — Drawings (kills the Graph dependency) — ✅ DONE 2026-08-06

Landed with phase 1. `Document` became `Drawing` with a `FileField`;
`FolderLink` is gone. Two things worth knowing:

- **Django 6.0's `FileResponse` has no Range support** (verified against the
  installed source, not assumed). PDF.js relies on ranges to show page 1 of
  a large CAD drawing without downloading the whole file, and the old Graph
  proxy passed them through — so `drawing_pdf` implements `Range` by hand:
  206 with `Content-Range`, `bytes=-N` suffix ranges, and 416 when
  unsatisfiable. All three are tested.
- **Export is now a download, not an upload.** `pdf_export.stamp_notes` is
  untouched (including the CAD coordinate fix); only its destination
  changed, so the viewer's Eksportér dropdown became plain links.

`Drawing` still belongs directly to the organization — phase 2 adds the
`project` FK.

Original plan, for reference:

- `Drawing` model + upload form (multi-file, admin/PM only), page count read
  once on save via pypdf.
- Serve bytes via a login-and-company-checked `FileResponse` — this
  *replaces* `document_pdf`'s Graph proxy and is strictly simpler; Django's
  `FileResponse` handles Range requests natively, which is what PDF.js
  needs.
- Repoint `viewer.html` and `pdf-preview.js` from `Document` to `Drawing`.
  `pdf-preview.js` currently points at a hardcoded static PDF — this is
  where that goes away.
- Delete `core/graph.py`, `FolderLink`, the folder picker/browse/
  `open_document` views, `core:folders`, and the Mapper nav entry.

Ends with: upload a real drawing to a real project and pin notes on it.

### Phase 4 — Registrations

- Migrate `Note` → `Registration` with the new fields. Given 8 rows of dev
  data, a fresh migration is fine; don't write data-preserving migration
  code for this.
- `RegistrationPhoto` with multiple photos. `core/images.py` already
  produces the "medium" rendition — add a thumbnail alongside it, which is
  the part `storage_plan.md` costed.
- Status workflow (open → resolved), assignee, deadline, overdue
  highlighting. The `project_detail` table already renders all of this
  against demo dicts — it becomes a real queryset.
- The cross-project `/registrations/` list: filters by project, faggruppe,
  status, assignee, overdue.

### Phase 5 — Reports & Oversigt

- Repoint `pdf_export.stamp_notes` at a download response instead of a
  Graph upload. The stamping logic (including the CAD coordinate fix) is
  kept as-is — it's the expensive part and it's already correct.
- Add a registration-list report (filtered, with photos) as the second
  report type; persist as `Report` rows so they're re-downloadable.
- Oversigt: KPI tiles (open, overdue, this week) + recent activity, now
  that there's something real to count.

The Oversigt half landed 2026-10-01 as part of a UX pass over the front
door, the sidebar and Projekter:

- `/` is now stat tiles, three capped "Kræver handling" lists (overskredet,
  afventer godkendelse, frist inden 7 dage — each linking to the same rows
  on Registreringer, which gained a `due=week` filter), active projects as
  rows, and a phone-only "+ Ny registrering" button.
- Sidebar: overdue count beside Registreringer (`nav_overdue_count`, lazy,
  in `core.context_processors`), who-is-logged-in footer, and a bottom tab
  bar below 992px in place of the hamburger. **Rapporter is out of the nav
  until this phase ships it** — the view and URL still exist.
- Project cards count overskredet / åbne / afventer instead of drawings and
  firms; "Fremdrift" became a segmented status bar (approved share of
  registrations was being read as construction progress, which it isn't);
  Projekter is grouped by status with afsluttede collapsed.

### Phase 6 — Production readiness

Prepared for a PythonAnywhere test server on 2026-08-07 (S3, Postgres and
real email deliberately deferred):

- Security settings behind `if not DEBUG` — secure cookies, SSL redirect, and
  `SECURE_PROXY_SSL_HEADER`, which PythonAnywhere **requires**: it terminates
  TLS at its proxy, so without it `SECURE_SSL_REDIRECT` loops forever. HSTS is
  left off on purpose; it is cached by browsers and cannot be withdrawn.
- `LOGGING` to stderr. With `DEBUG=False` and no mail backend, an unhandled
  exception was otherwise silent.
- `core/checks.py` — a deploy check that **errors** if `SITE_URL` is still
  localhost with `DEBUG` off. Invitation links are built from it, so the
  failure would otherwise land on a client as an unexplained connection error.
- Requirements pinned with `==`. reportlab draws the PDF stamps; an unpinned
  install breaks exports on the server while they still work locally.
- Bare `404.html` / `500.html`, standalone rather than extending `base.html`:
  `handler500` renders with no context processors, so `brand` and `user` are
  unavailable there.
- Dead `MS_*` / `TOKEN_ENC_KEY` entries purged from `.env`.

Static files are PythonAnywhere's own mapping plus `collectstatic`, so no
WhiteNoise. Nothing under `MEDIA_ROOT` is ever served directly — every file
goes through a login- and organization-checked view — so there is no media
mapping to configure and uploads cannot leak by URL.

Still open:

- **Postgres.** SQLite was chosen for a single-worker demo; a product with
  concurrent field writes shouldn't ship on it. Sharper than it looks:
  `SESSION_SAVE_EVERY_REQUEST = True` means *every request is a database
  write*, and SQLite serialises writes across the whole file. This is the
  first thing that will contend once several people are on site at once.
- Tests. **Started early rather than deferred** — `core/tests.py` has 23
  tests covering tenant isolation (org A cannot read, edit, delete or export
  anything of org B's), the admin/member permission split, the invitation
  lifecycle, and the Range handling. Still to cover: `pdf_export`'s
  coordinate handling, which is subtle enough to regress silently.
- Drop `Company.ms_tenant_id`, prune dead settings.
- S3 via `django-storages` if drawings/photos justify it (`storage_plan.md`
  has the costing — the answer was "cheap, decide on product fit").
- Reconsider the host. PythonAnywhere was picked for demo convenience;
  re-evaluate against a container host now that Postgres and background
  work are plausible.

## 5. Decisions — all answered 2026-08-06

Kept with their reasoning so they don't get re-litigated.

- **D1 — How do users get accounts? → Invite by email.** An organization
  admin invites an address; that creates an inactive user plus a signed,
  expiring link where the invitee sets their own password. No open
  registration, no self-signup.
- **D2 — Is `Layer` the same as faggruppe? → Yes, one concept. Rename
  `Layer` → `Discipline`.** Renaming rather than adding a parallel model:
  because the migrations are being reset anyway (§7), the rename is a pure
  find-and-replace with no migration risk *right now*, and expensive later.
- **D3 — Can a registration exist without a drawing? → Yes.**
  `Registration.drawing` is nullable.
- **D4 — Microsoft code: delete or keep dormant? → Delete.** Commit
  `e685bd4` is tagged **`sharepoint-integration`**, so the whole working
  Graph/MSAL implementation is one `git checkout` away if SharePoint
  returns as an optional per-organization integration.
- **D5 — The name. → `eConstruct`,** changed from `EzConstruct` on
  2026-08-07 and matching the `econstruct.eu.pythonanywhere.com` test host.
  Still a one-line change in `settings.BRAND_NAME` if it moves again — that
  constant has now absorbed four names without touching a template.
- **D6 — Multi-tenant. → Yes, and strictly.** This is a SaaS: many
  organizations, each **100% separated** from the others. The tenant model
  is named **`Organization`** (not `Company` — the project cards already
  use "Firmaer"/companies for the *subcontractors on a project*, a
  different concept that keeps that word free).

### Domain decisions, answered 2026-08-06 (second round)

- **D7 — What is a "Firma"? → A `Contractor` the organization owns, with no
  login.** Subcontractors are records you create (Elfirma X, VVS Y) and
  assign work to; they receive a PDF or an email, never an account. This
  keeps D6's sealed tenancy intact — there is no cross-organization sharing
  anywhere in the system. If subcontractor logins are ever wanted, that is a
  deliberate new feature with its own permission layer, not a small change.
- **D8 — Registration workflow → Åben → Løst → Godkendt.** No "igangsat"
  state. The verification step is the point: a fix isn't final until someone
  signs it off, which is what makes this an audit trail rather than a
  to-do list. "Overskredet" is derived from `deadline < now`, never stored.
- **D9 — Project access → explicit membership.** Users are added to
  projects and see only those, so a field worker's phone shows their site
  and nothing else.
- **D10 — Dokumenter → out of scope for now.** Only `Drawing` exists;
  the nav entry is gone until there's a real need.
- **D11 — Assignment → contractor required, person optional.** The firm
  owes the fix (`assigned_contractor`); someone at your own organization
  optionally owns chasing it (`responsible`).
- **D12 — Registrations are numbered sequentially per project.** #001, #002
  within each project, allocated under a row lock on the project. This is
  how people refer to one on site and in reports.
- **D18 — Faggruppe is optional on a registration (2026-10-02).** The form
  needs emne and firma; faggruppe, ansvarlig and frist sit in a folded
  "Ekstra" box for whoever wants to be thorough. Firma stays required (D11)
  and stays out of the box, because a required field inside a closed box
  fails out of sight. A registration with no faggruppe draws grey
  (`Registration.NO_DISCIPLINE_COLOR`) on pins, rows and PDF exports, and
  the viewer's faggruppe chips never hide it.
- **D19 — Pricing → one plan, no project cap, storage as the safety valve
  (2026-10-18).** 699 kr./month per organization, unlimited users and
  projects, 500 GB of photo storage included, every feature on the one
  plan. The first 10 customers get 499 kr./month for as long as they stay,
  in exchange for feedback — a permanent founding price, not a first-year
  discount, so there is no later price to state. Prices are shown in DKK
  only. Larger firms get extra storage or an agreement by need, not a
  higher tier. Reasoning: marginal cost per
  project is near zero (`storage_plan.md`), so tiers would be
  segmentation without customers to segment; a project cap would teach
  customers to mark live sites Afsluttet to free a slot, corrupting the
  counts they pay for; and tiers need plan state, enforcement and
  Mothership controls, none of which exist. The 500 GB is advertised
  only — nothing measures per-organization storage yet, so the planned
  warning at 400 GB and a usage figure on the Mothership client page are
  open work. The 699 kr. is a hypothesis to validate in demos, not a measured
  willingness to pay; revisit tiers only once 10–30 real customers show
  what actually varies.

### Internal console decisions, answered 2026-08-07

- **D13 — Where the internal admin lives → `mothership`, an app in this
  project, gated on `is_superuser`.** Not a second Django project: two
  deploys and duplicated models for a two-person tool. Not `is_staff`: that
  flag also opens Django admin and is the kind of thing you eventually hand
  a support person. Non-superusers get **404, not 403**, so a customer
  poking at URLs learns nothing about what's there. Named Mothership over
  Kontroltårnet/Bagbordet because it can never collide with construction
  vocabulary — "tårn" and "kran" are words on a real site.
- **D14 — How far Mothership sees into a client → counts and project names,
  nothing else.** No registration text, no photos, no drawings, no
  impersonation. D6 says organizations are 100% separated; this is the one
  place that reads across that line and the hole is deliberately exactly
  this wide. Project names are in because a support call starts with "which
  site are you on?". Impersonation was offered and declined.
- **D15 — A new client is seeded with the five standard disciplines, not
  with contractors.** A registration requires both, so an empty
  organization can't file anything (friction 4). The five faggrupper are
  the same on every Danish site and live in `core/defaults.py`;
  subcontractors are genuinely per-customer and can't be guessed, so the
  client detail page *warns* about missing contractors instead. Marked
  provisional by Martin — revisit once there are real clients.
- **D17 — An account is either ours or a customer's; each has one home.**
  Superusers land in Mothership on login and are redirected back to it from
  anywhere in `core`; customers land in the app and never see that
  Mothership exists. There is no link between the two halves in either
  direction. This costs nothing: a superuser has no organization, so every
  customer page is scoped to nothing and renders empty anyway — the old
  `Internt` sidebar entry led to a screen of zeros. Enforced in
  `accounts.views.LoginView` (the default destination, so an explicit
  `?next=` still wins) and `accounts.middleware.SuperuserHomeMiddleware`
  (bookmarks and typed URLs). **To look inside the customer app, use a
  seeded account, not the superuser** — `manage.py seed_demo` prints them.
- **D16 — Suspension is enforced per request, not only at login.** Sessions
  last 30 days and slide forward (§4 phase 1), so a login-time check alone
  would leave a suspended customer working for a month.
  `accounts.middleware.SuspendedOrganizationMiddleware` costs one indexed
  lookup per authenticated request; that is the price of "suspended" meaning
  now rather than eventually.

**Calls made without asking** (say the word and any of these change): a
registration carries a short `subject` plus an optional longer
`description`; `deadline` is optional; photos are many-per-registration with
a generated thumbnail; project status is Planlagt/Aktiv/Afsluttet; `case_no`
is typed by hand, not generated; any project member can create a
registration and mark it Løst, but only its author or an org admin can mark
it Godkendt.

  **D6 makes scoping a correctness requirement, not a style choice.**
  Every queryset that touches organization-owned data filters on
  `request.user.organization`, and every object lookup by pk is scoped in
  the same query (`get_object_or_404(Model, pk=pk, organization=...)`),
  never fetched first and checked after. One missing filter is a
  cross-tenant data leak, so this is the first thing that gets tests in
  phase 6 — and the thing to check hardest in review.

## 6. What carries over unchanged

Worth stating so it doesn't get re-litigated:

- The dashboard shell, sidebar, icon sprite, typography, and Danish UI —
  all independent of where files and identity come from.
- The PDF.js viewer and pin math (percent coords, one page at a time).
- `pdf_export.py`, including the CAD-page coordinate fix.
- `core/images.py`'s Pillow pipeline.
- Company scoping and the `company_admin_required` decorator.
- Mobile-first as the primary constraint (SPEC.md) — more true now, not
  less, if field workers are the main users.

---

## 7. Mothership — the internal console (built 2026-08-07)

The dashboard Martin and his partner use to run the SaaS, as opposed to the
app their customers use. `/mothership/`, superuser-only, its own Django app.
Decisions and their reasoning are D13–D17 in §5.

**The two halves do not connect.** A superuser logs in and lands here; a
customer logs in and lands in the app. Neither can navigate to the other, and
`createsuperuser` is the only way an account ends up on this side (D17).

**What it does:**

- **Client list** — every organization with user, project and registration
  counts, last activity, and search by name. Suspended clients are greyed
  rather than hidden; a client with no users is badged, because that is the
  state a half-finished setup leaves behind.
- **Create a client** — one form produces the organization, its five
  standard faggrupper, and its first org admin. The admin gets either an
  emailed invitation (the normal path; keeps D1's "nobody but the owner
  knows the password") or a password set on the spot.
- **Client detail** — counts, project names and status, users with last
  login, and open invitations *including the accept link*, so a client whose
  mail bounced can be helped by hand. A warning banner fires when a client
  can't yet file a registration (no users / no faggrupper / no firmaer).
- **Suspend and reactivate** — flips `Organization.is_active`, which was on
  the model but enforced nowhere. Now enforced twice: login is refused, and
  an open session ends on its next request (D16).

**Where things are:** `mothership/{views,forms,urls}.py`,
`templates/mothership/`, the `.ms-*` block at the end of `micki.css`, and
`core/defaults.py` (the one list of standard disciplines, shared with
`seed_demo`). The shell is deliberately *not* `base.html` — violet on black
against the customer app's navy on graphite, and no side rail, because both
will be open in adjacent tabs and only one of them can break a paying
customer.

**Friction from the previous handoff — all four closed:**

1. Creating an org admin took two saves → one form, `ClientCreateForm`.
2. `username` must equal the email → the form sets `username` from `email`;
   it is never typed. Tested.
3. An org admin with no organization returned 500 → `org_admin_required` now
   requires both halves (a 403, since there's nothing to administer), and
   `_disciplines(request)` joins the scoping helpers so the remaining call
   sites return an empty queryset instead of dereferencing None. The pages a
   fresh `createsuperuser` account lands on are tested.
4. A fresh organization couldn't file anything → disciplines are seeded
   (D15) and missing contractors are warned about on the client detail page.

The two smaller fixes offered last time (`add_fieldsets` on
`CustomUserAdmin`, a `create_org` command) are now superseded and not worth
doing.

### Next up

Phase 5 — **Rapporter**, the last placeholder page. `core.views.reports`
still renders `core/placeholder.html`, and `pdf_export.stamp_registrations`
already does the expensive part.

Open questions for Mothership itself, none of them urgent, none of them
specced: billing/subscription state, per-client usage over time, and an
audit trail of what a superuser did in here. Ask before building any of
them.

### State as of this handoff

- **Phases 1–4 done, plus Mothership.** Phase 5 (Rapporter) and phase 6
  (Postgres, S3, deploy) are open.
- **The database is empty and intentionally so.** Martin deleted it and is
  populating it himself. Schema is migrated; there are **zero users**, so
  `createsuperuser` (which now also gets you into Mothership) or
  `manage.py seed_demo` is needed before anything is reachable.
- **92 tests, all passing** — 56 in `core/tests.py`, 36 in
  `mothership/tests.py` (the superuser gate, client creation, suspension at
  both layers, where each kind of account lands, and the orgless-user 500s).
  The suite runs in ~1.6s (MD5 hashing under `if "test" in sys.argv`).
- `media/` holds ~21 orphaned files Martin is deleting by hand — not a bug.
- Every model now inherits `core.base.BaseModel` (created_at/updated_at)
  **except `User`**, which keeps `date_joined`. `created_at` is
  `auto_now_add`, so it cannot be backdated — importing historical data
  needs an UPDATE after insert. Any `save(update_fields=[...])` must list
  `"updated_at"` or the timestamp silently goes stale; there are tests
  pinning this.

### Working with Martin

- **He commits to git himself.** Never run `git add`/`commit`/`push`/`tag`.
  Read-only git is fine. Finish the work, run the tests, report, and leave
  it in the working tree.
- **Never run destructive requests against his dev database.** A POST to a
  delete endpoint during verification cost him a drawing on 2026-08-07; use
  the test database.
- UI is Danish, hardcoded (no gettext). URL paths and internal identifiers
  stay English, including the `micki:*` HTMX event names.
- Bootstrap 5 + HTMX, both vendored — no CDN, no React. He's fluent in both.
- Mobile-first: field workers on phones are the primary users.
- He iterates screen by screen and asks for small changes; he responds well
  to being told when something he asked for conflicts with something else
  on the page, so say so rather than silently reconciling it.
