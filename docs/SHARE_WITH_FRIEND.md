# Share with a Friend — FarmGrid AI

FarmGrid AI is an open-source, API-first farm financial advisory platform built
in Django. It gives smallholder farmers **explainable, range-based estimates** —
never hard promises — for crop input costs, equipment buying-vs-hiring, solar
vs grid vs diesel irrigation economics, subsidy eligibility, energy expenses and
expense anomalies.

## What makes it interesting

- **Honesty-first by construction.** Every estimate carries assumptions,
  limitations, warnings, a confidence label and verification flags. Vision
  outputs always require the user to confirm. Benchmark data is explicitly
  marked unverified/synthetic.
- **A real trained CNN** (MobileNetV3-Large) identifies tractor brands from
  photos — checksum-audited, lazily loaded, safe fallback when the artifact is
  missing, and audited per prediction. See `MODEL_CARD.md`.
- **Compliance-first data ingestion.** Data collection is network-off by
  default; sources are human-approved only; robots.txt/terms are checked and
  evidence is preserved; nothing is ever auto-published without a human review
  decision.
- **201 tests pass**, zero UI bloat, no magic numbers.

## Where to start

```
cd FarmGridAI
python -m venv .venv; .venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_platform
python manage.py runserver          # API at /api/v1/
python -m pytest                    # 201 tests
```

Docs: `README.md`, `MODEL_CARD.md`, `AI_ML_STATUS.md`,
`FINAL_RELEASE_REPORT.md`, `KNOWN_LIMITATIONS_AND_NEXT_STEPS.md`.