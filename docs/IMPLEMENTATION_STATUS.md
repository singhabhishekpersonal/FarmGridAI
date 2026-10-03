# FarmGrid AI — Implementation & Audit Status

Status report generated at the end of the implementation audit against
[`solution.txt`](../solution.txt). All statements below were verified by running
Django checks, the migration check, full route/schema generation, the e2e smoke
flow and the pytest suite.

## Verification summary

| Check | Result |
| --- | --- |
| `manage.py check` | 0 silenced (no issues) |
| `manage.py makemigrations --check --dry-run` | No changes detected |
| `manage.py migrate --check` | No changes detected |
| API route enumeration | 62 named routes; every route reverses and resolves back to itself |
| OpenAPI schema (`manage.py spectacular`) | Generates; only cosmetic "unable to guess serializer" notes for plain APIViews |
| Templates / static files | All 17 templates + 6 CSS/JS files are empty placeholders (0 bytes) — per the "no UI content" constraint |
| Test suite | **201 tests pass** (baseline 172 incl. 70 pre-existing + 102 data-ingestion + 29 new P0-fix regression/contract tests) |

## Audit findings fixed in this pass

1. **URL collision — RecommendationsListView was unreachable.**
   `apps/subsidies/urls.py` mounted `farms/<id>/recommendations` on
   `SubsidyRecommendationsView`, the same path as `RecommendationsListView`.
   Because subsidies was included first, the recommendations list view was
   shadowed. Moved the subsidy routes under a `subsidies/` prefix
   (`subsidies`, `subsidies/<scheme_id>`, `farms/<id>/subsidies/match`,
   `farms/<id>/subsidies/recommendations`, `farms/<id>/subsidies/checklists`)
   matching the spec, and renamed the recommendations engine endpoint
   `/generate` → `/run` per spec (`apps/recommendations/urls.py`).

2. **Equipment image upload crashed on every upload**
   (`apps/equipment/views.py`). It passed an `UploadedFile` into
   `reencode_image()` (bytes-only), unpacked its single `bytes` return as a
   `(bytes, mime)` tuple, and called `sniff_mime()` on a file object — any real
   image produced a 500. The endpoint now: validates size + extension + MIME
   before reading, re-encodes the raw bytes (EXIF-stripped, JPEG), stores
   sanitized bytes via `ContentFile` with SHA-256, width/height and the actual
   stored MIME, and returns a 400 for every invalid upload.

3. **`generate_machinery_recommendation(None, …)` crashed with TypeError.**
   The missing-usage guard sat below `calculate_equipment_utilization_score()`,
   which divides by the `None` first, making the guard dead code. Moved the
   guard up so `gather_more_information` is returned.

4. **Finance estimate contract was incomplete.**
   `calculate_buy_vs_rent`, `calculate_repair_vs_replace`,
   `calculate_machine_affordability` and `generate_machinery_recommendation`
   lacked `limitations` and `requires_official_verification`.
   `calculate_machine_affordability` lacked `data_confidence`. Added all of
   them; `requires_official_verification` is `True` whenever a subsidy amount
   is involved (buy-vs-rent, machinery recommendation).

5. **`ProfileCompleteness.score` crashed** on `FarmerProfile.crops` (no such
   relation), silently downgrading every recommendation's completeness signal
   to the `score=0.0` fallback. Now queries the real
   `FarmCrop` records for the user's farms and returned usable scores
   (`apps/accounts/services.py`).

6. OpenAPI/`registered` test-only: added contract tests (below) that make all
   of the above permanent regressions checks.

## P0 fixes from the final release audit (2026-09-25, all verified green)

7. **`Farm.all_objects` was a broken method reference** — `all_objects` pointed
   at the method instead of a real manager, so any "include deleted" query
   crashed. Added `AllObjectsManager` and bound `all_objects = AllObjectsManager()`
   (`apps/core/models.py`).
8. **Equipment operating-cost estimator crashed for real usage dicts**
   (`apps/equipment/services.py`): the annual total was passed as a dict into a
   parameter expecting an `EstimateRange`, raising
   `'dict' object has no attribute 'minimum'`. The estimator now rebuilds an
   `EstimateRange` from the computed annual totals. Zero-fuel cost cases
   (electric/solar) were already handled.
9. **`cost_per_hectare` raised `TypeError` on Decimal vs float** in
   `apps/expenses/services.py` (mixed `float`/`Decimal` division). Now coerces
   hectares with `float()`.
