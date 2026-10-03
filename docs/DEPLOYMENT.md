# Deploying

The app is one container: it serves the API, the HTML pages and the static
files from a single process, so a free single-container tier is enough. No
nginx, no S3, no managed database and no Celery broker are required.

## Deploy on Render (free) from GitHub

1. <https://render.com> → **New** → **Web Service** → connect
   `singhabhishekpersonal/FarmGridAI`
2. Render reads the `Dockerfile` in the repo root. Nothing else to configure.
3. Environment variables (only the first is required):

   | Variable | Value | Why |
   | --- | --- | --- |
   | `DJANGO_SECRET_KEY` | *(let Render generate)* | required, and a real key must not be a literal in the repo |
   | `DJANGO_DEBUG` | `false` | default anyway; set explicitly for clarity |
   | `TRUST_PROXY_HEADERS` | `true` | Render terminates TLS and forwards `X-Forwarded-Proto` |
   | `SECURE_SSL_REDIRECT` | `true` | correct behind Render's proxy |
   | `CELERY_TASK_ALWAYS_EAGER` | `true` | runs background work inline; no Redis needed |

   `DJANGO_ALLOWED_HOSTS` can be left unset — `settings.production` reads the
   hostname Render injects. Set it explicitly to pin the allowed hosts.

Or use the blueprint: **Infrastructure as Code** → **New Blueprint Instance** →
point it at the repo. `render.yaml` declares the service and the variables above.

Koyeb, Fly and Railway accept the same Dockerfile.

## What "free" actually costs you

The free web service tier has two limits that matter for this app:

- **It sleeps after roughly 15 minutes idle.** The first request after a gap
  waits while the container restarts. Fine for a demo link; bad for presenting
  live.
- **The filesystem is ephemeral.** Uploaded media and the SQLite file are lost
  on every redeploy, and the bundled free Postgres expires after 30 days. If the
  data has to survive, add a real database: set `DB_NAME`, `DB_USER`,
  `DB_PASSWORD` (and optionally `DB_HOST`, `DB_PORT`) and `settings.production`
  switches to PostgreSQL automatically.

If persistence matters more than auto-deploy, PythonAnywhere's free tier gives
you durable SQLite and proper static serving, but you deploy by `git pull`
rather than on every push.

## Static files

`settings.production` uses `whitenoise.storage.CompressedManifestStaticFilesStorage`
and `WhiteNoiseMiddleware`, so `collectstatic` output is served by the app
itself with content-hashed filenames — safe to cache hard, never stale. The
Dockerfile runs `collectstatic` during the build, so a broken `{% static %}`
reference fails the build instead of surfacing as unstyled pages in production.

To reproduce that check locally:

```powershell
$env:DJANGO_SETTINGS_MODULE = "FarmGridAI.settings.production"
$env:DJANGO_SECRET_KEY = "local-only"
$env:DJANGO_ALLOWED_HOSTS = "localhost"
python manage.py collectstatic --noinput
```

## Running production settings on Windows

`gunicorn` is Unix-only — it imports `fcntl` and will not start on Windows:

```
ModuleNotFoundError: No module named 'fcntl'
```

That is expected and does not affect the container, which is Linux. To exercise
the production stack locally on Windows, use any cross-platform WSGI server:

```powershell
pip install waitress
# then serve FarmGridAI.wsgi:application with waitress on a spare port
```

`.\run.ps1` uses Django's own `runserver` and is unaffected.

## ML / vision dependencies

`torch`, `torchvision` and `easyocr` are **not** in `requirements.txt` — together
they add roughly 3 GB of wheels, which no free tier can build. They live in
`requirements-ml.txt`:

```powershell
pip install -r requirements.txt -r requirements-ml.txt
```

The application runs without them. `apps/ml_engine/vision/classifier.py` guards
its `import torch` and reports an explicit `fallback` source, and the OCR
provider degrades to `heuristic`. The trained artifact (17 MB) is not committed
either; point `ML_EQUIPMENT_CLASSIFIER_WEIGHTS` at it to enable the CNN.

## Health check

`/api/v1/health` is a cheap, unauthenticated liveness probe and is what
`render.yaml` uses.
