# Micki — Implementation Plan & Handover

Companion to `SPEC.md` (read that first — it holds the *what* and every
agreed decision). This file holds the *how*: concrete steps, code-level
guidance, and current status, so any developer or AI session can continue
without re-deriving context.

## How to work on this project (from Martin)

- Martin is fluent in Bootstrap and enjoys HTMX — lean into HTMX patterns,
  don't reach for React/heavy JS. Vanilla JS only where PDF.js demands it.
- **Talk to Martin whenever unsure** — he asked to be consulted on open
  decisions rather than having them silently made.
- This is a pitch MVP for one target company; a rebuild after feedback is
  expected. Prefer shipping over architecture. But the Microsoft/Graph
  integration is the part that must be *real* (decided in spec Q&A).
- Mobile/tablet is the primary device. Test every template narrow-first.
- Timezone/locale: Europe/Copenhagen, UI in English.

## Current status

- [x] Spec agreed and written (`SPEC.md`, 2026-07-07)
- [x] Django 6.0 project scaffolded (`config`, apps `core` + `accounts`)
- [x] Step 0 done (2026-07-07): git init'd (no commits yet — Martin
      hasn't asked for one), .gitignore, requirements.txt, `.env` +
      `.env.example`, env-based settings, vendored Bootstrap 5.3 /
      HTMX 2 / PDF.js 5 in `static/vendor/`, `templates/base.html`
      (mobile viewport, HTMX CSRF via hx-headers on body).
- [x] Step 1 done: all models per SPEC §4, admin registrations
      (admin = provisioning UI), initial migrations applied to SQLite.
      No superuser yet — Martin runs `createsuperuser` himself.
