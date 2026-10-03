# FarmGrid AI

A Django-based farm financial advisory platform. It helps smallholder farmers
understand **crop input costs, equipment buying-vs-hiring, solar irrigation
economics, subsidy eligibility, energy expenses and expense anomalies** — with
every estimate delivered as an *explainable range*, never a hard claim.

Every figure carries a confidence level and a stated assumption.

## Stack

- Python 3.14, Django 6.1, Django REST Framework
- JWT auth (`simplejwt`), live `drf-spectacular` OpenAPI schema at `/api/schema/`
- scikit-learn (optional at runtime — graceful fallbacks), PyTorch optional
- Celery optional (tasks run eager/synchronous in development)
- SQLite by default (PostgreSQL-ready project layout)

## Quick start

```powershell
git clone <your-repo-url>
cd <repo>
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_platform      # benchmarks, schemes, knowledge base, catalogue

.\run.ps1                          # http://127.0.0.1:8000  (add -DemoUser for a login)
```

| Script | What it does |
| --- | --- |
| `run.ps1` | Starts the app locally. Backend and frontend are **one** process: Django serves the templates and static files from the same origin as the API, so there is no `npm install` and no separate dev server. |
| `run_live.ps1` | Publishes to a public `https://*.trycloudflare.com` URL through a Cloudflare tunnel. See the warning it prints before exposing a development server. |
| `verify.py` | End-to-end verification against a real HTTP surface. |
| `docs/` | Reference documentation - structure, API inventory, model card, tech stack. |
| `render.yaml` | Render blueprint. One container serves the API, the pages and the static files - see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md). |

## Setup

```powershell
# from the repository root
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_platform                # benchmarks, schemes, knowledge base, tractor catalog
python manage.py runserver
```

The web UI is API-first (`/api/v1/...`); Django admin is available at `/admin/`.

## Environment & settings

- Settings modules: `FarmGridAI.settings.base` + `.development` / `.production`
- Default invocation: `python manage.py` uses `.development` (via `DJANGO_SETTINGS_MODULE`)
- Celery is **optional**. `apps/api/tasks.py` and `FarmGridAI/__init__.py` guard
  the import; in development all background work runs in-process (`CELERY_TASK_ALWAYS_EAGER`).

## Seeding data

`seed_platform` is idempotent and loads:

| File | Destination |
| --- | --- |
| `data/seed/equipment_categories.json` | `EquipmentCategory` (benchmark price/HP/fuel ranges) |
| `data/seed/equipment_catalog.json` | `EquipmentCatalog` (brand/model/image from scraped tractorgyan data, **no invented prices**) |
| `data/seed/crop_cost_benchmarks.json` | `Crop` + `CropCostBenchmark` |
| `data/seed/bigha_rules.json` | `BighaConversionRule` (regional, unverified) |
| `data/seed/subsidy_schemes.json` | `SubsidyScheme` + rules + documents |
| `data/seed/knowledge_base.json` | `KnowledgeIntent` + `KnowledgeArticle` |
| `data/seed/energy_benchmarks.json` | tariff / diesel / solar-cost benchmarks |

`scripts/build_equipment_catalog.py` regenerates the catalog from
`../open-tractor/data/tractor_dataset.json` (sanitizes brands/models, drops
logo/duplicate rows, keeps original CDN image URLs).

### Vision dataset prep + CNN training (no new scraping)

Scripts prepare a **top-6 tractor-brand CNN dataset** strictly from existing
local data — **no new sites are accessed or scraped**:

| Script | Purpose |
| --- | --- |
| `scripts/download_dataset_images.py` | Re-download full-res originals of the *existing* `img_url`s from the existing CDN host (`images.tractorgyan.com`), stripping Cloudflare `/cdn-cgi/image/...` resize options. Skips robots-Disallowed URLs, rate-limits with jitter + retry, records each downloaded source URL, never contacts a new domain. |
| `scripts/build_classifier_dataset.py` | Joins `tractor_images/` ↔ `tractor_dataset.json` by `local_image_path` basename; excludes UI assets / <200 px / corrupt / missing files; SHA-256 dedup; normalizes brands (John → John Deere, etc.); builds **top-6 brands + `other`**; groups near-duplicates via perceptual dHash and does **grouped stratified splits**; writes `train/val/test/` folders + manifests/reports. |
| `scripts/train_equipment_classifier.py` | Trains a `mobilenet_v3_large` classifier (ImageNet pretrained, weighted CrossEntropyLoss for imbalance, train-only augmentation, early stop on validation macro-F1, patience 5). Evaluates on the **held-out test split only**, writes 9 artifact files + metadata + sha256 checksum. |
| `scripts/evaluate_equipment_classifier.py` | Re-run evaluation on the held-out test split; refuses to run unless the artifact checksum verifies. |