10. **Consents/language endpoints accepted non-boolean strings** as booleans
    (`"false"`/`"no"` were treated as truthy). All intake endpoints now use a
    strict helper `_strict_bool` (`apps/accounts/views.py`,
    `apps/data_ingestion/views.py`).
11. **Review-workflow publish could auto-publish** a queue row whose decision had
    not been explicitly approved by a human with recorded `decided_by` /
    `decided_at`. `publish()` now strictly requires `decision=APPROVED` AND a
    recorded human decision actor/timestamp, and raises `ReviewWorkflowError`
    otherwise (`apps/data_ingestion/services/review_workflow.py`). Subsidy
    publishes apply `_strict_bool` when reading `is_active`.
12. **Compliance evidence path used a per-process `hash()`** which changes every
    run and could produce filesystem-invalid names. `_evidence_dir` now uses a
    stable `base/compliance/<source.pk>` layout with a validated
    `_SAFE_RUN_ID` regex for run ids (`apps/data_ingestion/services/compliance.py`).
13. **HTTP client followed redirects without re-validating hosts** and could
    crash on a malformed `Content-Length`. Each redirect hop is now re-validated
    against the allowed hosts before following; unparseable Content-Length is
    treated as `ResponseTooLarge` (`apps/data_ingestion/services/http_client.py`).
14. **API middleware echoed arbitrary client-supplied request ids** and readiness
    leaked DB host/username. Request ids are now echoed only when they match
    `^[A-Za-z0-9._:-]{1,64}$`; the readiness probe redacts database errors to
    `"database unavailable"` (`apps/core/middleware.py`, `apps/api/views.py`).
15. **Subsidies `ProfileContext` ignored `income_farm`** (only `yearly_farm_income_min`
    was mapped). Added the `income_farm → yearly_farm_income_min` mapping
    (`apps/subsidies/services.py`).
16. **Finance affordability crashed on `annual_income=None`** and used a raw
    `None` EMI. `calculate_machine_affordability` now returns an honest
    unaffordable verdict with `data_confidence="low"` for missing/zero income,
    and `proposed_emi = proposed_emi or 0`
    (`apps/finance/services.py`).
17. **Duplicate CAPTCHA hint key** in the compliance home-region hints was fixed
    (`apps/data_ingestion/services/compliance.py`).
18. **3 new system endpoints** added with no secrets/paths/hostnames exported:
    `GET /api/v1/system/capabilities`, `GET /api/v1/system/model-status`,
    `GET /api/v1/system/data-source-status` (`apps/api/views.py`, `apps/api/urls.py`).
    OpenAPI regenerated (`openapi.yaml`) with the new paths; the remaining 346
    schema warnings are the pre-existing "unable to guess serializer" notes for
    utility APIViews (74 unique), not regressions.

## Module status

### Complete, deterministic (no external dependencies)

- **Auth & accounts** — JWT register/login/logout, profile, consents,
  language preference, profile-completeness scoring.
- **Farms** — CRUD, parcels, summary, land-unit conversion, regional bigha
  rules (refuses to guess when no rule exists).
- **Crops** — catalog + per-farm input-cost estimates (range-based,
  benchmark sourced).
- **Expenses** — typed expenses (electricity, fuel, labour, transport, rental,
  inputs), documents (PDF/image upload with size/extension validation),
  monthly summary, anomaly analysis.
- **Energy** — pump profile, solar-vs-grid-vs-diesel comparison,
  solar configuration, projections, tariff/diesel benchmarks.
- **Finance** — EMI, ownership vs rental, repair vs replace affordability,
  machinery decision engine — all range-based with assumptions, limitations,
  warnings, confidence and verification flags.
- **Subsidies** — scheme catalog, eligibility rule engine, match, checklists;
  always "preliminary, verify officially".
- **Recommendations** — rule-first engine producing explainable, persisted
  recommendations with evidence + assumptions + limitations.
- **Chatbot** — deterministic, sourced knowledge-base engine with intents and
  citations; LLM layer is gated behind `uses_llm` and optional.
- **Equipment** — catalog, categories, farmer CRUD, image upload (validated +
  sanitized), operating-cost estimator.
