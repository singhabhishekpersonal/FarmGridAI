"""Settings package.

Selecting a settings module:
- ``FarmGridAI.settings.development`` for local/dev (SQLite + console mail).
- ``FarmGridAI.settings.production`` for production (PostgreSQL, strict security).

The ``DJANGO_SETTINGS_MODULE`` environment variable overrides the default that
``manage.py`` uses.
"""