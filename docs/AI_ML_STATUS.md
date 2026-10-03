# AI/ML Status — FarmGrid AI

Status snapshot reviewed on **2026-09-25** (post-fix release gate). All facts
below are verified against the live registry, the on-disk artifact, and
`_eval_report.json`; nothing is fabricated.

## 1. Model registry (live DB truth)

`MLModelRegistry` contains **1 registered model**, `active`, with **1 active
version**:

| Key | Type | Status | Active version | Artifact | Notes |
| --- | --- | --- | --- | --- | --- |
| `equipment_classifier` | vision | **active** | `v1` | present & checksum-verified | CNN, MobileNetV3-Large, top-6 brands + `other` |

- No `TrainingRun` rows exist (nothing auto-retrains; activation is manual, gated
  and evidence-backed).
- `ModelStatusView` (GET `/api/v1/system/model-status/`) exposes safe, aggregate
  metadata only (never artifact paths/secrets) — covered by contract tests.

## 2. Equipment classifier — verified metrics (held-out test, 179 images)

From `data/models/equipment_classifier/equipment_classifier_mobilenetv3_top6_v1_eval_report.json`,
independently re-verified this session:
- test accuracy 0.81006, balanced accuracy 0.69348, macro-F1 **0.7316**,
  weighted-F1 0.80017, top-3 0.98324, val macro-F1 (best) 0.74584.
- Per-class F1: Farmtrac 0.857, John Deere 0.923, Mahindra 0.571, New Holland
  0.727, Powertrac 0.769, Sonalika 0.400, other 0.873.
- Distribution of usage at runtime: predictions with max-softmax ≥ 0.55 are
  served from the model (`source=ml_model`); below threshold → `unknown`;
  anything malformed/missing/corrupt artifact → hard fallback (`used_ml=false`).
- Checksum independently recomputed and matching; classifier load smoke test
  passed in-process (`available=True`, `artifact_available=True`,
  `model_version=v1`, 7 classes). See `MODEL_CARD.md`.

## 3. Classical / rule-based estimators (in code; not "model" registries)

These ship as deterministic calculations wrapped in the estimate contract
(assumptions + limitations + flags + confidence) and are exercised by the test
suite:
- Expense range estimator (`expense_estimator`) — bucketed per-area → range.
- Operating-cost estimator (`operating_cost_estimator`) — per-usage, fuel-type,
  and hours; zero-cost fuels handled correctly.
- Recommendation ranker, crop-cost estimation, energy option comparison with
  breakeven and NPV — no phantom breakevens; expected scenario chosen by label.
- Finance affordability — unaffordable when income unknown/≤ 0; income-burden
  never a fabricated number.
- Anomaly detector / forecast baselines: present as capability placeholders in
  registry choices; **not** activated.

## 4. RAG / chatbot
- Chatbot knowledge-intent RAG is operational; `KnowledgeIntent.objects.filter(is_active=True)`
  is NOT a bug (no change made). Model registry choice
  `rag_chatbot_orchestrator` exists but no registry entry is active — the
  chatbot serves curated in-domain knowledge with grounding
  (`available_models_found` claim must be re-verified against DB truth before
  any chatbot report, per the audit).

## 5. AI governance posture
- **No auto-retrain, no auto-activation**: the CNN was activated only after the
  documented gate passed (artifact + checksum + labels/metadata agreement +
  `test_macro_f1≥0.70` + inference smoke test + registry/version metrics).
- **Every prediction is appraised**: `needs_user_confirmation` always true for
  vision; all financial outputs are estimates carrying assumptions, limitations,
  confidence labels and verification flags.
- **Subsidy and official-source data is never auto-published**: the 3 PM-KUSUM
  records sit in `DataReviewQueue` as `pending` with evidence packets
  (`data/ingested/reports/subsidy_review_packets/`) awaiting human decision.

## 6. Known gaps → next steps
- CNN: tiny per-brand test supports (6–15 images); `other` dominance; no OOD
  detector; unverified image licensing. Targets: ≥50 labeled images per brand
  from compliant sources; dedicated out-of-domain validation set; re-train only
  after data growth and re-evaluate with the same held-out script before any
  re-activation.
- Re-verify the chatbot `available_models_found` claim against DB truth before
  surfacing any chatbot capability claim.