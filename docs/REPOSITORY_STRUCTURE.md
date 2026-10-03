# Repository structure

What every top-level folder and file is for, and what is deliberately kept out
of version control.

## Layout at a glance

```
.
├── apps/                    Django applications (the product)
├── FarmGridAI-frontend/      Templates, static assets and the JS test harness
├── FarmGridAI/            Project config: settings, URLs, Celery, ASGI/WSGI
├── scripts/                 Standalone data and ML tooling (not part of the server)
├── data/                    Seed data (committed) and fetched/model artifacts (ignored)
├── docs/                    Reference documentation
├── media/                   User uploads                      [ignored]
├── logs/                    Runtime logs                      [ignored]
├── staticfiles/             collectstatic output              [ignored]
│
├── manage.py                Django entry point
├── verify.py                End-to-end verification (drives real HTTP)
├── pytest.ini               Test runner configuration
├── run.ps1                  Start backend + frontend locally
├── run_live.ps1             Publish to a public URL via a Cloudflare tunnel
├── openapi.yaml             Generated API contract (committed on purpose)
├── requirements.txt         Pinned Python dependencies
├── Dockerfile               Container image
├── docker-compose.yml       Container orchestration
└── .env.example             Template for environment variables
```

## `apps/` - the Django applications

Fourteen domain and platform apps. Each holds `models.py`, `views.py`,
`serializers.py`, `urls.py`, `services.py` and `migrations/`.

| App | Responsibility |
| --- | --- |
| `core` | Shared mixins, middleware, the i18n catalog and the `{% t %}` tag |
| `accounts` | Registration, login, JWT issue/refresh, logout, consent, language preference |
| `farms` | Farms, land parcels, crops, summaries, bigha/area conversion |
| `crops` | Crop catalogue and per-crop cost estimation |
| `equipment` | Equipment catalogue, ownership, images, running-cost analysis |
| `expenses` | Expenses by category, receipt documents, summaries and analysis |
| `energy` | Pump profiles, solar configuration and comparison, projections, benchmarks |
| `finance` | Income profile, buy-vs-rent, repair-vs-replace, affordability |
| `subsidies` | Scheme catalogue, eligibility matching, recommendations, checklist |
| `recommendations` | Recommendation generation, explanation, runs and feedback |
| `ml_engine` | Model registry, ranking, forecasting, vision classifier, OCR |
| `chatbot` | Keyword intent matching and knowledge-base retrieval (no external LLM) |
| `data_ingestion` | Sources, collection runs, artifacts, records, review queue, provenance |
| `api` | Capability descriptor, model/data-source status, Celery tasks |
| `web` | Server-rendered pages, language switch, per-page background media |

## `FarmGridAI-frontend/` - the frontend

There is **no bundler and no `npm install`**. Django serves the templates and
static files from the same origin as the API, which is why one process runs the
whole site.

```
FarmGridAI-frontend/
├── templates/     24 Django templates (base, partials, one folder per domain)
├── static/
│   ├── css/       base.css, forms.css, dashboard.css
│   ├── js/        app.js, dashboard.js, uploads.js
│   └── images/    logo, favicon, field and solar photography
└── tests/
    └── i18n_test.js   Node harness: language switching, auth chrome, CSRF,
                      and that every KS.t() call site resolves in the catalog
```

`i18n_test.js` needs Node, but Node is only for the tests - the app itself has no
JavaScript dependencies.

## `FarmGridAI/` - project configuration

| File | Purpose |
| --- | --- |
| `settings/base.py` | Shared settings, all environment-driven |
| `settings/development.py` | `manage.py` default. DEBUG on, SQLite, Celery eager |
| `settings/production.py` | Strict settings. **Requires `DJANGO_ALLOWED_HOSTS`** |
| `urls.py` | Root URLconf, API mount, `/api/schema/` |
| `celery.py` | Celery application |
| `staticfiles.py` | `VersionedStaticStorage` - appends `?v=<mtime>` in development |
| `asgi.py` / `wsgi.py` | Server entry points |

## `scripts/` - standalone tooling

Dataset builders, the equipment classifier training/evaluation scripts, data
ingestion CLI and provenance reporting. These are run by hand from a terminal,
not imported by the server.

## `data/` - what is and is not committed

| Path | Committed | Notes |
| --- | --- | --- |
| `data/seed/` | **yes** | `seed_platform` needs it on a fresh clone |
| `data/models/**/*.pt` | no | Trained weights, 17 MB. Rebuild with `scripts/` |
| `data/ingested/` | no | Fetched data and provenance reports, ~3 MB |

## Not committed, and why

`.gitignore` is the authority. The rules that matter most:

- **`.env`** is excluded; **`.env.example`** is committed. Copy it to `.env` and
  fill it in. Never commit real credentials.
- **`db.sqlite3`** is excluded. Create it with `python manage.py migrate`.
- **Model weights** use `data/models/**/*.pt`. A plain `data/models/*.pt` would
  **not** match, because in `.gitignore` `*` does not cross `/` - and the
  classifier lives one directory deeper. This is the single easiest mistake to
  make in this repo.
- **`media/`, `logs/`, `staticfiles/`** are runtime output.
- **`docs/frontend.txt`** is a stale snapshot of the templates, excluded on
  purpose.

## Running it

```powershell
.\run.ps1                                  # local, http://127.0.0.1:8000
.\run.ps1 -Migrate -Seed -DemoUser         # first-time setup
.\run_live.ps1                             # public URL via a Cloudflare tunnel
```

See the root `README.md` for the full command reference.