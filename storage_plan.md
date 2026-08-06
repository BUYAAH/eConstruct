# Storage Plan — Self-Hosted Photos (Registreringer)

Exploratory note, not an agreed spec. Written 2026-07-27 to think through
whether/how we'd store our own images for the future **Registreringer**
(site-photo registrations) feature, where field workers upload phone
photos rather than us reading files that already live in SharePoint. This
is a deliberately different pattern from the current PDF viewer (SPEC.md
§1 "Sharepoint" row — live Graph fetch, no copies stored): here, *we*
would be the origin of the files, so we control the whole lifecycle.

**Scope of this doc:** the storage/cost shape of the idea only. No code
design — implementation is a separate step if we decide to build this.

---

## 1. The idea, in broad terms

For every uploaded photo, keep three renditions instead of just the
original:

| Rendition | Purpose | Rough size (~5 MB phone original) |
|---|---|---|
| **Thumbnail** | Grid/list views, fast scrolling on mobile | ~15 KB |
| **Medium** (~2048px longest edge) | The normal "open and look at it" view | ~400–600 KB |
| **Original** | Full-res download, export, zoom-to-detail, legal/QA record | ~5 MB (as uploaded) |

Mechanically, this is: on upload, hand the original to **Pillow** to
produce the medium and thumbnail copies (resize + re-encode JPEG,
correcting EXIF rotation), then push all three to **S3** under a
per-company/per-project key prefix. Django stores only the resulting S3
keys on the model — never the image bytes themselves — plus whatever
metadata (uploader, timestamp, project, GPS if we want it later).

Two implementation notes worth flagging now (still broad-strokes, not
code):

- **No background queue needed at this size.** A single Pillow resize of
  a phone photo is sub-second; doing it synchronously inside the upload
  request is fine and sidesteps the fact that PythonAnywhere has no
  Celery (SPEC.md §2).
- **Serve from S3/CloudFront directly, not through Django.** The current
  PDF proxy streams SharePoint bytes through the Django app deliberately
  (Graph tokens must stay server-side). Self-hosted images don't have
  that constraint — use short-lived **presigned S3 URLs** (or a
  CloudFront distribution in front of the bucket) so phones fetch image
  bytes straight from AWS. This matters because PythonAnywhere plans have
  bandwidth/CPU allowances, and a proxy would burn through those for
  every photo view for no benefit.

---

## 2. Assumptions used below

Picked to keep the estimate honest without needing real usage data yet:

- **~1000 photos per project** (given).
- **~5 MB average original** (typical modern phone JPEG).
- **Medium ≈ 500 KB, thumbnail ≈ 15 KB** after Pillow re-encoding.
- **Region:** an EU S3 region (eu-west-1/eu-central-1), since this is a
  Danish company — prices below use current (2025) EU list prices, in
  USD, excluding VAT. **Verify at aws.amazon.com/s3/pricing before
  budgeting for real** — AWS pricing changes and I'm not treating these
  as exact quotes.
- **Storage class: S3 Standard** for everything, no lifecycle tiering.
  At the volumes below, the storage line item is small enough that the
  extra complexity of Infrequent-Access/Glacier tiers (minimum storage
  durations, retrieval fees, more moving parts) isn't worth it yet.
- **Usage pattern per project**, over an assumed 3–6 month active
  project life, across all the people who touch it (workers, sales,
  admin reviewing registrations):
  - Thumbnail viewed ~30× per photo (grid browsing, re-browsing)
  - Medium viewed ~10× per photo (opening a registration)
  - Original viewed ~1.5× per photo (occasional full-res/export)

These view-count assumptions are the biggest lever in the whole estimate
— they're a guess, not a measurement. Worth revisiting once the feature
is live and we have real numbers.

---

## 3. Per-project cost estimate

**Storage added per project:**

| Rendition | Count | Size each | Total |
|---|---|---|---|
| Original | 1000 | 5 MB | ~5 GB |
| Medium | 1000 | 500 KB | ~0.5 GB |
| Thumbnail | 1000 | 15 KB | ~0.015 GB |
| **Total** | | | **~5.5 GB** |