Dataset output: `../open-tractor/data/tractor_brand_dataset/` (1,803 retained
images; train 1,444 / val 180 / test 179; 108 duplicates removed; 681 excluded;
**0 near-duplicate groups span more than one split**). Classes: Mahindra,
Sonalika, Farmtrac, John Deere, New Holland, Powertrac + `other`. `unknown`
class exists in the label mapping but never appears in images (it is an
inference-time fallback only).

Model artifacts (<code>FarmGridAI/data/models/equipment_classifier/</code>):

| Artifact | Value |
| --- | --- |
| Architecture | MobileNetV3-Large (ImageNet transfer learning) |
| Test accuracy / balanced / top-3 | 0.810 / 0.693 / 0.983 |
| Test macro-F1 / weighted F1 | 0.7316 / 0.8002 |
| Early stop | epoch 19, best val macro-F1 0.7458 (epoch 14) |
| Activation gate (macro-F1 ≥ 0.70) | **passed — registered active** |
| Unknown threshold | max softmax < 0.55 → `unknown`, farmer confirmation required |

The classifier is **opt-in**: Django inference loads the artifact lazily,
verifies the sha256 checksum, runs CPU/CUDA-safe top-k softmax inference and
never downloads anything at request time. If the artifact is missing or its
checksum mismatches, every request falls back to `source="fallback"` with
`used_ml=false` and a full audit row.

Full quality report: `../open-tractor/data/tractor_brand_dataset/dataset_quality_report.md`.

Dataset constraints honored:
- Single source domain, no new downloads/scraping.
- No CAPTCHA/login/robots bypass; robots.txt checked on the CDN host.
- Source URLs preserved per image; images are SHA-256 keyed.
- Vision/OCR outputs always set `needs_user_confirmation: true`.

### Safe data ingestion & dataset enrichment (`apps/data_ingestion/`)

A **compliance-first** web-data collection + dataset-enrichment pipeline. It can
ingest subsidy/benchmark/equipment text and images, but only from **approved**
sources, never bypassing robots.txt/login/CAPTCHA/paywalls, and nothing reaches a
live domain table or training dataset without human review.

Key workflows (all human-gated):

| Step | How |
| --- | --- |
| Register a source | admin, `register_source`, or `POST /api/v1/data-ingestion/sources/` — starts `pending` |
| Check compliance | `check_source_compliance` command/CLI or API — fetches robots.txt + terms (offline ⇒ `manual_review`), saves evidence + hash |
| Approve | admin action or `compliance` command `--approve` by a **human actor**; sets `collection_enabled` |
| Collect | `collect_source` command / `collect_approved_source.py` / API `collect` — downloads, validates (MIME, min-dim, blur, brightness, UI-icon/text-heavy), SHA-256 dedups, stores raw bytes |
| Manual import | `import_manual_dataset` / `import_approved_images.py` / API — offline, requires an approved `manual_import` source |
| Review | data-`ingestion` API review-queue endpoints or admin actions (`review_workflow`) — approve/reject/publish |
| Publish | `publish` enqueues → writes `SubsidyScheme`/benchmarks/`EquipmentCatalog` **guarded**: subsidy publishes are always illustrative + `needs_official_verification`, and never overwrite verified/active values |
| Build dataset | `build_equipment_dataset` / `build_equipment_dataset.py` — leakage-safe grouped split + versioned `manifest.json` (never retrains, proposal only) |

Data model: `DataSource` → `SourceComplianceCheck` / `IngestionRun` →
`CollectedArtifact` / `ExtractedRecord` → `DataReviewQueue` (the human gate
between intake and domain tables). Every step records audit events
(`khetsathi.audit`) and provenance (source history, artifact/record traces,
JSON + Markdown reports).

Network is **off by default** (`DATA_INGESTION_NETWORK_ALLOWED=false`): without it
every automated compliance/collection step is recorded as a `manual_review` /
dry-run instead of touching the wire. Development fixtures ship as 11
**pending / manual-review placeholder sources** — none are pre-approved; a human
must approve before any collection.

Management commands: `register_source`, `check_source_compliance`,
`collect_source` (dry-run by default), `import_manual_dataset`,
`validate_ingested_data`, `build_equipment_dataset`, `generate_ingestion_report`,
`cleanup_unapproved_data` (quarantines, never deletes).