- **Data ingestion & dataset enrichment** (`apps/data_ingestion/`) —
  compliance-first intake engine: source registry (human-approval gated),
  robots.txt/terms compliance checks with stored evidence, rate-limited
  downloader, SHA-256 dedup, image-quality gates, provenance tracing,
  review/publish workflow (guarded writes to `SubsidyScheme` / benchmarks /
  `EquipmentCatalog`), leakage-safe staging-dataset builder with versioned
  manifest, REST API + 8 management commands + 7 operator scripts. Network is
  **off by default**; automation never approves a source and never auto-
  overwrites a verified/active domain value.

### Model-dependent modules (graceful fallback today)

- **Vision classifier** (`apps/ml_engine/vision/classifier.py`) — real CNN
  inference is now **live**: a trained MobileNetV3-Large brand classifier is
  registered and active. Inference lazily loads the artifact, verifies the
  sha256 checksum, runs CPU/CUDA-safe top-k softmax, applies the unknown
  threshold (0.55) and records a `PredictionAuditLog` row. Without a valid
  artifact it returns `unknown` with `source="fallback"` and does not pretend a
  prediction happened.
- **OCR** (`apps/ml_engine/ocr/__init__.py`) — uses `pytesseract` when
  available, otherwise a heuristic provider; output is always evidence only.
- **Expense forecast / anomaly** — sklearn-based when models are trained;
  otherwise deterministic rules/naive baselines.
- **Recommendation ranker** — classical ML ranker optional; engine runs purely
  on policy rules without it.
- Every prediction routes through `log_prediction()` in
  `apps/ml_engine/registry.py` with model name/version/input-hash/audit row, so
  fallback usage is fully transparent.

### Environment-dependent

- **Celery** — not installed; import is guarded and background tasks run
  eager/in-process in development (`CELERY_TASK_ALWAYS_EAGER`).
- **Email/SMS** — not wired; `EMAIL_BACKEND` still Django's default.

## Remaining real-world data integrations before production

- **Subsidies**: per-scheme official rates, application portals, document
  requirements and state/district eligibility must be synchronized from
  government sources; the platform only does preliminary matching.
- **Machinery prices & rentals**: current dealer quotes and regional rental
  markets are needed to tighten buy-vs-rent and repair-vs-replace ranges.
- **Energy inputs**: live electricity tariffs and diesel/solar-cost benchmarks
  need periodic official updates.
- **Equipment marketplace**: catalog contains brands/models/images from scraped
  data; per-model prices are intentionally not fabricated — connect to a
  price feed to move beyond category benchmarks.
- **Vision/OCR**: the classifier artifact is **trained and active** (see below).
  Remaining: more labeled images per brand to push macro-F1 higher, and a
  tesseract-capable deployment to upgrade OCR from heuristic to model inference.

## Vision dataset preparation (Option A — completed) + CNN training

### Dataset (top-6, local data only)

Prepared a **top-6 tractor-brand classifier dataset** **without scraping any
new site**. Everything is derived from the existing
`../open-tractor/data/tractor_dataset.json` + `../open-tractor/tractor_images/`.

| Script | What it does |
| --- | --- |
| `scripts/download_dataset_images.py` | Optional full-res re-download of the **existing** `img_url` list from the existing CDN host; strips Cloudflare `/cdn-cgi/image/...` resize options; respects robots.txt (skips disallowed paths), rate limits + retries, records downloaded source URL, refuses new domains. |
| `scripts/build_classifier_dataset.py` | Join → sanitize → exclude → SHA-256 dedup → brand normalization → **top-6 + `other`** → dHash near-dup grouping → grouped stratified split → train/val/test + report CSVs/JSON. |
| `scripts/train_equipment_classifier.py` | MobileNetV3-Large transfer-learning trainer (weighted CrossEntropy, train-only augmentation, early stop on val macro-F1, seed 42, writes all artifacts + checksum + metadata, evaluates on held-out test only). |
| `scripts/evaluate_equipment_classifier.py` | Standalone held-out test evaluation; refuses to run unless the artifact sha256 verifies. |

Results (`../open-tractor/data/tractor_brand_dataset/`):

| Metric | Value |
| --- | --- |
| Dataset records | 2,098 |
| Retained images | **1,803** |
| train / val / test | 1,444 / 180 / 179 (80.1 / 10.0 / 9.9 %) |
| Duplicates removed (SHA-256) | 108 |
| Excluded total | 681 (168 UI asset, 386 unmapped, 15 <200px, 4 empty path, 0 corrupt, 0 missing) |
| Near-dup groups spanning >1 split | **0** |
| Image source domain | `images.tractorgyan.com` only |
| Classes | Mahindra, Sonalika, Farmtrac, John Deere, New Holland, Powertrac, `other`; `unknown` is an inference fallback label with no images |

