# Micki — MVP v0.1 Specification

B2B SaaS: companies connect their SharePoint, users open PDFs from it on
phone/tablet, drop pin-notes on the page, and target each note at an
audience "layer" (e.g. Sales, Technicians).

**Status of this document:** agreed spec for v0.1, 2026-07-07. The MVP is a
pitch vehicle for one target company; expect a partial rebuild after their
feedback, so bias every decision toward *shipping the demo*, not toward
long-term architecture.

---

## 1. Decisions made (with rationale)

| Area | Decision | Why |
|---|---|---|
| Login | Microsoft SSO (Entra ID) only | One integration gives both auth and Graph tokens for SharePoint |
| SharePoint | Live fetch via Microsoft Graph API, no copies stored | PythonAnywhere disk is limited; always-current documents; no sync jobs |
| Demo tenant | Own Microsoft 365 dev/trial tenant with fake SharePoint data | No dependency on target company's IT pre-sale; app built multi-tenant so their real tenant is one admin-consent away |
| Note layers | Company-configurable (admin CRUDs layers) | Requested; layers are *filtering*, not access control, in v0.1 |
| Annotation UX | Point pin: tap page → marker at x/y → note form | Works on scanned PDFs, simple coordinate model, HTMX-friendly |
| Note lifecycle | Create, read, edit/delete own; admins delete any | No threads, no resolve status in v0.1 |
| Roles | Company Admin + Member | Admin: layers, users, folder selection. Member: view + annotate |
| Billing | None — companies created manually in Django admin | Deal is closed by hand; Stripe is post-MVP |
| Database | SQLite | Demo-scale; rebuild expected after pitch feedback |
| PDF viewer | One page at a time, prev/next + page jumper | Simple pin math, HTMX partials, good on mobile |
| UI language | **Danish** (changed 2026-07-27; was English) | Pitch audience is a Danish construction firm. Strings are hardcoded — gettext/i18n stays out of scope (§6). URL paths and internal identifiers stay English |
| Shell | SaaS dashboard: left sidebar (Oversigt, Projekter, Mapper, Registreringer, Rapporter, Brugere, Indstillinger), content right | Reads as a real product in the pitch; sidebar collapses to a Bootstrap offcanvas below 992px |
| Hosting | PythonAnywhere (deployed before the pitch) | Real URL for OAuth redirect and follow-up link |
| Devices | **Phone/tablet first** | Primary users are on mobile — touch-first PDF viewer, responsive Bootstrap throughout |

## 2. Constraints

- **PythonAnywhere:** WSGI only — no websockets (HTMX polling if live-ness is
  ever needed), no Celery; scheduled tasks are the only background option.
  Outbound HTTPS to `graph.microsoft.com` and `login.microsoftonline.com` is
  fine (whitelisted / paid accounts unrestricted).
- **Mobile-first:** all templates responsive Bootstrap 5; pin touch targets
  ≥ 44px; PDF page must pinch-zoom.
- **Graph API:** delegated permissions via the signed-in user. Requires
  `Files.Read.All` and `Sites.Read.All` (delegated) — these need **admin
  consent** in the customer tenant. In our dev tenant we are the admin, so
  the demo is unblocked.

## 3. Tech stack

- Django 6.0 (existing project: `config` + apps `core`, `accounts`)
- Custom user model `accounts.User` (already wired) — will gain
  `company` FK and `is_company_admin` flag; Microsoft OAuth identity via
  MSAL (`msal` package; hand-rolled auth backend rather than allauth, since
  we need the Graph access/refresh tokens from the same flow)
- Bootstrap 5 + HTMX (vendored static files — no CDN reliance during a pitch)
- PDF.js (vendored) for client-side rendering; pin overlay is a positioned
  `<div>` on top of the canvas
- `requests` or `httpx` for Graph calls
- SQLite; secrets via environment variables (`.env` locally,
  PythonAnywhere env vars in prod) — the committed `SECRET_KEY` in
  settings.py must be rotated out before deploy

## 4. Data model (v0.1)

