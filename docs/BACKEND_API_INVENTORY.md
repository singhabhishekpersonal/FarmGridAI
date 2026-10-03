# Backend API Inventory

Autoritative inventory of the HTTP API exposed by FarmGrid AI under
`/api/v1/` (from `apps/api/urls.py` + included app routers; re-verified
2026-09-25). All routes reverse cleanly; the OpenAPI schema is regenerated from
this router via `python manage.py spectacular --file openapi.yaml`.

## Auth & account (`/api/v1/auth/`)

| Route | Name | Methods | Notes |
| --- | --- | --- | --- |
| `auth/register` | auth-register | POST | JWT register |
| `auth/login` | auth-login | POST | JWT login |
| `auth/logout` | auth-logout | POST | Revoke/blacklist refresh |
| `auth/profile` | profile | GET/PATCH | Farmer profile + completeness score |
| `auth/consents` | consents | GET/PUT | Consent preferences (strict booleans) |
| `auth/language` | language | GET/PUT | Preferred language (whitelisted codes) |

## Farms (`/api/v1/farms/`)

| Route | Name | Methods | Notes |
| --- | --- | --- | --- |
| `farms` | farm-list | GET/POST | CRUD list/create |
| `farms/<uuid>` | farm-detail | GET/PATCH/DELETE | Soft delete (recording `updated_by`) |
| `farms/<uuid>/land-parcels` | farm-land-parcels | GET/POST | Land parcels |
| `farms/<uuid>/summary` | farm-summary | GET | Aggregated farm summary |
| `land-units/convert` | land-unit-convert | POST | Unit conversion |
| `bigha-rules` | bigha-rules | GET | Regional bigha rules (refuses to guess) |

## Crops (`/api/v1/`)

| Route | Name | Methods | Notes |
| --- | --- | --- | --- |
| `crops` | crop-catalog | GET | Crop catalog (needs `slug`) |
| `farms/<uuid>/crops` | farm-crop-list | GET/POST | Farm crops |
| `farms/<uuid>/crops/estimates` | farm-crop-estimates | GET | Input-cost estimates (ranges) |
| `farms/<uuid>/crops/<uuid>/estimate` | farm-crop-estimate-detail | GET | Single-crop estimate |

## Equipment (`/api/v1/`)

| Route | Name | Methods | Notes |
| --- | --- | --- | --- |
| `equipment/categories` | equipment-categories | GET | Categories + benchmark ranges |
| `equipment/catalog` | equipment-catalog | GET | Catalog (no invented prices) |
| `farms/<uuid>/equipment` | farmer-equipment-list | GET/POST | Farmer-owned equipment CRUD |
| `farms/<uuid>/equipment/<uuid>` | farmer-equipment-detail | GET/PATCH/DELETE | Soft delete |
| `farms/<uuid>/equipment/<uuid>/images` | equipment-image-upload | GET/POST | Validated + sanitized image upload |
| `.../images/<uuid>/analyze` | equipment-image-analyze | POST | OCR + CNN brand estimate (needs user confirmation) |
| `.../operating-cost` | equipment-operating-cost | GET | Operating-cost estimate (ElectricRange) |

## Expenses (`/api/v1/`)

| Route | Name | Methods | Notes |
| --- | --- | --- | --- |
| `farms/<uuid>/expenses` | expense-list | GET/POST | Typed expense create/list |
| `farms/<uuid>/expenses/electricity` | electricity-bill | GET/POST/... | Electricity bill expenses |
| `farms/<uuid>/expenses/fuel` | fuel-expense | GET/POST/... | Fuel |
| `farms/<uuid>/expenses/inputs` | input-expense | GET/POST/... | Inputs |
| `farms/<uuid>/expenses/labour` | labour-expense | GET/POST/... | Labour |
| `farms/<uuid>/expenses/transport` | transport-expense | GET/POST/... | Transport |
| `farms/<uuid>/expenses/rental` | rental-expense | GET/POST/... | Rental |
| `farms/<uuid>/expenses/analysis` | expense-analysis | POST | Anomaly analysis (typed buckets) |
| `farms/<uuid>/expenses/summary` | expense-summary | GET | Monthly summary (bucketed, `cost_per_hectare` safe) |
| `farms/<uuid>/expenses/documents` | expense-document | GET/POST | PDF/image documents |

## Energy (`/api/v1/`)

| Route | Name | Methods | Notes |
| --- | --- | --- | --- |
| `farms/<uuid>/pump-profile` | pump-profile | GET/PUT | Pump profile |
| `farms/<uuid>/solar-configuration` | solar-configuration | GET/POST | Solar system config |
| `farms/<uuid>/energy/analyze` | energy-analyze | POST | Energy analysis |
| `farms/<uuid>/energy/solar-comparison` | solar-comparison | POST | Solar vs grid vs diesel (no phantom breakeven) |
| `farms/<uuid>/energy/projection` | energy-projection | POST | Cost projection |
| `energy/tariff-benchmarks` | tariff-benchmarks | GET | Tariff benchmarks |
| `energy/diesel-price-benchmarks` | diesel-price-benchmarks | GET | Diesel benchmarks |

## Finance (`/api/v1/`)