Class imbalance (max/min, non-empty `other`): 18.0× overall (`other` 1,208 vs
Powertrac 67); 2.3× among the 6 named classes (Mahindra 154 vs Powertrac 67).

Reports written: `dataset_manifest.csv`, `class_distribution.csv`,
`duplicates_removed.csv`, `excluded_images.csv`, `labels.json`,
`dataset_metadata.json`, `dataset_quality_report.md`.

### Training run (real CNN)

| Metric | Value |
| --- | --- |
| Architecture / transfer | `mobilenet_v3_large`, ImageNet1K_V2 weights, fine-tuned |
| Run config | epochs ≤25 (early stop at 19), patience 5, lr 3e-4, batch 16, AdamW wd 1e-4, seed 42, weighted CrossEntropyLoss |
| Best epoch (val macro-F1) | 14 — **0.7458** |
| Test accuracy / balanced acc / top-3 | **0.810 / 0.693 / 0.983** |
| Test macro-F1 / weighted-F1 | **0.7316 / 0.8002** (179 held-out images) |
| Unknown threshold | 0.55 (max softmax below ⇒ `unknown`, low confidence) |
| Activation gate | macro-F1 0.7316 ≥ 0.70 → **registered & marked active** |
| Artifacts | `FarmGridAI/data/models/equipment_classifier/equipment_classifier_mobilenetv3_top6_v1.{pt,_labels,_metadata,_metrics,_confusion_matrix,_confusion_matrix_normalized,_classification_report,_training_history,_checksum,_eval_report}` |

Per-class test results (precision/recall/F1, n): Farmtrac 1.000/0.750/0.857 (8),
John Deere 1.000/0.857/0.923 (7), Mahindra 0.500/0.667/0.571 (15),
New Holland 1.000/0.571/0.727 (7), Powertrac 0.714/0.833/0.769 (6),
Sonalika 0.800/0.267/0.400 (15), other 0.840/0.909/0.873 (121).

Weakest axes: Mahindra↔other confusion (10 Mahindra test images classified as
`other`), Sonalika's low recall. Repeatable with
`python scripts/train_equipment_classifier.py --dataset-dir "<…>/tractor_brand_dataset" --output-dir "data\models\equipment_classifier"`.

## Safe data ingestion & dataset enrichment (`apps/data_ingestion/`)

Compliance-first intake of subsidy/benchmark/equipment data + images, built so no
automated step can touch the network or impact live data without a human.

### Pipeline (every gate is human-driven)

| Stage | Mechanism |
| --- | --- |
| Register source | `register_source` / API `POST /sources/` → `pending` |
| Compliance check | `run_compliance_check` fetches robots.txt + terms (RFC 9309 via stdlib `urllib.robotparser`), stores raw evidence + SHA-256; offline/net-disabled ⇒ `manual_review` with reason |
| Approve | admin action / command `--approve --user <human>`; sets `approved_by` + `collection_enabled` (never auto) |
| Collect / import | `collect_source` (dry-run default; real run needs `DATA_INGESTION_NETWORK_ALLOWED=true`), `download_url` rate-limited + size-capped + redirect-limited; `import_manual_dataset` is fully offline and manual_import-only |
| Validate | MIME/decode, min-dimension (320px), Laplacian blur, dark/bright, UI-icon/text-heavy heuristics, PII-key rejection (hard personal/credential keys block; soft contact keys warn), HTTP(S)-only URLs |
| Dedup | SHA-256 byte dedup + dHash/Hamming near-duplicate grouping |
| Review | `DataReviewQueue` is the only path into domain tables: `approve` / `reject` / `publish` (admin or API), human actor recorded |
| Publish guards | `review_workflow`: subsidy publishes are always `is_illustrative=True` + `needs_official_verification=True`, `source_url` preserved, **verified/active values never overwritten**; rollback only deactivates, never deletes |
| Dataset build | `build_staging_dataset` partitions **by whole source-URL groups** (no leakage across train/val/test), writes `manifest.json` with sha256 + provenance per entry; it proposes — it never retrains or mutates model artifacts |

