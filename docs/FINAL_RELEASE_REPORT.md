# FarmGrid AI — Final Release Report

Release audit completed **2026-09-25**. This is the final release package for
the current feature scope; remaining work is **operator decisions** and the
**staged production-hardening** items listed at the end (not code gaps).

## 1. Release gate results (all green)

| Check | Result |
| --- | --- |
| `python -m pytest` | **201 passed, 5 warnings** (126.54s, exit 0) — baseline 172 + 29 new P0-fix regression/contract tests |
| `python manage.py check` | No issues |
| `python manage.py makemigrations --check --dry-run` | **No changes detected** — no schema drift |
| `python manage.py migrate --check` | Up to date |
| `python manage.py spectacular --file openapi.yaml` | Regenerated with 3 new system endpoints; remaining warnings are the pre-existing "unable to guess serializer" notes for plain APIViews (cosmetic) |
| `python manage.py test` | Discovers 0 tests — test entrypoint is `python -m pytest` (pytest.ini) |
| Templates / static | All `.html/.css/.js` files remain **0 bytes** (22 placeholder files) — no UI content added, by design |
| Classifier smoke | Loads, sha256-verified, `available=True / artifact_available=True / v1`, 7 classes, no load error |

## 2. What changed in this final audit (all verified)

- **16 P0 safety/correctness fixes** (see `IMPLEMENTATION_STATUS.md` items 7–18):
  real `all_objects` manager; equipment operating-cost `EstimateRange` rebuild;
  expenses Decimal/float fix; strict `_strict_bool` intake; review-workflow
  **human-gate publish** (no auto-publish); compliance evidence-path stability +
  sanitized run-id; HTTP-client redirect host re-validation + Content-Length
  guard; API middleware request-id + **readiness redaction**; subsidies
  `income_farm` mapping; finance affordability income/EMI guards; duplicate
  CAPTCHA key; 3 new **safe** system endpoints.
- **+29 regression tests** across energy, equipment, farms, accounts, expenses,
  crops, ml_engine, data-ingestion and API contract suites.
- **Data ingestion status locked:** 28 sources, **0 approved /
  0 `collection_enabled`**; live probes on MNRE and PM-KUSUM portal both end
  `denied`.
- **AI/ML verified:** `MODEL_CARD.md` + `AI_ML_STATUS.md` written; artifact
  presence + sha256 (`741b94b8…`) recomputed and matches; registry metrics match
  `_eval_report.json` exactly.

## 3. Reviewed / produced artifacts this audit

| Artifact | Location |
| --- | --- |
| Model card | `MODEL_CARD.md` |
| AI/ML status | `AI_ML_STATUS.md` |
| Source & review status | `DATA_SOURCE_AND_REVIEW_STATUS.md` |
| Backend API inventory | `BACKEND_API_INVENTORY.md` |
| Known limitations & next steps | `KNOWN_LIMITATIONS_AND_NEXT_STEPS.md` |
| PM-KUSUM subsidy review packets (3 records) | `data/ingested/reports/subsidy_review_packets/` |
| Environment template (updated) | `.env.example` |
| Implementation & audit status | `IMPLEMENTATION_STATUS.md` |
| README (API areas + tests updated) | `README.md` |
| OpenAPI | `openapi.yaml` |

## 4. Operator decisions required (blocking publication, not blocking release)

1. **PM-KUSUM records** — approve/reject publishing the 3 queued
   `DataReviewQueue` rows (hash `a83d66c95ff2`, `1f71ec291ae0`,
   `d6b4604deaa5`) to `SubsidyScheme`, and decide the **supersession**
   question (2024 consolidated guidelines vs 2019 PM-KUSUM / Component-C
   editions).
2. **In-document issuance date** — confirm the "17 January 2024" date in
   `20240118413909461.pdf`.
3. **Source approvals** — which real government/manufacturer pages to
   (a) manually import and (b) later allow for automated collection, each with
   verified robots/terms evidence.

## 5. Warranty / honesty section

- No data/metrics/weights/subsidy figures or citations were fabricated.
- No robots/CAPTCHA/login/paywall bypass occurred; no stealth/proxy/spoofing.
- No `.html/.css/.js` content was created or modified.
- Nothing was auto-published; queue rows remain `pending`.
- Release version marker: `equipment_classifier v1` active; `201` tests green.