- [x] Step 2 Django side done: `accounts/microsoft.py` (MSAL app
      factory, Fernet-encrypted token cache, `get_graph_token` with
      silent refresh + `ReauthRequired`), login/callback/logout views
      (auth-code flow via `initiate_auth_code_flow`), error templates,
      `core.home` placeholder at `/`. Smoke-tested: anonymous `/` →
      302 to `/auth/login/`. Decision made en route: new users from a
      known company tenant are auto-created **active** (smoother demo)
      — flag to Martin if he'd rather approve each user.
      **NOT tested end-to-end** — blocked on Azure app registration
      (Martin's browser task, see Step 2 "Azure side"). `.env` has
      empty MS_CLIENT_ID / MS_CLIENT_SECRET.
- [x] Azure done (2026-07-07, live session with Martin): dev tenant
      **Buyaah.onmicrosoft.com** (Business Basic trial — expires ~2026-08-07,
      renew/replace before pitch if later!), admin
      MartinRahbek@Buyaah.onmicrosoft.com, multi-tenant app registration
      client id 6ee95d97-b92c-420f-9b3b-746bc49487de, delegated
      User.Read/Files.Read.All/Sites.Read.All with admin consent, secret in
      `.env`. Tenant id 8556f059-9cce-4f76-af7e-05f29b662b09 = Company
      "Buyaah" (pk 1) in DB with layers Sales/Technicians. Martin's user is
      company admin. SharePoint site "Documentation" with PDFs exists.
- [x] Step 2 verified end-to-end: real Microsoft login round trip works.
- [x] Step 3 done & verified: `core/graph.py` (note: `/sites?search=*`
      500s on fresh tenants — list_sites merges followedSites + root +
      search), folder picker with HTMX drill-down, FolderLink CRUD,
      folder browsing with subfolders + PDF listing.
- [x] Step 4 done & verified: `document_pdf` streaming proxy (Range
      pass-through), PDF.js one-page viewer (`static/js/viewer.js`),
      fit-to-width, dpr-sharp, prev/next + page jumper.
- [x] Step 5 built (awaiting Martin's live test): pin notes CRUD.
      Architecture: `#pin-layer` div over the canvas re-fetches
      `core:pins` partial via hx-trigger on `micki:page-rendered` /
      `micki:refresh-pins` events (bubbled to body); note form/detail in
      a Bootstrap bottom offcanvas (`#note-sheet`); save/delete responses
      send HX-Trigger close+refresh; layer chips filter pins client-side.
      Coords stored as pct (Decimal 6,3), add-mode toggle guards against
      accidental taps.
- [x] Step 5 verified live, plus scope addition Martin chose: **export to
      SharePoint** (Files.ReadWrite.All added + admin-consented; scope in
      settings). Two modes in `core/pdf_export.py` (pypdf + reportlab):
      "summary" (numbered dots drawn on page + sticky annots + appended
      summary page) and "inline" (flattened text boxes). Upload via Graph
      upload session, conflictBehavior=replace, names "<stem> (annotated
      | inline notes).pdf". **Coordinate gotcha fixed**: pages with
      non-zero-origin boxes (CAD exports!) — overlays drawn 0-based and
      merged with merge_transformed_page(translate(left,bottom)); use
      cropbox not mediabox. Verified by rendering with pypdfium2
      (dev-only dep).
- [x] Step 6 built: /manage/ page for company admins — layer CRUD
      (inline HTMX rows, delete blocked while notes use the layer) and
      user activate/deactivate + admin toggle (self-change blocked).
      Navbar "Manage" button for admins.
- [ ] Step 7–8 (mobile polish pass, realistic demo data, deploy).

## Step 0 — Housekeeping (30 min)

1. `git init` + `.gitignore` as above.
2. `requirements.txt`:
   ```
   Django>=6.0,<6.1
   msal            # Microsoft auth-code flow + token cache
   requests        # Graph calls
   python-dotenv   # local .env loading
   cryptography    # encrypt the MSAL token blob at rest
   ```
3. Settings hygiene: read `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`,
   `MS_CLIENT_ID`, `MS_CLIENT_SECRET`, `MS_REDIRECT_URI`, and
   `TOKEN_ENC_KEY` from env (dotenv locally). Rotate the committed
   SECRET_KEY. Add `LOGIN_URL = "accounts:login"`.
4. Create `templates/` and `static/vendor/` dirs; vendor Bootstrap 5.3,
   HTMX 2.x, PDF.js (download, don't CDN — pitch must not depend on
   third-party uptime). `base.html` with mobile viewport meta,
   Bootstrap, HTMX, and a `{% block %}` layout.

## Step 1 — Models + admin (spec §4)

All domain models go in `core` except User (in `accounts`).
Exact fields are in SPEC.md §4. Notes:

- `Note.x_pct` / `y_pct`: `DecimalField(max_digits=6, decimal_places=3)`,
  percent of page width/height, origin top-left of the page as rendered
  at scale 1.
- `MsToken.blob`: `BinaryField` storing the **Fernet-encrypted** MSAL
  serialized token cache (`cryptography.fernet`, key from env). One row
  per user, `OneToOneField`.
- `Layer.color`: 7-char hex string; give the admin form a
  `<input type="color">` widget.
- Register everything in Django admin — admin *is* the provisioning UI
  for Company/User activation in v0.1.
- Then: first `makemigrations` + `migrate`, create superuser.

## Step 2 — Microsoft SSO (the critical path)

### Azure side (Martin does this in a browser, guide him)
1. Get a Microsoft 365 dev/trial tenant (Microsoft 365 Developer Program,
   or a trial Business Basic tenant). Create a SharePoint site with a
   document library, a few folders, and realistic dummy PDFs.
2. Entra ID → App registrations → New: **multi-tenant**
   ("Accounts in any organizational directory"), web platform,
   redirect URIs `http://localhost:8000/auth/callback/` and later
   `https://<name>.pythonanywhere.com/auth/callback/`.
3. Delegated permissions: `User.Read`, `Files.Read.All`, `Sites.Read.All`.
   Grant admin consent in the dev tenant.
4. Create a client secret → into `.env`.

### Django side (`accounts` app)
- Use **msal** `ConfidentialClientApplication` directly — do NOT use
  django-allauth/social-auth; we need the Graph token cache from the same
  flow and allauth fights us on that.
- Views: `login` (redirect to `get_authorization_request_url`, common
  endpoint `https://login.microsoftonline.com/common`), `callback`
  (exchange code via `acquire_token_by_authorization_code` with the Graph
  scopes, then):
  1. Read `oid` (object id) and `tid` (tenant id) from the ID token claims.
  2. Look up User by `ms_object_id`. If none: find Company by
     `ms_tenant_id`; if company exists and is active → create User
     (inactive-by-default is fine for v0.1: admin flips them active);
     if no company → friendly "your organisation isn't set up yet" page.
  3. `django.contrib.auth.login()` with a custom no-password backend.
  4. Serialize the MSAL cache → encrypt → upsert `MsToken`.
- `get_graph_token(user)` helper: load+decrypt cache into a
  `SerializableTokenCache`, `acquire_token_silent` (MSAL refreshes via
  refresh token automatically), re-persist cache if
  `has_state_changed`. If silent acquisition fails → raise a
  `ReauthRequired` exception; a middleware or the Graph client catches it
  and redirects to login. **Build and test this refresh path immediately**
  (spec risk #1) — set a calendar reminder to re-test after >1h idle.

## Step 3 — Graph client + folder linking (`core`)

- Thin module `core/graph.py`, functions taking `user`:
  `list_sites()`, `list_drive_children(drive_id, item_id)`,
  `get_item(drive_id, item_id)`, `stream_content(drive_id, item_id)`.
  Endpoints: `GET /sites?search=*`, `GET /sites/{id}/drives`,
  `GET /drives/{id}/items/{id}/children`, `.../content` (follow the 302).
- Admin-only folder picker: HTMX-driven drill-down (site → drive →
  folders), each level a partial; "Link this folder" button creates a
  `FolderLink`.
- Member document browser: linked folders → children filtered to
  `.pdf` (check `file.mimeType`), HTMX partials, mobile list-group UI.
  Opening a PDF get-or-creates the `Document` row by
  `(drive_id, item_id)`.

## Step 4 — PDF proxy + viewer

- `document_pdf` view: streams Graph content through Django
  (`StreamingHttpResponse`), enforcing company membership. Support the
  `Range` header if straightforward (Graph supports range requests;
  PDF.js will use them and large files get much cheaper) — otherwise
  full-file for v0.1 and note it.
- Viewer page: PDF.js renders **one page** to a canvas inside a
  `position:relative` wrapper; pin overlay is an absolutely-positioned
  div on top. Pins placed by `x_pct/y_pct` of the wrapper. Prev/next +
  page jumper (server round-trip not needed — page nav is client-side;
  pins for the whole document are loaded as JSON, filtered per page).
- Touch: pinch-zoom via CSS-transform on the wrapper (pins scale with it
  for free since they're percent-positioned inside it); pin hit
  targets ≥ 44px; a floating "add note" mode toggle so scrolling/zooming
  doesn't accidentally drop pins.

## Step 5 — Notes CRUD (HTMX)

- Tap in add-mode → JS computes pct coords → HTMX GET note form into a
  Bootstrap offcanvas (bottom sheet on mobile) with hidden coord/page
  fields + text + layer `<select>`.
- POST creates the Note, response swaps in the new pin + closes sheet.
- Tap pin → HTMX GET note detail card (author, time, layer chip, text;
  edit/delete buttons if `note.author == user` or admin).
- Layer filter: chip row above viewer; client-side show/hide by
  `data-layer-id` (no round trip).

## Step 6 — Layer & user management (admin role)

- `is_company_admin`-gated section: Layer CRUD (name, color, sort) and
  user list (activate/deactivate, toggle admin). Plain Django forms +
  HTMX inline edits. Keep it small.

## Step 7 — Polish + demo data

- Walk every screen at 390px width. Empty states ("No folders linked
  yet — ask your admin"). Error states for Graph failures (SharePoint
  down, token expired, file deleted → Document "missing" state).
- Seed the dev-tenant SharePoint with PDFs that resemble the target
  company's real documents (ask Martin what industry/doc types).

## Step 8 — Deploy (PythonAnywhere)

1. Paid account (needed for custom scheduled tasks? not for v0.1 — free
   works only if whitelist covers Graph; **use a paid account** to avoid
   the outbound whitelist problem entirely — confirm with Martin).
2. Push code (GitHub) → clone in PA console → virtualenv →
   `pip install -r requirements.txt`.
3. WSGI config → `config.wsgi`; env vars in the WSGI file or `.env`
   loaded by dotenv; `DEBUG=False`, `ALLOWED_HOSTS`, static files via
   PA static-files mapping (`collectstatic`).
4. Add the production redirect URI in Azure; test full OAuth round trip.
5. Full pitch rehearsal on a phone against the deployed site.

## Known decisions still open (ask Martin, don't decide silently)

1. Note taggable with multiple layers or exactly one? (Spec assumes one.)
2. PythonAnywhere paid vs free account (see Step 8.1).
3. Industry/content of the demo PDFs for the dev tenant.
4. ~~App/product name~~ ANSWERED 2026-07-07: the product brand is
   **ImagR** (user-facing strings only). Internal identifiers (repo name,
   CSS file/classes, `micki:*` JS/HTMX event names) deliberately stay
   "micki" — do not blanket-rename them.

## Gotchas already identified

- MSAL scopes for `acquire_token_by_authorization_code` must NOT include
  the reserved scopes (`openid`, `profile`, `offline_access`) — msal adds
  them; passing them raises an error.
- Graph `/content` returns a 302 to a pre-authed download URL; `requests`
  follows it by default — fine, but don't send the Authorization header
  to the redirect target manually.
- PDF.js worker file must be served same-origin (vendored) and its
  version must exactly match the main library.
- SQLite + PythonAnywhere is fine for the demo but don't enable multiple
  web workers.
- Django 6.0: nothing project-relevant removed vs 5.x, but check any
  third-party package claims 6.0 support before adding it.
- **runserver's StatReloader is flaky on this Windows machine** when
  several files change in quick succession — it has twice kept a stale
  URLconf after `urls.py` edits (symptom: NoReverseMatch for a URL that
  `manage.py shell` reverses fine). Fix: restart runserver after edits
  that touch `urls.py`.