### Module pieces

- **Models** (migration `0001_initial`): `DataSource`, `SourceComplianceCheck`,
  `IngestionRun`, `CollectedArtifact`, `ExtractedRecord`, `DataReviewQueue` — all
  UUID-keyed via `apps.core.models.BaseModel` (audit + soft delete).
- **Services** (`services/`, 23 modules): urlutils, hashing, http_client,
  robots, terms, compliance, source_registry, downloader, validation,
  deduplication, provenance, image_validation, image_collector,
  review_workflow, record_factory, scheme/benchmark/equipment-catalog ingestion,
  document/html/pdf parsers, dataset_enrichment, planner.
- **API** (`/api/v1/data-ingestion/`, staff-gated): sources (+ `compliance`,
  `collect`), runs, artifacts, records, review-queue
  `approve`/`reject`/`publish`, manual import, dataset report, provenance report.
- **Commands**: `register_source`, `check_source_compliance`, `collect_source`,
  `import_manual_dataset`, `validate_ingested_data`, `build_equipment_dataset`,
  `generate_ingestion_report`, `cleanup_unapproved_data` (quarantine, no deletes),
  `register_official_sources` (provisioning, idempotent),
  `import_manual_documents` (offline PM-KUSUM official-document ingest,
  manifest-driven), `mnre_compliance_review` (host-locked MNRE compliance-only
  review, ≤ 5 requests, no PDFs, no publish).
- **Scripts** (`scripts/`): `check_source_compliance.py`,
  `collect_approved_source.py`, `import_approved_images.py`,
  `build_equipment_dataset.py`, `validate_dataset_quality.py`,
  `generate_data_provenance_report.py`, `export_review_queue.py` — dry-run by
  default; collection additionally requires `DATA_INGESTION_NETWORK_ALLOWED=true`.

### Test coverage (102 data-ingestion tests + 29 new P0 regression/contract tests; suite now 201)

robots parsing, compliance decision matrix (incl. offline⇒manual_review,
terms-required-for-allow, manual_import path), source registry lifecycle,
download/canary URL guards, image-quality gates (valid/blurry/dark/bright/reject),
manual import + duplicate bytes skipped, SHA-256 + perceptual-hash dedup,
provenance report structure, review/publish guards (illustrative subsidy,
never-overwrite-verified, rollback deactivates), API permissions + endpoint
contracts, and always-on dry-run behavior, plus 20 new tests for the offline
PM-KUSUM/MNRE manual-import pipeline and the host-locked MNRE compliance review.

Dev fixtures ship 11 **pending / manual-review placeholder sources** — verified
not pre-approved, so collection and publishing are never accidentally enabled.

### Provisioned official sources (all manual-review, collection disabled)

`python manage.py register_official_sources` (idempotent) registered 14 real
official sources as `manual_review` + `collection_enabled=False`, stored base URL
+ derived robots.txt URL, ran an **offline** compliance check per source
(`run_id=provision-official`), and emitted the required **source compliance
report** (JSON + Markdown; every policy field mandated by intake) at
`data/ingested/reports/source_compliance_report(.md/.json)`. Verified: 14
sources, 0 policy violations (no auto-approval, collection off, no robots
fetched). Sources: PM-KUSUM, MNRE, MoA&FW, SMAM (login-gated DBT, high risk),
MP Agriculture (HTTP-only, high risk), MPUVN renewable, MPERC tariff, DES cost
of cultivation, and Mahindra / Sonalika / Farmtrac / John Deere India / New
Holland India / Powertrac specification sites (copyrighted imagery ⇒ manual
import recommended). Everything stays pending until an operator approves each
source; no collection performed.

### First approved live dry-run (PM-KUSUM) — compliance blocked, no collection

The operator approved a limited compliance review + sandboxed dry-run for the
PM-KUSUM portal. The live compliance review ran with network enabled for that
single run (`approved_dry_run_source`, operator `green`, host-locked to
`pmkusum.mnre.gov.in`, HTTPS-only, >= 5 s pacing, <= 5 pages, <= 20 MB).
Result: **block** — 0 artifacts, 0 extracted records, 0 review-queue rows.
`https://pmkusum.mnre.gov.in/robots.txt` returns HTTP 200 but serves the
portal's SPA HTML (`Content-Type: text/html`, 24001 bytes, no `User-agent`
directives), i.e. **no parseable robots.txt exists** — treated as
unavailable/ambiguous, so nothing was collected. Full report +
preserved robots evidence (SHA-256 `a32fc270…c84279b`):
`data/ingested/reports/pmkusum_approved_dry_run_20260925_131235/`.
Recommendation recorded: manual import of the official public PM-KUSUM
guideline documents. The run also surfaced + fixed a latent
`SafeHTTPClient` host-approval bug (full base URLs in `allowed_hosts` were
compared raw against hostnames; now normalized via
`urlutils.hostname_allowed`) — locked by a regression test.