```
Company        name, slug, ms_tenant_id (nullable until first SSO), is_active
User           (AbstractUser) + company FK, is_company_admin bool,
               ms_object_id (Entra user id)
MsToken        user 1:1 — encrypted access/refresh token cache (MSAL cache blob)
Layer          company FK, name, color, sort_order
FolderLink     company FK, drive_id, item_id, display_path, added_by
               — a SharePoint folder the admin selected
Document       company FK, folder_link FK, drive_id, item_id, name, etag
               — lightweight registry row created the first time a PDF is
               opened; anchors notes. NO file contents stored.
Note           document FK, page_number, x_pct, y_pct (percent of page size,
               so pins survive zoom/DPI), layer FK, author FK, text,
               created_at, updated_at
```

Coordinates stored as **percentages of the rendered page**, not pixels —
zoom- and device-independent.

Identity rule: a SharePoint file is identified by `(drive_id, item_id)`.
Renames/moves keep `item_id` stable, so notes survive them. If a file is
deleted in SharePoint the Document row remains with a "missing" state.

## 5. Screens & flows

1. **Login** — "Sign in with Microsoft" → MSAL auth-code flow → match/create
   User by `ms_object_id`; user must belong to an active Company (first user
   of a company is provisioned manually via Django admin for v0.1).
2. **Folder picker (admin)** — browse the tenant's SharePoint sites/drives
   via Graph, select folders → creates FolderLinks.
3. **Document browser (member)** — list linked folders → list PDFs inside
   (live Graph listing, HTMX partials) → tap a PDF.
4. **Viewer** — PDF.js renders page N (fetched through our proxy view that
   streams the file from Graph with the user's token — the browser never
   talks to Graph directly). Overlay shows pins for visible layers.
   - Layer filter: toggle chips above the page.
   - Tap empty spot → pin drops → HTMX note form (text + layer) in a
     bottom sheet / offcanvas (mobile-friendly).
   - Tap existing pin → note card with author/time; edit/delete if owner.
   - Prev/next page, page jumper, pinch-zoom.
5. **Layer management (admin)** — CRUD list of layers (name, color).
6. **User list (admin)** — see company users, toggle admin flag,
   deactivate. (Invites = "sign in with Microsoft and I'll activate you"
   for v0.1.)

## 6. Explicitly out of scope for v0.1

Stripe/self-serve signup · note threads/replies · resolve status ·
text-highlight annotations · continuous-scroll viewer · writing anything
back to SharePoint · offline/caching of PDFs · email notifications ·
non-PDF file types · search across notes · i18n.

## 7. Risks & mitigations

1. **Graph token lifetime** — access tokens last ~1h; MSAL refresh tokens
   must be cached server-side (`MsToken`) and refreshed silently, or users
   get logged out mid-annotation. Build token refresh early, not last.
2. **Large PDFs over live fetch** — a 50 MB scanned PDF streams through
   PythonAnywhere on every open. Mitigation: PDF.js range requests if
   feasible; otherwise accept for demo, note as v0.2 caching work.
3. **Admin consent at the real customer** — the pitch should include the
   sentence "your IT clicks one approval link" and we should have that
   link ready (multi-tenant app registration).
4. **Touch precision for pins** — test pin placement on an actual phone
   early; zooming before dropping a pin must feel natural.

## 8. Build order

1. Models + migrations, Django admin for Company/Layer/User provisioning
2. Microsoft SSO (MSAL auth-code flow, dev tenant app registration)
3. Graph: folder browse + folder linking + PDF listing
4. PDF proxy view + PDF.js single-page viewer (responsive)
5. Pins + notes CRUD with layer tagging (HTMX)
6. Layer management + layer filter UI
7. Polish for mobile, seed demo data in dev-tenant SharePoint
8. Deploy to PythonAnywhere, end-to-end rehearsal of the pitch flow

## 9. Open questions (fine to defer)

- Should a note be taggable with *multiple* layers, or exactly one?
  (v0.1 assumes exactly one.)
- Do Members see all layers, or should "my layers" be a per-user default
  filter? (v0.1: everyone sees everything, filter is a view toggle.)
- What happens to notes when a FolderLink is removed? (v0.1: documents
  and notes are kept but hidden.)