**Storage cost:** 5.5 GB × ~$0.023/GB-month ≈ **$0.13/month per project**,
for as long as we keep the files. Negligible on its own.

**Upload (write) cost:** 1000 originals uploaded by users + 2000 derived
uploads (medium + thumbnail) from Pillow ≈ 3000 PUT requests, at
~$0.005/1000 requests ≈ **$0.015 per project**, a one-time cost as photos
come in.

**View (read) cost — requests:** (30 + 10 + 1.5) × 1000 ≈ 41,500 GET
requests over the project's active life, at ~$0.0004/1000 ≈ **$0.017 per
project**. Also negligible.

**View (read) cost — data transfer out, the real line item:**

| Rendition | Transfers | Volume out |
|---|---|---|
| Thumbnail | 30,000 | ~0.43 GB |
| Medium | 10,000 | ~4.8 GB |
| Original | 1,500 | ~7.3 GB |
| **Total** | | **~12.5 GB** |

At ~$0.09/GB egress: ≈ **$1.13 per project**, spread over its active
months.

**Total AWS cost per project, over its active life:** storage +
requests + egress ≈ **$0.15 (one-time-ish) + ~$1.13 (egress) + ~$0.13/month
ongoing storage ≈ roughly $1.50–2.50 all-in for an active project's
lifetime**, then ~$0.13/month for as long as we keep the photos
afterward (essentially free to just retain them — there's no strong
cost reason to ever delete old registrations).

---

## 4. Scaling beyond one project

Since storage and egress both scale ~linearly with photo count, and the
per-project number above is already small:

| Active projects at once | Storage/month | Egress (one-time, spread over life) | Rough monthly AWS bill |
|---|---|---|---|
| 1 | $0.13 | $1.13 total | well under $1 |
| 10 | $1.30 | ~$11 total | a few dollars |
| 50 | $6.50 | ~$56 total | ~$15–20 |
| 200 | $26 | ~$225 total | ~$60–80 |

Even at 200 simultaneously-active projects (far beyond the current
one-pitch-company scope), AWS costs stay in "pocket change" territory —
well under what a single PythonAnywhere paid plan or one hour of
developer time costs.

**AWS Free Tier note:** new AWS accounts get meaningful free allowances
in the first 12 months (some S3 storage, request, and data-transfer-out
quota), and CloudFront has an ongoing free tier (1 TB/month transfer,
10M requests/month) that would likely cover this app's bandwidth
entirely at pilot scale if we put CloudFront in front of the bucket.
Don't bank on exact numbers here without checking current terms, but
directionally: a single pilot project like the one we're pitching would
likely cost close to **$0** in year one.

---

## 5. Bottom line

- **Cost is not a reason to avoid this.** At ~1000 photos/project, the
  entire AWS bill — storage, uploads, and all the repeat viewing — comes
  out to roughly **$1.50–2.50 per project** over its active life, plus a
  fraction of a cent per month per project to keep photos around
  afterward indefinitely. This holds even under fairly generous "people
  keep re-browsing photos" assumptions.
- **The real cost driver, if any, is egress (data transfer out)** —
  it's ~85% of the AWS bill above — which means the thing worth
  optimizing later isn't storage tiering, it's **caching** (CloudFront in
  front of S3) if usage ever gets heavy enough to matter, which at this
  scale it won't for a long while.
- **Decision should be driven by product fit, not cost:** does
  Registreringer need us to own the images (so we can generate
  thumbnails, keep them after a SharePoint folder is unlinked, avoid a
  live Graph round-trip per thumbnail, etc.), not whether we can afford
  to store them — we clearly can.

## 6. Open questions (for Martin)

1. Retention: keep photos forever once a project closes, or is there an
   expected archive/delete point? (Doesn't change the cost story much
   either way, but affects whether lifecycle rules are worth adding
   later.)
2. Do we want CloudFront in front of the bucket from day one (better
   mobile latency, keeps PythonAnywhere's bandwidth untouched), or is
   direct S3 presigned-URL serving fine to start and CloudFront is a
   later optimization?
3. Should Registreringer photos live in the same AWS account/region as
   anything else we might self-host later, or is this the first thing
   that pushes us onto AWS at all?