Remaining real-world integration: approval + verified terms/robots evidence for
real government/manufacturer domains, licensing notes for any published images,
and a human triage team to work the review queue before any staging dataset is
used to retrain.

### Offline manual import of official PM-KUSUM documents (per operator approval)

PM-KUSUM web collection is **permanently stopped** per operator instruction. The
operator-approved path is now a fully offline, manifest-driven manual import:

- **Command** `import_manual_documents --folder <data/imports/pmkusum_official>
  --operator-user <human>`; it **refuses to run** while
  `DATA_INGESTION_NETWORK_ALLOWED=true` (no internet, ever). Source identity is
  configurable (`--source-name` / `--source-base-url` / `--organization`,
  defaulting to the PM-KUSUM manual source), so the same pipeline serves the
  MNRE manual source (`mnre_official` import dir registered; source
  `MNRE Official Documents (manual import)`, `manual://mnre-official-documents`,
  `manual_review`, collection off — `run-a5b776b4d9b7`).
- Import directory `DATA_INGESTION_IMPORT_DIR` defaults to
  `data/imports/pmkusum_official/`. Each PDF requires a sibling
  `<stem>.manifest.json` (document_title optional, `source_url` HTTPS-only,
  `source_organization`, `retrieval_date` ISO not in future,
  `source_attribution`, `permission_license_note`; optional
  `expected_sha256`/`expected_size_bytes`).
- Per-document validation: extension, MIME magic, PDF integrity (pypdf), file
  size, SHA-256 (cross-checked against manifest), duplicate status, source URL
  scheme, retrieval date, attribution + license note.
- Originals are stored byte-identical as raw `CollectedArtifact`s
  (hash-named PDF under `data/ingested/<run_id>/pdf/`). SHA-256 duplicates are
  skipped and reported (never re-stored).
- After validation only, text is extracted and **only 9 whitelisted fields** are
  captured verbatim (scheme name/component, official eligibility/benefit/
  document-requirements/application-procedure wording, effective date,
  amendment/version info, official source URL). No eligibility/benefit amounts,
  percentages, costs or dates are ever inferred; absent fields stay empty.
- Every record lands in `DataReviewQueue` flagged
  `preliminary` + `requires_official_verification` + `requires_human_review`;
  **nothing is published** and source stays `manual_review`,
  `collection_enabled=false`.
- **Online source verification** (operator-granted, opt-in `--verify-online`,
  gated on `DATA_INGESTION_NETWORK_ALLOWED=true`): uses the **exact manifest
  URLs only** (`document_url`, `source_url`, optional
  `official_reference_url` — at most one request each, HTTPS only, official
  government domains `.gov.in/.nic.in`, no robots.txt, no crawling, no
  retries). PDF URLs are verified without reading their bodies; HTML pages are
  read to a small cap to cross-check the stated title / filename / hash and
  public-download signals. Failed/blocked checks mark online verification
  `unavailable`, add a limitation and keep `requires_human_review` — a valid
  local document is never rejected because online verification failed.
- **Twelve reports** under `data/ingested/reports/manual_import_<ts>/`: import
  validation, raw artifact/provenance, PDF integrity + checksum, manifest
  validation, online source-verification, extraction summary, duplicate
  report, review-queue export, fields requiring manual verification, records
  not safe to publish, documents with unavailable/failed online verification,
  and a final import status report that separates locally verified /
  manifest-declared / online-verified / extracted-unreviewed /
  human-review-required / not-for-recommendations facts and runs an end-of-run
  safety checklist (import-dir snapshot proves originals unchanged and no new
  files; live-table counts prove nothing was published). Source:
  `manual_import` / `manual://pmkusum-official-documents`; offline compliance
  decision `manual_review`.

