# Data Source & Review Status

Live snapshot re-verified during the final release audit on **2026-09-25**
(direct DB queries + persisted compliance reports).

## Policy (hard guarantees, unchanged)

- **0 of 28 sources approved** (`approval_status=approved`), **0
  `collection_enabled=True`**. Nothing can be collected automatically.
- Network is **off by default** (`DATA_INGESTION_NETWORK_ALLOWED=false`); without
  an operator-flipped flag every automated compliance/collection step records a
  `manual_review` / dry-run instead of touching the wire.
- Approval is a **human action only** — `approved_by` must be recorded; no
  automation ever approves a source.

## Source registry (DB truth: 28 rows)

- **14 real official sources**, all `manual_review`, collection disabled
  (registered by `register_official_sources`; compliance report at
  `data/ingested/reports/source_compliance_report(.md/.json)`):
  PM-KUSUM Official Portal and MNRE **must never be auto-collected**:
  live compliance checks record `decision=denied` for both (MNRE robots allows
  root but a login/registration gateway wall was detected;
  `login_required_detected=true`; PM-KUSUM robots.txt is not a parseable robots
  file → treated as unavailable/ambiguous → blocked, 0 artifacts).
  Also present: MoA&FW, SMAM, MP Agriculture (HTTP-only), MPUVN renewable,
  MPERC tariff, DES cost-of-cultivation, and Mahindra / Sonalika / Farmtrac /
  John Deere / New Holland / Powertrac manufacturer spec sites
  (manual import recommended for copyrighted imagery).
- **2 official manual-import sources**, `manual_review`, collection disabled:
  `PM-KUSUM Official Documents (manual import)` and `MNRE Official Documents
  (manual import)`.
- **12 pending/placeholder/dev rows** (category examples, `Example … (placeholder)`,
  `Manual local corpus (placeholder)`, `T`) — all `pending`, all disabled,
  never approved. Verified not pre-approved.
- 36 persisted `SourceComplianceCheck` rows: endpoint decision matrix matches —
  every automated-capable real government/manufacturer source resolves to
  `manual_review` (offline/compliance-ambiguous → manual) or `denied` (MNRE,
  PM-KUSUM). No `allowed` decisions exist on any real web source.

## Ingestion runs (DB truth: 8)

| run_id | status | type | source |
| --- | --- | --- | --- |
| run-f095b2b88774 | completed | manual import | PM-KUSUM Official Documents (2 records, 2 docs) |
| run-aa82e3bae92b | completed | manual import | PM-KUSUM Official Documents (1 record, 1 doc) |
| run-a5b776b4d9b7 | completed | manual import | MNRE Official Documents (0 records) |
| run-6fb6ff7a5f87 / ec3dbeb6d1d1 / 5cf9e633d4aa | failed | live attempt | PM-KUSUM Official Portal (0 records/extracted; compliance-blocked) |
| run-4ce86382128d / d8f78460c49e | dry_run | dry-run | Manual local corpus (placeholder) (0 records) |

**No live web collection completed.** The only completed runs are offline manual
imports of already-local official documents.

## Review queue (DB truth)

- Total queued for `SubsidyScheme`: **3 records**, all `decision=pending`,
  `risk_level`, `requires_human_review=True`:
  1. `a83d66c95ff2` — `20240118413909461.pdf` — Comprehensive PM-KUSUM Guidelines
     (run-aa82e3bae92b, validation ok).
  2. `1f71ec291ae0` — `KUSUMguidelines.pdf` — PM-KUSUM Implementation Guidelines
     (run-f095b2b88774, validation ok).
  3. `d6b4604deaa5` — `FinalGuidelinesforimplementationofComponent C.pdf` —
     Component-C Guidelines (run-f095b2b88774, validation ok).
- All three: `preliminary=True`, `is_estimate=True`, `verified=False`,
  `verification_status=validated` (structural validation only — NOT a human
  approval).
- **Nothing published to `SubsidyScheme`.** `review_workflow.publish()` now
  strictly refuses to publish without an explicit human `decision=APPROVED`
  plus recorded `decided_by`/`decided_at`;
  subsidy publishes always set `is_illustrative=True`,
  `needs_official_verification=True`, preserve `source_url`, and never
  overwrite verified/active values.

## Evidence packets for review (generated 2026-09-25)

`data/ingested/reports/subsidy_review_packets/`:
- `README_INDEX.md` — index + supersession question.
- `20240118413909461_PM_KUSUM_comprehensive_guidelines.md`
- `KUSUMguidelines_pm_kusum_guidelines.md`
- `ComponentC_guidelines.md`

Each packet quotes only the extracted/anchored wording actually present in the
records, flags every human-review question (in-document date "17 January 2024"
must be confirmed; exact CFA/state-share split; component targets; scheme
validity till March 2026), and recommends **do not publish automatically**.
Operator decisions required: (1) whether the 2024 consolidated guidelines
supersede the 2019 editions; (2) confirm the in-document date; (3) approve
publishing the queued records after verification.

## PM-KUSUM import reports (operator-approved offline manual imports)

- `data/ingested/reports/manual_import_20260925_141138/`
- `data/ingested/reports/manual_import_20260925_142245/`
- MNRE compliance review (host-locked, blocked at gateway wall):
  `data/ingested/reports/mnre_compliance_review_20260925_133435/`
- PM-KUSUM approved dry-run compliance reports under
  `data/ingested/reports/pmkusum_approved_dry_run_20260925_131*/` (blocked).