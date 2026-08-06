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
Company            unchanged (ms_tenant_id becomes dead — drop in phase 6)
User               unchanged (ms_object_id + MsToken die in phase 1)

Project            NEW. company, name, slug, case_no, address, status,
                   manager -> User, members -> M2M User, created/updated.
                   Fields are lifted straight from _DEMO_PROJECTS so the
                   existing template keeps working.

Drawing            REPLACES Document. project, name, file (FileField),
                   page_count, uploaded_by, created. No drive_id/item_id.

Discipline         Layer, renamed and re-scoped (see decision D2).
                   company, name, color, sort_order.

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

### Phase 1 — Local auth (unblocks everything)

The whole login path is Microsoft. Replace it:

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

### Phase 2 — Project model

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

### Phase 3 — Drawings (kills the Graph dependency)

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

### Phase 6 — Production readiness

- **Postgres.** SQLite was chosen for a single-worker demo; a product with
  concurrent field writes shouldn't ship on it. Do this before deploying,
  not after.
- Tests. Not 100% coverage — cover company-scoping (every view leaks
  cross-company data if it's wrong), the permission decorators, and
  `pdf_export`'s coordinate handling, which is subtle enough to regress
  silently.
- Drop `Company.ms_tenant_id`, prune dead settings.
- S3 via `django-storages` if drawings/photos justify it (`storage_plan.md`
  has the costing — the answer was "cheap, decide on product fit").
- Reconsider the host. PythonAnywhere was picked for demo convenience;
  re-evaluate against a container host now that Postgres and background
  work are plausible.

## 5. Decisions needed from Martin

Numbered so they can be answered by reference. **D1–D3 gate phases 1–4;
D4–D6 can wait.**

- **D1 — How do users get accounts?** Recommend admin-invites-by-email with
  a set-password link: matches the B2B shape already in the code and avoids
  open registration. Alternative is magic links (no passwords at all, nicer
  on a phone, needs working outbound email either way).
- **D2 — Is `Layer` the same thing as faggruppe?** `Layer` is per-company
  name + colour + sort order; the demo registrations' `category` +
  `color` (Konstruktion/Brand/El/VVS/Kvalitet) is *exactly* that shape.
  Recommend renaming `Layer` → `Discipline` and having one concept. Say so
  if Sales/Technicians-style audience layers are meant to survive
  *alongside* trade groups — that's two models, not one.
- **D3 — Can a registration exist without a drawing?** Recommend yes
  (nullable). Affects phase 4's model and the viewer's role.
- **D4 — Delete the Microsoft code or keep it dormant?** Recommend
  deleting it in phase 1/3 and tagging commit `e685bd4` (e.g.
  `git tag sharepoint-integration e685bd4`) so it's one command to
  recover. Construction firms do live in SharePoint, so this may well come
  back as an optional per-company integration — but half-wired dead code
  in a product build costs more than a git tag does.
- **D5 — The name.** Still `EzConstruct`, still flagged as a working title
  (PLAN.md open question 4). One-line change in `settings.BRAND_NAME`.
  Worth settling before anything user-facing ships.
- **D6 — Multi-company or single?** Every query is company-scoped today. If
  this is now one product for many customers, that's right and stays. If
  it's being built for one firm, a lot of scoping could go — but
  recommend keeping it, since removing it later is easy and adding it back
  is not.

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