Tests: 24 (validation accept/reject matrix, manifest requirements, extraction
whitelist + no-inference, command happy path, duplicate handling, missing
manifest, network-enabled refusal, custom MNRE-style source isolation,
document_url/official_reference_url validation, caveats extraction,
verify-online gating, blocked-verification-without-rejection).

### MNRE compliance-only review (per operator approval) — blocked

Operator approved a host-locked compliance-only review of `https://mnre.gov.in/`
(≤ 5 requests, ≥ 5 s pacing, no PDF downloads, no data collection/extraction, no
publish). Outcome `mnre_compliance_review`:

- **robots.txt result** — `https://mnre.gov.in/robots.txt`: HTTP 200, real
  robots (67 bytes, `User-agent: *` / `Disallow: /wp-admin/` /
  `Allow: /wp-admin/admin-ajax.php`), unambiguous, **root path allowed**
  (SHA-256 `9311bab3…7acab7`, preserved with homepage in
  `data/ingested/compliance/…/_898039/run-70e17d7dcb4b/`).
- **target-path permission result** — evaluated 0 paths: review stopped at the
  gateway wall before permission assessment (nothing further downloaded).
- **policy/terms URL result** — not fetched (stopped at the wall; not required
  to reach a decision).
- **login/CAPTCHA/paywall detection** — `login_required_detected: true`,
  `captcha: false`, `paywall: false`; notes: `login/registration wall detected`.
  The homepage is a WordPress/S3WaaS portal and its markup carries **Parichay
  Single Sign-On login machinery**
  (`wp-content/mu-plugins/parichay-sso/…/login.css`), i.e. credential-gated areas
  exist on the domain and public-vs-gated content cannot be safely
  distinguished, which the approved scope excludes.
- **collection-risk assessment / recommendation** — **BLOCKED** (gateway wall);
  stop. Source left in `manual_review` with `collection_enabled=false`; no PDFs
  downloaded, no records extracted, nothing published. 4 requests total (all
  within budget, all to `mnre.gov.in`). `SourceComplianceCheck` row persisted
  (`run-70e17d7dcb4b`) with the real evidence path.
- Recommended downstream action for MNRE data: **manual import preferred**

### Django integration

- `EquipmentClassifier` (`apps/ml_engine/vision/classifier.py`) lazy-loads the
  artifact, verifies the sha256 checksum, loads labels + metadata, runs the same
  CPU-safe preprocessing as training, returns top-k predictions, applies the
  unknown threshold, and labels confidence low/medium/high. It never downloads
  anything during a request; any failure falls back to `source="fallback"`.
- `EquipmentImagePrediction` gained honest ML fields via migration
  (`predicted_brand`, `used_ml`, `confidence_label`, `top_predictions`,
  `unknown_threshold`, `artifact_available`). `predicted_class` stays an
  equipment kind (`tractor` for the six brands, `unknown` otherwise); the brand
  is stored separately in `predicted_brand`.
- `python manage.py register_equipment_model` registers `MLModelRegistry` +
  `MLModelVersion` and only activates when the gate passes (artifact present,
  checksum valid, test macro-F1 ≥ 0.70, labels/metadata consistent, inference
  smoke test OK). The analyze endpoint surfaces `used_ml`, `model_name`,
  `model_version`, `artifact_available`, `top_predictions`, `confidence_label`,
  `unknown_threshold`, `source` and `limitations`.

Honesty constraints observed:
- **No new sites scraped/accessed.** Single existing CDN domain.
- No CAPTCHA / login / robots.txt bypass.
- Test metrics are reported from the **held-out test split only**; val/train
  numbers are never relabeled as test metrics.
- `needs_user_confirmation` is always true; the classifier only states brand
  category and never claims model/year/mileage/engine health/repair history.
- Images are only used to prepare/train a dataset; licensing of the scraped
  images is unverified, so redistribution/disclosure remains an open issue.
- **Finance**: bank loan tenors/rates and income verification to replace the
  assumed default figures.
- **Chatbot LLM layer**: an API key + guardrails to enable `uses_llm`.
- **Ops/security**: production `SECRET_KEY` (≥32 bytes), HTTPS, rate limiting,
  email/SMS delivery, structured logging, backup of audit tables.

## Runbook

```powershell
python -m pytest                 # 201 tests
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py spectacular --file openapi.yaml
python app_smoke.py              # (see temp e2e smoke under tool temp dir)
```
