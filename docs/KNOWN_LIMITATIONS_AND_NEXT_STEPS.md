# Known Limitations & Next Steps

Honest list, updated at the final release audit (2026-09-25). Nothing here is
hidden; every item is a real, disclosed gap.

## Data / benchmarks
- **Subsidies are preliminary only.** Per-scheme official rates, application
  portals, document requirements and state/district eligibility must be
  synchronized from government sources. The 3 PM-KUSUM records in the review
  queue are validated-but-unpublished, with evidence packets generated; a human
  must decide the supersession question and confirm the in-document issuance
  date ("17 January 2024") before anything is published.
- **Benchmarks are reference ranges, not live quotes.** Electricity tariffs,
  diesel and solar costs, machinery prices/rentals and crop-cost benchmarks are
  seeded reference values with `is_verified=False` /
  `is_synthetic_benchmark=True`; confirm current official rates before major
  spending.
- **Equipment catalog has brands/models/images only** — per-model prices are
  intentionally not fabricated; connect to a price feed to move beyond category
  benchmarks. Source images (tractorgyan CDN) have **unverified licensing**;
  redistribution/disclosure remains an open issue.
- **Bigha has no universal size.** The platform uses regional
  `BighaConversionRule` rows and refuses to guess when no rule exists.

## Models / ML
- **CNN is a small-data feasibility demo, not production.** Per-brand test
  supports are 6–15 images; macro-F1 0.7316 ± wide uncertainty; `other` is an
  18×-larger bucket; unknown handling is max-score thresholding only (**no OOD
  detector** — an out-of-domain image that resembles a named brand may pass
  0.55). Improve by adding ≥50 labeled images per brand from compliant sources,
  a dedicated out-of-domain set, then re-train + re-evaluate on the same held-out
  script before any re-activation (which is manual and gated).
- **OCR is heuristic when tesseract is unavailable.** Output is evidence only.
- **Chatbot LLM layer is off by default** (`CHATBOT_LLM_ENABLED=false`); the
  deterministic intent/source engine is the active path. The `available_models_found`
  claim needs re-verification against DB truth before any chatbot capability
  report (per audit).
- **Registry only has one active model** (`equipment_classifier` v1). Forecast/
  anomaly/ranker models are optional classical components with rules fallbacks.

## Data ingestion
- **All 28 sources: 0 approved / 0 collection_enabled.** Network is disabled by
  default; the two live compliance probes that ran (MNRE, PM-KUSUM portal) ended
  `denied`. Real integration requires per-source human approval + verified
  robots/terms evidence; MNRE and the PM-KUSUM portal are **manual-import
  recommended** (login gateway / non-parseable robots.txt respectively).
- **Online verification is UNREVIEWED evidence only** — it never approves a
  record and never rejects a locally valid document.

## Ops / security / deployment
- **Not production-hardened yet**: production `SECRET_KEY` (≥32 bytes),
  HTTPS termination, rate limiting at the edge, structured logging, email/SMS
  delivery, backup of audit tables, and a DB user/password not required by the
  default SQLite path all remain for the production phase.
- **Celery/Redis** not required in dev (eager mode); required for real
  background collection.

## Known-good constraints (kept)
- All `.html/.css/.js` placeholder files remain **0 bytes** (no UI content
  added) — by design.
- Every financial output is an estimate with assumptions/limitations/warnings/
  confidence/verification flags; vision outputs require user confirmation.
- No auto-approve, no auto-publish, no auto-retrain, no robots/CAPTCHA/login
  bypass, no network access during request handling.

## Next steps (priority)
1. Operator: decide PM-KUSUM supersession + confirm in-document dates +
   approve publishing the 3 queued records (or reject).
2. Operator: per-source approval of the crucial government pages (manual import
   for MNRE/PM-KUSUM; automated review later for MPERC, DES, MPUVN).
3. Collect ≥50 labeled images per tractor brand (compliant sources), then a
   controlled re-train + re-evaluate cycle (gated activation).
4. Wire production secrets/HTTPS/logging/backups and enable real background
   collection for approved sources.