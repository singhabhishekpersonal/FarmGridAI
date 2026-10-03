# Documentation

Project documentation for FarmGrid AI. The root `README.md` covers setup and
day-to-day use; this folder holds the reference material.

## Start here

| Document | What it answers |
| --- | --- |
| [REPOSITORY_STRUCTURE.md](REPOSITORY_STRUCTURE.md) | What every folder and top-level file is, and what is deliberately not committed |
| [TECH_STACK.txt](TECH_STACK.txt) | Languages, frameworks, versions and the runtime flow diagram |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Deploying for free from GitHub, what the free tiers cost, and how the production settings behave |
| [BACKEND_API_INVENTORY.md](BACKEND_API_INVENTORY.md) | The REST endpoints, grouped by app |
| [MODEL_CARD.md](MODEL_CARD.md) | The equipment image classifier: architecture, training data, measured metrics, limits |
| [KNOWN_LIMITATIONS_AND_NEXT_STEPS.md](KNOWN_LIMITATIONS_AND_NEXT_STEPS.md) | What is incomplete or risky. **Read this before trusting a number.** |

## Status and reporting

| Document | What it covers |
| --- | --- |
| [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) | Feature-by-feature completion state |
| [AI_ML_STATUS.md](AI_ML_STATUS.md) | ML components and their readiness |
| [DATA_SOURCE_AND_REVIEW_STATUS.md](DATA_SOURCE_AND_REVIEW_STATUS.md) | Ingestion sources, approvals and review queue |
| [IMPROVEMENT_SUMMARY.md](IMPROVEMENT_SUMMARY.md) | Changes made in the most recent pass |
| [FINAL_RELEASE_REPORT.md](FINAL_RELEASE_REPORT.md) | Release readiness |
| [FINAL_AUTONOMOUS_COMPLETION_REPORT.md](FINAL_AUTONOMOUS_COMPLETION_REPORT.md) | Completion report from the autonomous pass |

## Sharing

| Document | What it covers |
| --- | --- |
| [SHARE_WITH_FRIEND.md](SHARE_WITH_FRIEND.md) | A short, non-technical walkthrough for demonstrating the app |

## Generated

| File | Notes |
| --- | --- |
| `frontend.txt` | A one-off snapshot of every template and script. Kept for reference only and **not committed** - the files under `FarmGridAI-frontend/` are the source of truth and this copy would silently go stale. |
| `../openapi.yaml` | Generated from the code with `python manage.py spectacular --file openapi.yaml`. Committed so the API contract is reviewable in a diff. |