Official sources are provisioned by `register_official_sources` (idempotent): it
registers the 14 real government / manufacturer sources (PM-KUSUM, MNRE, MoA&FW,
SMAM, MP Agriculture, MPUVN, MPERC, DES, and the Mahindra / Sonalika / Farmtrac /
John Deere India / New Holland India / Powertrac spec sites) as
**manual-review only** with collection disabled, stores their base URL + derived
robots.txt URL, runs an **offline** compliance check per source, and writes the
required **source compliance report** (JSON + Markdown, every field mandated by
the intake policy) to `data/ingested/reports/source_compliance_report(.md/.json)`.
No source is approved and no collection happens — those stay pending until an
operator explicitly approves each one.

Standalone operator scripts under `scripts/`: `check_source_compliance.py`,
`collect_approved_source.py`, `import_approved_images.py`,
`build_equipment_dataset.py`, `validate_dataset_quality.py`,
`generate_data_provenance_report.py`, `export_review_queue.py` (all default to
dry-run / read-only; collection still requires the env flag above).

API (staff-gated, mounted at `/api/v1/data-ingestion/`): sources CRUD +
`compliance` + `collect`, runs, artifacts, records, review-queue
`approve`/`reject`/`publish`, manual import, dataset report, provenance report.

### Honesty conventions

Everything that is not officially verified is explicitly flagged:
- All benchmark records have `is_verified=False` / `is_synthetic_benchmark=True`.
- Subsidy matches always carry `needs_official_verification: true` and a
  "preliminary matching only" message.
- Equipment vision/OCR outputs always set `needs_user_confirmation: true`.
- Bigha has **no universal size** — the platform uses regional rules and holds
  them in `BighaConversionRule` (state/district level), refusing to guess when no rule exists.

## Main API areas (`/api/v1/`)

- `auth/register`, `auth/login` (JWT)
- `farms/`, `farms/<id>/`, `land-units/convert`, `bigha-rules/`
- `farms/<id>/expenses/...`  — typed expenses, monthly summary, anomaly analysis
- `farms/<id>/equipment/...` — equipment CRUD, image upload, OCR + vision pipeline
- `farms/<id>/energy/...`    — solar vs grid vs diesel comparison
- `farms/<id>/subsidies/match`, `farms/<id>/subsidies/recommendations`, `farms/<id>/subsidies/checklists`
- `farms/<id>/recommendations/run`
- `chat/sessions`, `chat/sessions/<id>/ask` — deterministic, sourced chatbot
- `data-ingestion/sources`, `data-ingestion/sources/<id>/compliance|collect`,
  `data-ingestion/runs`, `data-ingestion/artifacts`, `data-ingestion/records`,
  `data-ingestion/review-queue` (+ `approve`/`reject`/`publish`),
  `data-ingestion/import`, `data-ingestion/dataset-report`, `data-ingestion/provenance`
- `auth/consents`, `auth/language` — strict-boolean consent & language preferences
- `api/health`, `api/readiness` (readiness redacts database internals)
- `system/capabilities`, `system/model-status`, `system/data-source-status` —
  safe metadata (no secrets, paths, hostnames)

## Testing

```powershell
python -m pytest
```

Tests cover land-unit conversion (incl. regional bigha), farm service invariants,
the subsidy rule engine, expense anomaly/forecast services, the recommendation
engine, chatbot intent/source behaviour, equipment image-upload validation,
the finance estimate contract, API route/reverse consistency, serializer-model
field parity, cross-farmer access isolation, the equipment-classifier CNN
(checksum/fallback/unknown-threshold/audit), dataset quality (no empty class
folders, no split leakage), ML-registry activation gates, and the data-ingestion
pipeline (robots parsing, compliance, source registry, download validation,
image quality gates, dedup, provenance, review/publish guards, API permissions
and endpoint contracts) — **201 tests**.

## Known limitations

- Scraped tractor data contains **brands/models/images only** — prices are
  intentionally left as category-level benchmarks, never fabricated per model.
- `tractors.json` (`₹`-only empty fields) and `tractor_gallery.json` (empty) were
  not usable for price extraction.
- Solar comparisons, tariffs and diesel prices are benchmark references —
  confirm current official rates before major spending.
- Data ingestion is **network-off by default**; collected images/schemes remain
  in a staging/review queue until a human approves and publishes them. The
  development "source registry" is example placeholders — no real government
  or manufacturer source is pre-approved.
- drf-spectacular logs "unable to guess serializer" for plain utility endpoints
  (health/readiness) — schema output is unaffected.
