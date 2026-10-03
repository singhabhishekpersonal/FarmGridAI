#!/usr/bin/env python3
"""Shared bootstrap for the data-ingestion CLI scripts.

Each script is an operator-facing helper (not a runtime dependency): it wires
up Django settings and logging, then delegates to the ``data_ingestion``
service layer. Scripts are safe by default:

* never reach the network unless ``DATA_INGESTION_NETWORK_ALLOWED`` is set;
* never approve/block sources automatically (human-only);
* never delete data - rollback/cleanup always quarantines.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_SETTINGS = "FarmGridAI.settings.development"


def bootstrap(settings_module=None):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", settings_module or DEFAULT_SETTINGS)
    import django

    django.setup()

    import logging

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )


def add_dry_run_flag(parser, default=True):
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=default,
        help="plan only; never persist artifacts/records (default: on)",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="perform the real operation (overrides the dry-run default)",
    )
    parser.add_argument(
        "--no-dry-run",
        dest="dry_run",
        action="store_false",
        help="alias for --execute",
    )


def is_execute(args):
    return bool(getattr(args, "execute", False)) or not bool(getattr(args, "dry_run", True))


def print_report(report, indent=2):
    if callable(getattr(report, "items", None)):
        for key, value in report.items():
            if isinstance(value, (list, dict)) and value:
                print(f"{' ' * indent}{key}:")
                print_report(value, indent + 2)
            else:
                print(f"{' ' * indent}{key}: {value}")
    else:
        print(f"{' ' * indent}{report}")


def resolve_source(identifier):
    """Resolve ``identifier`` to a DataSource by id (UUID) or name."""
    import uuid

    from apps.data_ingestion.models import DataSource

    try:
        uuid.UUID(str(identifier))
    except (ValueError, TypeError):
        pass
    else:
        qs = DataSource.objects.filter(pk=identifier)
        if qs.exists():
            return qs.first()
    qs = DataSource.objects.filter(name__iexact=identifier)
    if qs.exists():
        return qs.first()
    raise SystemExit(f"source not found for: {identifier}")