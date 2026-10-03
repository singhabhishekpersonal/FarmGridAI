# syntax=docker/dockerfile:1
#
# FarmGrid AI - single-container image for a PaaS (Render, Koyeb, Fly, Railway).
#
# Serves the API, the HTML pages and the static files from one process, so a
# free single-container tier is enough: no separate static host, no nginx, no
# managed database and no Celery broker are required.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # The platform terminates TLS and forwards plain HTTP over the loopback
    # socket, so Django has to trust X-Forwarded-Proto or SECURE_SSL_REDIRECT
    # loops forever.
    TRUST_PROXY_HEADERS=true \
    DJANGO_SETTINGS_MODULE=FarmGridAI.settings.production

WORKDIR /app

# psycopg[binary] and Pillow ship manylinux wheels, so these are only needed
# if a wheel is unavailable for the platform - they are cheap insurance.
RUN apt-get update && apt-get install -y --no-install-recommends \
      libpq5 \
      libjpeg62-turbo \
      zlib1g \
      libxml2 \
      && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
# torch/torchvision/easyocr are deliberately absent (see requirements-ml.txt):
# they add ~3 GB of wheels and no free tier can build that.
RUN pip install -r requirements.txt

COPY . .

# Writable locations for runtime output.
RUN mkdir -p /app/media /app/staticfiles /app/logs

# Fail the build rather than deploy a broken image if static collection breaks
# (a missing {% static %} reference is otherwise only discovered on first page
# load, in production).
RUN DJANGO_SECRET_KEY=build-only \
    DJANGO_ALLOWED_HOSTS=localhost \
    SECRET_KEY=build-only \
    python manage.py collectstatic --noinput

# PaaS providers inject PORT; default keeps `docker run` working.
EXPOSE 8000

# `sh -c` so $PORT expands at run time. Migrations run on every boot, which is
# what makes a fresh deploy come up with its tables. One worker: the free tiers
# give 512 MB, and this app's memory is dominated by a single request.
CMD ["sh", "-c", "python manage.py migrate --noinput && \
     gunicorn FarmGridAI.wsgi:application \
       --bind 0.0.0.0:${PORT:-8000} \
       --workers ${WEB_CONCURRENCY:-1} \
       --timeout ${GUNICORN_TIMEOUT:-60} \
       --access-logfile - \
       --error-logfile -"]