| Route | Name | Methods | Notes |
| --- | --- | --- | --- |
| `farms/<uuid>/income-profile` | income-profile | GET/PUT | Income profile |
| `farms/<uuid>/finance/buy-vs-rent` | buy-vs-rent | POST | Buy-vs-rent (estimate contract) |
| `farms/<uuid>/finance/repair-vs-replace` | repair-vs-replace | POST | Repair-vs-replace (estimate contract) |
| `farms/<uuid>/finance/affordability` | affordability | POST | Affordability (income-safe) |
| `farms/<uuid>/finance/machinery-decision` | machinery-decision | POST | Machinery decision engine |
| `farms/<uuid>/finance/scenarios` | finance-scenarios | POST/GET | Scenarios |

## Subsidies (`/api/v1/`)

| Route | Name | Methods | Notes |
| --- | --- | --- | --- |
| `subsidies` | subsidy-scheme-list | GET | Scheme catalog |
| `subsidies/<uuid>` | subsidy-scheme-detail | GET | Scheme detail |
| `farms/<uuid>/subsidies/match` | subsidy-match | POST | Preliminary eligibility match |
| `farms/<uuid>/subsidies/recommendations` | subsidy-recommendations | GET | Rule-first matches |
| `farms/<uuid>/subsidies/checklists` | subsidy-checklists | GET | Doc-requirements checklists |

## Recommendations (`/api/v1/`)

| Route | Name | Methods | Notes |
| --- | --- | --- | --- |
| `farms/<uuid>/recommendations` | recommendation-list | GET | Persisted recommendations |
| `farms/<uuid>/recommendations/run` | recommendation-run | POST | Run engine (explainable, persisted) |
| `farms/<uuid>/recommendations/<uuid>/explain` | recommendation-explain | GET | Evidence + assumptions |
| `farms/<uuid>/recommendations/<uuid>/feedback` | recommendation-feedback | POST | Feedback |
| `farms/<uuid>/opportunities` | cost-saving-opportunities | GET | Cost-saving opportunities |
| `farms/<uuid>/recommendation-runs` | recommendation-runs | GET | Run history |

## Data ingestion (staff-gated, `/api/v1/data-ingestion/`)

| Route | Name | Methods | Notes |
| --- | --- | --- | --- |
| `data-ingestion/sources` | data-ingestion-sources | GET/POST | Source registry (strict bools) |
| `data-ingestion/sources/<uuid>` | data-ingestion-source-detail | GET/PATCH | Patch coerces bool fields |
| `data-ingestion/sources/<uuid>/compliance-check` | data-ingestion-compliance | POST | robots/terms evidence + sha256 |
| `data-ingestion/sources/<uuid>/collect` | data-ingestion-collect | POST | Dry-run default; real run requires `DATA_INGESTION_NETWORK_ALLOWED=true` |
| `data-ingestion/sources/<uuid>/runs` | data-ingestion-source-runs | GET | Runs for a source |
| `data-ingestion/runs` | data-ingestion-runs | GET | All runs |
| `data-ingestion/runs/<uuid>` | data-ingestion-run-detail | GET | Run detail |
| `data-ingestion/artifacts` | data-ingestion-artifacts | GET/... | Raw artifacts |
| `data-ingestion/artifacts/<uuid>` | data-ingestion-artifact-detail | GET/... | Artifact detail |
| `data-ingestion/records` | data-ingestion-records | GET/... | Extracted records |
| `data-ingestion/records/<uuid>` | data-ingestion-record-detail | GET/... | Record detail |
| `data-ingestion/review-queue` | data-ingestion-review-queue | GET | Human gate rows |
| `data-ingestion/review-queue/<uuid>/approve` | data-ingestion-review-approve | POST | Human approve (records actor) |
| `data-ingestion/review-queue/<uuid>/reject` | data-ingestion-review-reject | POST | Human reject |
| `data-ingestion/review-queue/<uuid>/publish` | data-ingestion-review-publish | POST | Requires prior APPROVED + actor + timestamp |
| `data-ingestion/manual-import` | data-ingestion-manual-import | POST | Offline manual import |
| `data-ingestion/dataset-report` | data-ingestion-dataset-report | GET | Staging dataset report |
| `data-ingestion/provenance-report` | data-ingestion-provenance-report | GET | Provenance |

## Chat (`/api/v1/chat/`)

| Route | Name | Methods | Notes |
| --- | --- | --- | --- |
| `chat/sessions` | chat-session-create | GET/POST | Chat sessions |
| `chat/sessions/<uuid>/ask` | chat-ask | POST | Intent-based, sourced answers |
| `chat/sessions/<uuid>/messages` | chat-history | GET | Message history |

## System (`/api/v1/system/`) — added in final release

| Route | Name | Methods | Notes |
| --- | --- | --- | --- |
| `system/capabilities` | system-capabilities | GET | Safe capability flags (no secrets/paths/hostnames) |
| `system/model-status` | system-model-status | GET | ML registry/version aggregates (no artifact paths) |
| `system/data-source-status` | system-data-source-status | GET | Source counts by approval status |

## Health

| Route | Name | Methods | Notes |
| --- | --- | --- | --- |
| `health` | health | GET | Liveness |
| `readiness` | readiness | GET | DB readiness; redacts database internals (`"database unavailable"`) |

## Notes
- Router also exposes the Django admin at `/admin/` (out of API scope) and
  OpenAPI schema at `/api/schema/` (drf-spectacular), plus JWT token endpoints
  from `simplejwt` where enabled.
- The `352.46`-warnings figure for `manage.py spectacular` is all
  "unable to guess serializer for <generic APIView>" for plain utility views
  (consents/language/health/readiness/data-ingestion actions) — graceful
  fallback serializers, not regressions.